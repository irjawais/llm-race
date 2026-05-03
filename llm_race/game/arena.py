"""Arena — modern pygame race with glow trails + terminal stats panel.

Visible elements (top to bottom):
- Header: drawais branding + prompt label
- Race lanes: gradient-filled progress bars + glowing rocket/car sprites
  + live token counter next to each sprite
- Bottom: terminal-style stats panel with live tok/s, tokens, elapsed,
  status — feels like a real benchmark dashboard, retro CRT vibe.
"""
from __future__ import annotations

import math
import os
import random
import time
from collections import deque
from dataclasses import dataclass, field
from queue import Empty
from typing import TYPE_CHECKING

import pygame

from llm_race.runners.base import EventKind

if TYPE_CHECKING:
    from llm_race.orchestrator import Orchestrator
    from llm_race.runners.base import RunnerSpec


# drawais palette
BG_TOP = (8, 6, 18)
BG_BOT = (28, 8, 48)
HEADER_BG = (16, 10, 30)
LANE_BG = (18, 12, 32)
LANE_BG_ALT = (24, 14, 40)
TRACK_LINE = (60, 40, 90)
TRACK_DASH = (140, 100, 200)
WHITE = (245, 240, 255)
GREY = (180, 175, 200)
DIM = (110, 100, 140)
GREEN_NEON = (52, 224, 156)
RED_NEON = (255, 92, 130)
PANEL_BG = (12, 8, 22)
PANEL_BORDER = (80, 50, 130)
TERMINAL_FG = (180, 240, 200)

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

SCREEN_W = 1440
SCREEN_H = 900
HEADER_H = 80
PANEL_H = 220
LANE_AREA_TOP = HEADER_H
LANE_AREA_BOT = SCREEN_H - PANEL_H
LANE_HEIGHT_DEFAULT = 110

TRACK_LEFT = 200
TRACK_RIGHT = SCREEN_W - 80
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
    rolling: deque = field(default_factory=lambda: deque(maxlen=20))
    last_token_count: int = 0
    last_tok_time: float = field(default_factory=time.time)
    instant_tps: float = 0.0


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
        self.confetti: list[list[float]] = []
        self.race_over = False
        self.race_over_at: float | None = None
        self.winner_id: str | None = None
        self.frame = 0
        self.terminal_lines: deque[tuple[float, str, tuple[int, int, int]]] = deque(maxlen=12)
        self._bg_surf: pygame.Surface | None = None

    def run(self) -> None:
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        pygame.init()
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        pygame.display.set_caption("LLM Race · drawais")
        self.clock = pygame.time.Clock()
        self.font_title = pygame.font.SysFont("Helvetica", 38, bold=True)
        self.font_sub = pygame.font.SysFont("Helvetica", 20)
        self.font_label = pygame.font.SysFont("Helvetica", 24, bold=True)
        self.font_winner = pygame.font.SysFont("Helvetica", 88, bold=True)
        self.font_brand = pygame.font.SysFont("Helvetica", 20, bold=True)
        self.font_big_num = pygame.font.SysFont("Menlo", 36, bold=True)
        self.font_small_num = pygame.font.SysFont("Menlo", 16, bold=True)
        self.font_term = pygame.font.SysFont("Menlo", 15)
        self.font_term_b = pygame.font.SysFont("Menlo", 15, bold=True)
        self._bg_surf = self._build_background()
        self._add_log("[boot] arena ready · 60 fps · race armed", TERMINAL_FG)
        for lane in self.lanes:
            self._add_log(f"[runner] + {lane.spec.label or lane.spec.id}", lane.color)
        self.orch.start()
        self._add_log("[orch] streaming started · waiting for first token...", TERMINAL_FG)

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

    # -- update -----------------------------------------------------------

    def update(self) -> None:
        self.frame += 1
        while True:
            try:
                ev = self.orch.queue.get_nowait()
            except Empty:
                break
            self._apply(ev)

        now = time.time()
        for lane in self.lanes:
            # tokens-per-second: rolling window using last_token_count
            dt = now - lane.last_tok_time
            if dt >= 0.25:
                delta = lane.token_count - lane.last_token_count
                if dt > 0:
                    instant = delta / dt
                    lane.rolling.append(instant)
                    lane.instant_tps = sum(lane.rolling) / len(lane.rolling) if lane.rolling else 0.0
                lane.last_tok_time = now
                lane.last_token_count = lane.token_count
            if lane.error or lane.finished:
                continue
            diff = lane.target_progress - lane.progress
            lane.velocity = diff * 0.10
            lane.progress += lane.velocity

        # Confetti physics
        new_conf = []
        for c in self.confetti:
            c[3] += 0.18
            c[0] += c[2]
            c[1] += c[3]
            c[5] += c[6]
            if c[1] < SCREEN_H + 20:
                new_conf.append(c)
        self.confetti = new_conf

        if not self.race_over and all(l.finished or l.error for l in self.lanes):
            self.race_over = True
            self.race_over_at = time.time()

    def _apply(self, ev) -> None:
        lane = next((l for l in self.lanes if l.spec.id == ev.runner_id), None)
        if lane is None:
            return
        lane.last_event_time = time.time()
        if ev.kind == EventKind.START:
            self._add_log(f"[{lane.spec.id}] START", lane.color)
            return
        if ev.kind == EventKind.TOKEN:
            lane.token_count = ev.token_count
            lane.target_progress = min(1.0, lane.token_count / self.target_tokens)
            return
        if ev.kind == EventKind.THINK_OPEN:
            lane.thinking = True
            self._add_log(f"[{lane.spec.id}] <think> ...", DIM)
            return
        if ev.kind == EventKind.THINK_CLOSE:
            lane.thinking = False
            self._add_log(f"[{lane.spec.id}] </think> resume", lane.color)
            return
        if ev.kind == EventKind.FINISH:
            lane.finished = True
            lane.target_progress = 1.0
            lane.finish_time = ev.elapsed
            self._add_log(
                f"[{lane.spec.id}] FINISH · {lane.token_count} tokens · {ev.elapsed:.1f}s",
                GREEN_NEON,
            )
            if self.winner_id is None:
                self.winner_id = lane.spec.label or lane.spec.id
                idx = self.lanes.index(lane)
                cy = self._lane_y(idx)
                for _ in range(280):
                    self.confetti.append([
                        TRACK_RIGHT, cy,
                        random.uniform(-3.5, 3.5),
                        random.uniform(-7.5, -1.0),
                        random.choice(LANE_COLORS),
                        0.0,
                        random.uniform(-0.1, 0.1),
                    ])
            return
        if ev.kind == EventKind.ERROR:
            lane.error = ev.error
            self._add_log(f"[{lane.spec.id}] ERROR · {ev.error[:64]}", RED_NEON)
            return

    def _add_log(self, line: str, color: tuple[int, int, int]) -> None:
        self.terminal_lines.append((time.time(), line, color))

    # -- draw -------------------------------------------------------------

    def draw(self) -> None:
        if self._bg_surf is not None:
            self.screen.blit(self._bg_surf, (0, 0))
        else:
            self.screen.fill(BG_TOP)

        # Header
        pygame.draw.rect(self.screen, HEADER_BG, (0, 0, SCREEN_W, HEADER_H))
        pygame.draw.line(self.screen, PANEL_BORDER, (0, HEADER_H - 1), (SCREEN_W, HEADER_H - 1), 1)
        title = self.font_title.render("LLM RACE", True, WHITE)
        self.screen.blit(title, (28, 20))
        sub = self.font_sub.render("// " + self.prompt_label[:90], True, GREY)
        self.screen.blit(sub, (28 + title.get_width() + 16, 32))
        # drawais branding (right)
        brand = self.font_brand.render("drawais", True, LANE_COLORS[0])
        self.screen.blit(brand, (SCREEN_W - 24 - brand.get_width(), 18))
        host = self.font_small_num.render(
            f"target  {self.target_tokens} tokens   ·   elapsed  {time.time() - self.start_time:5.1f}s",
            True, DIM,
        )
        self.screen.blit(host, (SCREEN_W - 24 - host.get_width(), 48))

        # Lanes
        n = len(self.lanes)
        usable = LANE_AREA_BOT - LANE_AREA_TOP - 32
        lane_h = max(72, min(LANE_HEIGHT_DEFAULT, usable // max(n, 1)))
        for i, lane in enumerate(self.lanes):
            top = LANE_AREA_TOP + 16 + i * lane_h
            self._draw_lane(top, lane_h, lane)

        # Confetti
        for c in self.confetti:
            pygame.draw.rect(self.screen, c[4], (int(c[0]), int(c[1]), 5, 5))

        # Bottom panel — terminal-ish stats
        self._draw_panel()

        if self.winner_id is not None:
            self._draw_winner()

    def _build_background(self) -> pygame.Surface:
        surf = pygame.Surface((SCREEN_W, SCREEN_H))
        for y in range(SCREEN_H):
            t = y / SCREEN_H
            r = int(BG_TOP[0] + (BG_BOT[0] - BG_TOP[0]) * t)
            g = int(BG_TOP[1] + (BG_BOT[1] - BG_TOP[1]) * t)
            b = int(BG_TOP[2] + (BG_BOT[2] - BG_TOP[2]) * t)
            pygame.draw.line(surf, (r, g, b), (0, y), (SCREEN_W, y))
        # Subtle dot grid
        for y in range(0, SCREEN_H, 32):
            for x in range(0, SCREEN_W, 32):
                surf.set_at((x, y), (38, 24, 60))
        return surf

    def _lane_y(self, i: int) -> int:
        n = len(self.lanes)
        usable = LANE_AREA_BOT - LANE_AREA_TOP - 32
        lane_h = max(72, min(LANE_HEIGHT_DEFAULT, usable // max(n, 1)))
        top = LANE_AREA_TOP + 16 + i * lane_h
        return top + lane_h // 2

    def _draw_lane(self, top: int, lane_h: int, lane: LaneState) -> None:
        # Background card with rounded edges (simulated with rect + border)
        card_color = LANE_BG if (self.lanes.index(lane) % 2 == 0) else LANE_BG_ALT
        pygame.draw.rect(self.screen, card_color, (16, top, SCREEN_W - 32, lane_h - 8),
                         border_radius=14)
        pygame.draw.rect(self.screen, PANEL_BORDER, (16, top, SCREEN_W - 32, lane_h - 8),
                         width=1, border_radius=14)
        mid = top + (lane_h - 8) // 2

        # Label panel (left)
        label = (lane.spec.label or lane.spec.id)[:24]
        text = self.font_label.render(label, True, lane.color)
        self.screen.blit(text, (32, top + 12))
        # tok/s under label
        tps = self.font_small_num.render(f"{lane.instant_tps:5.1f} tok/s", True, GREY)
        self.screen.blit(tps, (32, top + 40))
        # token count
        tc = self.font_small_num.render(f"{lane.token_count:>4d} tok", True, lane.color)
        self.screen.blit(tc, (32, top + 60))

        # Track gradient line
        track_y = mid + lane_h // 8
        pygame.draw.line(self.screen, TRACK_LINE, (TRACK_LEFT, track_y),
                         (TRACK_RIGHT, track_y), 2)
        for dx in range(TRACK_LEFT, TRACK_RIGHT, 28):
            pygame.draw.line(self.screen, TRACK_DASH, (dx, track_y),
                             (dx + 14, track_y), 2)

        # Filled progress bar above track (subtle)
        fill_w = int(lane.progress * TRACK_LEN)
        bar_h = 6
        bar_y = track_y - 14
        pygame.draw.rect(self.screen, (28, 16, 44),
                         (TRACK_LEFT, bar_y, TRACK_LEN, bar_h), border_radius=3)
        if fill_w > 0:
            pygame.draw.rect(self.screen, lane.color,
                             (TRACK_LEFT, bar_y, fill_w, bar_h), border_radius=3)

        # Start + finish lines
        pygame.draw.line(self.screen, (220, 220, 220),
                         (TRACK_LEFT - 4, top + 8), (TRACK_LEFT - 4, top + lane_h - 16), 2)
        # Finish — checker
        for ny in range(top + 8, top + lane_h - 16, 8):
            for k in range(2):
                col = WHITE if (((ny // 8) + k) % 2 == 0) else (10, 10, 10)
                pygame.draw.rect(self.screen, col, (TRACK_RIGHT + 2 + k * 8, ny, 8, 8))

        # Sprite — modern rocket-y triangle with glow trail
        x = TRACK_LEFT + int(lane.progress * TRACK_LEN)
        if lane.error:
            err = self.font_label.render("DNF", True, RED_NEON)
            self.screen.blit(err, (x - 22, mid - 14))
            return
        self._draw_sprite(x, mid, lane)

        # Right-side big counter
        big_color = GREEN_NEON if lane.finished else (lane.color if not lane.thinking else DIM)
        big_n = self.font_big_num.render(f"{lane.token_count:>4d}", True, big_color)
        self.screen.blit(big_n, (SCREEN_W - 32 - big_n.get_width(), top + 14))
        unit = self.font_small_num.render("tokens", True, GREY)
        self.screen.blit(unit, (SCREEN_W - 32 - unit.get_width(), top + 56))

    def _draw_sprite(self, x: int, mid: int, lane: LaneState) -> None:
        # Glow trail (alpha rectangles fading behind the sprite)
        glow = pygame.Surface((120, 28), pygame.SRCALPHA)
        for i in range(8):
            alpha = max(0, 110 - i * 14)
            pygame.draw.rect(
                glow, (*lane.color, alpha),
                (110 - i * 14, 8, 12, 12), border_radius=4,
            )
        self.screen.blit(glow, (x - 110, mid - 14))

        # Body — rounded "ship" pointing right
        body_rect = pygame.Rect(x - 18, mid - 10, 36, 20)
        pygame.draw.rect(self.screen, lane.color, body_rect, border_radius=6)
        pygame.draw.polygon(
            self.screen, lane.color,
            [(x + 16, mid - 10), (x + 28, mid), (x + 16, mid + 10)],
        )
        # Cockpit
        pygame.draw.circle(self.screen, WHITE, (x + 4, mid), 4)
        pygame.draw.circle(self.screen, lane.color, (x + 4, mid), 2)
        # Tail flame (animated)
        flicker = 6 + (self.frame % 4) * 2
        if not lane.thinking:
            pygame.draw.polygon(
                self.screen, (253, 224, 71),
                [(x - 18, mid - 6), (x - 18 - flicker, mid),
                 (x - 18, mid + 6)],
            )
            pygame.draw.polygon(
                self.screen, (251, 146, 60),
                [(x - 18, mid - 4), (x - 18 - flicker // 2, mid),
                 (x - 18, mid + 4)],
            )

        # Thinking bubble (shown above)
        if lane.thinking:
            bx, by = x + 4, mid - 30
            pygame.draw.circle(self.screen, (255, 255, 255), (bx, by), 14, 2)
            pygame.draw.circle(self.screen, (255, 255, 255), (bx - 14, by + 12), 4, 1)
            pygame.draw.circle(self.screen, (255, 255, 255), (bx - 22, by + 18), 2, 1)
            qmark = self.font_label.render("?", True, WHITE)
            self.screen.blit(qmark, (bx - 6, by - 12))

    def _draw_panel(self) -> None:
        py = SCREEN_H - PANEL_H + 8
        pygame.draw.rect(self.screen, PANEL_BG, (16, py, SCREEN_W - 32, PANEL_H - 16),
                         border_radius=12)
        pygame.draw.rect(self.screen, PANEL_BORDER, (16, py, SCREEN_W - 32, PANEL_H - 16),
                         width=1, border_radius=12)

        # Left half: per-runner stats grid
        x0 = 32
        y0 = py + 12
        col_w = (SCREEN_W // 2 - 64) // max(1, min(len(self.lanes), 4))

        head_color = (200, 180, 240)
        header_y = y0
        head = self.font_term_b.render("RUNNER".ljust(20) + "TOK".rjust(7) + "  TPS".rjust(8) + "  TIME".rjust(8) + "  STATUS".rjust(11), True, head_color)
        self.screen.blit(head, (x0, header_y))
        pygame.draw.line(self.screen, PANEL_BORDER,
                         (x0, header_y + 22), (SCREEN_W // 2 - 16, header_y + 22), 1)

        elapsed = time.time() - self.start_time
        for i, lane in enumerate(self.lanes):
            row_y = header_y + 28 + i * 22
            label = (lane.spec.label or lane.spec.id)[:18]
            tok = lane.token_count
            tps = lane.instant_tps
            t = lane.finish_time if lane.finished else elapsed
            if lane.error:
                status = "DNF"
                stcol = RED_NEON
            elif lane.finished:
                status = "DONE"
                stcol = GREEN_NEON
            elif lane.thinking:
                status = "THINK"
                stcol = (200, 180, 240)
            else:
                status = "RUN  "
                stcol = lane.color
            line = (
                f"{label:<20}{tok:>7d}{tps:>7.1f}{t:>7.1f}s   "
            )
            self.screen.blit(self.font_term.render(line, True, lane.color), (x0, row_y))
            stx = x0 + self.font_term.size(line)[0]
            self.screen.blit(self.font_term_b.render(status, True, stcol), (stx, row_y))

        # Right half: rolling terminal log
        log_x = SCREEN_W // 2 + 16
        log_y = py + 12
        log_w = SCREEN_W - log_x - 32
        head2 = self.font_term_b.render("LOG", True, head_color)
        self.screen.blit(head2, (log_x, log_y))
        pygame.draw.line(self.screen, PANEL_BORDER,
                         (log_x, log_y + 22), (SCREEN_W - 32, log_y + 22), 1)
        # render last N lines newest at bottom
        recent = list(self.terminal_lines)[-10:]
        line_h = 17
        for j, (t_at, msg, color) in enumerate(recent):
            ts = self.font_term.render(f"{t_at - self.start_time:6.2f}s", True, DIM)
            self.screen.blit(ts, (log_x, log_y + 30 + j * line_h))
            content = self.font_term.render(msg[:96], True, color)
            self.screen.blit(content, (log_x + 64, log_y + 30 + j * line_h))

        # Blinking caret
        if (self.frame // 30) % 2 == 0:
            cy = log_y + 30 + len(recent) * line_h
            pygame.draw.rect(self.screen, TERMINAL_FG, (log_x + 64, cy + 2, 8, 14))

    def _draw_winner(self) -> None:
        if self.race_over_at is None:
            return
        pulse = 1.0 + 0.10 * math.sin(self.frame * 0.18)
        msg = "WINNER · " + (self.winner_id or "")
        text = self.font_winner.render(msg, True, LANE_COLORS[0])
        w = int(text.get_width() * pulse)
        h = int(text.get_height() * pulse)
        scaled = pygame.transform.smoothscale(text, (w, h))
        x = (SCREEN_W - w) // 2
        y = (SCREEN_H - h) // 2 - 60
        backdrop = pygame.Surface((w + 80, h + 40), pygame.SRCALPHA)
        backdrop.fill((10, 6, 22, 220))
        self.screen.blit(backdrop, (x - 40, y - 20))
        # Outer ring (animated)
        ring = pygame.Rect(x - 40, y - 20, w + 80, h + 40)
        pygame.draw.rect(self.screen, LANE_COLORS[1], ring, width=2, border_radius=18)
        self.screen.blit(scaled, (x, y))
