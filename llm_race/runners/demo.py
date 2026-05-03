"""Synthetic runner — emits fake tokens at a configurable rate.

Used for offline tweet-thumbnail recordings and for verifying the renderer
without a live vLLM/Ollama endpoint. Reads ``rate_tps`` and ``jitter`` from
the runner's ``extra_headers`` map (we reuse that field to avoid touching
the spec schema).
"""
from __future__ import annotations

import asyncio
import random
import time
from typing import AsyncIterator

from llm_race.runners.base import EventKind, RaceEvent, Runner


class DemoRunner(Runner):
    """Synthetic token stream — used for demos, tests, screenshots."""

    async def stream(self, prompt: str, max_tokens: int) -> AsyncIterator[RaceEvent]:
        rate = float(self.spec.extra_headers.get("rate_tps", "40"))
        jitter = float(self.spec.extra_headers.get("jitter", "0.35"))
        think_after = int(self.spec.extra_headers.get("think_after", "0"))
        think_for = int(self.spec.extra_headers.get("think_for", "0"))

        t0 = time.time()
        token_count = 0
        yield RaceEvent(EventKind.START, self.spec.id, 0.0)

        in_think = False
        opened_think = False
        while token_count < max_tokens:
            instant_rate = max(1.0, rate * (1.0 + (random.random() - 0.5) * jitter))
            await asyncio.sleep(1.0 / instant_rate)
            token_count += 1

            # Optional <think> block simulation.
            if (think_after and not opened_think
                    and token_count >= think_after):
                opened_think = True
                in_think = True
                yield RaceEvent(EventKind.THINK_OPEN, self.spec.id, time.time() - t0)
            if (in_think and think_for
                    and token_count >= think_after + think_for):
                in_think = False
                yield RaceEvent(EventKind.THINK_CLOSE, self.spec.id, time.time() - t0)

            yield RaceEvent(
                EventKind.TOKEN, self.spec.id,
                time.time() - t0,
                "" if in_think else "x ",
                token_count,
            )

        yield RaceEvent(EventKind.FINISH, self.spec.id,
                        time.time() - t0, token_count=token_count)
