# GNSS / NMEA-2000 Broadcast — Reverse-Engineering Findings

The Trimble CFX-750 nav controller (SA `0x1C`) broadcasts its full GNSS
solution on the same CAN bus as the SAM200 motor and IMD600 IMU. Unlike the
Proprietary-A motor/IMU traffic, this is **standard J1939 + NMEA-2000**, so
the layouts are public and decode without reverse-engineering — the work here
is confirming which PGNs the CFX actually emits, at what rate, and cross-
checking the values. All figures below are from the same `.trc` captures in
Documents (primarily `trimble drive straight.trc`).

## Why this matters

Between the three nodes, a single CAN tap exposes the **whole guidance stack**:
RTK position + heading from `0x1C` (this doc), roll from the IMD600, and
steering command/feedback from the SAM200. Position for AgOpenGPS could come
off CAN instead of a separate serial-NMEA tap from the receiver — one fewer
cable, and the RTK fix-quality flag comes along for free.

## Bus basics

- ISOBUS/J1939, 250 kbit/s. Same physical bus as motor + IMU.
- All GNSS traffic is **broadcast from SA `0x1C`** (global destination), so no
  request/subscribe is needed — just listen.
- Nothing here has to be solicited and nothing acknowledges; it's free-running
  telemetry.

## PGN inventory (all from SA 0x1C)

| CAN ID | PGN | Name | Rate | Transport |
|---|---|---|---|---|
| `19F8051C` | 129029 (0x1F805) | GNSS Position Data | 1 Hz | N2K fast-packet |
| `19F8021C` | 129026 (0x1F802) | COG & SOG, Rapid Update | 1 Hz | single frame |
| `19F0101C` | 126992 (0x1F010) | System Time | 0.2 Hz | single frame |
| `18FEF31C` | 65267 (0xFEF3) | Vehicle Position (VP1) | 1 Hz | single frame |
| `18FEE81C` | 65256 (0xFEE8) | Vehicle Direction/Speed (VDS) | 1 Hz | single frame |
| `18FEE61C` | 65254 (0xFEE6) | Time/Date (TD) | 1 Hz | single frame |

## 129029 — GNSS Position Data (the important one)

NMEA-2000 fast-packet, 43-byte payload reassembled from 7 CAN frames. Standard
layout, confirmed byte offsets:

| Bytes | Field | Encoding |
|---|---|---|
| 0 | SID | sequence id |
| 1–2 | Position date | u16, days since 1970-01-01 |
| 3–6 | Position time | u32, ×0.0001 s (UTC seconds of day) |
| 7–14 | Latitude | i64, ×1e-16 deg |
| 15–22 | Longitude | i64, ×1e-16 deg |
| 23–30 | Altitude | i64, ×1e-6 m (**ellipsoidal**) |
| 31 | Type / Method | low nibble = GNSS type, high nibble = method |
| 32 | Integrity | 2 bits + reserved |
| 33 | Number of SVs | u8 |
| 34–35 | HDOP | i16, ×0.01 |
| 36–37 | PDOP | i16, ×0.01 |
| 38–41 | Geoidal separation | i32, ×0.01 m |
| 42 | Reference stations | u8 (+ per-station data if present) |

**Method nibble** (byte 31 >> 4) is the RTK status, and it's the headline:
`0`=no GNSS, `1`=GNSS, `2`=DGNSS, `3`=Precise, **`4`=RTK Fixed**, `5`=RTK Float,
`6`=dead-reckoning, `7`=manual, `8`=simulate.

**Type nibble** (byte 31 & 0x0F): `0`=GPS, `1`=GLONASS, `2`=GPS+GLONASS, etc.

Decoded snapshot:

```
lat 47.5313844   lon 20.1413136   alt 138.41 m (ellipsoidal)
method 4 = RTK FIXED,  type 0 = GPS,  sats 11-12,  HDOP 0.94,  PDOP 1.92
geoidal separation 40.92 m
```

Across the run the fix held at `(type 0, method 4)` with 11–12 SVs the whole
time — a solid RTK-fixed solution.

## 129026 — COG & SOG, Rapid Update

Single frame:

| Bytes | Field | Encoding |
|---|---|---|
| 0 | SID | |
| 1 | COG reference | bits 0–1: 0=true, 1=magnetic |
| 2–3 | COG | u16, ×0.0001 rad |
| 4–5 | SOG | u16, ×0.01 m/s |
| 6–7 | reserved | |

Snapshot: COG 276.4°, SOG ~0 (stationary in this capture). COG is only
meaningful while moving — at rest it holds the last valid heading and SOG
reads ~0, so it is **not** a substitute for a real heading sensor at low speed.

## 65267 — Vehicle Position (VP1, J1939)

The lower-resolution J1939 twin of 129029's lat/lon:

| Bytes | Field | Encoding |
|---|---|---|
| 0–3 | Latitude | u32, ×1e-7 deg, offset −210 |
| 4–7 | Longitude | u32, ×1e-7 deg, offset −210 |

Snapshot: lat 47.5313843, lon 20.1413135 — agrees with 129029 to 1e-7 (its
full resolution). No altitude or quality here; if you're reading CAN, prefer
129029.

## 65256 — Vehicle Direction/Speed (VDS, J1939)

| Bytes | Field | Encoding |
|---|---|---|
| 0–1 | Compass bearing | u16, ×1/128 deg |
| 2–3 | Nav-based speed | u16, ×1/256 km/h |
| 4–5 | Pitch | u16, ×1/128 deg, offset −200 |
| 6–7 | Altitude | u16, ×0.125 m, offset −2500 (**MSL**) |

Snapshot: bearing 276.4° (matches COG), speed ~0, altitude 97.4 m.

**Pitch is not populated** — the raw field is `0x0000`, which through the
−200° offset reads as a nonsense −200°, i.e. "no data." So there is no usable
attitude here; roll/pitch must come from the IMD600.

## 65254 — Time/Date and 126992 — System Time

Two independent UTC clocks. TD (J1939):

| Byte | Field | Encoding |
|---|---|---|
| 0 | Seconds | ×0.25 s |
| 1 | Minutes | |
| 2 | Hours | |
| 3 | Month | |
| 4 | Day | ×0.25 day |
| 5 | Year | offset +1985 |
| 6–7 | Local min/hour offset | |

Snapshot: **2026-09-21 12:48:22 UTC.** System Time (126992: SID, source
nibble, u16 date-days, u32 time-×0.0001 s) gives the same instant at 0.2 Hz.

## Validation cross-check (why the decode is trustworthy)

The altitudes come from two differently-encoded messages and reconcile
exactly:

```
129029 ellipsoidal alt   138.41 m
  −  129029 geoidal sep    40.92 m
  =                        97.49 m  ≈  65256 VDS MSL altitude 97.4 m   ✓
```

Independent encodings agreeing to 0.1 m confirms the field offsets and scales
are right, not just internally consistent.

## Caveats

- **All GNSS PGNs are 1 Hz in these captures** (System Time 0.2 Hz). Fine for
  logging, slow for tight autosteer. The CFX may allow a higher position
  output rate — not tested. This is the rate the CFX chose to emit, not a bus
  limit.
- **No usable pitch/roll** on the bus (VDS pitch is blank); use the IMD600.
- **COG/SOG are motion-derived** — no valid heading at standstill.
- Geoidal-separation resolution assumed at ×0.01 m; the altitude cross-check
  validates it for this unit.

## Open questions

- Whether the CFX can be configured to output position faster than 1 Hz (5/10
  Hz), and whether COG/SOG rapid update speeds up with it.
- Reference-station block in 129029 (byte 42 onward) — not parsed; would carry
  RTK base-station id / age-of-corrections if present.
- Integrity byte (129029 byte 32) — always seen as default; not exercised.

## Relevance to the AgOpenGPS bridge

AgOpenGPS needs position + heading + fix status, and all three are here
without any handshake — just a passive listener. Natural implementation
mirrors the other bridges: reassemble 129029 (fast-packet), read the method
nibble for RTK status, and emit position to AgOpenGPS in its expected form
(NMEA GGA/VTG synthesized from these fields, or the PGN the Teensy firmware
already publishes). Combined with IMD600 roll and SAM200 steering, the entire
guidance loop is readable — and mostly writable — off one CAN tap.
