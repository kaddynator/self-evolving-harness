from __future__ import annotations

import asyncio
import threading
from typing import Callable, List, Optional

from src.observability.events import PipelineEvent


class EventBus:
    """Thread-safe event bus.

    Sync subscribers (terminal, logging) are called directly in the
    publishing thread.  Async SSE clients are served via asyncio.Queue
    instances bridged with loop.call_soon_threadsafe().
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: List[Callable[[PipelineEvent], None]] = []
        self._sse_queues: List[asyncio.Queue] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._history: List[PipelineEvent] = []  # replayed to late SSE subscribers

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def subscribe(self, callback: Callable[[PipelineEvent], None]) -> None:
        with self._lock:
            self._subscribers.append(callback)

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def add_sse_queue(self, q: asyncio.Queue) -> None:
        """Register a queue for a new SSE client. Replays history first."""
        with self._lock:
            self._sse_queues.append(q)
            history_snapshot = list(self._history)

        # Replay past events so a late-joining browser sees full context
        if self._loop:
            for event in history_snapshot:
                self._loop.call_soon_threadsafe(q.put_nowait, event)

    def remove_sse_queue(self, q: asyncio.Queue) -> None:
        with self._lock:
            try:
                self._sse_queues.remove(q)
            except ValueError:
                pass

    def clear_history(self) -> None:
        """Discard accumulated event history. Call before each new run so
        late-joining SSE clients don't receive stale events from prior runs."""
        with self._lock:
            self._history.clear()

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    def publish(self, event: PipelineEvent) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
            queues = list(self._sse_queues)
            self._history.append(event)

        for sub in subscribers:
            try:
                sub(event)
            except Exception:
                pass  # never let an observer crash the pipeline

        if self._loop and queues:
            for q in queues:
                self._loop.call_soon_threadsafe(q.put_nowait, event)
