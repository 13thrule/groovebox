"""Renders your actual saved groovebox patterns/settings into a real
standalone song -- a General MIDI .mid file, built by arranging all 8
saved slots into a produced song structure (intro, groove, build,
drop, breakdown, rebuild, final chorus, fading outro), not just a
straight back-to-back chain of loops.

This is not a reimplementation of the app: it imports the same
patterns.py data model and reads current_program()/get_probability()
the live app uses, so accent, per-step probability, swing, per-track
volume/pan, master volume and delay all come from your real saved
data. On top of that, each SONG section can:
  - mute whole groups (drums-only intro, bass/lead breakdown, etc.)
  - ramp master volume across its own bars (builds, fades)
  - override delay for that section (echo-heavy breakdown/outro)
  - "humanize" -- multiply every step's probability, so a section
    that repeats the same pattern for many bars doesn't play back
    bit-for-identical every time (this is a real use of the
    probability feature, layered on top of whatever you've set
    per-step, not a replacement for it)

Run: python render_song.py
Output: ../groovebox_song.mid (next to groovebox_patterns.json)
"""

import random
from pathlib import Path

import mido

from patterns import (
    TRACKS, NUM_STEPS, load_patterns, load_settings, get_probability, current_program,
    GROUP_KICK, GROUP_SNARE, GROUP_HAT, GROUP_BASS, GROUP_LEAD,
)

OUT_FILE = Path(__file__).parent.parent / "groovebox_song.mid"
TICKS_PER_BEAT = 480
TEMPO_BPM = 96  # no BPM is persisted digitally (it lives on the board's pot), so this is a render-time choice
DRUM_CHANNEL = 9
NOTE_DURATION_FRACTION = 0.9  # how much of a step's length a note stays held for
ECHO_DELAY_STEPS = 2  # ~0.3s at 96 BPM, close to midi_output.DELAY_TIME_SEC's 0.18s

random.seed(20260812)  # reproducible "maybe" hits/humanize rolls, not different every render

# Each section: slot to play, how many bars, which groups to silence,
# a (start, end) master-volume ramp across the section's own bars,
# a delay override (None = use the saved setting), and a humanize
# factor multiplied into every step's probability (1.0 = no change).
SONG = [
    # slot  bars  mute                       volume     delay  humanize
    (0,     4,    {GROUP_BASS, GROUP_LEAD},   (55, 85),  0,     1.0),   # intro: drums only, building in
    (0,     4,    set(),                      (95, 100), 0,     1.0),   # bass/lead drop in over the same beat
    (1,     8,    set(),                      (100, 100),0,     0.9),   # groove -- slight humanize so 8 bars isn't robotic
    (2,     4,    set(),                      (100, 118),0,     1.0),   # buildup -- rising intensity
    (3,     8,    set(),                      (118, 118),0,     1.0),   # drop -- peak energy
    (4,     8,    set(),                      (110, 110),0,     0.85),  # drive -- densest pattern, extra humanize
    (5,     8,    {GROUP_KICK, GROUP_SNARE},  (70, 85),  45,    1.0),   # breakdown -- just hats/bass/lead, echoey
    (6,     4,    set(),                      (85, 110), 20,    1.0),   # rebuild -- drums return, light echo
    (7,     8,    set(),                      (120, 120),0,     1.0),   # final chorus -- climax
    (0,     4,    {GROUP_LEAD},               (90, 30),  55,    1.0),   # outro: thins out, echo tail, fades
]


def _emit_note(events, t, step_ticks, track, value, master_volume, delay_amount):
    if track["type"] == "drum":
        note = track["note"]
        channel = DRUM_CHANNEL
        base_velocity = value  # drum step value IS the velocity (this is where accent shows up)
    else:
        note = max(0, min(127, track["root"] + value))
        channel = track["channel"]
        base_velocity = 100  # matches midi_output.NOTE_BASE_VELOCITY

    scale = (track.get("volume", 127) / 127.0) * (master_volume / 127.0)
    velocity = max(1, min(127, int(base_velocity * scale)))
    duration_ticks = max(1, int(step_ticks * NOTE_DURATION_FRACTION))

    events.append((t, mido.Message("note_on", channel=channel, note=note, velocity=velocity)))
    events.append((t + duration_ticks, mido.Message("note_off", channel=channel, note=note)))

    if delay_amount > 0:
        echo_velocity = int(velocity * 0.5 * (delay_amount / 100.0))
        if echo_velocity >= 1:
            echo_t = t + step_ticks * ECHO_DELAY_STEPS
            events.append((echo_t, mido.Message("note_on", channel=channel, note=note, velocity=echo_velocity)))
            events.append((echo_t + duration_ticks, mido.Message("note_off", channel=channel, note=note)))


def _lerp(start, end, frac):
    return start + (end - start) * frac


def build_song(slots, settings, song=None):
    song = SONG if song is None else song
    swing = settings.get("swing", 12)
    base_delay = settings.get("delay_amount", 0)
    ticks_per_step = TICKS_PER_BEAT // 4

    events = []
    t = 0
    for slot_idx, bars, mute_groups, volume_range, delay_override, humanize in song:
        pattern = slots[slot_idx]
        delay_amount = base_delay if delay_override is None else delay_override
        vol_start, vol_end = volume_range

        for bar in range(bars):
            bar_frac = bar / (bars - 1) if bars > 1 else 1.0
            master_volume = max(1, min(127, int(_lerp(vol_start, vol_end, bar_frac))))

            for step in range(NUM_STEPS):
                # same swing formula as groovebox.ino's loop(): even-indexed
                # steps get lengthened, pushing the following upbeat later
                step_ticks = ticks_per_step
                if step % 2 == 0:
                    step_ticks += (ticks_per_step * swing) // 100

                for track in TRACKS:
                    if track["group"] in mute_groups:
                        continue
                    val = pattern[track["key"]][step]
                    if val is None:
                        continue
                    prob = min(100, get_probability(pattern, track["key"], step) * humanize)
                    if prob < 100 and random.uniform(0, 100) > prob:
                        continue
                    _emit_note(events, t, step_ticks, track, val, master_volume, delay_amount)

                t += step_ticks

    return events, t


def render(slots=None, settings=None, song=None, out_file=None):
    """slots/settings/song/out_file are all optional -- omit them to
    render your real saved patterns (the CLI default). Pass your own
    to render a different set of patterns (e.g. freshly-composed ones,
    see compose_song.py) through the same swing/velocity/delay engine."""
    if slots is None:
        slots = load_patterns()
    if settings is None:
        settings = load_settings()  # also fills in TRACKS' real saved program_idx/volume/pan as a side effect
    out_file = out_file or OUT_FILE

    events, total_ticks = build_song(slots, settings, song)
    events.sort(key=lambda e: e[0])

    mid = mido.MidiFile(ticks_per_beat=TICKS_PER_BEAT)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(TEMPO_BPM), time=0))
    track.append(mido.MetaMessage("track_name", name="Groovebox Song", time=0))

    for tr in TRACKS:
        if tr["type"] == "note":
            track.append(mido.Message("program_change", channel=tr["channel"],
                                       program=current_program(tr), time=0))
            track.append(mido.Message("control_change", channel=tr["channel"],
                                       control=10, value=tr.get("pan", 64), time=0))

    last_tick = 0
    for tick, msg in events:
        track.append(msg.copy(time=tick - last_tick))
        last_tick = tick

    out_file.parent.mkdir(parents=True, exist_ok=True)
    mid.save(out_file)

    duration_sec = mido.tick2second(total_ticks, TICKS_PER_BEAT, mido.bpm2tempo(TEMPO_BPM))
    bars_total = sum(bars for _, bars, _, _, _, _ in (song or SONG))
    print(f"Wrote {out_file}")
    print(f"{bars_total} bars, {duration_sec/60:.1f} min at {TEMPO_BPM} BPM, "
          f"swing {settings.get('swing')}, {len(events)} MIDI events")
    return out_file


if __name__ == "__main__":
    render()
