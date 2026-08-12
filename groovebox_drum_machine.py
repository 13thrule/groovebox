"""Entry point for the groovebox drum machine. Everything that
matters lives in groovebox_app/ as separate modules:

  patterns.py     -- track list + pattern data model (load/save)
  midi_output.py  -- MIDI port + note playback
  serial_link.py  -- board communication (auto-reconnect, protocol)
  gui.py          -- the step-grid window, wires the above together

To add a feature: a new track goes in patterns.py's TRACKS list and
nothing else needs to change. A new control (e.g. a swing-timing
knob) means a new field in the STEP:/HIT: protocol (serial_link.py +
groovebox.ino) and a new GUI element (gui.py). Keeping this file thin
is deliberate -- it should never need to grow.

Run: python groovebox_drum_machine.py [COM_PORT]
"""

import sys
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "groovebox_app"))

from serial_link import SerialLink, find_port
from gui import DrumMachine


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else find_port()
    if not port:
        print("Couldn't auto-detect the board's serial port.")
        import serial.tools.list_ports
        print("Available ports:")
        for p in serial.tools.list_ports.comports():
            print(f"  {p.device} -- {p.description}")
        print("\nRun again with the port explicitly: python groovebox_drum_machine.py COM9")
        return

    link = SerialLink(port)
    root = tk.Tk()
    DrumMachine(root, link)
    root.mainloop()


if __name__ == "__main__":
    main()
