from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import websocket

ROOT = Path(__file__).resolve().parent
PROFILE = ROOT / "facebook_scanner_profile"
COOKIE_PATH = ROOT / "data" / "facebook_cookies.json"
DEBUG_PORT = 9222


def find_chrome() -> str | None:
    candidates = [
        shutil.which("chrome"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for path in candidates:
        if path and Path(path).exists():
            return str(path)
    return None


def get_json(url: str):
    with urllib.request.urlopen(url, timeout=3) as r:
        return json.loads(r.read().decode("utf-8"))


def wait_debugger(timeout: int = 30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            return get_json(f"http://127.0.0.1:{DEBUG_PORT}/json")
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("Chrome debugging port did not become ready")


def cdp_call(ws_url: str, method: str, params=None, call_id=1):
    ws = websocket.create_connection(ws_url, timeout=10, origin="http://127.0.0.1")
    try:
        ws.send(json.dumps({"id": call_id, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == call_id:
                if "error" in msg:
                    raise RuntimeError(str(msg["error"]))
                return msg.get("result", {})
    finally:
        ws.close()


def main():
    chrome = find_chrome()
    if not chrome:
        print("ERROR: Google Chrome was not found on this PC.")
        sys.exit(2)

    PROFILE.mkdir(parents=True, exist_ok=True)
    COOKIE_PATH.parent.mkdir(parents=True, exist_ok=True)

    args = [
        chrome,
        f"--remote-debugging-port={DEBUG_PORT}",
        f"--user-data-dir={PROFILE}",
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
        "https://www.facebook.com/ads/library/",
    ]

    print("Opening a dedicated Chrome window for the scanner...")
    proc = subprocess.Popen(args)
    targets = wait_debugger()

    print()
    print("====================================================")
    print(" ONE-TIME FACEBOOK LOGIN")
    print("====================================================")
    print("In the Chrome window that opened:")
    print("1) Log in to Facebook normally.")
    print("2) Open Meta Ad Library if it is not already open.")
    print("3) Come back to this window and press ENTER.")
    print()
    input("Press ENTER after Facebook login is complete... ")

    targets = get_json(f"http://127.0.0.1:{DEBUG_PORT}/json")
    page = None
    for target in targets:
        if target.get("type") == "page" and "facebook.com" in target.get("url", ""):
            page = target
            break
    if not page:
        raise RuntimeError("No Facebook tab found in the dedicated Chrome window")

    result = cdp_call(page["webSocketDebuggerUrl"], "Network.getAllCookies")
    cookies = result.get("cookies", [])
    fb = {}
    for c in cookies:
        domain = str(c.get("domain", ""))
        if "facebook.com" in domain:
            name = str(c.get("name", ""))
            value = str(c.get("value", ""))
            if name and value:
                fb[name] = value

    if "c_user" not in fb or "xs" not in fb:
        print("ERROR: Facebook login cookies were not found.")
        print("Make sure you are logged in inside the dedicated Chrome window and run this again.")
        sys.exit(3)

    COOKIE_PATH.write_text(json.dumps(fb, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"SUCCESS: Facebook session saved locally ({len(fb)} cookies).")
    print("The cookie file stays on this PC and is not uploaded by the scanner.")

    try:
        proc.terminate()
    except Exception:
        pass


if __name__ == "__main__":
    main()
