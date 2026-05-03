"""Arena — the pyxel game window.

Zero numeric stats by design. The viewer just sees who's ahead.
- Each runner is a sprite on its own lane.
- Sprite advances right based on tokens streamed.
- "Thinking" = sprite stops, thought bubble appears.
- First sprite to cross the finish line gets a winner banner + confetti.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from queue import Empty
from typing import TYPE_CHECKING

import pyxel

from llm_race.runners.base import EventKind

if TYPE_CHECKING:
    from llm_race.orchestrator import Orchestrator
    from llm_race.runners.base import RunnerSpec


# drawais palette: purple #c084fc · pink #f472b6 · cyan #22d3ee · yellow #fde047
LANE_COLORS = [10, 8, 12, 11, 14, 9, 13, 6]  # pyxel palette indices
SCREEN_W = 320
SCREEN_H = 200
LANE_HEIGHT = 22
TRACK_LEFT = 24
TRACK_RIGHT = SCREEN_W - 16
TRACK_LEN = TRACK_RIGHT - TRACK_LEFT


@dataclass
class LaneState:
    spec: "RunnerSpec"
    color: int
    progress: float = 0.0  # 0..1
    velocity: float = 0.0  # smoothed pixels/frame for animation
    target_progress: float = 0.0
    token_count: int = 0
    finished: bool = False
    finish_time: float | None = None
    thinking: bool = False
    error: str | None = None
    # pacing
    last_event_time: float = field(default_factory=time.time)


class Arena:
    """Pyxel game state."""

    def __init__(self, orch: "Orchestrator", target_tokens: int = 1024,
                 prompt_label: str = "build me Tetris in Python") -> None:
        self.orch = orch
        self.target_tokens = target_tokens
        self.prompt_label = prompt_label
        self.lanes: list[LaneState] = [
            LaneState(r.spec, color=LANE_COLORS[i % len(LANE_COLORS)])
            for i, r in enumerate(orch.runners)
        ]
        self.start_time = time.time()
        self.t0 = self.start_time
        self.confetti: list[tuple[float, float, float, float, int]] = []
        self.race_over = False
        self.race_over_at: float | None = None
        self.winner_id: str | None = None
        # Frame counter for animation
        self.frame = 0

    # ----- public API ----------------------------------------------------

    def run(self) -> None:
        pyxel.init(SCREEN_W, SCREEN_H, title="LLM Race · drawais",
                   fps=60, capture_scale=2)
        self.orch.start()
        pyxel.run(self.update, self.draw)

    # ----- update --------------------------------------------------------

    def update(self) -> None:
        self.frame += 1
        # Drain queued events
        while True:
            try:
                ev = self.orch.queue.get_nowait()
            except Empty:
                break
            self._apply(ev)

        # Smooth motion: ease toward target
        for lane in self.lanes:
            if lane.error or lane.finished:
                continue
            diff = lane.target_progress - lane.progress
            lane.velocity = diff * 0.08
            lane.progress += lane.velocity

        # Confetti physics
        new_confetti = []
        for x, y, vx, vy, c in self.confetti:
            vy += 0.18  # gravity
            x += vx
            y += vy
            if y < SCREEN_H + 8:
                new_confetti.append((x, y, vx, vy, c))
        self.confetti = new_confetti

        # Race over check: all lanes finished or errored
        if not self.race_over and all(l.finished or l.error for l in self.lanes):
            self.race_over = True
            self.race_over_at = time.time()

        # Auto-quit a few seconds after race is over (for clean screen-record)
        if self.race_over and self.race_over_at and time.time() - self.race_over_at > 6.0:
            pyxel.quit()

        if pyxel.btnp(pyxel.KEY_Q) or pyxel.btnp(pyxel.KEY_ESCAPE):
            pyxel.quit()

    def _apply(self, ev) -> None:
        lane = next((l for l in self.lanes if l.spec.id == ev.runner_id), None)
        if lane is None:
            return
        lane.last_event_time = time.time()
        if ev.kind == EventKind.START:
            return
        if ev.kind == EventKind.TOKEN:
            lane.token_count = ev.token_count
            lane.target_progress = min(1.0, lane.token_count / self.target_tokens)
            return
        if ev.kind == EventKind.THINK_OPEN:
            lane.thinking = True
            return
        if ev.kind == EventKind.THINK_CLOSE:
            lane.thinking = False
            return
        if ev.kind == EventKind.FINISH:
            lane.finished = True
            lane.target_progress = 1.0
            lane.finish_time = ev.elapsed
            if self.winner_id is None:
                self.winner_id = lane.spec.id
                # Burst of confetti for the winner
                for i in range(80):
                    import random
                    x = TRACK_RIGHT
                    y = self._lane_y(self.lanes.index(lane))
                    vx = random.uniform(-2.0, 2.0)
                    vy = random.uniform(-3.0, -0.5)
                    c = random.choice([8, 9, 10, 11, 12, 14])
                    self.confetti.append((x, y, vx, vy, c))
            return
        if ev.kind == EventKind.ERROR:
            lane.error = ev.error
            return

    # ----- draw ----------------------------------------------------------

    def draw(self) -> None:
        pyxel.cls(0)  # black bg
        # Top banner
        pyxel.rect(0, 0, SCREEN_W, 14, 1)
        title = "LLM RACE"
        pyxel.text(8, 4, title, 7)
        sub = self.prompt_label[:48]
        pyxel.text(8 + len(title) * 4 + 6, 4, "·  " + sub, 13)
        # drawais logo bottom-right
        pyxel.text(SCREEN_W - 56, 4, "drawais", 14)

        # Track surface
        pyxel.rect(0, 14, SCREEN_W, SCREEN_H - 14, 0)

        # Finish line column (right) — checkered
        for y in range(14, SCREEN_H, 4):
            c = 7 if (y // 4) % 2 == 0 else 0
            pyxel.rect(TRACK_RIGHT + 2, y, 4, 4, c)
        # Start line (left)
        pyxel.rect(TRACK_LEFT - 2, 14, 1, SCREEN_H - 14, 5)

        # Lanes
        for i, lane in enumerate(self.lanes):
            self._draw_lane(i, lane)

        # Confetti
        for x, y, _, _, c in self.confetti:
            pyxel.pset(int(x), int(y), c)

        # Winner banner
        if self.winner_id is not None:
            self._draw_winner()

    def _lane_y(self, i: int) -> int:
        top = 18 + i * LANE_HEIGHT
        return top + LANE_HEIGHT // 2

    def _draw_lane(self, i: int, lane: LaneState) -> None:
        top = 18 + i * LANE_HEIGHT
        mid = top + LANE_HEIGHT // 2
        # lane stripe
        pyxel.line(TRACK_LEFT, mid + 6, TRACK_RIGHT, mid + 6, 5)
        # dashed mid line
        for dx in range(TRACK_LEFT, TRACK_RIGHT, 8):
            pyxel.line(dx, mid + 6, dx + 4, mid + 6, 13)
        # Label (model id, left-aligned, small)
        label = (lane.spec.label or lane.spec.id)[:18]
        pyxel.text(2, top + 2, label, lane.color)

        # Sprite x position
        x = TRACK_LEFT + int(lane.progress * TRACK_LEN)
        # Body
        if lane.error:
            pyxel.text(x - 4, mid - 2, "X_X", 8)
            pyxel.text(x - 12, mid + 6, "(error)", 8)
            return
        # Animation phase
        bob = int((self.frame + i * 7) // 6) % 2
        # Simple stick-runner: head, body, legs
        head_y = mid - 8 + (bob if not lane.thinking else 0)
        body_y = mid - 4
        feet_y = mid + 1
        pyxel.circ(x, head_y, 2, lane.color)
        pyxel.line(x, head_y + 2, x, body_y + 2, lane.color)
        # Arms
        pyxel.line(x - 3, body_y, x + 3, body_y, lane.color)
        # Legs alternate
        if bob == 0:
            pyxel.line(x, body_y + 2, x - 3, feet_y, lane.color)
            pyxel.line(x, body_y + 2, x + 2, feet_y, lane.color)
        else:
            pyxel.line(x, body_y + 2, x - 2, feet_y, lane.color)
            pyxel.line(x, body_y + 2, x + 3, feet_y, lane.color)

        # Thinking bubble
        if lane.thinking:
            pyxel.circb(x + 6, head_y - 4, 3, 7)
            pyxel.text(x + 4, head_y - 6, "?", 7)

        # Finished checkmark
        if lane.finished:
            pyxel.text(x + 4, mid - 4, "OK", 11)

    def _draw_winner(self) -> None:
        # Pulsing "WINNER" banner
        if self.race_over_at is None:
            return
        pulse = (self.frame // 6) % 2
        c = 10 if pulse == 0 else 14
        wname = self.winner_id or ""
        msg = "WINNER: " + wname[:24]
        bw = len(msg) * 4 + 8
        bx = (SCREEN_W - bw) // 2
        by = SCREEN_H // 2 - 8
        pyxel.rect(bx - 2, by - 2, bw + 4, 16, 0)
        pyxel.rectb(bx - 2, by - 2, bw + 4, 16, c)
        pyxel.text(bx + 4, by + 4, msg, c)
