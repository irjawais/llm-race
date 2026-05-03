"""Smoke tests for the runner abstraction."""
import asyncio

import pytest

from llm_race.runners.base import EventKind, RunnerSpec
from llm_race.runners.openai_compat import OpenAICompatRunner, _approx_tokens


def test_approx_tokens_basic():
    assert _approx_tokens("hello world") >= 3
    assert _approx_tokens("") == 1


def test_runner_spec_defaults():
    s = RunnerSpec(id="x", base_url="http://localhost:1234/v1", model="m")
    assert s.api_key == "sk-no-key"
    assert s.timeout == 600.0
    assert s.extra_headers == {}


def test_event_kind_enum():
    assert EventKind.START.value == "start"
    assert EventKind.TOKEN.value == "token"
    assert EventKind.THINK_OPEN.value == "think_open"


def test_runner_constructible():
    spec = RunnerSpec(id="x", base_url="http://localhost:1234/v1", model="m")
    runner = OpenAICompatRunner(spec)
    assert runner.spec.id == "x"
