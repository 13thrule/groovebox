"""The step-grid GUI. Owns the on-screen pattern editing and playhead
display; delegates actual sound to midi_output, actual board
communication to serial_link, and actual pattern data to patterns.
"""

import copy
import queue
import random
import time
import tkinter as tk

import midi_output
import effects
from history import History
from mixer_window import MixerWindow
from song_mode import SongMode
from patterns import (
    TRACKS, NUM_SLOTS, NUM_STEPS, SCALE, NORMAL_VELOCITY, ACCENT_VELOCITY,
    load_patterns, save_patterns, load_settings, save_settings, current_program_name,
    get_probability, cycle_probability,
)

FILL_GROUPS = {"clhat", "kick"}  # which tracks the Fill button layers extra hits into
FILTER_CHANNELS = [t["channel"] for t in TRACKS if t["type"] == "note"]  # filter cutoff skips drums
ALL_GROUPS_MASK = (1 << 5) - 1

# "on" cell colors -- 6-digit hex so _shade() can blend them toward grey
# for per-step probability < 100%.
COLOR_ACCENT = "#55ee22"
COLOR_DRUM_ON = "#33aa66"
COLOR_NOTE_ON = "#3366aa"
COLOR_OFF = "#222222"
TAP_TIMEOUT_SEC = 2.0  # gap after which a new tap-tempo run starts fresh


class DrumMachine:
    def __init__(self, root, link):
        self.root = root
        self.link = link
        self.slots = load_patterns()
        self.settings = load_settings()  # restores saved instrument choices before we open MIDI
        self.current_slot = 0
        self.current_mute = 0
        self.current_step = -1
        self.last_fx = None

        self.solo_mask = 0  # groups soloed from the GUI (separate from the board's hardware mute)
        self.history = History()
        self.song_mode = SongMode()
        self.clipboard_pattern = None
        self.tap_times = []

        self.midi_out = midi_output.open_output()

        self._build_gui()
        self.root.after(10, self._poll_queue)

    # ---------------------------------------------------------- GUI

    def _build_gui(self):
        self.root.title("Groovebox Drum Machine")
        self.root.configure(bg="#111")
        self.root.bind("<Control-z>", lambda e: self.undo())

        top = tk.Frame(self.root, bg="#111")
        top.pack(fill="x", padx=8, pady=6)

        self.status_label = tk.Label(top, text="connecting...", fg="#8f8", bg="#111", font=("Consolas", 10))
        self.status_label.pack(side="left")

        fx = tk.Frame(top, bg="#111")
        fx.pack(side="left", padx=20)
        tk.Label(fx, text="Reverb", fg="#8cf", bg="#111", font=("Consolas", 9)).pack(side="left")
        self.reverb_slider = tk.Scale(fx, from_=0, to=127, orient="horizontal", length=100,
                                       bg="#111", fg="#8cf", troughcolor="#333", highlightthickness=0,
                                       command=self._on_reverb)
        self.reverb_slider.set(40)
        self.reverb_slider.pack(side="left", padx=(2, 14))
        tk.Label(fx, text="Chorus", fg="#8cf", bg="#111", font=("Consolas", 9)).pack(side="left")
        self.chorus_slider = tk.Scale(fx, from_=0, to=127, orient="horizontal", length=100,
                                       bg="#111", fg="#8cf", troughcolor="#333", highlightthickness=0,
                                       command=self._on_chorus)
        self.chorus_slider.set(0)
        self.chorus_slider.pack(side="left", padx=2)
        tk.Label(fx, text="Swing", fg="#8cf", bg="#111", font=("Consolas", 9)).pack(side="left")
        self.swing_slider = tk.Scale(fx, from_=0, to=75, orient="horizontal", length=100,
                                      bg="#111", fg="#8cf", troughcolor="#333", highlightthickness=0,
                                      command=self._on_swing)
        self.swing_slider.set(self.settings.get("swing", 12))
        self.swing_slider.pack(side="left", padx=(2, 14))
        tk.Label(fx, text="Filter (A2 pot):", fg="#666", bg="#111", font=("Consolas", 9)).pack(side="left", padx=(0, 2))
        self.filter_label = tk.Label(fx, text="--", fg="#666", bg="#111", font=("Consolas", 9), width=4)
        self.filter_label.pack(side="left")

        tabs = tk.Frame(top, bg="#111")
        tabs.pack(side="right")
        self.tab_buttons = []
        for i in range(NUM_SLOTS):
            b = tk.Button(tabs, text=f"Slot {i+1}", width=8,
                           command=lambda i=i: self.select_slot(i))
            b.pack(side="left", padx=2)
            self.tab_buttons.append(b)
        tk.Button(tabs, text="Copy", width=6, command=self.copy_pattern).pack(side="left", padx=(14, 2))
        tk.Button(tabs, text="Paste", width=6, command=self.paste_pattern).pack(side="left", padx=2)

        # Second row: master mix, delay, song mode, tap tempo, mixer window
        top2 = tk.Frame(self.root, bg="#111")
        top2.pack(fill="x", padx=8, pady=(0, 6))

        tk.Label(top2, text="Master Vol", fg="#8cf", bg="#111", font=("Consolas", 9)).pack(side="left")
        self.master_slider = tk.Scale(top2, from_=0, to=127, orient="horizontal", length=100,
                                       bg="#111", fg="#8cf", troughcolor="#333", highlightthickness=0,
                                       command=self._on_master_volume)
        self.master_slider.set(self.settings.get("master_volume", 100))
        self.master_slider.pack(side="left", padx=(2, 14))

        tk.Label(top2, text="Delay", fg="#8cf", bg="#111", font=("Consolas", 9)).pack(side="left")
        self.delay_slider = tk.Scale(top2, from_=0, to=100, orient="horizontal", length=100,
                                      bg="#111", fg="#8cf", troughcolor="#333", highlightthickness=0,
                                      command=self._on_delay)
        self.delay_slider.set(self.settings.get("delay_amount", 0))
        self.delay_slider.pack(side="left", padx=(2, 14))

        tk.Button(top2, text="Tap Tempo", width=10, command=self._tap_tempo).pack(side="left", padx=(0, 4))
        self.tap_label = tk.Label(top2, text="-- BPM", fg="#666", bg="#111", font=("Consolas", 9), width=8)
        self.tap_label.pack(side="left", padx=(0, 14))

        self.song_btn = tk.Button(top2, text="Song: OFF", width=10, command=self._toggle_song_mode)
        self.song_btn.pack(side="left", padx=(0, 14))

        tk.Button(top2, text="Mixer...", width=10, command=self._open_mixer).pack(side="left")

        grid = tk.Frame(self.root, bg="#111")
        grid.pack(padx=8, pady=8)

        tk.Label(grid, text="", width=17, bg="#111").grid(row=0, column=0)
        for s in range(NUM_STEPS):
            tk.Label(grid, text=str(s + 1), fg="#666", bg="#111", width=3,
                     font=("Consolas", 8)).grid(row=0, column=s + 1)

        self.row_labels = {}
        self.cells = {}
        for r, t in enumerate(TRACKS):
            is_note = t["type"] == "note"
            lbl = tk.Label(grid, text=self._row_label_text(t), fg="#8cf" if is_note else "#ddd",
                            bg="#111", width=17, anchor="w", font=("Consolas", 10), cursor="hand2")
            lbl.grid(row=r + 1, column=0, sticky="w")
            if is_note:
                lbl.bind("<Button-1>", lambda e, t=t: self.change_instrument(t))
                lbl.bind("<Button-3>", lambda e, t=t: self.toggle_solo(t))
            else:
                lbl.bind("<Button-1>", lambda e, t=t: self.toggle_solo(t))
            self.row_labels[t["key"]] = lbl

            for s in range(NUM_STEPS):
                cell = tk.Button(grid, width=3, height=1, bg="#222", relief="flat",
                                  font=("Consolas", 8))
                cell.grid(row=r + 1, column=s + 1, padx=1, pady=1)
                cell.bind("<Button-1>", lambda e, t=t, s=s: self.toggle_cell(t, s))
                cell.bind("<Button-3>", lambda e, t=t, s=s: self.cycle_note(t, s))
                cell.bind("<Button-2>", lambda e, t=t, s=s: self.cycle_prob(t, s))
                self.cells[(t["key"], s)] = cell

        hint2 = tk.Label(self.root,
                          text="Left-click a Bass/Lead label to cycle its instrument   |   "
                               "Right-click a Bass/Lead label, or left-click a drum label: solo",
                          fg="#8cf", bg="#111", font=("Consolas", 9))
        hint2.pack()

        hint = tk.Label(self.root,
                         text="Left-click a drum cell: off -> normal -> accent (!)   |   "
                              "Left-click a Bass/Lead cell: toggle   |   Right-click: cycle its note   |   "
                              "Middle-click: cycle step probability   |   Ctrl+Z: undo",
                         fg="#666", bg="#111", font=("Consolas", 9))
        hint.pack(pady=(0, 8))

        self.redraw_grid()
        effects.set_reverb(self.midi_out, self.reverb_slider.get())
        effects.set_chorus(self.midi_out, self.chorus_slider.get())
        self.link.send_swing(self.swing_slider.get())

    def _on_reverb(self, value):
        effects.set_reverb(self.midi_out, int(value))

    def _on_chorus(self, value):
        effects.set_chorus(self.midi_out, int(value))

    def _on_swing(self, value):
        self.link.send_swing(int(value))
        self.settings["swing"] = int(value)
        save_settings(self.settings)

    def _on_master_volume(self, value):
        self.settings["master_volume"] = int(value)
        save_settings(self.settings)

    def _on_delay(self, value):
        self.settings["delay_amount"] = int(value)
        save_settings(self.settings)

    def _open_mixer(self):
        MixerWindow(self.root, self.midi_out, self.settings, on_change=self.redraw_grid)

    def _tap_tempo(self):
        now = time.time()
        if self.tap_times and now - self.tap_times[-1] > TAP_TIMEOUT_SEC:
            self.tap_times = []
        self.tap_times.append(now)
        self.tap_times = self.tap_times[-8:]
        if len(self.tap_times) < 2:
            return
        intervals = [b - a for a, b in zip(self.tap_times, self.tap_times[1:])]
        bpm = 60.0 / (sum(intervals) / len(intervals))
        bpm = max(40, min(240, bpm))
        self.link.send_bpm(int(round(bpm)))
        self.tap_label.configure(text=f"{int(round(bpm))} BPM")

    def _toggle_song_mode(self):
        enabled = self.song_mode.toggle()
        self.song_btn.configure(text=f"Song: {'ON' if enabled else 'OFF'}",
                                 relief="sunken" if enabled else "raised")
        if enabled:
            self.current_slot = self.song_mode.current_slot()
            self.redraw_grid()

    def _row_label_text(self, track):
        if track["type"] == "note":
            return f"{track['label']}: {current_program_name(track)}"
        return track["label"]

    def change_instrument(self, track):
        midi_output.next_instrument(self.midi_out, track)
        save_settings(self.settings)
        self.redraw_grid()

    def toggle_solo(self, track):
        self.solo_mask ^= (1 << track["group"])
        self.redraw_grid()

    def _effective_mute(self):
        """Hardware mute (from the board's physical buttons) OR'd with
        whatever the GUI's solo selection excludes -- soloing a group
        mutes every other group on top of any hardware mute already in
        effect."""
        mute = self.current_mute
        if self.solo_mask:
            mute |= (~self.solo_mask) & ALL_GROUPS_MASK
        return mute

    @staticmethod
    def _shade(hex_color, prob):
        """Blends an "on" color toward grey as step probability drops
        below 100 -- a quick visual read of which hits are a sure thing
        vs. which ones only sometimes fire."""
        if prob >= 100:
            return hex_color
        r = int(hex_color[1:3], 16)
        g = int(hex_color[3:5], 16)
        b = int(hex_color[5:7], 16)
        frac = prob / 100.0
        grey = 0x33
        r = int(r * frac + grey * (1 - frac))
        g = int(g * frac + grey * (1 - frac))
        b = int(b * frac + grey * (1 - frac))
        return f"#{r:02x}{g:02x}{b:02x}"

    def redraw_grid(self):
        pattern = self.slots[self.current_slot]
        effective_mute = self._effective_mute()
        for i, b in enumerate(self.tab_buttons):
            b.configure(relief="sunken" if i == self.current_slot else "raised")
        for t in TRACKS:
            muted = bool(effective_mute & (1 << t["group"]))
            soloed = bool(self.solo_mask & (1 << t["group"]))
            is_note = t["type"] == "note"
            active_color = "#8cf" if is_note else "#ddd"
            label_color = "#fa4" if soloed else ("#555" if muted else active_color)
            self.row_labels[t["key"]].configure(text=self._row_label_text(t), fg=label_color)
            for s in range(NUM_STEPS):
                val = pattern[t["key"]][s]
                prob = get_probability(pattern, t["key"], s)
                cell = self.cells[(t["key"], s)]
                on = val is not None
                accented = on and t["type"] == "drum" and val >= ACCENT_VELOCITY
                text = ""
                if on and t["type"] == "note":
                    text = f"+{val}" if val else "0"
                elif accented:
                    text = "!"
                if on:
                    base = COLOR_ACCENT if accented else (COLOR_DRUM_ON if t["type"] == "drum" else COLOR_NOTE_ON)
                    color = self._shade(base, prob)
                else:
                    color = COLOR_OFF
                if s == self.current_step:
                    color = "#ee4" if not on else "#ff8"
                cell.configure(bg=color, text=text, fg="#000" if s == self.current_step else "#eee")

    def _push_undo(self):
        self.history.push(self.current_slot, self.slots[self.current_slot])

    def undo(self):
        entry = self.history.undo()
        if entry is None:
            return
        slot_index, pattern = entry
        self.slots[slot_index] = pattern
        self.current_slot = slot_index
        save_patterns(self.slots)
        self.redraw_grid()

    def copy_pattern(self):
        self.clipboard_pattern = copy.deepcopy(self.slots[self.current_slot])

    def paste_pattern(self):
        if self.clipboard_pattern is None:
            return
        self._push_undo()
        self.slots[self.current_slot] = copy.deepcopy(self.clipboard_pattern)
        save_patterns(self.slots)
        self.redraw_grid()

    def toggle_cell(self, track, step):
        """Note tracks: simple on/off (the note itself is set via
        right-click/cycle_note). Drum tracks: a 3-state cycle,
        off -> normal -> accent -> off, same idea as the 808/909's
        accent -- it's what makes a step read as *played* rather than
        just quantized on/off."""
        self._push_undo()
        pattern = self.slots[self.current_slot]
        cur = pattern[track["key"]][step]
        if track["type"] == "note":
            pattern[track["key"]][step] = None if cur is not None else 0
        elif cur is None:
            pattern[track["key"]][step] = NORMAL_VELOCITY
        elif cur < ACCENT_VELOCITY:
            pattern[track["key"]][step] = ACCENT_VELOCITY
        else:
            pattern[track["key"]][step] = None
        save_patterns(self.slots)
        self.redraw_grid()

    def cycle_note(self, track, step):
        if track["type"] != "note":
            return
        self._push_undo()
        pattern = self.slots[self.current_slot]
        cur = pattern[track["key"]][step]
        if cur is None:
            pattern[track["key"]][step] = SCALE[0]
        else:
            idx = SCALE.index(cur) if cur in SCALE else -1
            pattern[track["key"]][step] = SCALE[(idx + 1) % len(SCALE)]
        save_patterns(self.slots)
        self.redraw_grid()

    def cycle_prob(self, track, step):
        self._push_undo()
        pattern = self.slots[self.current_slot]
        cycle_probability(pattern, track["key"], step)
        save_patterns(self.slots)
        self.redraw_grid()

    def select_slot(self, idx):
        if self.song_mode.enabled:
            self.song_mode.enabled = False
            self.song_btn.configure(text="Song: OFF", relief="raised")
        self.current_slot = idx
        self.redraw_grid()

    # --------------------------------------------------- Main-thread

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.link.events.get_nowait()
                if kind == "status":
                    self.status_label.configure(text=payload)
                elif kind == "log":
                    print(payload)
                elif kind == "step":
                    self._handle_step(payload)
        except queue.Empty:
            pass
        self.root.after(5, self._poll_queue)

    def _handle_step(self, info):
        # While song mode drives the arrangement, it owns current_slot --
        # otherwise trust the board's own PAT field (physical button or
        # GUI slot click, whichever last changed it there).
        if not self.song_mode.enabled and info["pattern"] != self.current_slot:
            self.current_slot = info["pattern"]
        self.current_mute = info["mute"]
        self.current_step = info["step"]

        if self.song_mode.enabled and info["step"] == 0:
            new_slot = self.song_mode.advance_bar()
            if new_slot is not None:
                self.current_slot = new_slot

        fx = info.get("fx", 0)
        if fx != self.last_fx:
            self.last_fx = fx
            effects.set_filter_cutoff(self.midi_out, fx, channels=FILTER_CHANNELS)
            self.filter_label.configure(text=str(fx))

        pattern = self.slots[self.current_slot]
        effective_mute = self._effective_mute()
        hit_mask = 0
        for t in TRACKS:
            if effective_mute & (1 << t["group"]):
                continue
            val = pattern[t["key"]][info["step"]]

            if info["fill"] and t["key"] in FILL_GROUPS:
                if t["key"] == "clhat":
                    val = val if val is not None else 100
                if t["key"] == "kick" and info["step"] >= 12:
                    val = val if val is not None else 100

            if val is None:
                continue

            prob = get_probability(pattern, t["key"], info["step"])
            if prob < 100 and random.randint(1, 100) > prob:
                continue

            midi_output.play(self.midi_out, t, val,
                              master_volume=self.settings.get("master_volume", 100),
                              delay_amount=self.settings.get("delay_amount", 0))
            hit_mask |= 1 << t["group"]

        self.link.send_hit(hit_mask)
        self.redraw_grid()
