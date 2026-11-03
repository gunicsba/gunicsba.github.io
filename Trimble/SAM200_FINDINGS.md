# SAM200 / Trimble CFX-750 CAN Protocol — Reverse-Engineering Findings

Bench work reconstructing how the Trimble CFX-750 drives the SAM200 steering
motor over CAN (J1939 Proprietary-A, PGN 0xEF00), so it can be driven directly
(bypassing the CFX) and eventually bridged to AgOpenGPS. All findings below
are from live PCAN captures (`.trc` files in Documents) and bench tests with
a PEAK PCAN-USB adapter, cross-checked against the AgOpenGPS Teensy autosteer
firmware source (`C:\AgOpenGPS\AOG_CAN_Teensy4.1\...`) where relevant.

## Bus basics

- ISOBUS/J1939, 250 kbit/s.
- Command (nav controller -> motor): `ID 0x18EFCD1C` (DA=0xCD motor, SA=0x1C nav)
- Status (motor -> nav controller): `ID 0x18EF1CCD` (DA=0x1C nav, SA=0xCD motor)
- A third node (SA `0x8F`, likely the IMD600 IMU) streams its own traffic
  independently and is unaffected by anything below.

## Command opcodes (on `18EFCD1C`, byte 0 = command)

| Byte0 | Byte1 | Meaning | Notes |
|---|---|---|---|
| `0x0F` | `0xA1 0x01 0x02` | Subscribe to 10 Hz status | sent 3x at startup |
| `0x0F` | `0x33 0x00 0x00` | Request status/version reply | sent alongside subscribe |
| `0xA0` | `0x00 <reg> 0x00` | Register read request | reply echoes reg + int32 value |
| `0xA0` | `0x01 <reg> 0x00 <val:i32 LE>` | Register write | motor echoes the write back on `18EF1CCD` |
| `0xA1` | `0x01 0x00 0x00 <pos:i32 LE>` | "Hold at position X" (disengage-safe hold / handshake pre-step) | see engage sequence below |
| `0xA1` | `0x3D 0x00 0x00 0x00 0x00 0x00 0x00` | Zero counter / enter position control | flips `reg00` toward 3 |
| `0xA1` | `0x09 0x00 0x00 <target:i32 LE>` | **Position setpoint command** | the only real-time drive command; no speed field exists (see below) |
| `0xA1` | `0x11 0x00 0x00 0x00 0x00 0x00 0x00` | Disengage | drops out of position control |
| `0x01` | `<ctr> <motor_ctr_echo> 0x00` | Heartbeat, ~2s cadence | motor replies with its own heartbeat counter |

The `A1` "sub-opcodes" `01/09/11/3D` are really combinations of flag bits on
top of mode 1. The status byte `40` is also a flag bit. See *Cross-check
against the CFX-750 firmware* below.

## Status opcodes (on `18EF1CCD`, from the motor)

| Byte0 | Byte1 | Meaning |
|---|---|---|
| `0xA1` | `0x40 <pos:i32 LE>` | **Actual position feedback** — confirmed, used throughout |
| `0xA0` | `0x00 <reg> <val:i32 LE>` | Register read/write reply |
| `0x01` | heartbeat echo | |
| `0xA2` | `00 00 00 <code> 00 00 00` | **Unsolicited fault/event code.** Always `00 00 00 00 00 00 00` in every idle capture; fires with `code=0x0A` at the exact moment of an operator-override auto-disengage (confirmed in two independent traces, see below). Pushed by the motor without being polled — faster signal than waiting on the next `reg00` read. |
| `0xA3` | 7 data bytes, two int16 fields + 3 more bytes | **Partially decoded, not confirmed.** First two int16 fields sit at `0000 0000` at idle and jump to non-zero, correlated values during an active zero-crossing/engage transient — plausible current/torque candidate, but unconfirmed (see Open Questions). Last 3 bytes in a different capture drifted slowly while fully idle, unrelated to motion — likely a slow ADC channel (temp/voltage), not current. |

## Known registers (read via `0xA0 0x00`)

| Reg | Meaning | Evidence |
|---|---|---|
| `0x00` | **State machine.** `1`=idle, `3`=position control engaged, `4`=idle/ready (seen as the pre-engage default). Confirmed extensively. | dozens of traces |
| `0x05`, `0x06` | **Disengage sensitivity pair**, written together by the CFX when you change that % setting. Both scale *down* as sensitivity % goes *up*: `20%→(19800,360)`, `25%→(18875,350)`, `35%→(17025,330)`. This is the threshold pair behind the auto-disengage fault. | 3 traces, real CFX writes |
| `0x1B` | **Likely motor current.** The CFX firmware decodes it as `sqrt(raw) / 119` (`0x79efb4`), which reads like an I²-type value turned into amps. Normally small (~100-200 raw ≈ 0.1), it spikes to huge values (100k-1.7M+ raw ≈ 3-11) at the exact moment of a manual wheel override, then settles back after the motor auto-disengages. That fits the motor fighting the driver. The earlier "following-error accumulator" reading is probably wrong. | 2 disengage traces + firmware |
| `0x14` | **Controller temperature, °C.** The firmware converts raw → volts (`raw / 1241.21`, i.e. a 12-bit ADC at 3.3 V) and then applies the TI LM20 sensor formula: `T = sqrt((1.8639 − V) / 3.88e-6 + 2196200) − 1481.96` (`0x79eefc`). | firmware |
| `0x2A` | **Supply voltage, V** = `raw × 0.0088623` (`0x79ef74`), i.e. a 12-bit ADC at 3.3 V behind an ~11:1 divider. | firmware |

The CFX polls these in the round-robin `0x14, 0x2A, 0x1B, 0x00`, one
register per call on 4 of every 10 calls (`0x79ee48`). That is the same cycle
our scripts copied.

**IMPORTANT correction from earlier in this session:** registers `0x05`/`0x06`
were originally assumed (by us) to be steering *angle/position limits*
("`WRITE_LIMITS`" in the early scripts) based on nothing but the specific
values `19800`/`360` recurring at startup. The disengage-sensitivity traces
prove this was wrong — they're the disengage-sensitivity thresholds, not a
position range. Any script still calling `write_reg(0x05, 19800)` /
`write_reg(0x06, 360)` is actually just setting disengage sensitivity to a
~20%-equivalent value, which happens to be harmless, but the old comments
calling it "limits" are incorrect and should be read as historical.

## Cross-check against the CFX-750 firmware

Static analysis of the CFX-750 v8.10 display firmware (see
[ROLL_COMPENSATION_FINDINGS.md](ROLL_COMPENSATION_FINDINGS.md) for the image
and tooling) confirms the protocol above. In the firmware the SAM200 is the
**"CUDA"** actuator (`controls/actuators/actuator_cuda.cpp`).

**`A1` byte 1 is a bitfield, not an opcode.** The command builder
(`0x79eb90`) packs:

```
A1 <ctrl> 00 00 <value:i32 LE>
ctrl = mode (bits 0-1, always 1) | 0x04·b | 0x08·c | 0x10·a | 0x20·d
```

| CFX method | Flags | Sent as | Matches |
|---|---|---|---|
| Engage (`0x700e14`) | a, b, c, d | `A1 3D 00 00 00000000` | engage step 3 |
| Hold/sync, every 10th tick **while not engaged** (`0x70112c`) | none | `A1 01 00 00 <current pos>` | engage step 2 (the echo fix) |
| Disengage (`0x701450`) | a | `A1 11 00 00 00000000` | disengage |
| `SetShaftPos`, **only while engaged** (`0x70133c`) | c | `A1 09 00 00 <counts>` | the 50 Hz setpoint stream |

So the CFX itself keeps sending `A1 01 <pos>` while idle. That explains why
engaging only became reliable once we echoed the position first.

**Status parsing** (`0x79f2d8` dispatches on byte 0):
- `A1` status (`0x79e81c`): byte 1 bit 6 (`0x40`) is a flag, bytes 2-5 are
  the **position (i32)**, and byte 7 is a separate status byte the CFX stores.
- `A2` (`0x79e8ac`): the fault code is a u16 built from bytes 3-4. The
  observed `0x0A` override code fits.
- `A0` (`0x79e970`): byte 1 = read/write, u16 register, i32 value.
- `A3` is parsed into a structure that wasn't decoded.

**Counts are motor-encoder clicks, 4096 per revolution.** `SetShaftPos`
converts degrees of motor-shaft (steering-wheel) rotation as

```c
counts = (int)(-deg * 4096.0 / 360.0);     // 11.378 counts per steering-wheel degree, sign inverted
```

The minus sign is the same direction flip we found by trial
(`MOTOR_DIRECTION = -1`). Both the command (`A1 09`) and the feedback
(`A1 40`) are in these clicks, relative to the zero set by `A1 3D` at engage.

**How the CFX gets from wheel angle to `deg`** (base actuator `0x6fd398`):

```c
sw_deg  = theta_wheel_deg * (2*PI / AnglePerTurn);  // steering ratio from the APT calibration
sw_deg += freeplayOffset;   // +FreeplayRight / -FreeplayLeft, applied when the commanded angle reverses
counts  = -sw_deg * 4096 / 360;
```

So **counts per degree of wheel angle = 4096 / AnglePerTurn_deg**. At the
firmware default of 20° per steering-wheel turn that is about **205**. The
real value is vehicle-specific and comes from the angle-per-turn calibration.
Above 2 m/s a small speed- and rate-dependent extra term (logged as
`valveDeadBand`) is also added; it wasn't decoded further.

**Disengage-sensitivity formula** (`0x700f50`):

```c
r     = 100 - pct;          // pct clamped to <= 100
reg05 = r * 185 + 5000;     // asserted <= 23500
reg06 = r * 2   + 200;      // asserted <= 400
```

This reproduces all three captured pairs exactly: 20% → 19800/360,
25% → 18875/350, 35% → 17025/330. Because `0x1B` looks like a current value,
reg `0x05` is most likely the current threshold and reg `0x06` probably a
time or filter length (unconfirmed).

## The engage sequence (validated fix)

The motor does **not** reliably re-enter position control (`reg00 -> 3`) just
by sending `A1 3D`. Reverse-engineered from a real successful CFX engage
(`trimble drive straight.trc`, ~msg 2665-2710):

```
1. Wait for a real position reading (A1 40) -- don't engage on pos=None
2. Send A1 01 <that same actual position>   (echo/sync step)
3. Send A1 3D 00 00 00 00 00 00             (zero counter / engage)
4. Start streaming A1 09 <target> immediately
-> reg00 reaches 3 within ~100-800ms
```

Skipping step 2 (which every one of our early scripts did) is why engagement
was inconsistent — it worked once by luck (motor was freshly power-cycled,
in the receptive `reg00=4` idle state) and then failed every subsequent
attempt in the same session.

**Once `reg00` drops out of 3 (whether via our own failed re-engage attempt
or a real auto-disengage), it does not recover on its own.** Confirmed dead
ends: waiting longer before retry, adding a settle pause, manually nudging
the wheel. The only thing that reliably reset it back to the receptive state
was **power-cycling the SAM200**. The position-echo fix above (validated
after a power cycle) has not yet been re-tested specifically against a
genuinely stuck (`reg00=1`) motor without a power cycle in between — that's
still an open question, not a confirmed second fix for that specific case.

## Automatic disengage on operator override

Confirmed in two independent recordings ("holding the wheel" and "turning
the wheel 90 degrees") with the CFX connected and actively steering:

- `reg00` drops from 3 to 4 within ~200-800ms of the operator physically
  resisting/turning the wheel.
- An unsolicited `A2 00 00 00 0A 00 00 00` fires in the same window in
  **both** traces (identical fault code `0x0A`), never seen at any other
  time in any capture.
- Register `0x1B` spikes hugely in the same window (see table above).

Conclusion: the SAM200 has its own onboard following-error safety cutout,
independent of the CFX. It watches (very likely) reg `0x1B` against the
`0x05`/`0x06` sensitivity threshold and disengages itself when forced off
its commanded position — this is the real mechanism behind "let go of the
wheel to disengage," not something the CFX has to explicitly detect and
command.

## CFX settings: what actually reaches the motor over CAN

Six settings traces recorded with the CFX doing the writing. Only one of
them produces any CAN traffic:

| CFX setting | Reaches the motor via CAN? | Notes |
|---|---|---|
| Disengage sensitivity (20/25/35%) | **Yes** — writes reg `0x05`/`0x06` | confirmed values above |
| Max angle allowed (40°/45°) | No — zero register writes, zero `A1 09` traffic | traces never showed autosteer actually engaged; likely a CFX-internal clamp on what it will ever *request* |
| Degree/second limit (20/40) | No — `reg00` stuck at 1 (idle) throughout, no writes | same conclusion: CFX-side ramp-rate limit, never sent to the motor |
| Degree/second² limit (50/90) | No — same | CFX-side acceleration/jerk limit |

**Caveat:** none of the max-angle or deg/s(²) traces actually had autosteer
engaged during capture, so "no CAN effect" is confirmed for the *settings
themselves*, but we have not yet captured a trace proving these limits are
respected (or ignored) *while actively driving*. The architectural
conclusion (motor has no native concept of max angle/speed/accel; it's all
shaped client-side before the position value is ever sent) is strongly
supported but rests on absence of evidence for the writes, not a positive
test of the CFX's ramping behavior under each setting.

## How "speed" actually works (no native speed mode)

Checked all 3,010 `A1 09` messages captured across every trace (ours and the
real CFX's): bytes 2-3 are `00 00` in every single one. The command is fully
packed as `[0xA1, 0x09, reserved, reserved, position:i32 LE]` — there is no
velocity/speed field anywhere in this message.

Confirmed directly from `trimble drive straight.trc`: the CFX sends a new
`A1 09` roughly every 20ms (~50Hz) with the target nudged by a small,
continuously-varying delta (observed deltas from -10 to +29 counts/tick
during real steering corrections) — never one large jump. "Speed" is
entirely an emergent property of how fast the sender changes the setpoint
between messages, shaped by (a) the CFX's own deg/s and deg/s² limits and
(b) its live steering PID reacting to GPS/heading error.

This is exactly the model our own bridge implements: a rate-limited ramp
toward the desired target, using a port of the real Teensy firmware's
`AutosteerPID.ino` proportional/soft-landing shape (`calcSteeringPID()`),
just outputting counts/sec instead of raw PWM duty. The same approach could
be ported into the actual Teensy `CAN_All_Brands.ino` firmware as a new
brand handler: replace `motorDrive()`'s PWM output with an accumulator that
integrates `pwmDrive` into a running position target and sends it as `A1 09`.

## Open questions / unconfirmed

- **Counts-per-degree scale**: *resolved from the firmware* — 4096 counts per
  steering-wheel revolution, so `4096 / AnglePerTurn_deg` counts per degree of
  wheel angle (about 205 at the default 20°/turn). Still needed: the
  AnglePerTurn of the actual test tractor (run the CFX's APT calibration, or
  measure the wheel angle for a known number of steering-wheel turns). The
  bridge's `COUNTS_PER_DEGREE = 550` was a guess and is probably about 2.7×
  too high.
- **`A3` current/torque candidate**: bytes 1-4 are a plausible but unproven
  current/torque channel. Would need a deliberate load test (resist the
  wheel while engaged, watch if these fields scale with resistance) to
  confirm before trusting it.
- **Registers `0x14`, `0x2A`, `0x1B`**: decoded from the firmware
  (temperature, supply voltage, likely motor current; see the register
  table). They are not yet checked against live values.
- **Meaning of reg `0x06`** in the disengage pair: the formula is known, the
  unit isn't.
- **`reg00` full state table**: only `1`, `3`, `4` observed and partially
  understood (`3`=engaged, `1`/`4`=not engaged in two apparently different
  idle flavors — the distinction between them, if any, isn't nailed down).
- **Whether the position-echo engage fix recovers a genuinely stuck
  (`reg00=1`) motor** without a power cycle — not yet re-tested after the
  fix was added.

## Scripts built this session (all in this folder)

| File | Purpose |
|---|---|
| `steertest.py` | Original bench triangle-wave driver (motor alone on bus) |
| `steertest_halfway.py` | One-shot slow-out / dwell / fast-return motion profile |
| `steertest_rightpause.py` | Turn-right / hold / slow-return profile; carries the validated engage-sequence fix |
| `steertest_agopengps_bridge.py` | Live bridge: listens for AgOpenGPS's real PGN 254 (steer setpoint) + PGN 252 (Kp/PWM settings) over UDP 8888, drives the SAM200 accordingly, replies with PGN 253 so AgOpenGPS sees a connected module. Includes direction flip, and the ported rate-limiter described above. |
