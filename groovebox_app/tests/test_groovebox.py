"""Headless tests for the groovebox app -- exercises the real
patterns/history/song_mode modules and drives the actual DrumMachine
GUI class by calling its production methods directly (no physical
clicks needed; Tkinter widgets are created but never shown). No
serial board or audible MIDI output is required -- both are faked.

Run with: python -m pytest tests/test_groovebox.py -v
"""

import queue
import sys
import tkinter as tk
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import patterns
import midi_output
import gui as gui_module
from history import History
from song_mode import SongMode


class FakeLink:
    """Stands in for serial_link.SerialLink -- records what would have
    been sent to the board instead of touching a real port."""

    def __init__(self):
        self.events = queue.Queue()
        self.sent_hits = []
        self.sent_swing = []
        self.sent_bpm = []

    def send_hit(self, mask):
        self.sent_hits.append(mask)

    def send_swing(self, percent):
        self.sent_swing.append(percent)

    def send_bpm(self, bpm):
        self.sent_bpm.append(bpm)


class FakeMidiOut:
    """A mido output port never has to leave the process for these
    tests -- this just records what was sent."""

    def __init__(self):
        self.sent = []

    def send(self, msg):
        self.sent.append(msg)


@pytest.fixture(scope="session")
def tk_root():
    # Windows' Tcl interpreter doesn't like being repeatedly created and
    # torn down in-process -- one hidden root for the whole test session,
    # reused by every test that needs a DrumMachine.
    root = tk.Tk()
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def isolated_storage(tmp_path, monkeypatch):
    """Redirects pattern/settings persistence to a throwaway temp dir
    so tests never read or overwrite the user's real saved song data."""
    monkeypatch.setattr(patterns, "PATTERNS_FILE", tmp_path / "patterns.json")
    monkeypatch.setattr(patterns, "SETTINGS_FILE", tmp_path / "settings.json")
    yield tmp_path


@pytest.fixture
def silent_midi(monkeypatch):
    """Replaces midi_output.play with a recorder -- verifies playback
    was *invoked* correctly without making the test suite noisy or
    depending on a real synth device being present."""
    calls = []

    def fake_play(midi_out, track, value, master_volume=100, delay_amount=0):
        calls.append({
            "track": track["key"], "value": value,
            "master_volume": master_volume, "delay_amount": delay_amount,
        })

    monkeypatch.setattr(midi_output, "play", fake_play)
    monkeypatch.setattr(gui_module.midi_output, "play", fake_play)
    return calls


@pytest.fixture
def machine(tk_root, isolated_storage, silent_midi, monkeypatch):
    """A real DrumMachine, built for real (Tkinter widgets and all),
    just never packed onto a visible screen and never given a real
    serial port or MIDI device."""
    monkeypatch.setattr(midi_output, "open_output", lambda: FakeMidiOut())
    for w in tk_root.winfo_children():
        w.destroy()
    dm = gui_module.DrumMachine(tk_root, FakeLink())
    yield dm


# ------------------------------------------------------------- patterns.py

def test_empty_pattern_has_probability_arrays():
    p = patterns.empty_pattern()
    for t in patterns.TRACKS:
        assert p[t["key"]] == [None] * patterns.NUM_STEPS
        assert p[t["key"] + patterns.PROB_KEY_SUFFIX] == [100] * patterns.NUM_STEPS


def test_cycle_probability_wraps_through_tiers():
    p = patterns.empty_pattern()
    seen = [patterns.get_probability(p, "kick", 0)]
    for _ in range(len(patterns.PROB_TIERS)):
        seen.append(patterns.cycle_probability(p, "kick", 0))
    # starts at 100, then steps through the remaining tiers, then wraps back to 100
    assert seen == [100] + patterns.PROB_TIERS[1:] + [patterns.PROB_TIERS[0]]
    assert seen[-1] == seen[0]  # full cycle returns to where it started


def test_all_starter_patterns_build_without_error():
    for fn in (patterns.default_starter_pattern, patterns.trap_starter_pattern,
               patterns.funk_starter_pattern, patterns.afrobeat_starter_pattern,
               patterns.boombap_starter_pattern, patterns.disco_starter_pattern,
               patterns.dnb_starter_pattern):
        p = fn()
        assert any(v is not None for v in p["kick"]), f"{fn.__name__} has no kick hits"


def test_settings_round_trip(isolated_storage):
    s = patterns.load_settings()
    s["swing"] = 33
    s["master_volume"] = 77
    s["delay_amount"] = 25
    patterns.TRACKS[-1]["volume"] = 55  # lead track
    patterns.save_settings(s)

    reloaded = patterns.load_settings()
    assert reloaded["swing"] == 33
    assert reloaded["master_volume"] == 77
    assert reloaded["delay_amount"] == 25
    assert patterns.TRACKS[-1]["volume"] == 55  # mixer level survived the round trip


# -------------------------------------------------------------- history.py

def test_history_undo_restores_prior_state_after_further_mutation():
    h = History()
    pattern = patterns.empty_pattern()
    h.push(0, pattern)  # snapshot before the edit below
    pattern["kick"][0] = 100  # mutate in place, as gui.py does

    slot, restored = h.undo()
    assert slot == 0
    assert restored["kick"][0] is None  # snapshot must be a deep copy, unaffected by the later mutation


def test_history_respects_slot_index_across_slot_switches():
    h = History()
    h.push(2, {"kick": [None]})
    h.push(5, {"kick": [90]})
    slot, _ = h.undo()
    assert slot == 5
    slot, _ = h.undo()
    assert slot == 2
    assert h.undo() is None
    assert not h.can_undo()


def test_history_bounded_by_maxlen():
    h = History(maxlen=3)
    for i in range(5):
        h.push(i, {})
    popped = [h.undo()[0] for _ in range(3)]
    assert popped == [4, 3, 2]  # oldest two (0, 1) were evicted
    assert h.undo() is None


# ------------------------------------------------------------- song_mode.py

def test_song_mode_advances_after_correct_bar_count():
    sm = SongMode(arrangement=[(0, 2), (1, 3)])
    sm.enabled = True
    assert sm.current_slot() == 0
    assert sm.advance_bar() is None  # bar 1 of 2 -- not time to switch yet
    assert sm.advance_bar() == 1     # bar 2 of 2 -- switches to slot 1
    assert sm.advance_bar() is None
    assert sm.advance_bar() is None
    assert sm.advance_bar() == 0     # wraps back to the start of the arrangement


def test_song_mode_disabled_never_advances():
    sm = SongMode(arrangement=[(0, 1), (1, 1)])
    assert sm.advance_bar() is None
    assert sm.current_slot() == 0


# --------------------------------------------------------- gui.py: solo/mute

def test_solo_mutes_every_other_group(machine):
    kick_track = patterns.TRACK_BY_KEY["kick"]
    machine.toggle_solo(kick_track)
    mute = machine._effective_mute()
    assert not (mute & (1 << patterns.GROUP_KICK))       # soloed group stays audible
    assert mute & (1 << patterns.GROUP_SNARE)             # everything else is silenced
    assert mute & (1 << patterns.GROUP_LEAD)

    machine.toggle_solo(kick_track)  # toggling again clears the solo
    assert machine._effective_mute() == machine.current_mute


def test_hardware_mute_still_applies_without_solo(machine):
    machine.current_mute = 1 << patterns.GROUP_SNARE
    assert machine._effective_mute() == 1 << patterns.GROUP_SNARE


# --------------------------------------------------- gui.py: editing + undo

def test_toggle_cell_drum_cycles_off_normal_accent_off(machine):
    kick_track = patterns.TRACK_BY_KEY["kick"]
    pattern = machine.slots[machine.current_slot]
    pattern["kick"][0] = None

    machine.toggle_cell(kick_track, 0)
    assert pattern["kick"][0] == patterns.NORMAL_VELOCITY
    machine.toggle_cell(kick_track, 0)
    assert pattern["kick"][0] == patterns.ACCENT_VELOCITY
    machine.toggle_cell(kick_track, 0)
    assert pattern["kick"][0] is None


def test_undo_reverts_a_cell_edit(machine):
    kick_track = patterns.TRACK_BY_KEY["kick"]
    pattern = machine.slots[machine.current_slot]
    pattern["kick"][3] = None

    machine.toggle_cell(kick_track, 3)
    assert pattern["kick"][3] == patterns.NORMAL_VELOCITY
    machine.undo()
    assert machine.slots[machine.current_slot]["kick"][3] is None


def test_cycle_prob_via_gui_matches_patterns_module(machine):
    kick_track = patterns.TRACK_BY_KEY["kick"]
    machine.cycle_prob(kick_track, 5)  # starts at 100 (not in the cycle's own tier list) -> first tier
    pattern = machine.slots[machine.current_slot]
    assert patterns.get_probability(pattern, "kick", 5) == patterns.PROB_TIERS[1]


def test_copy_paste_pattern(machine):
    machine.select_slot(0)
    machine.slots[0]["kick"][0] = patterns.ACCENT_VELOCITY
    machine.copy_pattern()

    machine.select_slot(1)
    machine.slots[1]["kick"][0] = None
    machine.paste_pattern()
    assert machine.slots[1]["kick"][0] == patterns.ACCENT_VELOCITY


# ------------------------------------------------------ gui.py: step handling

def test_handle_step_skips_muted_group_and_reports_hit_mask(machine):
    machine.select_slot(0)
    machine.slots[0] = patterns.empty_pattern()  # isolate from the real starter/saved pattern data
    pattern = machine.slots[0]
    pattern["kick"][0] = 100
    pattern["snare"][0] = 100
    machine.current_mute = 1 << patterns.GROUP_SNARE

    machine._handle_step({"step": 0, "pattern": 0, "mute": 1 << patterns.GROUP_SNARE,
                           "fill": False, "fx": 0})

    assert machine.link.sent_hits[-1] == 1 << patterns.GROUP_KICK  # snare muted, didn't fire


def test_handle_step_zero_probability_never_fires(machine, monkeypatch):
    machine.select_slot(0)
    machine.slots[0] = patterns.empty_pattern()  # isolate from the real starter/saved pattern data
    pattern = machine.slots[0]
    pattern["kick"][0] = 100
    patterns.cycle_probability(pattern, "kick", 0)  # 100 -> 75
    monkeypatch.setattr(gui_module.random, "randint", lambda a, b: 100)  # force a "miss"

    machine._handle_step({"step": 0, "pattern": 0, "mute": 0, "fill": False, "fx": 0})
    assert machine.link.sent_hits[-1] == 0


def test_song_mode_overrides_board_pattern_sync(machine):
    machine.song_mode.set_arrangement([(3, 1), (5, 1)])
    machine.song_mode.enabled = True
    machine.current_slot = 3

    # Board reports it's still on slot 0 -- song mode should win, not the board.
    machine._handle_step({"step": 1, "pattern": 0, "mute": 0, "fill": False, "fx": 0})
    assert machine.current_slot == 3

    # Bar boundary (step 0) advances the arrangement.
    machine._handle_step({"step": 0, "pattern": 0, "mute": 0, "fill": False, "fx": 0})
    assert machine.current_slot == 5


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
