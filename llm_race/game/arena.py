"""Arena — pygame race window.

Zero numeric stats by design. The viewer just sees who's ahead.
- Each runner is a sprite on its own lane.
- Sprite advances right based on tokens streamed.
- "Thinking" = sprite stops, thought bubble appears.
- First sprite to cross the finish line gets a winner banner + confetti.
"""
from __future__ import annotations

import math
import os
import random
import sys
import time
from dataclasses import dataclass, field
from queue import Empty
from typing import TYPE_CHECKING

import pygame

from llm_race.runners.base import EventKind

if TYPE_CHECKING:
    from llm_race.orchestrator import Orchestrator
    from llm_race.runners.base import RunnerSpec


# drawais palette
BG = (10, 10, 18)
BG_GRAD = (28, 12, 44)
BAR = (24, 16, 40)
TRACK = (40, 24, 56)
LANE_LINE = (90, 70, 130)
LANE_DASH = (180, 130, 230)
WHITE = (240, 240, 255)
GREY = (160, 160, 180)

LANE_COLORS = [
    (192, 132, 252),   # purple
    (244, 114, 182),   # pink
    (34, 211, 238),    # cyan
    (253, 224, 71),    # yellow
    (74, 222, 128),    # green
    (251, 146, 60),    # orange
    (251, 113, 133),   # rose
    (165, 180, 252),   # indigo
]

SCREEN_W = 1280
SCREEN_H = 720
TOP_BAR_H = 64
LANE_HEIGHT = 88
TRACK_LEFT = 96
TRACK_RIGHT = SCREEN_W - 64
TRACK_LEN = TRACK_RIGHT - TRACK_LEFT


@dataclass
class LaneState:
    spec: "RunnerSpec"
    color: tuple[int, int, int]
    progress: float = 0.0
    velocity: float = 0.0
    target_progress: float = 0.0
    token_count: int = 0
    finished: bool = False
    finish_time: float | None = None
    thinking: bool = False
    error: str | None = None
    last_event_time: float = field(default_factory=time.time)


class Arena:
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
        self.confetti: list[list[float]] = []
        self.race_over = False
        self.race_over_at: float | None = None
        self.winner_id: str | None = None
        self.frame = 0

    def run(self) -> None:
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        pygame.init()
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        pygame.display.set_caption("LLM Race · drawais")
        self.clock = pygame.time.Clock()
        self.font_title = pygame.font.SysFont("Helvetica", 30, bold=True)
        self.font_sub = pygame.font.SysFont("Helvetica", 18)
        self.font_label = pygame.font.SysFont("Helvetica", 22, bold=True)
        self.font_winner = pygame.font.SysFont("Helvetica", 64, bold=True)
        self.font_brand = pygame.font.SysFont("Helvetica", 16, bold=True)

        self.orch.start()
        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN and event.key in (pygame.K_q, pygame.K_ESCAPE):
                    running = False
            self.update()
            self.draw()
            pygame.display.flip()
            self.clock.tick(60)
            if self.race_over and self.race_over_at and time.time() - self.race_over_at > 6.0:
                running = False
        pygame.quit()

    def update(self) -> None:
        self.frame += 1
        while True:
            try:
                ev = self.orch.queue.get_nowait()
            except Empty:
                break
            self._apply(ev)
        for lane in self.lanes:
            if lane.error or lane.finished:
                continue
            diff = lane.target_progress - lane.progress
            lane.velocity = diff * 0.08
            lane.progress += lane.velocity
        new_confetti = []
        for c in self.confetti:
            c[3] += 0.18
            c[0] += c[2]
            c[1] += c[3]
            c[5] += c[6]
            if c[1] < SCREEN_H + 20:
                new_confetti.append(c)
        self.confetti = new_confetti
        if not self.race_over and all(l.finished or l.error for l in self.lanes):
            self.race_over = True
            self.race_over_at = time.time()

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
                self.winner_id = lane.spec.label or lane.spec.id
                idx = self.lanes.index(lane)
                cy = self._lane_y(idx)
                for _ in range(220):
                    self.confetti.append([
                        TRACK_RIGHT, cy,
                        random.uniform(-3.5, 3.5),
                        random.uniform(-7.0, -1.0),
                        random.choice(LANE_COLORS),
                        0.0,
                        random.uniform(-0.1, 0.1),
                    ])
            return
        if ev.kind == EventKind.ERROR:
            lane.error = ev.error
            return

    def draw(self) -> None:
        # Vertical gradient background
        for y in range(SCREEN_H):
            t = y / SCREEN_H
            r = int(BG[0] + (BG_GRAD[0] - BG[0]) * t)
            g = int(BG[1] + (BG_GRAD[1] - BG[1]) * t)
            b = int(BG[2] + (BG_GRAD[2] - BG[2]) * t)
            pygame.draw.line(self.screen, (r, g, b), (0, y), (SCREEN_W, y))

        # Top bar
        pygame.draw.rect(self.screen, BAR, (0, 0, SCREEN_W, TOP_BAR_H))
        title = self.font_title.render("LLM RACE", True, WHITE)
        self.screen.blit(title, (24, 16))
        sub = self.font_sub.render("·  " + self.prompt_label[:80], True, GREY)
        self.screen.blit(sub, (24 + title.get_width() + 16, 24))
        brand = self.font_brand.render("drawais", True, LANE_COLORS[0])
        self.screen.blit(brand, (SCREEN_W - 24 - brand.get_width(), 24))

        # Track region
        track_top = TOP_BAR_H + 16
        track_bot = track_top + len(self.lanes) * LANE_HEIGHT
        pygame.draw.rect(self.screen, TRACK, (0, track_top, SCREEN_W, track_bot - track_top))

        # Start line
        pygame.draw.line(self.screen, (255, 255, 255), (TRACK_LEFT - 6, track_top),
                         (TRACK_LEFT - 6, track_bot), 2)
        # Finish line — checkered
        for y in range(track_top, track_bot, 12):
            for k in range(3):
                col = WHITE if (((y // 12) + k) % 2 == 0) else (10, 10, 10)
                pygame.draw.rect(self.screen, col, (TRACK_RIGHT + 4 + k * 8, y, 8, 12))

        for i, lane in enumerate(self.lanes):
            self._draw_lane(i, lane)

        for c in self.confetti:
            pygame.draw.rect(self.screen, c[4], (int(c[0]), int(c[1]), 4, 4))

        if self.winner_id is not None:
            self._draw_winner()

    def _lane_y(self, i: int) -> int:
        return TOP_BAR_H + 16 + i * LANE_HEIGHT + LANE_HEIGHT // 2

    def _draw_lane(self, i: int, lane: LaneState) -> None:
        top = TOP_BAR_H + 16 + i * LANE_HEIGHT
        mid = top + LANE_HEIGHT // 2
        # lane separator
        pygame.draw.line(self.screen, LANE_LINE, (0, top + LANE_HEIGHT - 1),
                         (SCREEN_W, top + LANE_HEIGHT - 1), 1)
        # dashed mid line
        for dx in range(TRACK_LEFT, TRACK_RIGHT, 32):
            pygame.draw.line(self.screen, LANE_DASH, (dx, mid + 28),
                             (dx + 16, mid + 28), 2)
        # Label
        label_text = self.font_label.render(
            (lane.spec.label or lane.spec.id)[:24], True, lane.color
        )
        self.screen.blit(label_text, (8, top + 8))

        x = TRACK_LEFT + int(lane.progress * TRACK_LEN)
        if lane.error:
            err = self.font_label.render("X", True, (255, 80, 80))
            self.screen.blit(err, (x - 8, mid - 12))
            sub = self.font_sub.render("(error)", True, (255, 120, 120))
            self.screen.blit(sub, (x - 24, mid + 16))
            return

        # Sprite — runner with bobbing legs
        bob = (self.frame // 6 + i * 3) % 2
        head_y = mid - 22 + (0 if not lane.thinking else 0)
        # Head
        pygame.draw.circle(self.screen, lane.color, (x, head_y), 9)
        # Body
        pygame.draw.line(self.screen, lane.color, (x, head_y + 9), (x, mid), 4)
        # Arms
        if not lane.thinking:
            arm_offset = 6 if bob == 0 else -6
            pygame.draw.line(self.screen, lane.color, (x, mid - 8),
                             (x - 10, mid - 8 + arm_offset), 3)
            pygame.draw.line(self.screen, lane.color, (x, mid - 8),
                             (x + 10, mid - 8 - arm_offset), 3)
        else:
            # Arm raised "thinking"
            pygame.draw.line(self.screen, lane.color, (x, mid - 8),
                             (x + 10, head_y - 6), 3)
        # Legs
        if not lane.thinking:
            if bob == 0:
                pygame.draw.line(self.screen, lane.color, (x, mid),
                                 (x - 8, mid + 14), 4)
                pygame.draw.line(self.screen, lane.color, (x, mid),
                                 (x + 6, mid + 14), 4)
            else:
                pygame.draw.line(self.screen, lane.color, (x, mid),
                                 (x - 6, mid + 14), 4)
                pygame.draw.line(self.screen, lane.color, (x, mid),
                                 (x + 8, mid + 14), 4)
        else:
            pygame.draw.line(self.screen, lane.color, (x, mid),
                             (x - 6, mid + 14), 4)
            pygame.draw.line(self.screen, lane.color, (x, mid),
                             (x + 6, mid + 14), 4)

        # Thinking bubble
        if lane.thinking:
            bx, by = x + 18, head_y - 18
            pygame.draw.circle(self.screen, WHITE, (bx, by), 14, 2)
            pygame.draw.circle(self.screen, WHITE, (bx - 14, by + 12), 4, 1)
            pygame.draw.circle(self.screen, WHITE, (bx - 22, by + 18), 2, 1)
            qmark = self.font_label.render("?", True, WHITE)
            self.screen.blit(qmark, (bx - 4, by - 10))

        # Finished checkmark — small star
        if lane.finished:
            st = self.font_label.render("OK", True, (74, 222, 128))
            self.screen.blit(st, (x + 14, mid - 12))

    def _draw_winner(self) -> None:
        if self.race_over_at is None:
            return
        pulse = 1.0 + 0.15 * math.sin(self.frame * 0.2)
        msg = "WINNER · " + (self.winner_id or "")
        text = self.font_winner.render(msg, True, LANE_COLORS[0])
        w = int(text.get_width() * pulse)
        h = int(text.get_height() * pulse)
        scaled = pygame.transform.smoothscale(text, (w, h))
        x = (SCREEN_W - w) // 2
        y = (SCREEN_H - h) // 2
        # backdrop
        backdrop = pygame.Surface((w + 64, h + 32), pygame.SRCALPHA)
        backdrop.fill((10, 10, 18, 200))
        self.screen.blit(backdrop, (x - 32, y - 16))
        self.screen.blit(scaled, (x, y))
