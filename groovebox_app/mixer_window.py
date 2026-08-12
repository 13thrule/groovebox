"""Per-track volume/pan mixer -- a separate window rather than
cramming 15 more sliders into the main grid. Volume works for every
track (applied as a velocity multiplier in midi_output.play(), since
GM percussion voices all share one MIDI channel and can't be leveled
via channel-volume CC individually). Pan only does anything audible
for Bass/Lead, which have their own channels -- drum pan sliders are
shown disabled so it's clear why.
"""

import tkinter as tk

from patterns import TRACKS, save_settings


class MixerWindow:
    def __init__(self, parent, midi_out, settings, on_change=None):
        self.midi_out = midi_out
        self.settings = settings
        self.on_change = on_change

        self.win = tk.Toplevel(parent)
        self.win.title("Mixer")
        self.win.configure(bg="#111")

        header = tk.Frame(self.win, bg="#111")
        header.pack(fill="x", padx=8, pady=(8, 0))
        tk.Label(header, text="Track", fg="#666", bg="#111", width=10, anchor="w",
                 font=("Consolas", 9)).pack(side="left")
        tk.Label(header, text="Volume", fg="#666", bg="#111", width=14,
                 font=("Consolas", 9)).pack(side="left")
        tk.Label(header, text="Pan", fg="#666", bg="#111", width=14,
                 font=("Consolas", 9)).pack(side="left")

        for t in TRACKS:
            row = tk.Frame(self.win, bg="#111")
            row.pack(fill="x", padx=8, pady=2)
            tk.Label(row, text=t["label"], fg="#ddd" if t["type"] == "note" else "#aaa",
                     bg="#111", width=10, anchor="w", font=("Consolas", 9)).pack(side="left")

            vol = tk.Scale(row, from_=0, to=127, orient="horizontal", length=140,
                            bg="#111", fg="#8cf", troughcolor="#333", highlightthickness=0,
                            command=lambda v, t=t: self._on_volume(t, v))
            vol.set(t["volume"])
            vol.pack(side="left", padx=4)

            pan = tk.Scale(row, from_=0, to=127, orient="horizontal", length=140,
                            bg="#111", fg="#8cf" if t["type"] == "note" else "#444",
                            troughcolor="#333", highlightthickness=0,
                            state="normal" if t["type"] == "note" else "disabled",
                            command=lambda v, t=t: self._on_pan(t, v))
            pan.set(t["pan"])
            pan.pack(side="left", padx=4)

    def _on_volume(self, track, value):
        track["volume"] = int(value)
        self._save()

    def _on_pan(self, track, value):
        if track["type"] != "note":
            return
        track["pan"] = int(value)
        import mido
        self.midi_out.send(mido.Message("control_change", channel=track["channel"],
                                         control=10, value=track["pan"]))
        self._save()

    def _save(self):
        save_settings(self.settings)
        if self.on_change:
            self.on_change()
