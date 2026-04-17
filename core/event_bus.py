from __future__ import annotations

import queue
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(slots=True)
class Event:
    name: str
    payload: Any
    created_at: float = field(default_factory=time.time)


class EventBus:
    def __init__(self) -> None:
        self._queue: queue.Queue[Event] = queue.Queue()
        self._subscribers: dict[str, list[Callable[[Any], None]]] = defaultdict(list)
        self._lock = threading.RLock()

    def subscribe(self, event_name: str, callback: Callable[[Any], None]) -> None:
        with self._lock:
            self._subscribers[event_name].append(callback)

    def publish(self, event_name: str, payload: Any) -> None:
        self._queue.put(Event(name=event_name, payload=payload))

    def dispatch_pending(self, limit: int = 128) -> int:
        processed = 0
        while processed < limit:
            try:
                event = self._queue.get_nowait()
            except queue.Empty:
                break

            with self._lock:
                callbacks = list(self._subscribers.get(event.name, []))
                callbacks.extend(self._subscribers.get("*", []))

            for callback in callbacks:
                callback(event.payload)
            processed += 1

        return processed
