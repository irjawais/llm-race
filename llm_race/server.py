"""FastAPI WebSocket server for llm-race v0.3.

The web UI connects to ``/race`` and receives one JSON message per RaceEvent.
The same process serves the static frontend from ``llm_race/web``.

Wire format (one JSON object per WebSocket frame):

    {"kind": "start"|"token"|"think_open"|"think_close"|"finish"|"error",
     "runner_id": "qwen3-8b",
     "elapsed": 1.234,
     "text": "the next token",
     "token_count": 42,
     "error": null}

Plus a single bootstrap frame ``{"kind": "config", ...}`` sent right after the
connection opens, carrying the runner roster + colors + prompt.
"""
from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from llm_race.orchestrator import Orchestrator
from llm_race.runners.base import EventKind, RunnerSpec
from llm_race.runners.demo import DemoRunner
from llm_race.runners.openai_compat import OpenAICompatRunner

WEB_DIR = Path(__file__).parent / "web"

# SpaceX-yellow + 4 runner colors for the orbs.
RUNNER_COLORS = ["#22D3EE", "#A78BFA", "#F472B6", "#34D399", "#F5C518", "#60A5FA"]


def _spec_from_yaml(entry: dict[str, Any]) -> RunnerSpec:
    return RunnerSpec(
        id=entry["id"],
        base_url=entry["base_url"],
        model=entry["model"],
        api_key=entry.get("api_key", "sk-no-key"),
        sprite=entry.get("sprite", "orb"),
        label=entry.get("label"),
        extra_headers=entry.get("extra_headers") or {},
        timeout=entry.get("timeout", 600.0),
    )


def make_app(config: dict[str, Any], target_tokens: int, max_tokens: int) -> FastAPI:
    app = FastAPI(title="llm-race")

    runner_meta = []
    for i, entry in enumerate(config["runners"]):
        runner_meta.append({
            "id": entry["id"],
            "label": entry.get("label") or entry["id"],
            "model": entry["model"],
            "color": RUNNER_COLORS[i % len(RUNNER_COLORS)],
        })

    bootstrap = {
        "kind": "config",
        "title": config.get("title", "llm-race"),
        "prompt": config.get("prompt", "say hi"),
        "target_tokens": target_tokens,
        "max_tokens": max_tokens,
        "runners": runner_meta,
    }

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.websocket("/race")
    async def race_ws(ws: WebSocket) -> None:
        await ws.accept()
        await ws.send_text(json.dumps(bootstrap))

        runners = []
        for entry in config["runners"]:
            spec = _spec_from_yaml(entry)
            kind = (entry.get("kind") or "openai").lower()
            if kind == "demo":
                # carry rate hints through extra_headers (avoids new schema fields)
                hdrs = dict(spec.extra_headers)
                if "rate_tps" in entry:
                    hdrs["rate_tps"] = str(entry["rate_tps"])
                if "jitter" in entry:
                    hdrs["jitter"] = str(entry["jitter"])
                if "think_after" in entry:
                    hdrs["think_after"] = str(entry["think_after"])
                if "think_for" in entry:
                    hdrs["think_for"] = str(entry["think_for"])
                spec.extra_headers = hdrs
                runners.append(DemoRunner(spec))
            else:
                runners.append(OpenAICompatRunner(spec))
        orch = Orchestrator(runners, prompt=bootstrap["prompt"], max_tokens=max_tokens)
        orch.start()

        loop = asyncio.get_running_loop()
        try:
            while True:
                event = await loop.run_in_executor(None, _drain_one, orch)
                if event is None:
                    if orch.is_done():
                        break
                    continue
                payload = asdict(event)
                payload["kind"] = event.kind.value
                await ws.send_text(json.dumps(payload))
        except WebSocketDisconnect:
            return
        finally:
            try:
                await ws.close()
            except Exception:
                pass

    return app


def _drain_one(orch: Orchestrator):
    """Block briefly on the orchestrator queue; return None on timeout."""
    try:
        return orch.queue.get(timeout=0.1)
    except Exception:
        return None


def serve(config_path: Path, host: str, port: int,
          target_tokens: int, max_tokens: int, open_browser: bool) -> None:
    import yaml
    import uvicorn

    cfg = yaml.safe_load(config_path.read_text())
    app = make_app(cfg, target_tokens=target_tokens, max_tokens=max_tokens)

    if open_browser:
        url = f"http://{host}:{port}/"
        threading.Timer(0.8, lambda: _open_browser(url)).start()

    uvicorn.run(app, host=host, port=port, log_level="info")


def _open_browser(url: str) -> None:
    import webbrowser
    try:
        webbrowser.open(url)
    except Exception:
        pass
