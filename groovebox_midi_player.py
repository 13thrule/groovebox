"""Reads trigger events from the R4 groovebox sketch over serial and
turns each into a real MIDI note sent to a synth -- by default,
Windows' built-in "Microsoft GS Wavetable Synth" (always available,
no install needed). Swap MIDI_PORT_NAME below to route into a real
DAW (e.g. Tracktion Waveform) once you've got one set up as a MIDI
input instead.

Protocol (one line per event, from the firmware):
  K / S / H / O / C   -- kick / snare / closed hat / open hat / clap
  B:<note> / L:<note> -- bass/lead note, <note> is a MIDI note number
  # ...                -- a status/debug line, just printed

Run: python groovebox_midi_player.py [COM_PORT]
If no port is given, it tries to auto-detect an Arduino-like device.
"""

import sys
import threading
import time

import serial
import serial.tools.list_ports
import mido

BAUD = 115200
MIDI_PORT_NAME = None  # None = use the first available output (Windows GS synth)

DRUM_CHANNEL = 9  # MIDI channel 10 (0-indexed) -- General MIDI percussion
BASS_CHANNEL = 0
LEAD_CHANNEL = 1
BASS_PROGRAM = 33  # Electric Bass (finger)
LEAD_PROGRAM = 80  # Lead 1 (square)

DRUM_NOTES = {"K": 36, "S": 38, "H": 42, "O": 46, "C": 39}
NOTE_OFF_DELAY = 0.25  # seconds before releasing a triggered note


def find_port():
    for p in serial.tools.list_ports.comports():
        if "Arduino" in (p.description or "") or "USB Serial" in (p.description or ""):
            return p.device
    ports = list(serial.tools.list_ports.comports())
    if len(ports) == 1:
        return ports[0].device
    return None


def open_midi_out():
    names = mido.get_output_names()
    if not names:
        print("No MIDI output ports found at all -- nothing to play through.")
        sys.exit(1)
    name = MIDI_PORT_NAME or names[0]
    print(f"MIDI output: {name}")
    return mido.open_output(name)


def schedule_note_off(midi_out, channel, note, delay=NOTE_OFF_DELAY):
    def off():
        midi_out.send(mido.Message("note_off", channel=channel, note=note))

    threading.Timer(delay, off).start()


def handle_line(midi_out, line):
    line = line.strip()
    if not line:
        return
    if line.startswith("#"):
        print(line[1:].strip())
        return

    if line in DRUM_NOTES:
        note = DRUM_NOTES[line]
        midi_out.send(mido.Message("note_on", channel=DRUM_CHANNEL, note=note, velocity=100))
        schedule_note_off(midi_out, DRUM_CHANNEL, note, delay=0.12)
        return

    if line.startswith("B:") or line.startswith("L:"):
        try:
            note = int(line[2:])
        except ValueError:
            return
        channel = BASS_CHANNEL if line.startswith("B:") else LEAD_CHANNEL
        note = max(0, min(127, note))
        midi_out.send(mido.Message("note_on", channel=channel, note=note, velocity=100))
        schedule_note_off(midi_out, channel, note)
        return

    print(f"(unrecognized: {line})")


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else find_port()
    if not port:
        print("Couldn't auto-detect the board's serial port.")
        print("Available ports:")
        for p in serial.tools.list_ports.comports():
            print(f"  {p.device} -- {p.description}")
        print("\nRun again with the port explicitly: python groovebox_midi_player.py COM9")
        return

    midi_out = open_midi_out()
    midi_out.send(mido.Message("program_change", channel=BASS_CHANNEL, program=BASS_PROGRAM))
    midi_out.send(mido.Message("program_change", channel=LEAD_CHANNEL, program=LEAD_PROGRAM))

    print(f"Opening {port} at {BAUD} baud...")
    ser = None
    while ser is None:
        try:
            ser = serial.Serial(port, BAUD, timeout=1)
        except serial.SerialException:
            print("  board not ready yet, retrying...")
            time.sleep(1.0)

    print("Listening for events. Ctrl+C to stop.")
    try:
        while True:
            try:
                raw = ser.readline()
            except serial.SerialException:
                print("[lost connection, reconnecting...]")
                ser.close()
                ser = None
                while ser is None:
                    try:
                        time.sleep(1.0)
                        ser = serial.Serial(port, BAUD, timeout=1)
                        print("[reconnected]")
                    except serial.SerialException:
                        pass
                continue
            if raw:
                try:
                    line = raw.decode("utf-8", errors="ignore")
                except Exception:
                    continue
                handle_line(midi_out, line)
    except KeyboardInterrupt:
        pass
    finally:
        if ser:
            ser.close()
        midi_out.close()
        print("\nStopped.")


if __name__ == "__main__":
    main()
