# CFX-750 Steering Without a Wheel Angle Sensor — Firmware Reverse-Engineering Findings

How the Trimble CFX-750 steers with EZ-Steer / EZ-Pilot style actuators,
which have **no wheel angle sensor (WAS)**. Everything here comes from static
analysis of the display firmware **v8.10** (`v8_10_CFX_750_Firmware.img`, build
date Aug 7 2019, PowerPC/eCos, load base 0). Nothing was confirmed with live
captures.

See [ROLL_COMPENSATION_FINDINGS.md](ROLL_COMPENSATION_FINDINGS.md) for the
image layout and tooling, [IMD_FINDINGS.md](IMD_FINDINGS.md) for the IMU CAN
stream, and [SAM200_FINDINGS.md](SAM200_FINDINGS.md) for the motor.

**TL;DR.** The display never measures the wheel angle. It **commands** a wheel
angle through a calibrated motor model (angle-per-turn, freeplay) and
**infers** the actual angle from how fast the vehicle is turning (yaw rate →
equivalent wheel angle through a kinematic model). A Kalman filter fuses the
two. A state-feedback controller adds a learned **bias** term, because the
system never knows where "straight ahead" really is.

## Modules involved

| Source file (from asserts) | Role |
|---|---|
| `nc/nc_ezsteer.c`, `nc/nc_common.c` | Navigation-control loop for EZ-Steer (`NCDIAGS` log) |
| `controls/tarragon/tarragon.c`, `tarragon_impl.c` | Steering controller: Kalman filter (`UPDATEKF`), control law (`UPDATEMAKO`), approach/hold logic |
| `controls/cal/control_cal_apt.cpp` | Angle-per-turn (APT) calibration |
| `controls/actuators/actuator_scm*` | EZ-Steer controller (SCM): motor position commands (`SetShaftPos`) |
| `controls/actuators/actuator_cuda.cpp` | EZ-Pilot / SAM200 ("CUDA"): `A1` position targets in 4096-count encoder clicks |
| `utility/least_square_fit_line.cpp` | Line fit used by the APT calibration |

User-facing tuning keys: `AnglePerTurn`, `AnglePerTurnLeft`,
`AnglePerTurnRight`, `Freeplay` (left/right), `FreeplayOffset`, `MotorSpeed`,
`EZSteerLoopGain`, `ApprCtrlAggressiveness`, online aggressiveness, and the
per-vehicle "Steering Delay".

## 1. Open-loop actuation: wheel angle → motor position

The steering command from the controller is a **wheel angle**. A base
actuator method (`0x6fd398`) turns it into a steering-wheel position using
the calibrated steering ratio, plus a freeplay (backlash) offset. Each
actuator's `SetShaftPos` then converts that into motor units. The CUDA
(SAM200) actuator uses this method as vtable slot `0x1c`; the EZ-Steer SCM
very likely shares it.

```c
// 0x6fd398, input: theta_cmd (rad), v (m/s)
if (theta_cmd > theta_prev && lastDir == LEFT)  { fpOffset += freeplay(RIGHT); lastDir = RIGHT; }
if (theta_cmd < theta_prev && lastDir == RIGHT) { fpOffset -= freeplay(LEFT);  lastDir = LEFT;  }
//   freeplay(dir) = freeplay[dir] * 57.2958 / k_20c   (0x6fcfb8; k_20c default 0.4064)
extra  = (v > 2.0) ? small speed/rate-dependent term : 0;   // logged as "valveDeadBand", not decoded
sw_deg = theta_cmd_deg * (2*PI / AnglePerTurn)              // steering ratio, 0x6fd1b4
       + (fpOffset + extra) * scale;
SetShaftPos(sw_deg);                                        // vtable slot 0x78
```

The freeplay offset only moves when the commanded angle **reverses
direction**: it takes up the slack in the steering linkage. `AnglePerTurn` is
a single combined value in the actuator; the calibration measures left and
right separately and combines them.

### Motor units per actuator

| Actuator | `SetShaftPos` | Conversion | Units per steering-wheel turn |
|---|---|---|---|
| EZ-Steer (SCM, friction wheel) | `0x6fffa4` | `deg * 120 / 360` | 120 |
| EZ-Pilot / **SAM200** ("CUDA", motor in the column) | `0x70133c` | `-deg * 4096 / 360` → sent as `A1 09 <i32>` | **4096** (encoder clicks, sign inverted) |

For the SAM200, the command and the `A1 40` feedback are both **encoder
clicks relative to the zero set at engage (`A1 3D`)**. It's "position mode"
only in the sense of "go to click N". The CFX streams a new target every
20 ms with small steps, so the speed comes from how fast the target moves.
That gives **counts per degree of wheel angle = 4096 / AnglePerTurn_deg**,
about 205 at the default 20°/turn. See
[SAM200_FINDINGS.md](SAM200_FINDINGS.md#cross-check-against-the-cfx-750-firmware)
for the full message mapping.

Defaults in the base actuator config (`0x6fd79c`):

| Offset | Default | Meaning |
|---|---|---|
| `+0x204` / `+0x208` | — | Freeplay, one value per direction |
| `+0x20c` | 0.4064 | Scale used to turn freeplay into degrees (meaning unclear) |
| `+0x210` | 0.349 rad (**20°**) | AnglePerTurn → steering ratio 18:1 |
| `+0x214` | 62.83 (20π) | Probably a motor speed/rate limit |
| `+0x220` / `+0x222` | 2 / 20 | Small integer settings, not identified |

The motor follows these position targets at the configured Motor Speed. Speed
constants in `0x6fd1cc` (0.67/0.89, 1.56/1.79, 3.35/3.58 m/s, i.e. about
1.5/2, 3.5/4 and 7.5/8 mph) suggest the motor speed/acceleration setting
switches with ground speed, with a small overlap band between levels. The
firmware logs `LOSPEED`/`HISPEED Setting vel/accel`. I didn't read that code
in detail.

## 2. Turn rate → equivalent wheel angle (kinematic model, `0x6b710c`)

This is the core trick that replaces the WAS. The measured turn rate is
converted into the wheel angle that would produce it. The model is chosen by
vehicle type:

```c
// f1 = turn input, v = speed, L = wheelbase (vehicle config +0x8)
switch (vehicleType) {
  case 0,3,4,5,6,8:  delta = atan(f1 * L);                   // bicycle model; f1 = curvature (yaw rate / v)
                     clamp to ±PI/2;          break;
  case 1:            delta = 2 * asin(clamp(f1*L/2 / v, -1, 1));   // matches an articulated tractor
                     break;
  case 2,7:          delta = (v > 0) ? f1 : 0;               // passed straight through (tracked?)
                     break;
}
// reverse direction, 0x6b723c:  yawRate = v / L * tan(delta)
```

The type-to-vehicle mapping is inferred from the formulas. The UI lists FWD
tractor, 4WD articulated, tracked, combine, swather, sprayer and floater, but
the enum order wasn't confirmed.

## 3. Kalman filter (`UPDATEKF`, `0x707b3c`)

This is a 3-state filter run every control cycle. It fuses "what we
commanded" with "what the vehicle actually did".

**Model input: the previous steering command**, not motor feedback (the
caller passes the last output, stored at `0x1fe8ee8`, in as `f1`). A bias input
(`in+0x30`) is subtracted first, and the result goes through a first-order
lag that models the **Steering Delay** setting τ (`vehicle+0xb0`):

```c
u = cmd_prev - bias;
if (tau > 0)  lagged += dt * (2/tau) * (u - lagged);   // 0x707d38
else          lagged  = u;
```

**Measurements** (`z`, built at `0x707ee8`):

| z | Source |
|---|---|
| z0 | cross-track velocity `v * sin(headingError)` |
| z1 | `in+0x00`, probably cross-track error |
| z2 | wheel angle derived from the measured yaw rate through the kinematic model (section 2) |

The yaw rate (`in+0x38`) can first pass a helper (`0x707ae8`).

**Matrices and noise:**
- Starting covariance: `P0 = 1000·I` (`0x1cc7888`).
- Fixed 3×3 measurement-noise matrix (`0x1cc78d0`):
  ```
  [ 0.5197   0.0740   0.1529
    0.0740   0.1673  -0.0176
    0.1529  -0.0176   0.3938 ]
  ```
- Process noise:
  - The wheel-angle state gets `0.1 · k · dt` (`k = vehicle+0x98`).
  - The diagonal terms are `1e-4 / dt`.
  - **Below 2 m/s** the diagonal terms are inflated by `(2 / max(|v|, 0.1))²`
    (`0x707e88`), because at low speed the yaw rate says little about the
    wheel angle.
- The prediction adds the lagged command through fixed input columns
  (`0x707f20` loop).

**Outputs:**
- Filtered cross-track velocity, the second state, and the **estimated wheel
  angle**.
- Along-track speed = `sqrt(v² − x0²)`.
- The filter is reset when the input flag at `+0x40` is set.

## 4. Control law (Tarragon / "MAKO", `0x706804`)

1. Run the Kalman filter, then build the controller state vector (`0x705358`).
2. Run the approach/hold logic (`0x705a54`: `Approach Ctrl On/Off`,
   `Hold On/Off`, `hdgCmd`). Its constants include π/9 (20°), π/3 (60°)
   and 50 Hz.
3. **Online** (gains from `0x705724`): full-state feedback, roughly
   ```c
   u = (-k0*x1 - k1*x2) * g - k2*x3 - k3*x4;
   ```
   **Approach** (gains from `0x705490`): the heading-error term is replaced by
   `(hdgCmd − hdg)`.
4. Clamp the command (`Sat: thetaCmd = %f thetaMax = %f thBias = %f`):
   - `thetaMax` is the smaller of the stored limit and the kinematic model
     evaluated at a turn limit divided by speed.
   - The output is `theta_cmd = u + thBias`.
5. Rate-limit or filter the result (`0x705fbc` / `0x703a9c`), then send it to
   the actuator.

**`thBias` is how the missing WAS centre gets solved.** With no absolute
steering reference, the point where the motor thinks "centre" is drifts
(freeplay, side slope, tyre wear). The controller adds a correction learned
from the filter/feedback instead of trusting a fixed zero. `FreeplayOffset`
is the manual version of the same correction.

## 5. Angle-per-turn calibration (`control_cal_apt.cpp`)

From the UI text: *"rolling forward and permitting this controller to command
the steering motor to step a number of times and automatically compute a
value."* In the code (`0x6fb610`):

```c
// two least-squares line fits (0x68444) over the calibration run:
motSlope   = slope(motor position vs time);           // samples at cal+0x58
thetaSlope = slope(yaw-rate-derived wheel angle vs time);   // samples at cal+0x68
APT        = |thetaSlope / motSlope| * k;             // k = float at cal+0xb0
// done for the right and left directions separately, then combined
```

It logs `CAL STEERING result: motSlope=%f thetaSlope=%f APT=%f`. The
calibration uses the **same turn-rate → wheel-angle model** as the Kalman
filter, so the steering ratio and the estimator stay consistent with each
other.

## Recipe for AgOpenGPS (steering without a WAS)

```c
// calibration: step the motor while driving; APT = |d(delta_est)/dt| / |d(motor)/dt|
delta_est_meas = atan(L * yawRate / v);                        // IMU yaw rate, v > ~0.5 m/s
lagged        += dt * (2/tau) * ((cmd_prev - bias) - lagged);  // steering-delay model
// KF / complementary blend of lagged command and delta_est_meas -> delta_hat
// trust the yaw-rate term less at low speed (inflate its noise ~ (2/v)²)
cmd            = controller(xte, headingErr, delta_hat) + bias_learned;
sw_deg         = cmd_deg * (2*PI / APT) + freeplayOffset;      // freeplay offset steps on direction reversal
sam200_counts  = -sw_deg * 4096 / 360;                         // A1 09 target, clicks since engage
```

This mirrors the roll filter: the IMU handles the fast dynamics, and the
vehicle model plus GNSS correct the slow drift.

## Open questions / not traced

- **What each of the 3 Kalman-filter states means exactly**, and the contents
  of the input columns at `r24+0x58` / `r24+0xb8`.
- **The controller gain schedule** (`0x705490` / `0x705724`) and how Online
  Aggressiveness, Approach Aggressiveness and `EZSteerLoopGain` feed the gains.
- **How `thBias` is learned**: from a Kalman-filter state or a separate
  integrator.
- **Freeplay units**: the reversal logic is clear (section 1), but what the
  `0.4064` scale (`+0x20c`) represents is not.
- **The `valveDeadBand` term** added above 2 m/s (`0x6fd458`): its inputs and
  meaning were not decoded.
- **The two scale methods** (vtable `0x74` / `0x7c`) applied just before
  `SetShaftPos`: not resolved for the CUDA actuator.
- **The CUDA IMU path** (`CUDA_IMU`, `0x701dd4`) and the CUDA-specific
  calibration code (`0x702xxx`): not traced.
- **Autopilot (NAV controller) with a real WAS**: steering runs in the
  controller, not in this code.

## Address index (v8.10 image, base 0)

| Address | What |
|---|---|
| `0x6b710c` | yaw rate / curvature → equivalent wheel angle (per vehicle type) |
| `0x6b723c` | wheel angle → yaw rate (`v/L·tan δ`) |
| `0x6bc624` | EZ-Steer NC loop (`NCDIAGS`) |
| `0x6fb610` | APT calibration result (`motSlope`, `thetaSlope`, `APT`) |
| `0x68444` | least-squares line fit |
| `0x6fcfb8` | freeplay[dir] → degrees |
| `0x6fd1b4` | steering ratio `2π / AnglePerTurn` |
| `0x6fd1cc` | speed-dependent motor setting (LOSPEED/HISPEED) |
| `0x6fd398` | base actuator: wheel angle → steering-wheel deg (ratio + freeplay offset) |
| `0x6fd79c` | base actuator config defaults |
| `0x6fffa4` | EZ-Steer SCM `SetShaftPos` (deg × 120/360) |
| `0x70133c` | SAM200/CUDA `SetShaftPos` (−deg × 4096/360 → `A1 09`) |
| `0x700e14` / `0x70112c` / `0x701450` | SAM200 engage (`A1 3D`) / idle hold (`A1 01 <pos>`) / disengage (`A1 11`) |
| `0x79eb90` | SAM200 `A1` command builder (ctrl bitfield) |
| `0x705490` / `0x705724` | controller gains (approach / online) |
| `0x705a54` | approach / hold heading logic |
| `0x706120` | `UPDATEMAKO` logging/update |
| `0x706804` | Tarragon main step: KF → control law → saturation → output |
| `0x707b3c` | Kalman filter (`UPDATEKF`) |
| `0x1cc7828` / `0x1cc7888` / `0x1cc78d0` | identity / `1000·I` / measurement-noise matrices |
