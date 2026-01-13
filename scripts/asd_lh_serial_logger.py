#!/usr/bin/env python3
import argparse
import csv
import datetime
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

import serial


# -------------------------
#  Protokoll absztrakció
# -------------------------

@dataclass
class ParsedRecord:
    """Egységesített kimeneti rekord, amit majd CSV-be is tudunk írni."""
    protocol: str
    raw_line: str
    fields: Dict[str, str] = field(default_factory=dict)

    def to_row(self, field_order: Optional[list] = None) -> Dict[str, str]:
        row = {
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
            "protocol": self.protocol,
            "raw_line": self.raw_line,
        }
        if field_order:
            for key in field_order:
                row[key] = self.fields.get(key, "")
        else:
            # minden ismert mezőt rakjunk bele
            for key, value in self.fields.items():
                row[key] = value
        return row


class BaseProtocolParser:
    """Közös interfész: egy sorból próbál értelmezhető rekordot csinálni."""

    protocol_name = "BASE"

    def parse_line(self, line: str) -> Optional[ParsedRecord]:
        raise NotImplementedError


# -------------------------
#  AMAZONE ASD parser (váz)
# -------------------------

class ASDProtocolParser(BaseProtocolParser):
    """
    AMAZONE ASD – generikus váz.
    Itt kell majd a konkrét dokumentáció alapján testre szabni a sorformátumot.
    """

    protocol_name = "ASD"

    def parse_line(self, line: str) -> Optional[ParsedRecord]:
        line = line.strip()
        if not line:
            return None

        # Példának feltételezzünk pl. pontosvesszővel tagolt formátumot:
        # pl. "ACT;FieldID;JobID;Rate;Speed;Area"
        parts = line.split(";")
        record_type = parts[0].upper() if parts else ""

        fields: Dict[str, str] = {
            "type": record_type,
        }

        # Itt jön az, amit majd a doksiból be tudsz pontosítani:
        if record_type == "ACT":  # actual data record (példa)
            # ez csak példa indexelés, a valós mezők ettől eltérhetnek
            if len(parts) >= 6:
                fields.update(
                    {
                        "field_id": parts[1],
                        "job_id": parts[2],
                        "rate": parts[3],      # l/ha
                        "speed": parts[4],     # km/h
                        "area_total": parts[5] # ha
                    }
                )
        elif record_type == "TASK":  # kijuttatási terv (példa)
            # itt más mezőket vársz…
            if len(parts) >= 4:
                fields.update(
                    {
                        "field_id": parts[1],
                        "job_id": parts[2],
                        "target_rate": parts[3]
                    }
                )
        else:
            # ismeretlen / vegyes rekord – legalább a line-t mentsük
            # akár részben parse-olhatsz itt is
            fields["payload"] = ";".join(parts[1:])

        return ParsedRecord(protocol=self.protocol_name, raw_line=line, fields=fields)


# -------------------------
#  LH5500-szerű parser (váz)
# -------------------------

class LH5500ProtocolParser(BaseProtocolParser):
    """
    LH Agro LH5500 – csak minta.
    Klasszikus forma: "#H,...", "#A,...", "#F,..." stb.
    Konkrét mező-leképezést majd a dokumentáció alapján tudod finomhangolni.
    """

    protocol_name = "LH5500"

    def parse_line(self, line: str) -> Optional[ParsedRecord]:
        line = line.strip()
        if not line:
            return None

        if not line.startswith("#"):
            # nem LH-s rekord, akár kidobhatjuk
            return None

        # pl. "#H,2026-01-13,12:34:56,24.0,6.0,..." → ',' szeparátor
        parts = line.split(",")
        header = parts[0].upper()

        fields: Dict[str, str] = {
            "type": header.lstrip("#"),
        }

        # Példa: #H = header / job header
        if header == "#H":
            # Csak példa indexek!
            # Itt: dátum, idő, munkaszélesség, stb.
            if len(parts) >= 5:
                fields.update(
                    {
                        "date": parts[1],
                        "time": parts[2],
                        "work_width": parts[3],
                        "operator": parts[4],
                    }
                )

        # Példa: #A = actual log rekord
        elif header == "#A":
            if len(parts) >= 6:
                fields.update(
                    {
                        "distance": parts[1],
                        "speed": parts[2],
                        "applied_rate": parts[3],
                        "section_state": parts[4],
                        "area_total": parts[5],
                    }
                )

        # Példa: #F = field / tábla info
        elif header == "#F":
            if len(parts) >= 4:
                fields.update(
                    {
                        "field_id": parts[1],
                        "crop_type": parts[2],
                        "customer": parts[3],
                    }
                )
        else:
            # ismeretlen rekord – payload mentése
            fields["payload"] = ",".join(parts[1:])

        return ParsedRecord(protocol=self.protocol_name, raw_line=line, fields=fields)


# -------------------------
#  Serial olvasó
# -------------------------

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


def run_logger(
    port: str,
    baudrate: int,
    parser: BaseProtocolParser,
    csv_path: Optional[str] = None,
    debug_print: bool = True,
):
    ser = open_serial(port, baudrate)
    print(f"Soros port megnyitva: {port} @ {baudrate} baud, protokoll: {parser.protocol_name}")

    csv_file = None
    csv_writer = None
    fieldnames = ["timestamp", "protocol", "raw_line"]  # bővítjük dinamikusan

    if csv_path:
        csv_file = open(csv_path, "a", newline="", encoding="utf-8")
        csv_writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        # fejléct akkor írjuk, ha a fájl üres (vagy nagyon akarod, hogy mindig új legyen)
        if csv_file.tell() == 0:
            csv_writer.writeheader()

    buffer = ""

    try:
        while True:
            # soros olvasás (byte->str)
            data = ser.read(1024)
            if not data:
                # timeout
                continue

            try:
                text = data.decode("ascii", errors="ignore")
            except UnicodeDecodeError:
                # eldobunk minden fura dolgot
                continue

            buffer += text

            # sorokra bontás
            while "\n" in buffer or "\r" in buffer:
                # univerzális newline kezelés
                line, sep, rest = buffer.partition("\n")
                if not sep:
                    # nem volt \n, próbáljuk \r-rel
                    line, sep, rest = buffer.partition("\r")
                buffer = rest

                line = line.strip()
                if not line:
                    continue

                record = parser.parse_line(line)
                if record is None:
                    if debug_print:
                        print(f"[RAW] {line}")
                    continue

                # CSV mezők kezelése – bővítjük a fieldnames-t, ha új mező jön
                row = record.to_row()
                new_keys = [k for k in row.keys() if k not in fieldnames]
                if new_keys:
                    fieldnames.extend(new_keys)
                    if csv_writer:
                        # új writer a bővített mezőlistával
                        csv_writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
                        # opcionálisan új header – de ez már létező fájlnál nem szokás
                        # csv_writer.writeheader()

                if debug_print:
                    # egyszerű debug kiírás
                    print(f"[{row['timestamp']}] {record.protocol} {record.fields}")

                if csv_writer:
                    csv_writer.writerow(row)
                    csv_file.flush()

    except KeyboardInterrupt:
        print("Megszakítva (Ctrl+C).")
    finally:
        if csv_file:
            csv_file.close()
        ser.close()
        print("Soros port lezárva.")


# -------------------------
#  CLI kezelő
# -------------------------

def main():
    parser = argparse.ArgumentParser(
        description="AMAZONE ASD / LH5500-szerű soros dokumentáció logger Pythonban."
    )
    parser.add_argument("--port", required=True, help="Soros port (pl. COM3 vagy /dev/ttyUSB0)")
    parser.add_argument("--baud", type=int, default=9600, help="Baud rate (alapértelmezett: 9600)")
    parser.add_argument(
        "--protocol",
        choices=["asd", "lh5500"],
        required=True,
        help="Protokoll típus: 'asd' vagy 'lh5500'",
    )
    parser.add_argument(
        "--csv",
        help="CSV fájl elérési útja, ha logolni is szeretnél (pl. logs.csv)",
    )
    parser.add_argument(
        "--no-debug",
        action="store_true",
        help="Ne írjon ki sorokat a konzolra, csak CSV-be logoljon.",
    )

    args = parser.parse_args()

    if args.protocol == "asd":
        proto_parser = ASDProtocolParser()
    else:
        proto_parser = LH5500ProtocolParser()

    run_logger(
        port=args.port,
        baudrate=args.baud,
        parser=proto_parser,
        csv_path=args.csv,
        debug_print=not args.no_debug,
    )


if __name__ == "__main__":
    main()
