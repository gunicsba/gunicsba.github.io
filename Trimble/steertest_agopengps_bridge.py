#!/usr/bin/env python3
"""
Live bridge: AgOpenGPS steer setpoint -> SAM200 motor over PCAN.

Pretends to be a steer module listening for AgIO's broadcast PGN 254
(AutoSteer Data) on UDP 8888, and drives the SAM200 to match. Replies with
PGN 253 (actual angle) so AgOpenGPS sees a connected module.

RUN THIS WITH THE MOTOR ALONE ON THE BUS (real receiver/CFX unplugged) and
with the output mechanically decoupled or wheels off the ground.

Run this yourself in your own terminal (not launched for you) so you have a
live Ctrl-C at all times -- this runs indefinitely as long as AgOpenGPS does.

Requires: python-can, a PEAK PCAN adapter. ISOBUS/J1939 = 250 kbit/s.
"""

import can
import socket
import struct
import threading
import time

CHANNEL   = "PCAN_USBBUS1"
BITRATE   = 250000

MOTOR_SA  = 0xCD
OUR_SA    = 0x1C
CMD_ID    = 0x18EF0000 | (MOTOR_SA << 8) | OUR_SA   # 0x18EFCD1C
STAT_ID   = 0x18EF0000 | (OUR_SA  << 8) | MOTOR_SA  # 0x18EF1CCD

# --- angle <-> counts scale --------------------------------------------------
# GUESS, not confirmed: derived from the WRITE_LIMITS values (reg 0x05=19800,
# reg 0x06=360) as if reg 0x06 were max angle in tenths of a degree (36.0 deg)
# and reg 0x05 were the matching count limit. Verify against the real wheel
# angle before trusting this, and adjust.
COUNTS_PER_DEGREE = 19800 / 36.0    # ~550
MAX_COUNTS        = 5000            # safety clamp -- the range we've actually
                                     # tested, well under the ~19800 limit
WRITE_LIMITS      = True

MOTOR_DIRECTION   = -1   # motor turned the wrong way by default -- flip here
                          # (matches steerConfig.MotorDriveDirection in the
                          # Teensy firmware). Set back to 1 if this over-corrects.

# --- rate limiter, ported from the real AgOpenGPS Teensy firmware's PID
# (AutosteerPID.ino: calcSteeringPID) -- same shape, but the output drives a
# counts/sec ramp toward the target instead of a raw PWM duty cycle. Kp,
# high_pwm and low_pwm come live from AgOpenGPS's PGN 252 (AutoSteer Settings)
# so the existing Kp/MaxPWM/MinPWM sliders in AgOpenGPS tune this directly.
LOW_HIGH_DEGREES  = 3.0    # error band where the ramp rate tapers down (soft
                            # landing near the target) -- matches the firmware
PWM_TO_CPS        = 10.0   # GUESS: counts/sec of ramp rate per 1 "PWM" unit
                            # (0-255 scale). Tune this against how snappy vs.
                            # sluggish the motion feels.

UDP_PORT  = 8888   # AgIO broadcasts PGN 254 here (Settings.setIP_autoSteerPort)
TICK_DT   = 0.02   # 50 Hz command loop

REG_CYCLE = [0x14, 0x2A, 0x1B, 0x00]

state = {
    "reg00": None, "pos": None, "motor_ctr": 0,
    "target_deg": 0.0, "autosteer_on": False,
    "engaged": False, "last_pgn_time": 0.0,
    "reply_addr": None,
    "commanded_counts": 0.0,
    # PGN 252 defaults -- match the Teensy firmware's own defaults/quirks:
    # lowPWM reads udpData[8] (the "MinPWM" byte -- "LowPWM" is deprecated
    # for CAN setups), and minPWM is hardcoded to 1 rather than read.
    "kp": 15, "high_pwm": 250, "low_pwm": 5, "min_pwm": 1,
}
stop = threading.Event()


def s32(b):
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
        if d[0] == 0xA1 and d[1] == 0x40:
            state["pos"] = s32(d[2:6])
        elif d[0] == 0xA0 and d[1] == 0x00:
            reg, val = d[2], s32(d[4:8])
            if reg == 0x00:
                state["reg00"] = val
        elif d[0] == 0x01:
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


def pgn_crc(data):
    return sum(data[2:-1]) & 0xFF


def udp_loop(sock):
    while not stop.is_set():
        try:
            data, addr = sock.recvfrom(1024)
        except OSError:
            return
        if len(data) < 5 or data[0] != 0x80 or data[1] != 0x81:
            continue

        if data[3] == 0xFE and len(data) >= 14:   # AutoSteer Data
            status = data[7]
            angle_raw = struct.unpack("<h", bytes(data[8:10]))[0]  # deg * 100
            state["target_deg"] = angle_raw / 100.0
            state["autosteer_on"] = bool(status & 0x01)
            state["last_pgn_time"] = time.time()
            state["reply_addr"] = (addr[0], UDP_PORT)

        elif data[3] == 0xFC and len(data) >= 13:  # AutoSteer Settings
            state["kp"] = data[5]
            state["high_pwm"] = data[6]
            state["low_pwm"] = data[8]
            print(f"settings updated: Kp={state['kp']} highPWM={state['high_pwm']} "
                  f"lowPWM={state['low_pwm']} minPWM={state['min_pwm']}")


def send_pgn253(sock):
    if state["reply_addr"] is None or state["pos"] is None:
        return
    actual_deg_raw = int((state["pos"] / COUNTS_PER_DEGREE) * 100 * MOTOR_DIRECTION)
    pkt = [0x80, 0x81, 0x7F, 0xFD, 8,
           actual_deg_raw & 0xFF, (actual_deg_raw >> 8) & 0xFF,
           0x0F, 0x27,   # heading = 9999 -> N/A
           0xB8, 0x22,   # roll = 8888 -> N/A
           0x00,         # switch status
           0x00,         # pwm
           0]
    pkt[-1] = pgn_crc(pkt)
    try:
        sock.sendto(bytes(pkt), ("255.255.255.255", UDP_PORT))
    except OSError:
        pass


def main():
    bus = can.Bus(interface="pcan", channel=CHANNEL, bitrate=BITRATE)
    threading.Thread(target=rx_loop, args=(bus,), daemon=True).start()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("0.0.0.0", UDP_PORT))
    threading.Thread(target=udp_loop, args=(sock,), daemon=True).start()

    time.sleep(1.5)

    for _ in range(3):
        send(bus, [0x0F, 0xA1, 0x01, 0x02])
        send(bus, [0x0F, 0x33, 0x00, 0x00])
        time.sleep(0.05)

    if WRITE_LIMITS:
        write_reg(bus, 0x05, 19800)
        write_reg(bus, 0x06, 360)
        time.sleep(0.1)

    hb = 0
    for _ in range(10):
        heartbeat(bus, hb); hb += 1
        for reg in REG_CYCLE:
            read_reg(bus, reg); time.sleep(0.02)
        time.sleep(0.08)
    print(f"ready. reg00={state['reg00']} pos={state['pos']}  "
          f"listening for AgOpenGPS on UDP {UDP_PORT}. Ctrl-C to stop.")

    tick = 0
    try:
        while not stop.is_set():
            stale = (time.time() - state["last_pgn_time"]) > 1.0
            want_engaged = state["autosteer_on"] and not stale

            if want_engaged and not state["engaged"]:
                wait_t0 = time.time()
                while state["pos"] is None and time.time() - wait_t0 < 2.0:
                    heartbeat(bus, hb); hb += 1
                    time.sleep(0.05)
                send(bus, [0xA1, 0x01, 0x00, 0x00] + le32(state["pos"] or 0))
                time.sleep(0.02)
                send(bus, [0xA1, 0x3D, 0x00, 0x00, 0, 0, 0, 0])
                time.sleep(0.05)
                state["commanded_counts"] = 0.0  # zeroed by the A1 3D above
                state["engaged"] = True
                print("engaged")

            elif not want_engaged and state["engaged"]:
                send(bus, [0xA1, 0x11, 0x00, 0x00, 0, 0, 0, 0])
                time.sleep(0.02)
                send(bus, [0xA1, 0x01, 0x00, 0x00] + le32(state["pos"] or 0))
                state["engaged"] = False
                print("disengaged")

            if state["engaged"]:
                desired_counts = MOTOR_DIRECTION * state["target_deg"] * COUNTS_PER_DEGREE
                desired_counts = max(-MAX_COUNTS, min(MAX_COUNTS, desired_counts))

                # rate-limit the commanded position toward desired_counts using
                # the ported AutosteerPID.ino shape (see constants above)
                error_deg = (desired_counts - state["commanded_counts"]) / COUNTS_PER_DEGREE
                error_abs = abs(error_deg)
                kp, high_pwm, low_pwm, min_pwm = (
                    state["kp"], state["high_pwm"], state["low_pwm"], state["min_pwm"])
                high_low_per_deg = (high_pwm - low_pwm) / LOW_HIGH_DEGREES
                new_max = (error_abs * high_low_per_deg + low_pwm) if error_abs < LOW_HIGH_DEGREES else high_pwm

                pwm = kp * error_deg
                if pwm < 0:
                    pwm -= min_pwm
                elif pwm > 0:
                    pwm += min_pwm
                pwm = max(-new_max, min(new_max, pwm))

                step = pwm * PWM_TO_CPS * TICK_DT
                remaining = desired_counts - state["commanded_counts"]
                if abs(step) >= abs(remaining):
                    state["commanded_counts"] = desired_counts
                else:
                    state["commanded_counts"] += step

                send(bus, [0xA1, 0x09, 0x00, 0x00] + le32(state["commanded_counts"]))

            if tick % 10 == 0:
                read_reg(bus, REG_CYCLE[(tick // 10) % 4])
                send_pgn253(sock)
            if tick % 100 == 0:
                heartbeat(bus, hb); hb += 1
            if tick % 25 == 0:
                print(f"engaged={state['engaged']}  reg00={state['reg00']}  "
                      f"target_deg={state['target_deg']:6.2f}  pos={state['pos']}  "
                      f"cmd={state['commanded_counts']:7.0f}  "
                      f"Kp={state['kp']} hi={state['high_pwm']} lo={state['low_pwm']}  "
                      f"autosteer_on={state['autosteer_on']}  stale={stale}")

            tick += 1
            time.sleep(TICK_DT)
    except KeyboardInterrupt:
        pass
    finally:
        send(bus, [0xA1, 0x11, 0x00, 0x00, 0, 0, 0, 0])
        time.sleep(0.02)
        send(bus, [0xA1, 0x01, 0x00, 0x00] + le32(state["pos"] or 0))
        stop.set()
        time.sleep(0.1)
        sock.close()
        bus.shutdown()
        print("done.")


if __name__ == "__main__":
    main()
