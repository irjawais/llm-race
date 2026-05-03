"""OpenAI-compatible chat-completions streaming runner.

Works with vLLM, llama.cpp server, Ollama, LM Studio, SGLang, MLX-server,
and any other endpoint that exposes /v1/chat/completions with stream=true.

We count tokens locally from delta.content rather than relying on server
`usage` (which is inconsistent across implementations).
"""
from __future__ import annotations

import re
import time
from typing import AsyncIterator

from openai import AsyncOpenAI

from llm_race.runners.base import EventKind, RaceEvent, Runner

# Cheap word-piece-ish split. Real tokenizer-aware counting is in v0.2.
_TOKEN_RE = re.compile(r"\S+|\s+")


def _approx_tokens(s: str) -> int:
    return max(1, len(_TOKEN_RE.findall(s)))


class OpenAICompatRunner(Runner):
    """Streams a single chat completion and emits RaceEvents."""

    async def stream(self, prompt: str, max_tokens: int) -> AsyncIterator[RaceEvent]:
        client = AsyncOpenAI(
            base_url=self.spec.base_url,
            api_key=self.spec.api_key,
            timeout=self.spec.timeout,
            default_headers=self.spec.extra_headers or None,
        )

        t0 = time.time()
        token_count = 0
        in_think = False
        buf = ""
        stream = None

        try:
            yield RaceEvent(EventKind.START, self.spec.id, 0.0)
            # Use async-context-managed stream so aclose() runs cleanly even
            # when the surrounding loop is torn down.
            stream = await client.chat.completions.create(
                model=self.spec.model,
                messages=[{"role": "user", "content": prompt}],
                stream=True,
                max_tokens=max_tokens,
                temperature=0.6,
                top_p=0.95,
            )

            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                piece = (delta.content or "") if delta else ""
                if not piece:
                    continue
                buf += piece
                # Watch for <think> blocks (Qwen3, DeepSeek-R1-Distill, QwQ).
                while True:
                    if not in_think and "<think>" in buf:
                        head, _, buf = buf.partition("<think>")
                        if head:
                            t = _approx_tokens(head)
                            token_count += t
                            yield RaceEvent(
                                EventKind.TOKEN, self.spec.id,
                                time.time() - t0, head, token_count,
                            )
                        in_think = True
                        yield RaceEvent(EventKind.THINK_OPEN, self.spec.id, time.time() - t0)
                    elif in_think and "</think>" in buf:
                        head, _, buf = buf.partition("</think>")
                        # think tokens count towards work but render as "thinking"
                        if head:
                            t = _approx_tokens(head)
                            token_count += t
                            # Send a TOKEN event so the lane updates progress
                            # even while thinking — the UI shows the bubble
                            # but the runner still advances.
                            yield RaceEvent(
                                EventKind.TOKEN, self.spec.id,
                                time.time() - t0, "", token_count,
                            )
                        in_think = False
                        yield RaceEvent(EventKind.THINK_CLOSE, self.spec.id, time.time() - t0)
                    else:
                        break

                # Flush buf only when we hit a token boundary (whitespace) so
                # the game loop receives clean chunks.
                if buf and (buf[-1].isspace() or len(buf) > 64):
                    if in_think:
                        # While thinking, advance the counter — UI shows
                        # "thinking" badge but progress still moves slowly.
                        n = _approx_tokens(buf)
                        token_count += n
                        yield RaceEvent(
                            EventKind.TOKEN, self.spec.id,
                            time.time() - t0, "", token_count,
                        )
                    else:
                        n = _approx_tokens(buf)
                        token_count += n
                        yield RaceEvent(
                            EventKind.TOKEN, self.spec.id,
                            time.time() - t0, buf, token_count,
                        )
                    buf = ""

            # Flush trailing buffer
            if buf and not in_think:
                n = _approx_tokens(buf)
                token_count += n
                yield RaceEvent(
                    EventKind.TOKEN, self.spec.id,
                    time.time() - t0, buf, token_count,
                )

            yield RaceEvent(
                EventKind.FINISH, self.spec.id,
                time.time() - t0, token_count=token_count,
            )

        except Exception as e:  # noqa: BLE001  — surface any client error to UI
            yield RaceEvent(
                EventKind.ERROR, self.spec.id,
                time.time() - t0, error=f"{type(e).__name__}: {e}",
            )
        finally:
            # Explicitly close the stream's underlying SSE connection before
            # the event loop tears the client down.
            if stream is not None:
                try:
                    await stream.close()
                except Exception:  # noqa: BLE001
                    pass
            await client.close()
