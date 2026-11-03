#!/usr/bin/env python3
"""
First-time setup of Teltonika RutOS 7.x routers over the web API (no browser).

For each router it:
  1. logs in as admin with the factory password from the label
  2. does the forced first-login password change: factory password + "."
  3. relaxes the password policy: digits only, no upper/lower case or special characters
  4. sets the admin password to 12345678
  5. installs the NTRIP client package and sets up the NTRIP client (NTRIP_CONFIG below)
  6. sets the Wi-Fi key of every access point to 12345678

Endpoints and payloads come from a HAR recording of the RUT206 web UI.
Runs again safely: if a router is half done (or done), it carries on from where it is.

Usage:
  python teltonika_setup.py                     asks for each router's factory password in turn
  python teltonika_setup.py -p "sD+2B=0y"       one router
  python teltonika_setup.py --host 192.168.2.1  other address

Connect the PC by Ethernet: changing the Wi-Fi key drops Wi-Fi clients.
The router needs internet access (SIM or WAN) to download the NTRIP package.
"""
import argparse
import csv
import datetime
import os
import sys
import time

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

NEW_PASSWORD = "12345678"
NEW_WIFI_KEY = "12345678"

NTRIP_PACKAGE = "ntrip_client_v2"
NTRIP_CONFIG = {
    "name": "crtk",
    "device": "/dev/rs232",
    "enabled": "1",
    "baudrate": "19200",
    "databits": "8",
    "stopbits": "1",
    "parity": "none",
    "flowcontrol": "none",
    "ntrip_ip": "crtk.net",
    "ntrip_port": "2101",
    "ntrip_mount_point": "NEAR4",
    "ntrip_data_format": "n",
    "ntrip_user": "c",
    "ntrip_password": "c",
    "nmea_source": "4",
    "report_interval": "10",
    "user_nmea": "",
}

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "teltonika_setup_log.csv")

started = time.time()  # reset for each router


def say(msg):
    """print with the clock time and the seconds since this router's setup began"""
    print(f"{time.strftime('%H:%M:%S')} {time.time() - started:6.1f}s  {msg}")


class ApiError(Exception):
    pass


class Router:
    def __init__(self, host):
        self.base = host.rstrip("/") if "://" in host else f"https://{host}"
        self.s = requests.Session()
        self.s.verify = False  # self-signed certificate

    def call(self, method, path, data=None):
        body = None if data is None else {"data": data}
        r = self.s.request(method, self.base + path, json=body, timeout=15)
        try:
            j = r.json()
        except ValueError:
            raise ApiError(f"{method} {path}: HTTP {r.status_code}, reply is not JSON")
        if not j.get("success"):
            raise ApiError(f"{method} {path}: {j.get('errors', j)}")
        return j.get("data")

    def wait_until_up(self, timeout=180):
        end = time.time() + timeout
        while True:
            try:
                self.s.get(self.base + "/api/unauthorized/status", timeout=3)
                return
            except requests.RequestException:
                if time.time() > end:
                    raise ApiError(f"no router answering at {self.base}")
                time.sleep(2)

    def login(self, password):
        """True if the password works. The web UI keeps the session in a cookie;
        API clients may get a bearer token in the reply instead, so handle both."""
        r = self.s.post(self.base + "/api/login",
                        json={"username": "admin", "password": password}, timeout=15)
        try:
            j = r.json()
        except ValueError:
            return False
        if not j.get("success"):
            return False
        token = (j.get("data") or {}).get("token")
        if token:
            self.s.headers["Authorization"] = f"Bearer {token}"
        return True


def as_list(data):
    return data if isinstance(data, list) else [data]


def package_state(rt, report=None):
    """AVAILABLE, INSTALLED, ... or None if the router doesn't offer the package.
    With report (a dict), prints the package count whenever it changes."""
    pkgs = as_list(rt.call("GET", "/api/package_manager/all_packages/status") or [])
    if report is not None and report.get("count") != len(pkgs):
        report["count"] = len(pkgs)
        say(f"  package list: {len(pkgs)} packages available")
    pkg = next((p for p in pkgs if p.get("package") == NTRIP_PACKAGE), None)
    return pkg and pkg.get("type_str")


def wait_for(what, check, timeout):
    """Poll check() until it returns something truthy; errors count as not ready yet."""
    end = time.time() + timeout
    while True:
        try:
            result = check()
            if result:
                return result
        except (ApiError, requests.RequestException):
            pass
        if time.time() > end:
            raise ApiError(f"timed out waiting for {what}")
        time.sleep(5)


def setup_ntrip(rt):
    report = {}
    state = package_state(rt, report)
    if state is None:
        # the package list comes from the internet, which may come up well after the router
        say(f"  {NTRIP_PACKAGE} not in the package list yet, waiting up to 5 minutes for the router's internet ...")
        state = wait_for(f"{NTRIP_PACKAGE} to appear in the package list (does the router have internet?)",
                         lambda: package_state(rt, report), 300)
    if state != "INSTALLED":
        say(f"  installing {NTRIP_PACKAGE} (needs internet, takes about a minute) ...")
        rt.call("POST", "/api/package_manager/actions/install_multiple_packages",
                {"packages": [NTRIP_PACKAGE]})
        wait_for(f"{NTRIP_PACKAGE} to install", lambda: package_state(rt) == "INSTALLED", 300)
        say(f"  {NTRIP_PACKAGE} installed")
    else:
        say(f"  {NTRIP_PACKAGE} already installed")

    # the NTRIP API arrives with the package and may need a moment to come up
    entries = wait_for("the NTRIP API",
                       lambda: [as_list(rt.call("GET", "/api/ntrip/config") or [])], 60)[0]
    entry = next((e for e in entries if e.get("name") == NTRIP_CONFIG["name"]), None)
    if entry is None:
        entry = rt.call("POST", "/api/ntrip/config",
                        {"name": NTRIP_CONFIG["name"], "device": NTRIP_CONFIG["device"]})
    if all(entry.get(k, "") == v for k, v in NTRIP_CONFIG.items()):
        say(f"  NTRIP {NTRIP_CONFIG['name']}: already configured")
        return
    res = rt.call("PUT", f"/api/ntrip/config/{entry['id']}", {".type": "ntrip", **NTRIP_CONFIG})
    wrong = [k for k, v in NTRIP_CONFIG.items() if (res or {}).get(k, "") != v]
    if wrong:
        raise ApiError(f"NTRIP: router did not confirm {', '.join(wrong)}: {res}")
    say(f"  NTRIP {NTRIP_CONFIG['name']}: {NTRIP_CONFIG['ntrip_ip']}:{NTRIP_CONFIG['ntrip_port']}"
          f"/{NTRIP_CONFIG['ntrip_mount_point']} -> {NTRIP_CONFIG['device']} @ {NTRIP_CONFIG['baudrate']}")


def setup(host, factory):
    rt = Router(host)
    say(f"Waiting for router at {rt.base} ...")
    rt.wait_until_up()

    first = factory + "."
    current = next((p for p in (factory, first, NEW_PASSWORD) if rt.login(p)), None)
    if current is None:
        raise ApiError("login failed with the factory password, factory password + '.', and "
                       f"{NEW_PASSWORD} - check the password on the label")
    label = {factory: "factory password", first: "factory password + '.'",
             NEW_PASSWORD: NEW_PASSWORD}[current]
    say(f"  logged in with {label}")

    general = rt.call("GET", "/api/system/config/general")
    say(f"  device: {general.get('devicename', '?')}")

    # 1. forced first-login change
    if general.get("firstlogin") == "1":
        rt.call("POST", "/api/system/actions/change_password_firstlogin",
                {"password": first, "password_confirm": first})
        current = first
        say("  first-login password set (factory password + '.')")

    # 2. password policy: keep digits and length 8, drop the rest
    policy = as_list(rt.call("GET", "/api/password_policy/config"))[0]
    if policy.get("require_lower_upper") != "0" or policy.get("require_special") != "0":
        new_policy = {k: v for k, v in policy.items() if k != "days_since_change"}
        new_policy.update(require_lower_upper="0", require_special="0")
        rt.call("PUT", "/api/password_policy/config", [new_policy])
        say("  password policy relaxed (digits only)")
    else:
        say("  password policy already relaxed")

    # 3. admin password
    if current != NEW_PASSWORD:
        users = as_list(rt.call("GET", "/api/users/config"))
        admin_id = next((u["id"] for u in users if u.get("username") == "admin"), "login1")
        rt.call("PUT", "/api/users/config",
                [{"id": admin_id, "current_password": current,
                  "password": NEW_PASSWORD, "password_confirm": NEW_PASSWORD}])
        if not Router(host).login(NEW_PASSWORD):
            raise ApiError(f"password change reported success, but logging in with {NEW_PASSWORD} fails")
        say(f"  admin password set to {NEW_PASSWORD} (checked with a fresh login)")
    else:
        say(f"  admin password already {NEW_PASSWORD}")

    # 4. NTRIP client
    setup_ntrip(rt)

    # 5. Wi-Fi keys - last, because applying it restarts Wi-Fi
    ifaces = [i for i in as_list(rt.call("GET", "/api/wireless/interfaces/config") or [])
              if i.get("mode") == "ap" and i.get("encryption", "none") != "none"]
    ssids = [i.get("ssid", i["id"]) for i in ifaces]
    if not ifaces:
        say("  no encrypted Wi-Fi access points found")
    for iface in ifaces:
        if iface.get("key") == NEW_WIFI_KEY:
            say(f"  Wi-Fi {iface.get('ssid')}: key already {NEW_WIFI_KEY}")
            continue
        try:
            res = rt.call("PUT", f"/api/wireless/interfaces/config/{iface['id']}",
                          {"encryption": iface["encryption"], "key": NEW_WIFI_KEY})
        except requests.ConnectionError:
            raise ApiError(f"connection lost while setting the Wi-Fi key of {iface.get('ssid')} - "
                           "is this PC on the router's Wi-Fi? Use Ethernet, then run again")
        if (res or {}).get("key") != NEW_WIFI_KEY:
            raise ApiError(f"Wi-Fi {iface.get('ssid')}: router did not confirm the new key: {res}")
        say(f"  Wi-Fi {iface.get('ssid')}: key set to {NEW_WIFI_KEY}")

    return general.get("devicename", ""), ssids


def log(host, device, ssids, result):
    new = not os.path.exists(LOG_FILE)
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time", "host", "device", "ssids", "result"])
        w.writerow([datetime.datetime.now().isoformat(timespec="seconds"),
                    host, device, " ".join(ssids), result])


def run_one(host, factory):
    global started
    started = time.time()
    try:
        device, ssids = setup(host, factory)
    except (ApiError, requests.RequestException) as e:
        say(f"FAILED: {e}")
        log(host, "", [], f"FAILED: {e}")
        return False
    say(f"DONE: {device} {' '.join(ssids)}")
    log(host, device, ssids, "OK")
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="192.168.1.1", help="router address (default 192.168.1.1)")
    ap.add_argument("-p", "--password", help="factory password; without it, asks for one router after another")
    args = ap.parse_args()

    if args.password:
        sys.exit(0 if run_one(args.host, args.password) else 1)

    while True:
        factory = input("\nFactory password of the connected router (Enter to quit): ").strip()
        if not factory:
            break
        run_one(args.host, factory)
        say("Connect the next router.")


if __name__ == "__main__":
    main()
