"""Read-only system samples in a worker; missing sensors stay unknown."""
import re
import socket
import subprocess
import threading
import time
from pathlib import Path

from infopanel_data import finite


def firmware_flags():
    try:
        result = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True,
                                text=True, timeout=1, check=True)
        match = re.fullmatch(r"throttled=(0x[0-9a-fA-F]{1,8})", result.stdout.strip())
        return int(match[1], 16) if match else None
    except (OSError, subprocess.SubprocessError):
        return None


def cpu_temperature():
    try:
        value = float(Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000
        return value if finite(value) and 0 <= value <= 150 else None
    except (OSError, ValueError):
        return None


def age_label(seconds):
    if not finite(seconds) or seconds < 0:
        return "Stáří neznámé"
    if seconds < 60:
        return "Před " + str(int(seconds)) + " s"
    if seconds < 3600:
        return "Před " + str(int(seconds // 60)) + " min"
    if seconds < 86400:
        return "Před " + str(int(seconds // 3600)) + " h " + str(int(seconds % 3600 // 60)) + " min"
    return "Před " + str(int(seconds // 86400)) + " d"


def warnings(model):
    system = model.get("system") or {}
    flags = system.get("flags")
    items = []
    if finite(system.get("temp")) and system["temp"] >= 80:
        items.append("Vysoká teplota CPU")
    if type(flags) is int:
        if flags & 1:
            items.append("Podpětí")
        if flags & 8 and "Vysoká teplota CPU" not in items:
            items.append("Teplotní limit")
        if flags & 6:
            items.append("Omezený výkon CPU")
    if ((finite(system.get("disk_free")) and system["disk_free"] < 2**30) or
            (finite(system.get("disk")) and system["disk"] >= 90)):
        items.append("Dochází místo na disku")
    if (model.get("meteo") or {}).get("stale"):
        items.append("Meteo: zastaralá nebo chybějící data")
    return items


class SystemMonitor:
    def __init__(self, iface, stats=None, flags=firmware_flags, temperature=cpu_temperature):
        if stats is None:
            import psutil
            stats = psutil
        self.stats, self.iface = stats, iface
        self.errors = (OSError, ValueError, getattr(stats,"Error",OSError))
        self.read_flags, self.read_temperature = flags, temperature
        self.lock, self.stop = threading.Lock(), threading.Event()
        self.value, self.checked, self.previous = {}, None, None
        self.cpu_primed = False

    def poll(self):
        now = time.monotonic()
        sample = {"iface": self.iface}
        # A missing interface or sensor must not discard the other readings.
        try:
            cpu = self.stats.cpu_percent()
            sample["cpu"] = cpu if self.cpu_primed else None
            self.cpu_primed = True
            ram = self.stats.virtual_memory()
            sample.update(ram=ram.percent, ram_free=ram.available, ram_total=ram.total)
            disk = self.stats.disk_usage("/")
            sample.update(disk=disk.percent, disk_free=disk.free, disk_total=disk.total)
            seconds = max(0, int(time.time() - self.stats.boot_time()))
            sample["uptime"] = (f"{seconds // 86400} d " if seconds >= 86400 else "") + f"{seconds % 86400 // 3600:02d}:{seconds % 3600 // 60:02d}"
        except self.errors:
            pass
        try:
            link = self.stats.net_if_stats().get(self.iface)
            sample["link"] = bool(link.isup) if link is not None else None
            sample["ip"] = next((a.address for a in self.stats.net_if_addrs().get(self.iface, [])
                                 if a.family == socket.AF_INET), None)
            counter = self.stats.net_io_counters(pernic=True, nowrap=False).get(self.iface)
            previous, self.previous = self.previous, None
            if counter is not None and link is not None and link.isup:
                rx, tx = counter.bytes_recv, counter.bytes_sent
                sample.update(rx_bytes=rx, tx_bytes=tx)
                self.previous = (now, rx, tx)
                if previous is not None and now > previous[0] and rx >= previous[1] and tx >= previous[2]:
                    sample.update(rx_rate=(rx-previous[1])/(now-previous[0]),
                                  tx_rate=(tx-previous[2])/(now-previous[0]))
        except self.errors:
            self.previous = None
        sample.update(temp=self.read_temperature(), flags=self.read_flags())
        with self.lock:
            self.value, self.checked = sample, time.monotonic()

    def snapshot(self):
        with self.lock:
            return dict(self.value) if self.checked is not None and time.monotonic()-self.checked < 10 else {}

    def start(self):
        def run():
            while not self.stop.is_set():
                self.poll()
                self.stop.wait(2)
        threading.Thread(target=run, daemon=True).start()

    def close(self):
        self.stop.set()
