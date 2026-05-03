"""Orchestrator — runs N runners concurrently and feeds events to a queue.

The game loop consumes events from `queue` at 60 fps; runners produce events
in their own asyncio tasks. The queue is the single integration point.
"""
from __future__ import annotations

import asyncio
import threading
from queue import Queue
from typing import Iterable

from llm_race.runners.base import Runner, RaceEvent


class Orchestrator:
    """Run N runners concurrently against the same prompt."""

    def __init__(self, runners: Iterable[Runner], prompt: str, max_tokens: int = 8192) -> None:
        self.runners = list(runners)
        self.prompt = prompt
        self.max_tokens = max_tokens
        self.queue: Queue[RaceEvent] = Queue()
        self._thread: threading.Thread | None = None
        self._done = threading.Event()

    def start(self) -> None:
        """Launch async tasks in a background thread; main thread runs the game."""
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def is_done(self) -> bool:
        return self._done.is_set()

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._gather())
        finally:
            self._done.set()
            loop.close()

    async def _gather(self) -> None:
        await asyncio.gather(*(self._drain(r) for r in self.runners))

    async def _drain(self, runner: Runner) -> None:
        async for event in runner.stream(self.prompt, self.max_tokens):
            self.queue.put(event)
