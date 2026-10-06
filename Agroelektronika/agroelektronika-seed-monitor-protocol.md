# Agroelektronika Seed Monitor Controller Protocol

Reverse-engineered serial protocol of the Agroelektronika seed monitor controller (up to 12 sensors), based on oscilloscope measurements and RS232 sniffing.

## Physical layer

| Parameter | Value |
|---|---|
| Interface | RS232 (normal polarity: idle = negative) |
| Baud rate | 9600 |
| Frame format | 8N1 |
| Bit time | ~104 µs |
| Measured levels | idle ≈ −1 V, space (logic 0) ≈ +5 V (with USB-RS232 adapter connected) |

### Notes on levels

- The signal levels are weak and **out of RS232 spec** (spec requires below −3 V / above +3 V).
- Without the adapter connected, idle was measured at ≈ −8 V and the positive level at ≈ +2 V, so the levels shift depending on load.
- A MAX232/ST232-class receiver (threshold ≈ 0.8–2.4 V) reads the signal correctly at the levels measured with the adapter connected, but the margin is small.
- If reception is unreliable, use a receiver that switches around 0 V, such as an NPN transistor stage or an LM393 comparator feeding a TTL UART.

## Framing and timing

- One message = **2 bytes** ≈ 2.08 ms on the wire (20 bits).
- Messages repeat every **≈ 4 ms**, about 250 messages per second.
- The gap between messages is ≈ 1.9 ms.
- The message is sent continuously, even when no sensor is active.

## Message format

| Byte | Bit 7 | Bit 6 | Bit 5 | Bit 4 | Bit 3 | Bit 2 | Bit 1 | Bit 0 |
|---|---|---|---|---|---|---|---|---|
| 1 | **1** (sync) | S12 | S11 | S10 | S9 | S8 | S7 | 1 (?) |
| 2 | **0** | S6 | S5 | S4 | S3 | S2 | S1 | 0 (?) |

- **Bit 7** marks the byte position: `1` = first byte, `0` = second byte. This allows resynchronisation at any point in the stream.
- **Bits 1–6** hold 6 sensor flags per byte. A bit set to `1` means the sensor is active.
- **Bit 0** has been constant so far: `1` in byte 1 and `0` in byte 2. Its meaning is unknown (see open questions).
- Multiple active sensors are OR-ed together.

Idle message (no sensor active): `81 00`

## Sensor mapping

| Sensor | Message | Status |
|---|---|---|
| none | `81 00` | verified |
| 1 | `81 02` | verified |
| 2 | `81 04` | verified |
| 3 | `81 08` | verified |
| 2 + 3 | `81 0C` | verified |
| 4 | `81 10` | predicted |
| 5 | `81 20` | predicted |
| 6 | `81 40` | predicted |
| 7 | `83 00` | verified |
| 8 | `85 00` | verified |
| 9 | `89 00` | predicted |
| 10 | `91 00` | predicted |
| 11 | `A1 00` | verified |
| 12 | `C1 00` | verified |

## Decoding

### Formula

```
sensors = ((b1 >> 1) & 0x3F) << 6 | ((b2 >> 1) & 0x3F)
```

Bit 0 of `sensors` corresponds to sensor 1 and bit 11 to sensor 12.

### C example (byte-by-byte, with sync)

```c
#include <stdint.h>
#include <stdbool.h>

static uint8_t first_byte;
static bool have_first = false;

/* Feed every received byte. Returns true when a full message is decoded. */
bool seedmon_feed(uint8_t b, uint16_t *sensors)
{
    if (b & 0x80) {              /* first byte (sync) */
        first_byte = b;
        have_first = true;
        return false;
    }
    if (!have_first) {           /* second byte without a first: drop */
        return false;
    }
    have_first = false;
    *sensors = (uint16_t)(((first_byte >> 1) & 0x3F) << 6)
             | (uint16_t)((b >> 1) & 0x3F);
    return true;
}
```

## Sniffing setup used

- Oscilloscope: Hantek with OpenHantek (bit timing, levels).
- FTDI-based USB-RS232 adapter (DB9 male): signal to **pin 2 (RX)**, ground to **pin 5 (GND)**, common ground with the device.
- RealTerm: 9600 8N1, flow control None, hex display.
- The controller board contains an **ST232C** (MAX232-compatible) transceiver. The TTL-side pins (R1OUT/R2OUT, T1IN/T2IN) can be used as an alternative tap point with 5 V TTL levels.

## Open questions

- **Bit 0** meaning: possibly a fixed marker or a status/alarm flag. Check while disconnecting sensors, triggering alarms or changing settings.
- **Other direction**: only one line has been captured so far. Check whether the display or console sends anything back on the other wire.
- **Predicted mappings** (sensors 4, 5, 6, 9, 10) still need confirmation.
- **Sensor semantics**: whether "active" means seed pass detection, blockage or another condition, and how pulse frequency relates to seed rate.
- **Source of the weak levels**: whether the out-of-spec levels are by design or a sign of a weak or degraded driver.
