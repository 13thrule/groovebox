"""Effects -- standard MIDI CC messages, no DSP of our own. Reverb and
Chorus are GUI sliders (set-and-forget); Filter Cutoff is meant to be
driven live from the board's optional A2 pot (see groovebox.ino's
FX: field) for a real-time filter-sweep feel, same idea as a synth's
mod wheel.

Not every synth honours every CC -- Windows' built-in GS Wavetable
Synth supports reverb/chorus well; filter cutoff (CC74) support varies
by synth/soundfont, so treat that one as "try it and see."
"""

import mido

CC_REVERB = 91
CC_CHORUS = 93
CC_FILTER_CUTOFF = 74

ALL_CHANNELS = range(16)


def set_reverb(midi_out, value):
    """value: 0-127"""
    for ch in ALL_CHANNELS:
        midi_out.send(mido.Message("control_change", channel=ch, control=CC_REVERB, value=value))


def set_chorus(midi_out, value):
    """value: 0-127"""
    for ch in ALL_CHANNELS:
        midi_out.send(mido.Message("control_change", channel=ch, control=CC_CHORUS, value=value))


def set_filter_cutoff(midi_out, value, channels=ALL_CHANNELS):
    """value: 0-127. Defaults to all channels; pass specific channels
    (e.g. just bass/lead) to leave drums untouched."""
    for ch in channels:
        midi_out.send(mido.Message("control_change", channel=ch, control=CC_FILTER_CUTOFF, value=value))
