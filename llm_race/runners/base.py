"""Runner abstract base class + event types.

A Runner connects to one LLM endpoint and yields RaceEvents as the model
streams. The game loop consumes these events to advance the runner's sprite.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncIterator


class EventKind(str, Enum):
    START = "start"
    TOKEN = "token"
    THINK_OPEN = "think_open"
    THINK_CLOSE = "think_close"
    FINISH = "finish"
    ERROR = "error"


@dataclass
class RaceEvent:
    kind: EventKind
    runner_id: str
    elapsed: float
    text: str = ""
    token_count: int = 0
    error: str | None = None


@dataclass
class RunnerSpec:
    """One LLM entry from the YAML config."""

    id: str
    base_url: str
    model: str
    api_key: str = "sk-no-key"
    sprite: str = "runner_blue"
    label: str | None = None
    extra_headers: dict[str, str] = field(default_factory=dict)
    timeout: float = 600.0


class Runner(ABC):
    """A runner connects to one LLM endpoint and yields RaceEvents."""

    spec: RunnerSpec

    def __init__(self, spec: RunnerSpec) -> None:
        self.spec = spec

    @abstractmethod
    async def stream(self, prompt: str, max_tokens: int) -> AsyncIterator[RaceEvent]:
        """Yield RaceEvents until the model finishes (or errors)."""
        if False:
            yield  # type: ignore[unreachable]
