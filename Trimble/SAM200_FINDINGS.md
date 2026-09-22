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
| `0x1B` | **Likely a position-following-error accumulator.** Normally small (~100-200), spikes to huge values (100k-1.7M+) at the exact moment of a manual wheel-override, then settles back down after the motor auto-disengages. Strong circumstantial fit for "what the disengage-sensitivity threshold is measured against." | 2 disengage traces |
| `0x14`, `0x2A` | Polled continuously as part of the receiver's standard 4-register cycle (`0x14, 0x2A, 0x1B, 0x00`); values change during motion but meaning not decoded. | all traces |

**IMPORTANT correction from earlier in this session:** registers `0x05`/`0x06`
were originally assumed (by us) to be steering *angle/position limits*
("`WRITE_LIMITS`" in the early scripts) based on nothing but the specific
values `19800`/`360` recurring at startup. The disengage-sensitivity traces
prove this was wrong — they're the disengage-sensitivity thresholds, not a
position range. Any script still calling `write_reg(0x05, 19800)` /
`write_reg(0x06, 360)` is actually just setting disengage sensitivity to a
~20%-equivalent value, which happens to be harmless, but the old comments
calling it "limits" are incorrect and should be read as historical.

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

- **Counts-per-degree scale**: still unknown. No captured trace shows the
  motor actually being driven to a known real-world angle (the max-angle
  traces never engaged autosteer). The bridge's `COUNTS_PER_DEGREE` constant
  is a placeholder pending a real calibration trace.
- **`A3` current/torque candidate**: bytes 1-4 are a plausible but unproven
  current/torque channel. Would need a deliberate load test (resist the
  wheel while engaged, watch if these fields scale with resistance) to
  confirm before trusting it.
- **Registers `0x14`, `0x2A`**: read every cycle by both the CFX and our own
  scripts, values change during motion, meaning not decoded.
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
