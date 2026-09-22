# IMD600 / Trimble CFX-750 CAN Protocol — Reverse-Engineering Findings

Bench work reconstructing how the Trimble CFX-750 reads the IMD600 inertial
sensor over CAN (J1939 Proprietary-A, PGN 0xEF00), so its accel/gyro stream
can be consumed directly (bypassing the CFX) and eventually fed to AgOpenGPS.
All findings below are from the same live PCAN captures (`.trc` files in
Documents) used for the SAM200 work — the IMU shares the bus with the motor
and nav controller. Cross-checks against GNSS COG/SOG come from the nav
controller's own N2K broadcasts in the same traces.

## Bus basics

- ISOBUS/J1939, 250 kbit/s. Same physical bus as the SAM200 motor.
- IMU -> nav controller: `ID 0x18EF1C8F` (DA=0x1C nav, SA=0x8F IMU)
- nav controller -> IMU: `ID 0x18EF8F1C` (DA=0x8F IMU, SA=0x1C nav)
- The IMU streams continuously at ~150 CAN frames/s (50 sample-sets/s) and is
  **completely independent of the SAM200** — none of the motor traffic
  touches it, and vice versa.

## Device identity (from a power-cycle capture)

On replug the IMU claims its address and, on request, dumps its ID strings via
transport protocol. Decoded ASCII:

```
TNLID,28,47;VER,1.01,08/01/11;COM,J1939(+);NAME,F412A108103900A0;
*BARRA*604057038*0*83382... / 83390-00*604057038**Trimble*
```

- J1939 NAME: `F412A108103900A0` (matches the address-claim payload
  `18EEFF8F  F4 12 A1 08 10 39 00 A0`)
- Firmware VER 1.01, dated 08/01/11
- ECU tag `BARRA`, P/N **83390-00**, Trimble

(For comparison the SAM200 identifies as ECU `CUDA`, P/N 83382-01, VER 1.04.
Same Trimble app-layer, different board.)

## The sample stream (on `18EF1C8F`, byte0 = `0x0D`)

Each inertial sample is delivered as **3 back-to-back CAN frames**, at 50
sample-sets per second (so ~150 frames/s, confirmed at 150.5 Hz measured).

Frame framing byte is `byte1 = (set_counter << 4) | frame_index`:
- high nibble = rolling set counter `0..F` (ties the 3 frames of one sample together)
- low nibble = frame index `0`, `1`, `2`

### Frame 0 — timebase + temperature candidate

```
0D  (set|0)  00  <ts:u24 LE>  <int16 LE>
    byte2 = 0x00  (constant in every frame across all captures)
    bytes 3-5 = 24-bit little-endian microsecond timestamp, +20000 per set
    bytes 6-7 = int16, ~ -1100 .. -1195
```

- **Timestamp confirmed**: exactly +20000 µs between sets = 20 ms = 50 Hz.
  **Caveat for consumers**: it's only 24-bit, so it wraps every 2^24 µs
  (~16.78 s). Anything integrating dt must handle the modulo-2^24 rollover.
- **int16 field = temperature candidate (unconfirmed).** It sits around
  -1180 and drifts slowly (per-capture means ranged -1104 to -1183 across
  different runs) with no correlation to motion — the classic signature of a
  slow ADC channel, most likely die temperature. Scale/offset to °C not
  established.

### Frame 1 — accelerometer (int16 x3)

```
0D  (set|1)  <X:i16 LE>  <Y:i16 LE>  <Z:i16 LE>
```

- At rest, flat: X ≈ -2, Y ≈ +32, **Z ≈ +900** (gravity on Z).
- Raw counts. Engineering scale below.

### Frame 2 — gyroscope (int16 x3)

```
0D  (set|2)  <X:i16 LE>  <Y:i16 LE>  <Z:i16 LE>
```

- At rest, biases ≈ X 23, Y 11, **Z 15** counts.
- Z is yaw and goes positive during a right/clockwise turn (confirmed against
  GNSS COG in the right-then-left trace: gyro-Z integral tracks the +30° net
  heading change, corr 0.86 over the moving span).

## The calibration blob (`0F C9` -> transport protocol)

On startup (and after a replug) the nav controller requests the IMU's
calibration with a Proprietary-A request `0F C9 00 00 00` on `18EF8F1C`, and
the IMU returns a **107-byte payload via RTS/CTS transport protocol**
(connection-mode, destination-specific — not BAM):

```
IMU  18EC1C8F  10 6B 00 10 FF 00 EF 00   TP.CM RTS: 0x6B=107 bytes, 16 packets, PGN 0xEF00
nav  1CEC8F1C  11 10 01 FF FF 00 EF 00   TP.CM CTS
IMU  18EB1C8F  01 F2 C9 00 ...           TP.DT data packets (16 of them)
nav  1CEC8F1C  13 6B 00 10 FF 00 EF 00   TP.CM EndOfMsgAck
```

Reassembled payload = `F2 C9 00` (response opcode F2, echoing requested msg
C9) followed by **26 IEEE-754 float32 LE**:

| Floats | Interpretation |
|---|---|
| 9 | **Gyro 3×3 matrix**, diagonal `(-0.02, -0.02, +0.02)`, off-diagonals 0 |
| 9 | **Accel 3×3 matrix**, diagonal `(0.0109, 0.0109, -0.0109)`, off-diagonals 0 |
| 6 | Bias terms, all `0.0` in this unit |
| 2 | `1.0, 1.0` — trailing scale factors |

The matrices are the raw→engineering transforms. Diagonal-only here, so in
practice they reduce to per-axis scale + sign:

- **Accelerometer: 0.0109 (m/s²)/LSB.** Check: 900 counts × 0.0109 = 9.81 m/s².
  Z scale is negative, flipping the raw +900 gravity reading into the nav's
  body frame.
- **Gyroscope: 0.02 (°/s)/LSB** per the device's own calibration, X and Y
  negated, Z positive.

**Scale caveat (gyro).** The 0.02 value is what the IMU reports about itself,
so it's the trustworthy figure. Our independent cross-check against GNSS COG
rate landed in the same ballpark but noticeably higher (~0.025–0.035 °/s/LSB
depending on window), but that check is unreliable — it was done at ~0.9 m/s
where COG is very noisy, over a small net heading change. Treat 0.02 as
provisional-but-best until a proper stationary calibration is done (slow,
known-rate turn on the spot, or a turntable). The accel 0.0109 figure is
solid because gravity gives a clean 1 g reference.

## Startup / subscribe sequence

Reconstructed from the IMU-replug capture, in order:

```
1. 18EEFF8F  F4 12 A1 08 10 39 00 A0     IMU address claim (its NAME)
2. 18EF8F1C  0F 33 00 00                 nav: status/version request  -> IMU replies 33 06
3. 18EF8F1C  0F C9 00 00 00              nav: calibration request     -> 107-byte TP blob (above)
4. (ID strings TP dump: TNLID/VER/NAME/BARRA/PN)
5. 18EF8F1C  0F 0D 02 02 00              nav: start the 0D sample stream
   -> IMU begins streaming the 3-frame sets at 50 Hz
```

To pull the stream standalone (IMU alone on the bus, PCAN as SA 0x1C), the
minimum is to send `0F 0D 02 02 00`. The `0F C9` calibration read is optional
— you can just hard-code 0.0109 / 0.02 from this document — but reading it
live is the robust choice in case a different IMD unit ships different scale
factors.

## Heartbeat behaviour (shared with the SAM200 app-layer)

Same `0x01` heartbeat framework as the motor: `01 <ctr> <peer_ctr_echo>
<flag>`, ~2 s cadence, on `18EF8F1C` (nav) and `18EF1C8F` (IMU).

Confirmed dropout signature (useful as a "sensor present" check):

- While the IMU is unplugged, the nav's own counter keeps incrementing but its
  **echo byte freezes** at the last IMU counter it saw
  (`...01 3D 3D 00` → `01 3E 3D 00` → `01 3F 3D 00` ...).
- On replug the IMU's counter restarts at 1, so the nav's echo resyncs to a
  low value (`01 43 01 00`).

## No authentication handshake (contrast with the SAM200)

**The IMU has no `0F 32` challenge/response exchange.** The SAM200's suspected
authentication step (the ~293-byte reply + 16-byte answer that may gate motor
position control) has **no equivalent here** — the IMU goes straight from
address-claim → status → calibration → stream. So unlike the motor, the IMD600
looks freely usable: claim an address, send `0F 0D 02 02 00`, read the stream.
This is the easy half of the system.

## Engineering-unit conversion (summary)

```
accel_mps2  = raw_accel * 0.0109          # Z sign flips into body frame
gyro_dps    = (raw_gyro - bias) * 0.02    # X,Y negated; Z positive = right/CW
                                          # idle bias ≈ (23, 11, 15) counts, re-zero at rest
dt          = 0.020 s per set             # or use the u24 µs timestamp (handle 2^24 wrap)
```

Orientation convention (axis handedness, NED vs ENU, exact roll/pitch signs)
is **not fully pinned down** — only that Z-gyro positive = right turn and
Z-accel carries gravity. Confirm empirically before trusting roll/pitch for
terrain compensation.

## Open questions / unconfirmed

- **Gyro scale**: 0.02 °/s/LSB is device-stated but not independently
  confirmed at a known rate (see caveat). Needs a controlled-rate calibration.
- **Frame-0 int16 = temperature?** Behaves like a slow ADC channel but neither
  the quantity nor its scale/offset is established.
- **Frame-0 byte2 = 0x00** always; purpose unknown (sub-type / reserved).
- **`0F 33` -> `33 06` status code**: the IMU replies `33 06` (the SAM200
  replies `33 06` / `33 03`). Meaning of the code byte not decoded.
- **`0F 0D 02 02 00` parameters**: `02 02 00` presumably enable + rate/format,
  but not varied across captures, so the fields aren't confirmed. We only know
  this exact tuple yields the 50 Hz 3-frame stream.
- **Full axis/orientation convention** for feeding AgOpenGPS roll (and any
  yaw-rate fusion): needs a deliberate tilt/roll test on a known slope.
- **Whether the off-diagonal matrix terms are ever non-zero** on other IMD
  units (misalignment correction) — this unit's were all zero.

## Relevance to the AgOpenGPS bridge

AgOpenGPS mainly wants **roll** (for antenna/terrain compensation) and can use
**heading/yaw-rate** for fusion. Both are available here without any handshake,
which makes the IMD600 a drop-in inertial source once the axis convention and
gyro scale are nailed down. Natural next step mirrors the SAM200 bridge: a
listener that reassembles the 3-frame sets, applies the calibration matrices,
and emits roll (and optionally yaw rate) in the format AgOpenGPS's IMU/roll
path expects — either as the PGN the Teensy firmware already publishes, or
folded into the existing `steertest_agopengps_bridge.py`.
