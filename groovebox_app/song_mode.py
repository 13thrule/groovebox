"""Song mode -- chains multiple pattern slots into a longer automatic
arrangement (play slot 0 for N bars, then slot 1, etc.), the way a
real drum machine's song mode works. This lives entirely PC-side and
overrides the board's own pattern-slot selection while active; a
manual pattern-button press or GUI slot click turns it back off (same
"any manual control takes over" convention used elsewhere in the app).

To change the arrangement: edit DEFAULT_ARRANGEMENT below, or call
SongMode.set_arrangement() with your own list of (slot_index, bars)
tuples.
"""

# One full pass through all 8 starter slots -- adjust bar counts or
# reorder to build an actual "song" out of your own patterns.
DEFAULT_ARRANGEMENT = [
    (0, 4), (1, 4), (2, 8), (3, 8), (4, 4), (5, 4), (6, 8), (7, 8),
]


class SongMode:
    def __init__(self, arrangement=None):
        self.arrangement = list(arrangement or DEFAULT_ARRANGEMENT)
        self.enabled = False
        self.step_index = 0
        self.bars_elapsed = 0

    def set_arrangement(self, arrangement):
        self.arrangement = list(arrangement)
        self.reset()

    def reset(self):
        self.step_index = 0
        self.bars_elapsed = 0

    def toggle(self):
        self.enabled = not self.enabled
        if self.enabled:
            self.reset()
        return self.enabled

    def current_slot(self):
        if not self.arrangement:
            return None
        return self.arrangement[self.step_index][0]

    def advance_bar(self):
        """Call once per bar (i.e. when the board's step counter wraps
        to 0). Returns the pattern slot index to switch to, or None if
        no change is needed this bar."""
        if not self.enabled or not self.arrangement:
            return None

        self.bars_elapsed += 1
        slot_idx, bars = self.arrangement[self.step_index]
        if self.bars_elapsed >= bars:
            self.bars_elapsed = 0
            self.step_index = (self.step_index + 1) % len(self.arrangement)
            return self.arrangement[self.step_index][0]
        return None
