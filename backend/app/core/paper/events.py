"""Simple in-process event bus for paper trading events."""
from __future__ import annotations

from typing import Any, Callable


class _PaperEventBus:
    def __init__(self):
        self._listeners: list[Callable] = []

    def on(self, cb: Callable):
        self._listeners.append(cb)

    def emit(self, kind: str, payload: dict[str, Any]):
        for cb in self._listeners:
            try:
                cb(kind, payload)
            except Exception:
                pass

    def clear(self):
        self._listeners.clear()


paper_events = _PaperEventBus()
