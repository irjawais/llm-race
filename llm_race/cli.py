"""llm-race CLI entrypoint."""
from __future__ import annotations

from pathlib import Path

import typer
import yaml

from llm_race.game.arena import Arena
from llm_race.orchestrator import Orchestrator
from llm_race.runners.base import RunnerSpec
from llm_race.runners.openai_compat import OpenAICompatRunner

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command()
def run(
    config: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True,
                                  help="YAML race config (see configs/example.yaml)"),
    prompt: str = typer.Option(None, "--prompt", "-p",
                               help="Override the prompt in the config"),
    target_tokens: int = typer.Option(1024, "--target-tokens", "-t",
                                      help="Track length, in tokens"),
    max_tokens: int = typer.Option(8192, "--max-tokens",
                                   help="Server-side completion cap"),
) -> None:
    """Start a race using the YAML config."""
    cfg = yaml.safe_load(config.read_text())
    used_prompt: str = prompt or cfg.get("prompt") or "say hi"
    label = cfg.get("title", used_prompt)
    runners = []
    for entry in cfg["runners"]:
        spec = RunnerSpec(
            id=entry["id"],
            base_url=entry["base_url"],
            model=entry["model"],
            api_key=entry.get("api_key", "sk-no-key"),
            sprite=entry.get("sprite", "runner_blue"),
            label=entry.get("label"),
            extra_headers=entry.get("extra_headers") or {},
            timeout=entry.get("timeout", 600.0),
        )
        runners.append(OpenAICompatRunner(spec))

    orch = Orchestrator(runners, prompt=used_prompt, max_tokens=max_tokens)
    arena = Arena(orch, target_tokens=target_tokens, prompt_label=label)
    arena.run()


@app.command()
def version() -> None:
    """Print version."""
    from llm_race import __version__
    typer.echo(__version__)


if __name__ == "__main__":
    app()
