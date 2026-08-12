"""Serial connection to the R4 -- auto-reconnect, line parsing, and a
clean callback-based interface so nothing else in the app needs to
know about raw serial I/O, baud rates, or the wire protocol's exact
text format.

Protocol (see groovebox.ino's header for the authoritative version):
  Incoming (board -> PC), one line per 16th note:
    STEP:<0-15>,PAT:<0-3>,MUTE:<0-31>,FILL:<0|1>,FX:<0-127>
  Outgoing (PC -> board), after each step is handled:
    HIT:<0-31>   -- 5-bit group mask of what actually played
"""

import queue
import threading
import time

import serial
import serial.tools.list_ports

BAUD = 115200


def find_port():
    for p in serial.tools.list_ports.comports():
        if "Arduino" in (p.description or "") or "USB Serial" in (p.description or ""):
            return p.device
    ports = list(serial.tools.list_ports.comports())
    if len(ports) == 1:
        return ports[0].device
    return None


def parse_step_line(line):
    try:
        parts = dict(kv.split(":") for kv in line.split(","))
        return {
            "step": int(parts["STEP"]),
            "pattern": int(parts["PAT"]),
            "mute": int(parts["MUTE"]),
            "fill": bool(int(parts["FILL"])),
            "fx": int(parts.get("FX", 0)),
        }
    except (ValueError, KeyError):
        return None


class SerialLink:
    """Runs its own reader thread; pushes ("status"|"log"|"step", payload)
    tuples onto `events` (a queue.Queue) for the caller to drain on
    whatever thread it likes (e.g. a GUI's main-thread poll loop)."""

    def __init__(self, port):
        self.port = port
        self.events = queue.Queue()
        self._ser = None
        self._ser_lock = threading.Lock()
        threading.Thread(target=self._run, daemon=True).start()

    def send_hit(self, group_mask):
        self._send(f"HIT:{group_mask}\n")

    def send_swing(self, percent):
        self._send(f"SWING:{percent}\n")

    def send_bpm(self, bpm):
        self._send(f"SETBPM:{bpm}\n")

    def _send(self, line):
        with self._ser_lock:
            if self._ser is None:
                return
            try:
                self._ser.write(line.encode())
            except serial.SerialException:
                pass  # reader thread will notice and reconnect

    def _connect(self):
        while True:
            try:
                return serial.Serial(self.port, BAUD, timeout=1)
            except serial.SerialException:
                time.sleep(1.0)

    def _run(self):
        with self._ser_lock:
            self._ser = self._connect()
        self.events.put(("status", "connected"))

        while True:
            try:
                raw = self._ser.readline()
            except serial.SerialException:
                self.events.put(("status", "reconnecting..."))
                with self._ser_lock:
                    self._ser.close()
                    self._ser = self._connect()
                self.events.put(("status", "connected"))
                continue

            if not raw:
                continue
            line = raw.decode("utf-8", errors="ignore").strip()
            if not line:
                continue
            if line.startswith("#"):
                self.events.put(("log", line[1:].strip()))
            elif line.startswith("STEP:"):
                parsed = parse_step_line(line)
                if parsed:
                    self.events.put(("step", parsed))
