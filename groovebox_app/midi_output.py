"""MIDI output -- opening a port, sending notes, nothing else. Swap
MIDI_PORT_NAME to route into a real DAW (e.g. Tracktion Waveform) once
you've got one set up as a MIDI input, instead of the Windows built-in
synth.
"""

import sys
import threading

import mido

from patterns import TRACKS, current_program, cycle_instrument

MIDI_PORT_NAME = None  # None = first available (Windows GS Wavetable Synth)
DRUM_CHANNEL = 9  # MIDI channel 10 (0-indexed) -- General MIDI percussion
DRUM_NOTE_DURATION = 0.12
NOTE_DURATION = 0.25
NOTE_BASE_VELOCITY = 100  # fixed base for note tracks -- they don't have an accent concept, only drums do

# Delay/echo: not a MIDI CC (GM has no standardized delay-send CC most
# synths honour, unlike reverb/chorus), so this is a genuine software
# echo -- literally re-triggering the same note again, quieter, a
# fixed time later. Works regardless of what the receiving synth
# supports, which a CC-based approach couldn't guarantee.
DELAY_TIME_SEC = 0.18
DELAY_FEEDBACK = 0.5  # echo repeat's velocity, as a fraction of the original


def open_output():
    names = mido.get_output_names()
    if not names:
        print("No MIDI output ports found.")
        sys.exit(1)
    name = MIDI_PORT_NAME or names[0]
    print(f"MIDI output: {name}")
    out = mido.open_output(name)
    for t in TRACKS:
        if t["type"] == "note":
            out.send(mido.Message("program_change", channel=t["channel"], program=current_program(t)))
    return out


def next_instrument(midi_out, track):
    """Cycles a note track to its next instrument choice and applies it."""
    program = cycle_instrument(track)
    midi_out.send(mido.Message("program_change", channel=track["channel"], program=program))


def _send_note(midi_out, channel, note, velocity, duration):
    velocity = max(1, min(127, int(velocity)))
    midi_out.send(mido.Message("note_on", channel=channel, note=note, velocity=velocity))
    threading.Timer(duration, lambda: midi_out.send(
        mido.Message("note_off", channel=channel, note=note))).start()


def play(midi_out, track, value, master_volume=100, delay_amount=0):
    """Sends a note on for the given track/step value, and schedules
    the matching note off. `value` is the step's raw pattern entry --
    velocity for drums (this is where accent actually has an audible
    effect -- previously this was hardcoded and accent was silently
    ignored), a semitone offset for note tracks.

    master_volume (0-127) and the track's own "volume" (0-127, see
    mixer_window.py) both scale the final velocity -- this is how
    per-track level works even for drums, which all share one MIDI
    channel and can't be leveled via channel-volume CC individually.

    delay_amount (0-100): if set, schedules one echo repeat of this
    same note at reduced velocity -- see the DELAY_* constants above
    for why this is a real re-trigger rather than a MIDI CC.
    """
    if track["type"] == "drum":
        note = track["note"]
        channel = DRUM_CHANNEL
        duration = DRUM_NOTE_DURATION
        base_velocity = value
    else:
        note = max(0, min(127, track["root"] + value))
        channel = track["channel"]
        duration = NOTE_DURATION
        base_velocity = NOTE_BASE_VELOCITY

    scale = (track.get("volume", 127) / 127.0) * (master_volume / 127.0)
    velocity = base_velocity * scale
    _send_note(midi_out, channel, note, velocity, duration)

    if delay_amount > 0:
        echo_velocity = velocity * DELAY_FEEDBACK * (delay_amount / 100.0)
        if echo_velocity >= 1:
            threading.Timer(DELAY_TIME_SEC, lambda: _send_note(
                midi_out, channel, note, echo_velocity, duration)).start()
