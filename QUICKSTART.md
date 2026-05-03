# llm-race · quickstart

> Three.js + FastAPI WebSocket UI · v0.3

![hero](recordings/v3-hero.png)

---

## Install

```bash
git clone https://github.com/irjawais/llm-race
cd llm-race
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

---

## Option A — see the UI in 10 seconds (synthetic demo, no LLM needed)

```bash
llm-race serve configs/demo-synthetic.yaml --target-tokens 1500 --max-tokens 2500
```

Opens `http://127.0.0.1:8000/` in your browser. Four fake runners stream tokens
at different rates so you can verify the scene + telemetry HUD without firing
up any real LLM endpoint.

---

## Option B — race real models on a remote GPU box (SSH tunnel)

### Step 1 — start two vLLM servers on the remote box

```bash
ssh <remote>
# tmux pane 1
vllm serve <org>/Qwen3-8B-AWQ-INT4 --port 8001 --max-model-len 8192 \
  --enable-auto-tool-choice --tool-call-parser hermes

# tmux pane 2
vllm serve <org>/Qwen3-4B-AWQ-INT4 --port 8002 --max-model-len 8192 \
  --enable-auto-tool-choice --tool-call-parser hermes
```

### Step 2 — tunnel both ports back to your laptop

```bash
ssh -fN -L 8001:localhost:8001 -L 8002:localhost:8002 <remote>
```

### Step 3 — run the race

```bash
llm-race serve configs/demo-tunnel.yaml --target-tokens 800 --max-tokens 1024
```

---

## Option C — race local Ollama / LM Studio / llama.cpp servers

Anything OpenAI-compatible works. Edit a YAML — point `base_url` at the
local server, set `model` to whatever the server names it.

```yaml
title: "build me Snake in Python"
prompt: |
  Implement a complete, single-file Snake game in pure Python with pygame.
  Output ONLY the full code, no commentary.

runners:
  - id: a
    label: "Llama-3.1-8B (Ollama)"
    base_url: http://localhost:11434/v1
    model: llama3.1:8b

  - id: b
    label: "Mistral-7B (LM Studio)"
    base_url: http://localhost:1234/v1
    model: mistral-7b-instruct
```

```bash
llm-race serve my-config.yaml
```

---

## Flags

| Flag | What it does |
|---|---|
| `--port 9000` | Change web port (default 8000) |
| `--host 0.0.0.0` | Let the LAN watch — useful for second-monitor recording |
| `--no-browser` | Don't auto-open the browser (for OBS / screen-recording flows) |
| `--target-tokens N` | Track length in tokens — orb crosses the finish line at this count |
| `--max-tokens N` | Server-side completion cap |

---

## Stop everything

```bash
pkill -f "llm-race serve"
pkill -f "ssh -fN -L 8001"        # kill the SSH tunnel if you opened one
```

---

## Adding more runners

Copy any YAML in `configs/`, add another `- id: …` block per endpoint, and the
UI auto-stacks lanes. Up to ~6 runners look clean; beyond that the panels start
crowding the left rail.

---

## Troubleshooting

- **"connection refused"** — your local server / SSH tunnel isn't listening on
  the port the YAML names. Verify with `curl http://localhost:8001/v1/models`.
- **Browser shows blank canvas** — open DevTools console. If you see a CSP /
  importmap error, your browser is older than mid-2023; use Chrome / Firefox /
  Safari current release.
- **All runners stuck at 0 tok/s** — check the server log; usually the model
  name in the YAML doesn't match what vLLM advertises. Run
  `curl http://localhost:8001/v1/models` to see the canonical name.
- **Reasoning models look paused** — they're inside a `<think>` block. The HUD
  badge flips to `THINK` (violet); the orb keeps advancing because think
  tokens count toward total tokens.
