"""Track definitions and pattern data model -- what a track is, what
its default sound is, and how pattern slots are loaded/saved. No GUI,
MIDI, or serial code here; this module only knows about data.

To add a new drum track: add one entry to TRACKS with type "drum" and
a GM percussion note number. Nothing else needs to change -- the GUI
grid and pattern storage both derive from this one list.

To add a new instrument choice to Bass or Lead: add a (program,name)
tuple to that track's "programs" list. Click the track's row label in
the GUI to cycle through them -- that's the "vibes" switch.
"""

import json
from pathlib import Path

PATTERNS_FILE = Path(__file__).parent.parent / "groovebox_patterns.json"
SETTINGS_FILE = Path(__file__).parent.parent / "groovebox_settings.json"
NUM_SLOTS = 8
NUM_STEPS = 16

# Mute groups, matching the 5 physical buttons on the board:
GROUP_KICK, GROUP_SNARE, GROUP_HAT, GROUP_BASS, GROUP_LEAD = range(5)

SCALE = [0, 2, 3, 5, 7, 9, 10, 12]  # note cells cycle through these semitone offsets

# Drum step values: a step cycles None -> NORMAL_VELOCITY -> ACCENT_VELOCITY -> None.
# Real drum machines call this "accent" (TR-808/909) -- it's what makes a
# programmed beat sound played instead of quantized and flat.
NORMAL_VELOCITY = 90
ACCENT_VELOCITY = 127

BASS_PROGRAMS = [
    (33, "Elec Bass"), (35, "Fretless"), (36, "Slap Bass"),
    (38, "Synth1"), (39, "Synth2"), (32, "Acoustic"),
]
LEAD_PROGRAMS = [
    (80, "Sq Lead"), (81, "Saw Lead"), (4, "E.Piano"), (17, "Organ"),
    (27, "Clean Gtr"), (30, "Dist Gtr"), (62, "SynBrass"), (73, "Flute"),
]

DEFAULT_VOLUME = 100  # 0-127, per-track mixer level (see mixer_window.py)
DEFAULT_PAN = 64      # 0-127, center -- only audible on Bass/Lead, which have their own MIDI channels

TRACKS = [
    {"key": "kick",    "label": "Kick",    "group": GROUP_KICK,  "type": "drum", "note": 36},
    {"key": "snare",   "label": "Snare",   "group": GROUP_SNARE, "type": "drum", "note": 38},
    {"key": "clap",    "label": "Clap",    "group": GROUP_SNARE, "type": "drum", "note": 39},
    {"key": "clhat",   "label": "Cl Hat",  "group": GROUP_HAT,   "type": "drum", "note": 42},
    {"key": "ophat",   "label": "Op Hat",  "group": GROUP_HAT,   "type": "drum", "note": 46},
    {"key": "rim",     "label": "Rim",     "group": GROUP_HAT,   "type": "drum", "note": 37},
    {"key": "tom",     "label": "Tom",     "group": GROUP_HAT,   "type": "drum", "note": 45},
    {"key": "cowbell", "label": "Cowbell", "group": GROUP_HAT,   "type": "drum", "note": 56},
    {"key": "crash",   "label": "Crash",   "group": GROUP_HAT,   "type": "drum", "note": 49},
    {"key": "conga",   "label": "Conga",   "group": GROUP_HAT,   "type": "drum", "note": 63},
    {"key": "shaker",  "label": "Shaker",  "group": GROUP_HAT,   "type": "drum", "note": 70},
    {"key": "tamb",    "label": "Tamb",    "group": GROUP_HAT,   "type": "drum", "note": 54},
    {"key": "ride",    "label": "Ride",    "group": GROUP_HAT,   "type": "drum", "note": 51},
    {"key": "bass",    "label": "Bass",    "group": GROUP_BASS,  "type": "note", "channel": 0,
     "root": 33, "programs": BASS_PROGRAMS, "program_idx": 0},
    {"key": "lead",    "label": "Lead",    "group": GROUP_LEAD,  "type": "note", "channel": 1,
     "root": 69, "programs": LEAD_PROGRAMS, "program_idx": 0},
]
for _t in TRACKS:
    _t.setdefault("volume", DEFAULT_VOLUME)
    _t.setdefault("pan", DEFAULT_PAN)
TRACK_BY_KEY = {t["key"]: t for t in TRACKS}

PROB_KEY_SUFFIX = "__prob"  # parallel per-step probability grid, see empty_pattern()
PROB_TIERS = [100, 75, 50, 25]  # step probability cycles through these


def current_program(track):
    return track["programs"][track["program_idx"]][0]


def current_program_name(track):
    return track["programs"][track["program_idx"]][1]


def cycle_instrument(track):
    track["program_idx"] = (track["program_idx"] + 1) % len(track["programs"])
    return current_program(track)


def empty_pattern():
    p = {t["key"]: [None] * NUM_STEPS for t in TRACKS}
    for t in TRACKS:
        p[t["key"] + PROB_KEY_SUFFIX] = [100] * NUM_STEPS  # 100 = always plays
    return p


def get_probability(pattern, track_key, step):
    return pattern.get(track_key + PROB_KEY_SUFFIX, [100] * NUM_STEPS)[step]


def cycle_probability(pattern, track_key, step):
    key = track_key + PROB_KEY_SUFFIX
    if key not in pattern:
        pattern[key] = [100] * NUM_STEPS
    cur = pattern[key][step]
    idx = PROB_TIERS.index(cur) if cur in PROB_TIERS else -1
    pattern[key][step] = PROB_TIERS[(idx + 1) % len(PROB_TIERS)]
    return pattern[key][step]


def default_starter_pattern():
    """Slot 1: a funky house-ish starter groove."""
    p = empty_pattern()
    for s in (0, 4, 8, 12):
        p["kick"][s] = 100
    for s in (4, 12):
        p["snare"][s] = 100
    for s in range(0, 16, 2):
        p["clhat"][s] = 100
    for s in (2, 6, 10, 14):
        p["ophat"][s] = 100
    for s in (0, 6, 8, 14):
        p["bass"][s] = 0  # root note
    return p


def trap_starter_pattern():
    """Slot 2: syncopated kick, hi-hat rolls, cowbell accents."""
    p = empty_pattern()
    for s in (0, 3, 7, 10, 13):
        p["kick"][s] = 100
    for s in (4, 12):
        p["snare"][s] = 100
    for s in range(16):
        p["clhat"][s] = 100
    for s in (6, 14):
        p["cowbell"][s] = 100
    for s in (0,):
        p["bass"][s] = 0
    for s in (8,):
        p["bass"][s] = -3
    for s in (2, 6, 10):
        p["lead"][s] = 3
    return p


def funk_starter_pattern():
    """Slot 4: syncopated funk breakbeat -- ghost-note rim hits, an
    alternating hat/shaker 16th-note pocket, cowbell accents, and a
    syncopated bassline with anticipated hits (classic funk phrasing:
    landing just *before* the beat, not on it)."""
    p = empty_pattern()
    for s in (0, 3, 6, 10, 12):
        p["kick"][s] = 100
    for s in (4, 12):
        p["snare"][s] = 100
    for s in (2, 7, 9, 14):
        p["rim"][s] = 100  # ghost-note snare stand-in
    for s in range(0, 16, 2):
        p["clhat"][s] = 100
    for s in range(1, 16, 2):
        p["shaker"][s] = 100
    p["ophat"][14] = 100  # turnaround accent
    for s in (1, 5, 9, 13):
        p["conga"][s] = 100
    for s in (6, 14):
        p["cowbell"][s] = 100
    p["crash"][0] = 100
    p["tom"][15] = 100  # little fill into the next bar
    for s, offset in ((0, 0), (3, 7), (6, 0), (8, 3), (11, 0), (14, 5)):
        p["bass"][s] = offset
    for s, offset in ((2, 0), (10, 7)):
        p["lead"][s] = offset
    return p


def afrobeat_starter_pattern():
    """Slot 5: spacious Afrobeat/Latin groove -- constant 16th-note
    shaker (the genre's signature texture), a dense syncopated conga
    tumbao, offbeat tambourine, loose clave-adjacent cowbell, and a
    warm, wide-open bassline."""
    p = empty_pattern()
    for s in (0, 6, 10):
        p["kick"][s] = 100
    for s in (4, 12):
        p["rim"][s] = 100  # softer than a snare backbeat, more "world" feel
    for s in (0, 4, 8, 12):
        p["clhat"][s] = 100
    for s in range(16):
        p["shaker"][s] = 100
    for s in (2, 3, 7, 9, 11, 15):
        p["conga"][s] = 100
    for s in (0, 7, 10):
        p["cowbell"][s] = 100
    for s in (2, 6, 10, 14):
        p["tamb"][s] = 100
    for s, offset in ((0, 0), (6, 5), (10, 7), (13, 3)):
        p["bass"][s] = offset
    for s, offset in ((0, 0), (8, 7), (12, 9)):
        p["lead"][s] = offset
    return p


def boombap_starter_pattern():
    """Slot 6: laid-back boom-bap hip-hop -- classic syncopated kick,
    solid backbeat snare, steady 8th-note hats, and a sparse, moody
    bassline with a lead that just punctuates rather than carries a
    melody. Try switching Lead to E.Piano for the classic sample-chop
    feel."""
    p = empty_pattern()
    for s in (0, 7, 10):
        p["kick"][s] = 100
    for s in (4, 12):
        p["snare"][s] = 100
    for s in range(0, 16, 2):
        p["clhat"][s] = 100
    for s in (6, 14):
        p["rim"][s] = 100
    for s in (1, 5, 9, 13):
        p["shaker"][s] = 100
    p["crash"][0] = 100
    for s, offset in ((0, 0), (6, 0), (10, 10), (13, 5)):
        p["bass"][s] = offset
    for s, offset in ((3, 3), (11, 0)):
        p["lead"][s] = offset
    return p


def disco_starter_pattern():
    """Slot 7: four-on-the-floor disco -- open hat on every offbeat
    (the genre's signature "chick"), octave-jumping bassline, ride
    cymbal for shimmer, and a syncopated lead stab."""
    p = empty_pattern()
    for s in (0, 4, 8, 12):
        p["kick"][s] = 100
    for s in (4, 12):
        p["snare"][s] = 100
    for s in (2, 6, 10, 14):
        p["ophat"][s] = 100  # the classic disco offbeat "chick"
    for s in (0, 4, 8, 12):
        p["clhat"][s] = 100
    for s in range(0, 16, 2):
        p["ride"][s] = 100
    for s, offset in ((0, 0), (2, 12), (4, 0), (6, 12), (8, 7), (10, 7), (12, 0), (14, 12)):
        p["bass"][s] = offset  # root/octave pumping, classic disco bass
    for s, offset in ((3, 7), (11, 0)):
        p["lead"][s] = offset
    return p


def dnb_starter_pattern():
    """Slot 8: drum & bass / breakbeat -- a chopped Amen-break-style
    kick/snare pattern (the syncopation is the whole point, not
    on-the-beat), fast hats, and a deep sub-bass that mostly sits out
    of the way except for a couple of low stabs."""
    p = empty_pattern()
    for s in (0, 10):
        p["kick"][s] = 100
    for s in (4, 7, 12):
        p["snare"][s] = 100
    for s in (2, 9, 14):
        p["rim"][s] = 100  # extra chopped-break texture
    for s in range(16):
        p["clhat"][s] = 100
    for s in (6, 13):
        p["ophat"][s] = 100
    for s, offset in ((0, 0), (10, 0)):
        p["bass"][s] = offset
    p["lead"][7] = 3
    p["lead"][15] = 0
    return p


def load_patterns():
    if PATTERNS_FILE.exists():
        try:
            data = json.loads(PATTERNS_FILE.read_text())
            slots = []
            for i in range(NUM_SLOTS):
                if i < len(data):
                    p = empty_pattern()
                    p.update(data[i])
                    slots.append(p)
                else:
                    slots.append(empty_pattern())
            return slots
        except (json.JSONDecodeError, OSError):
            pass
    slots = [empty_pattern() for _ in range(NUM_SLOTS)]
    slots[0] = default_starter_pattern()
    slots[1] = trap_starter_pattern()
    if NUM_SLOTS > 2:
        slots[2] = funk_starter_pattern()
    if NUM_SLOTS > 3:
        slots[3] = afrobeat_starter_pattern()
    if NUM_SLOTS > 4:
        slots[4] = boombap_starter_pattern()
    if NUM_SLOTS > 5:
        slots[5] = disco_starter_pattern()
    if NUM_SLOTS > 6:
        slots[6] = dnb_starter_pattern()
    return slots


def save_patterns(slots):
    PATTERNS_FILE.write_text(json.dumps(slots, indent=2))


# ---------------------------------------------------------------------
# Settings (instrument choices, mixer levels, swing, master volume,
# delay) -- separate from pattern slots since these are global mixer/
# performance state, not per-pattern data. Fixes a real bug: instrument
# choice used to live only in memory on the TRACKS list and silently
# reset to default every restart.
#
# gui.py keeps the returned dict as self.settings and calls
# save_settings(self.settings) whenever anything in it changes; this
# module fills in program_idx/mixer from live TRACKS state at save
# time, so callers never need to build that part themselves.
# ---------------------------------------------------------------------

DEFAULT_SETTINGS = {
    "swing": 12,
    "master_volume": 100,
    "delay_amount": 0,
    "program_idx": {},
    "mixer": {},
}


def load_settings():
    settings = dict(DEFAULT_SETTINGS)
    if SETTINGS_FILE.exists():
        try:
            settings.update(json.loads(SETTINGS_FILE.read_text()))
        except (json.JSONDecodeError, OSError):
            pass
    for t in TRACKS:
        if t["type"] == "note" and t["key"] in settings["program_idx"]:
            t["program_idx"] = settings["program_idx"][t["key"]]
        if t["key"] in settings["mixer"]:
            t["volume"] = settings["mixer"][t["key"]].get("volume", DEFAULT_VOLUME)
            t["pan"] = settings["mixer"][t["key"]].get("pan", DEFAULT_PAN)
    return settings


def save_settings(settings):
    settings = dict(settings)
    settings["program_idx"] = {t["key"]: t["program_idx"] for t in TRACKS if t["type"] == "note"}
    settings["mixer"] = {t["key"]: {"volume": t["volume"], "pan": t["pan"]} for t in TRACKS}
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2))
