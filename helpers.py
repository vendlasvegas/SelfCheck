# utils/helpers.py
import subprocess

def run(cmd):
    try:
        out = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL, timeout=1.5)
        return out.decode("utf-8", "ignore").strip()
    except Exception:
        return ""

def get_wifi_rssi_dbm():
    txt = run("iw dev wlan0 link")
    for line in txt.splitlines():
        if "signal:" in line.lower():
            try:
                return int(float(line.split("signal:")[1].split("dBm")[0].strip()))
            except Exception:
                return None
    return None

def rssi_to_bars(rssi):
    if rssi is None: return 0
    if rssi >= -55: return 4
    if rssi >= -65: return 3
    if rssi >= -75: return 2
    if rssi >= -85: return 1
    return 0
