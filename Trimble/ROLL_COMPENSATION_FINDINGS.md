# CFX-750 Roll / Terrain Compensation — Firmware Reverse-Engineering Findings

How the Trimble CFX-750 turns raw accelerometer and gyro data into a roll
angle and uses it to correct the GNSS position. Everything here comes from
static analysis of the display firmware **v8.10** (`v8_10_CFX_750_Firmware.img`,
build date Aug 7 2019). Nothing was confirmed with live captures. This
document complements [IMD_FINDINGS.md](IMD_FINDINGS.md), which covers the IMD-600
CAN stream, and [SAM200_FINDINGS.md](SAM200_FINDINGS.md), which covers the motor.

**TL;DR.** The roll angle comes from **accelerometer and roll gyro only**,
fused in a PI complementary filter. GNSS never measures roll directly, but
**GNSS speed × fused yaw rate** is used to remove centripetal acceleration
before the accelerometer roll is computed. The resulting roll, together with
the heading, rotates the antenna lever arm to project the antenna down to the
ground. **Pitch is forced to 0** in that projection.

## The firmware image

- 256-byte header tagged `SATURN`, followed by a single zlib stream. It
  inflates to a 33.4 MB raw image.
- Big-endian PowerPC (**Freescale MPC5121e**) running **eCos**. No Linux and no
  filesystem image inside.
- **Load base is 0**: file offsets equal runtime addresses. This was confirmed
  by matching `lis/addi` string references.
- The same image covers the CFX-750 and the FM-750. The platform codename is
  "Saturn" and the UI family is "jamocha".
- Many source paths survive in assert strings, which is how the modules
  below were located.

Tooling used: Python `zlib` to unpack, a strings dump, and `capstone` (PPC32 BE)
plus small scripts that resolve `lis/addi` pairs, find `bl` callers, and
decode jump tables.

## Modules involved

| Source file (from asserts) | Role |
|---|---|
| `controls/rollFilter/roll_filter.c` | The roll complementary filter object |
| `sensor/rh_filter_wrapper.cpp` | Roll/heading wrapper: builds the accel roll measurement, runs both filters, projects the antenna |
| `controls/headingFilter/t2hf_impl.c` | Heading filter (yaw gyro + GNSS); supplies the heading, yaw rate and speed used here |
| `sensor/sn_task.cpp` | Sensor task: receives IMU blocks and runs a 50 Hz tick |
| `controls/actuators/actuator_scm*` | EZ-Steer (T2) controller: raw IMU counts over CAN |
| `controls/actuators/actuator_cuda.cpp` | EZ-Pilot / SAM-200 ("CUDA") path — **not traced** |
| `peripherals/imu/InertialDevice*.cpp` | External IMU, i.e. the IMD-600 ("BARRA") |
| `wizards/wizard_t2_roll_cal.cpp`, `wizard_barra_roll_cal.cpp` | Roll-offset calibration for the T2 and the IMD-600 |

Related config keys: `RollOffset`, `VehicleIMU`, `VehicleIMUCalDone`,
`VehicleIMUOrientationIsYPR`, `VehicleIMUOrientationEnum`,
`VehicleIMUOrientation{Yaw,PitchKey,Roll}`, `VehicleIMURollOffsetAngle`,
`VehicleIMURollOffsetDistance`, `AntennaHeight`, `AntennaToAxle`.

## IMU data block

Each IMU source posts a block of 8 doubles to the sensor task (message 1,
sub-type 0x24). The sensor task stores it unchanged.

| Index | Content |
|---|---|
| [0] | timestamp (int, ms) |
| [1] [2] [3] | accel X, **Y (lateral)**, Z — m/s² |
| [4] [5] [6] | gyro **X (roll rate)**, Y, **Z (yaw rate)** — rad/s |

The roll path uses only **accel Y**, **gyro X** and **gyro Z**.

### EZ-Steer T2 source (`0x6fec78..0x6fee38`)

The T2 controller sends **raw ADC counts** over CAN. The display only scales
them:

```
accel = raw * 9.80665 / (scale * range)          // -> [1], [2]
gyro  = raw * 1000 / scale * (pi/180)            // -> [4], [6]
```

The block is posted only once all 4 parts (status mask `0xF`) have arrived.
Otherwise the firmware logs `Missing IMU Data: status = %u`. All the fusion
happens on the display.

### IMD-600 source (IMU type 2, `0x70d3a8..0x70d40c`)

1. The block is rotated through the **mounting-orientation matrix**. That
   matrix is built from the configured yaw/pitch/roll by `0x70bd20` and applied
   by `0x70bff0`. `0x70ca78` is the same kind of Euler-to-3×3 builder.
2. Unit and sign fix-up after rotation:
   - gyro X × `+π/180`
   - gyro Y, Z × `−π/180`
   - accel Y, Z negated

   That is deg/s → rad/s plus a 180° flip about X.

This lines up with [IMD_FINDINGS.md](IMD_FINDINGS.md): the IMD-600 reports its
gyro in °/s (0.02 °/s/LSB), and the display converts it.

## Roll measurement from the accelerometer (`0x70d450..0x70d524`)

```c
a_lat  = imu.accel_y;
a_lat += speed * yawRate * cos(RollOffset);   // centripetal compensation
a_lat  = slew_limit(a_lat, a_lat_prev,
                    dt_ms * 25.0 / 1000);     // max 25 m/s² per s (0.5 per 20 ms sample)
a_lat_prev = a_lat;
roll_meas  = asin(clamp(a_lat / 9.80665, -1, +1)) - RollOffset;
roll_rate  = imu.gyro_x;
```

- `yawRate` (wrapper `+0x28`) and `speed` (wrapper `+0x30`) come from the
  heading filter output. `+0x30` is confirmed as speed by the dead-reckoning
  step (`speed · dt`); `+0x28` is therefore the yaw rate.
- `RollOffset` (wrapper `+0x328`) is the calibrated mounting tilt.
- If the IMU state is bad (state > 1), both the measurement and the rate are
  set to 0.
- The yaw gyro sent to the heading filter is also corrected for the mounting
  tilt: `yawRate_in = -gyro_z / cos(RollOffset)` (`0x70d648`).

## The roll complementary filter (`roll_filter.c`, update at `0x704f10`)

This is a small object (0x90 bytes, constructor `0x705284`) with a table of 7
function pointers: init, update, set inputs, get outputs, set gains, get
gains, and dump state.

Inputs: `[meas, rate, unused, unused, dt]`. The two middle values are filled
but never read by the update. Gains: `[Ki, Kp, unused]`.

```c
e      = roll_meas - roll;
integ += e * dt;                       // learns gyro bias
rate   = roll_rate + Ki * integ + Kp * e;
roll  += rate * dt;
// outputs: roll (+0x48), rate (+0x50)
```

The loop's characteristic polynomial is `s² + Kp·s + Ki`, so
`ωn = √Ki` and `ζ = Kp / (2√Ki)`.

**Bumpless gain changes** (`0x70503c`): when new gains are set and the new Ki
is not 0, the integrator is rescaled so the output does not jump:

```c
integ = (Ki_old * integ + (Kp_old - Kp_new) * (meas - roll)) / Ki_new;
```

### Gain schedule (`0x70ccd4`, selected via `0x70cda8(mode)`)

| Mode | Ki | Kp | ωn [rad/s] | ζ | When |
|---|---|---|---|---|---|
| 0 | 1.0 | 2.0 | 1.00 | 1.00 | Startup / initialisation |
| 1 | 0.5 | 0.85 | 0.71 | 0.60 | While a roll-calibration wizard runs |
| 2 | 0.025 | 0.333 | 0.16 | 1.05 | Normal running |

The switch to mode 2 happens **10 s after startup**. The wrapper keeps a
millisecond counter at `+0x2ac` (`+= dt_ms`) and changes mode when it equals
`10000`. The calibration wizards also restore mode 2 when they finish.

In mode 2 the accelerometer correction has a time constant of several
seconds, so short disturbances (bumps, sway) are ridden out mostly on the
gyro.

Timing: the filter runs on the sensor task's 50 Hz tick. `dt = dt_ms / 1000`
in the main path; only the first-pass path hard-codes `0.02`.

## Roll-offset calibration (`wizard_t2_roll_cal.cpp`, `wizard_barra_roll_cal.cpp`)

The user drives one line on level ground, then drives it again in the
opposite direction. The wizard stores:

```c
RollOffset = (roll_dir1 + roll_dir2) / 2;   // clamped to ±90°
```

The true ground slope flips sign between the two directions and cancels out,
leaving only the sensor's mounting tilt. The filter runs in mode 1 during the
wizard and is set back to mode 2 afterwards.

## Applying roll to the position (`0x70d8a8..0x70d944`)

```c
R = EulerToMatrix(pitch = 0.0, roll, PI/2 - heading);   // 0x70ca78
controlPoint = antennaPos - R * leverArm;               // ENU components at wrapper +0x1a0..+0x1b0
```

- `roll` is the filter output and `heading` is the heading-filter output.
- `π/2 − heading` converts a compass heading to a math angle.
- **Pitch is hard-coded to 0.0**, so there is no fore/aft (pitch) compensation.
- `leverArm` (3 doubles) comes from the GPS sensor object (vtable slot
  `0x10`). Its contents are inferred from the config keys: `AntennaHeight`
  and probably `AntennaToAxle`. With a purely vertical arm `h`, this reduces
  to a lateral shift of `h·sin(roll)` and a drop of `h·(1 − cos roll)`.
- The projection runs only on ticks with a **new GNSS fix** (wrapper flag
  `+0x10`). On the 50 Hz ticks in between, the position is **dead-reckoned**
  instead (`0x70d948`): `pos += speed·dt·(sin heading, cos heading)`.

## Reference implementation (for AgOpenGPS)

```c
// once per IMU sample (50 Hz)
double a = accel_y + speed * yaw_rate * cos(roll_offset);
a = clamp(a, a_prev - 25.0*dt, a_prev + 25.0*dt);  a_prev = a;
double meas = asin(clamp(a / 9.80665, -1, 1)) - roll_offset;

double e = meas - roll;
integ += e * dt;
roll  += (gyro_x + Ki*integ + Kp*e) * dt;

// gains: (Ki,Kp) = (1.0, 2.0) for the first 10 s, then (0.025, 0.333)
// on gain change: integ = (Ki_old*integ + (Kp_old-Kp_new)*e) / Ki_new
// offset cal: roll_offset = mean(roll measured driving the line both ways)
```

## Open questions / not traced

- **Exact lever-arm contents** (which config value goes into which component)
  and the sign conventions for roll and lateral offset.
- **The sign of the centripetal term in a real turn**, which depends on the
  heading filter's yaw-rate sign convention.
- **The EZ-Pilot / SAM-200 ("CUDA") IMU path** (`0x702xxx`). It has its own
  trig (cos/asin) and may pre-process the data differently.
- **Autopilot (NAV controller)** systems: there, terrain compensation runs
  inside the controller, not in this code.
- **The heading filter internals** (`t2hf_impl.c`). It receives roll and roll
  rate, probably to remove antenna sway from the GNSS velocity, but this
  wasn't decoded.
- **The two unused filter inputs and the unused third gain.** They are kept
  for logging (`%f,%f,%f,%f,%f` dump at `0x7051a8`).

## Address index (v8.10 image, base 0)

| Address | What |
|---|---|
| `0x704f10` | roll filter update |
| `0x70503c` | roll filter set gains (bumpless) |
| `0x705284` | roll filter constructor |
| `0x70c0f0` | wrapper constructor |
| `0x70c2f4` | wrapper first-pass processing (fixed dt 0.02, mode-0 gains) |
| `0x70c80c` | IMU age/validity check (`IMU reading missed…`) |
| `0x70ca78` | Euler → 3×3 rotation matrix |
| `0x70ccd4` / `0x70cda8` | gain-mode select |
| `0x70cdb0` / `0x70cdb8` | set / get `RollOffset` |
| `0x70d264` | wrapper main per-sample update (centripetal comp, filter, antenna projection) |
| `0x70bd20` / `0x70bff0` | IMD-600 mounting-orientation matrix build / apply |
| `0x6fec78..0x6fee98` | EZ-Steer T2 raw IMU scaling and posting |
| `0x70a9cc` | post IMU block to the sensor task |
| `0x588d10..0x58904c` | T2 roll-calibration wizard (two-way average) |
| `0xe2cf14` / `0xe2d6cc` / `0xe2b324` | libm `cos` / `sin` / `asin` |
