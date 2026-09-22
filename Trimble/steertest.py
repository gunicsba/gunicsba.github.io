#!/usr/bin/env python3
"""
SAM200 motor bench-drive over PCAN, reconstructed from Trimble .trc captures.

We impersonate the nav controller (SA 0x1C) and command the SAM200 (SA 0xCD)
using Proprietary-A (PGN 0xEF00).

  command  -> ID 0x18EFCD1C  (DA=CD motor, SA=1C us)
  status   <- ID 0x18EF1CCD  (from the motor)

RUN THIS WITH THE MOTOR ALONE ON THE BUS (real receiver unplugged) and with the
output mechanically decoupled or wheels off the ground. It moves a steering
motor closed-loop to a position setpoint.

Requires: python-can, a PEAK PCAN adapter.  ISOBUS/J1939 = 250 kbit/s.
"""

import can
import struct
import threading
import time

CHANNEL   = "PCAN_USBBUS1"
BITRATE   = 250000

MOTOR_SA  = 0xCD
OUR_SA    = 0x1C
CMD_ID    = 0x18EF0000 | (MOTOR_SA << 8) | OUR_SA   # 0x18EFCD1C
STAT_ID   = 0x18EF0000 | (OUR_SA  << 8) | MOTOR_SA  # 0x18EF1CCD

# --- what to attempt --------------------------------------------------------
WRITE_LIMITS = True     # write reg 0x05=19800, 0x06=360 first (receiver does this)
TARGET_MAX   = 400      # peak position command in encoder counts (start SMALL)
RAMP_CPS     = 200      # ramp rate, counts per second
# ---------------------------------------------------------------------------

REG_CYCLE = [0x14, 0x2A, 0x1B, 0x00]   # the four reads the receiver cycles

state = {"reg00": None, "pos": None, "motor_ctr": 0, "engaged_seen": False}
stop  = threading.Event()


def s32(b):  # little-endian signed int32 from 4 bytes
    return struct.unpack("<i", bytes(b))[0]


def le32(v):
    return list(struct.pack("<i", int(v)))


def rx_loop(bus):
    for msg in bus:
        if stop.is_set():
            return
        if msg.arbitration_id != STAT_ID or msg.dlc < 4:
            continue
        d = msg.data
        if d[0] == 0xA1 and d[1] == 0x40:          # status: actual position
            state["pos"] = s32(d[2:6])
        elif d[0] == 0xA0 and d[1] == 0x00:        # register read reply
            reg, val = d[2], s32(d[4:8])
            if reg == 0x00:
                state["reg00"] = val
                if val == 3:
                    state["engaged_seen"] = True
        elif d[0] == 0x01:                         # motor heartbeat counter
            state["motor_ctr"] = d[1]


def send(bus, data):
    bus.send(can.Message(arbitration_id=CMD_ID, is_extended_id=True,
                          data=bytes(data)))


def read_reg(bus, reg):
    send(bus, [0xA0, 0x00, reg, 0x00, 0, 0, 0, 0])


def write_reg(bus, reg, val):
    send(bus, [0xA0, 0x01, reg, 0x00] + le32(val))


def heartbeat(bus, ctr):
    send(bus, [0x01, ctr & 0xFF, state["motor_ctr"] & 0xFF, 0x00])


def main():
    bus = can.Bus(interface="pcan", channel=CHANNEL, bitrate=BITRATE)
    threading.Thread(target=rx_loop, args=(bus,), daemon=True).start()

    # 1. subscribe to 10 Hz status, ask for a status/version reply
    for _ in range(3):
        send(bus, [0x0F, 0xA1, 0x01, 0x02])
        send(bus, [0x0F, 0x33, 0x00, 0x00])
        time.sleep(0.05)

    # 2. optional limit writes
    if WRITE_LIMITS:
        write_reg(bus, 0x05, 19800)
        write_reg(bus, 0x06, 360)
        time.sleep(0.1)

    # 3. let the state machine settle while we poll registers + heartbeat
    hb = 0
    for _ in range(10):                    # ~1 s
        heartbeat(bus, hb); hb += 1
        for reg in REG_CYCLE:
            read_reg(bus, reg); time.sleep(0.02)
        time.sleep(0.08)
    print(f"before engage: reg00={state['reg00']} pos={state['pos']}")

    # 4. engage: zero the counter, then hold position control
    send(bus, [0xA1, 0x3D, 0x00, 0x00, 0, 0, 0, 0])
    time.sleep(0.05)

    # 5. 50 Hz command loop with a slow triangle target
    t0 = time.time()
    tick = 0
    target = 0.0
    direction = 1
    print("engaged. Ctrl-C to stop.")
    try:
        while not stop.is_set():
            target += direction * RAMP_CPS * 0.02
            if abs(target) >= TARGET_MAX:
                target = max(-TARGET_MAX, min(TARGET_MAX, target))
                direction *= -1
            send(bus, [0xA1, 0x09, 0x00, 0x00] + le32(target))

            if tick % 10 == 0:             # 200 ms register read
                read_reg(bus, REG_CYCLE[(tick // 10) % 4])
            if tick % 100 == 0:            # 2 s heartbeat
                heartbeat(bus, hb); hb += 1
            if tick % 25 == 0:
                print(f"t={time.time()-t0:5.1f}  reg00={state['reg00']}  "
                      f"target={target:7.0f}  pos={state['pos']}")
            if tick == 150 and not state["engaged_seen"]:
                print("  !! reg00 never reached 3 after 3 s -- the motor is "
                      "not entering position control.\n"
                      "     The '32' challenge/response handshake is the likely "
                      "gate. Disengaging.")
                break

            tick += 1
            time.sleep(0.02)
    except KeyboardInterrupt:
        pass
    finally:
        # 6. clean disengage
        send(bus, [0xA1, 0x11, 0x00, 0x00, 0, 0, 0, 0])
        time.sleep(0.02)
        send(bus, [0xA1, 0x01, 0x00, 0x00] + le32(state["pos"] or 0))
        stop.set()
        time.sleep(0.1)
        bus.shutdown()
        print("done.")


if __name__ == "__main__":
    main()