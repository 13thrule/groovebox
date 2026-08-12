"""Undo support -- a bounded stack of (slot_index, pattern_snapshot)
pairs. Storing the slot index alongside each snapshot means undo
still restores correctly even if you've switched slots since the
edit you're undoing.
"""

import copy

MAX_UNDO = 50


class History:
    def __init__(self, maxlen=MAX_UNDO):
        self.maxlen = maxlen
        self._stack = []

    def push(self, slot_index, pattern):
        """Call *before* mutating a pattern, with its state as it was
        just before the edit."""
        self._stack.append((slot_index, copy.deepcopy(pattern)))
        if len(self._stack) > self.maxlen:
            self._stack.pop(0)

    def undo(self):
        """Returns (slot_index, pattern) to restore, or None if
        there's nothing left to undo."""
        if not self._stack:
            return None
        return self._stack.pop()

    def can_undo(self):
        return bool(self._stack)
