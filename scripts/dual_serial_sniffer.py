#!/usr/bin/env python3
import argparse
import csv
import datetime
import sys
import threading
from typing import Optional

import serial


def open_serial(port: str, baudrate: int) -> serial.Serial:
    try:
        ser = serial.Serial(
            port=port,
            baudrate=baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=1.0,  # 1s read timeout
        )
        return ser
    except serial.SerialException as e:
        print(f"Nem sikerült megnyitni a portot ({port}): {e}", file=sys.stderr)
        sys.exit(1)


def current_timestamp() -> str:
    # ISO-8601, mikrosec pontosság
    return datetime.datetime.now().isoformat(timespec="microseconds")


def sniffer_thread(
    ser: serial.Serial,
    direction_label: str,
    csv_writer: Optional[csv.DictWriter],
    csv_file,
    fieldnames: list,
    lock: threading.Lock,
    debug_print: bool,
):
    """
    Egyik irány figyeléséért felelős thread.
    direction_label pl.: 'A→B' vagy 'B→A'
    """
    buffer = ""

    while True:
        try:
            data = ser.read(1024)
        except serial.SerialException as e:
            with lock:
                print(f"[{direction_label}] Soros hiba: {e}", file=sys.stderr)
            break

        if not data:
            # timeout
            continue

        try:
            text = data.decode("ascii", errors="ignore")
        except UnicodeDecodeError:
            # eldobunk mindent, amit nem tudunk ASCII-ként értelmezni
            continue

        buffer += text

        # sorokra bontás (ASD/LH-szerű protokollok általában sor-orientáltak)
        while "\n" in buffer or "\r" in buffer:
            line, sep, rest = buffer.partition("\n")
            if not sep:
                line, sep, rest = buffer.partition("\r")
            buffer = rest

            line = line.strip()
            if not line:
                continue

            ts = current_timestamp()
            row = {
                "timestamp": ts,
                "direction": direction_label,
                "raw_line": line,
            }

            if debug_print:
                with lock:
                    print(f"[{ts}] {direction_label}: {line}")

            if csv_writer is not None:
                with lock:
                    csv_writer.writerow(row)
                    csv_file.flush()


def main():
    parser = argparse.ArgumentParser(
        description="Kétirányú RS232 sniffer (2x USB–RS232 adapter) mikrosec időbélyeggel."
    )
    parser.add_argument("--port-a", required=True, help="Első soros port (pl. COM3 vagy /dev/ttyUSB0)")
    parser.add_argument("--port-b", required=True, help="Második soros port (pl. COM4 vagy /dev/ttyUSB1)")
    parser.add_argument("--baud", type=int, default=9600, help="Baud rate, mindkét portra (alapértelmezett: 9600)")
    parser.add_argument(
        "--csv",
        help="CSV logfájl elérési útja. Ha nincs megadva, automatikusan generál egyet a dátum alapján.",
    )
    parser.add_argument(
        "--no-debug",
        action="store_true",
        help="Ne írjon a konzolra, csak CSV-be logoljon.",
    )

    args = parser.parse_args()

    # Soros portok megnyitása
    ser_a = open_serial(args.port_a, args.baud)
    ser_b = open_serial(args.port_b, args.baud)

    print(f"Soros A: {args.port_a} @ {args.baud} baud")
    print(f"Soros B: {args.port_b} @ {args.baud} baud")

    # CSV előkészítés
    if args.csv:
        csv_path = args.csv
    else:
        now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = f"serial_sniff_{now_str}.csv"

    fieldnames = ["timestamp", "direction", "raw_line"]
    csv_file = open(csv_path, "a", newline="", encoding="utf-8")
    csv_writer = csv.DictWriter(csv_file, fieldnames=fieldnames)

    if csv_file.tell() == 0:
        csv_writer.writeheader()

    print(f"Logfájl: {csv_path}")

    lock = threading.Lock()
    debug_print = not args.no_debug

    # Threadek indítása
    thread_a = threading.Thread(
        target=sniffer_thread,
        args=(ser_a, "A→B", csv_writer, csv_file, fieldnames, lock, debug_print),
        daemon=True,
    )
    thread_b = threading.Thread(
        target=sniffer_thread,
        args=(ser_b, "B→A", csv_writer, csv_file, fieldnames, lock, debug_print),
        daemon=True,
    )

    thread_a.start()
    thread_b.start()

    print("Sniffer fut. Kilépés: Ctrl+C")

    try:
        # Fő thread csak várakozik
        while True:
            thread_a.join(timeout=1.0)
            thread_b.join(timeout=1.0)
            # Ha bármelyik thread megállt (hiba miatt), akkor kilépünk
            if not thread_a.is_alive() or not thread_b.is_alive():
                print("Az egyik sniffer thread leállt, kilépek.")
                break
    except KeyboardInterrupt:
        print("Megszakítva (Ctrl+C).")
    finally:
        try:
            ser_a.close()
        except Exception:
            pass
        try:
            ser_b.close()
        except Exception:
            pass
        csv_file.close()
        print("Portok zárva, logfájl lezárva.")


if __name__ == "__main__":
    main()
