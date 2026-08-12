"""Composes brand-new drum/bass/lead patterns from scratch by calling
the exact same methods a click in the live app triggers --
DrumMachine.toggle_cell() (the off -> normal -> accent cycle),
cycle_note() (walks the SCALE), cycle_prob() (the 100/75/50/25
probability tiers), change_instrument() (cycles a track's GM program).
Nothing here reuses the 8 patterns already saved in
groovebox_patterns.json, and nothing reuses the 7 canned genre starter
functions in patterns.py -- this writes new material with the real
tool, starting from empty_pattern() every time.

Storage is redirected to a scratch folder before any pattern data is
touched, so nothing this script does can overwrite your real saved
song or settings.

Run: python compose_song.py
Output: ../groovebox_generated_song.mid
"""

import queue
import shutil
import tkinter as tk
from pathlib import Path

import patterns

SCRATCH_DIR = Path(__file__).parent.parent / "_compose_scratch"
if SCRATCH_DIR.exists():
    shutil.rmtree(SCRATCH_DIR)
SCRATCH_DIR.mkdir()
patterns.PATTERNS_FILE = SCRATCH_DIR / "patterns.json"
patterns.SETTINGS_FILE = SCRATCH_DIR / "settings.json"

import midi_output
import render_song
from gui import DrumMachine

GENERATED_OUT_FILE = Path(__file__).parent.parent / "groovebox_generated_song.mid"
VERSE, CHORUS, BREAKDOWN = 0, 1, 2

# Section order/dynamics for the freshly-composed material -- same
# schema as render_song.SONG (mute groups, volume ramp, delay, humanize).
SONG_GENERATED = [
    (VERSE,     4, {patterns.GROUP_BASS, patterns.GROUP_LEAD}, (60, 90),   0,  1.0),
    (VERSE,     4, set(),                                      (95, 100),  0,  1.0),
    (CHORUS,    8, set(),                                      (105, 120), 0,  1.0),
    (BREAKDOWN, 8, set(),                                      (70, 85),   45, 1.0),
    (CHORUS,    8, set(),                                      (115, 120), 0,  0.9),
    (VERSE,     4, {patterns.GROUP_LEAD},                      (90, 25),   40, 1.0),
]


class FakeLink:
    def __init__(self):
        self.events = queue.Queue()

    def send_hit(self, mask):
        pass

    def send_swing(self, percent):
        pass

    def send_bpm(self, bpm):
        pass


class FakeMidiOut:
    def send(self, msg):
        pass


def set_note(dm, track, step, value):
    """Repeatedly calls the real cycle_note() until it lands on the
    wanted SCALE value -- same walk a right-click would do, just
    driven programmatically instead of by a mouse."""
    pattern = dm.slots[dm.current_slot]
    guard = 0
    while pattern[track["key"]][step] != value:
        dm.cycle_note(track, step)
        guard += 1
        if guard > len(patterns.SCALE) + 1:
            raise ValueError(f"{value} isn't reachable via cycle_note for {track['key']}")


def accent(dm, track, step):
    """off -> normal -> accent, via two real toggle_cell() calls."""
    dm.toggle_cell(track, step)
    dm.toggle_cell(track, step)


def hit(dm, track, step):
    """off -> normal, one real toggle_cell() call."""
    dm.toggle_cell(track, step)


def compose_verse(dm, slot=VERSE, change_instruments=True):
    kick, snare, clhat, rim, bass, lead = (
        patterns.TRACK_BY_KEY[k] for k in ("kick", "snare", "clhat", "rim", "bass", "lead"))

    dm.slots[slot] = patterns.empty_pattern()
    dm.select_slot(slot)

    for s in (0, 6, 10):
        hit(dm, kick, s)
    accent(dm, kick, 14)  # accented pickup into the next bar
    for s in (4, 12):
        hit(dm, snare, s)
    for s in range(0, 16, 2):
        hit(dm, clhat, s)
    for s in (3, 7, 11, 15):
        hit(dm, rim, s)  # ghost notes off the beat
    for s in (2, 6, 10, 14):
        dm.cycle_prob(clhat, s)  # 100 -> 75, so the hat pattern isn't bar-for-bar identical

    if change_instruments:
        dm.change_instrument(bass)  # move off whatever program it started at
    for s, deg in ((0, 0), (3, 3), (6, 0), (9, 5), (12, 0), (14, 7)):
        hit(dm, bass, s)
        set_note(dm, bass, s, deg)
    for s, deg in ((7, 7), (15, 12)):
        hit(dm, lead, s)
        set_note(dm, lead, s, deg)


def compose_chorus(dm, slot=CHORUS, change_instruments=True):
    kick, snare, clhat, ophat, crash, shaker, bass, lead = (
        patterns.TRACK_BY_KEY[k] for k in
        ("kick", "snare", "clhat", "ophat", "crash", "shaker", "bass", "lead"))

    dm.slots[slot] = patterns.empty_pattern()
    dm.select_slot(slot)

    for s in (0, 4, 8, 12):
        accent(dm, kick, s)
    accent(dm, snare, 4)
    accent(dm, snare, 12)
    hit(dm, snare, 10)  # extra ghost snare
    for s in range(16):
        hit(dm, clhat, s)
    for s in (1, 3, 5, 7, 9, 11, 13, 15):
        dm.cycle_prob(clhat, s)  # loosen the offbeats to 75%
    for s in (2, 6, 10, 14):
        hit(dm, ophat, s)
    accent(dm, crash, 0)  # impact on the downbeat of the chorus
    for s in (1, 3, 5, 7, 9, 11, 13, 15):
        hit(dm, shaker, s)
    for s in (3, 11):
        dm.cycle_prob(shaker, s)
        dm.cycle_prob(shaker, s)  # 100 -> 75 -> 50, sparser than the hats

    if change_instruments:
        dm.change_instrument(bass)  # a second cycle -- distinct from the verse's voice
    for s, deg in ((0, 0), (2, 0), (4, 3), (6, 3), (8, 5), (10, 5), (12, 7), (14, 7)):
        hit(dm, bass, s)
        set_note(dm, bass, s, deg)

    if change_instruments:
        for _ in range(2):
            dm.change_instrument(lead)  # brighter voice for the melodic hook
    for s, deg in ((0, 12), (4, 10), (8, 7), (12, 5)):
        hit(dm, lead, s)
        set_note(dm, lead, s, deg)


def compose_breakdown(dm, slot=BREAKDOWN, change_instruments=True):
    kick, ophat, shaker, bass, lead = (
        patterns.TRACK_BY_KEY[k] for k in ("kick", "ophat", "shaker", "bass", "lead"))

    dm.slots[slot] = patterns.empty_pattern()
    dm.select_slot(slot)

    hit(dm, kick, 0)
    for s in (4, 12):
        hit(dm, ophat, s)
    for s in (0, 8):
        hit(dm, shaker, s)
        dm.cycle_prob(shaker, s)  # 100 -> 75
        dm.cycle_prob(shaker, s)  # 75 -> 50, these only sometimes play

    for s, deg in ((0, 0), (8, 0)):
        hit(dm, bass, s)
        set_note(dm, bass, s, deg)
    for s, deg in ((0, 12), (6, 7), (10, 5)):
        hit(dm, lead, s)
        set_note(dm, lead, s, deg)
    dm.cycle_prob(lead, 10)  # this one's a maybe -- gives the phrase-end some air


def compose():
    """Standalone demo: composes into 3 scratch slots (storage
    redirected, your real save file untouched) and renders straight
    to a MIDI file. This is what produced groovebox_generated_song.mid."""
    root = tk.Tk()
    root.withdraw()
    orig_open_output = midi_output.open_output
    midi_output.open_output = lambda: FakeMidiOut()
    try:
        dm = DrumMachine(root, FakeLink())
        compose_verse(dm)
        compose_chorus(dm)
        compose_breakdown(dm)
        slots = [p for p in dm.slots]  # already independent dicts, one per real slot index
        settings = {"swing": 20, "master_volume": 100, "delay_amount": 0}
    finally:
        midi_output.open_output = orig_open_output
        root.destroy()

    out = render_song.render(slots=slots, settings=settings, song=SONG_GENERATED,
                              out_file=GENERATED_OUT_FILE)
    shutil.rmtree(SCRATCH_DIR, ignore_errors=True)
    return out


def overwrite_real_slots():
    """Replaces all NUM_SLOTS worth of your real saved patterns
    (groovebox_patterns.json) with freshly-composed material, cycling
    Verse/Chorus/Breakdown across every slot. Storage is pointed back
    at the real files for this (not the scratch dir) -- that's the
    whole point here. Instrument choice (Bass/Lead program, a GLOBAL
    setting shared by every slot, not per-pattern) is deliberately
    left alone: change_instruments=False everywhere, so your saved
    Slap Bass / Saw Lead pick survives untouched. Only hit/note/
    probability data -- genuinely per-slot -- gets overwritten."""
    real_patterns_file = SCRATCH_DIR.parent / "groovebox_patterns.json"
    real_settings_file = SCRATCH_DIR.parent / "groovebox_settings.json"
    patterns.PATTERNS_FILE = real_patterns_file
    patterns.SETTINGS_FILE = real_settings_file

    composers = [compose_verse, compose_chorus, compose_breakdown]

    root = tk.Tk()
    root.withdraw()
    orig_open_output = midi_output.open_output
    midi_output.open_output = lambda: FakeMidiOut()
    try:
        dm = DrumMachine(root, FakeLink())  # loads your real 8 saved slots + real settings
        for slot in range(patterns.NUM_SLOTS):
            composers[slot % len(composers)](dm, slot=slot, change_instruments=False)
    finally:
        midi_output.open_output = orig_open_output
        root.destroy()

    shutil.rmtree(SCRATCH_DIR, ignore_errors=True)
    print(f"Overwrote all {patterns.NUM_SLOTS} slots in {real_patterns_file}")


if __name__ == "__main__":
    compose()
