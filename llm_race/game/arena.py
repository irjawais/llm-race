"""Arena — pygame race with emoji characters + animated scene + terminal panel.

Layout zones (top → bottom, no overlap):
- HEADER (80 px): title + prompt + drawais brand + global timer
- LANE AREA (auto-sized): one card per runner, lane height fits usable space
- BOTTOM PANEL (240 px): per-runner table + scrolling colored log

Within each lane (left → right, gutters):
- LEFT GUTTER (220 px): model label + tok/s + token count
- TRACK (mid): progress bar, dashed scrolling road, sprite, glow trail
- RIGHT GUTTER (200 px): big tokens counter
- FINISH STRIP: checkered, between TRACK and RIGHT GUTTER
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


BG_TOP = (8, 6, 18)
BG_BOT = (28, 8, 48)
HEADER_BG = (16, 10, 30)
LANE_BG = (18, 12, 32)
LANE_BG_ALT = (22, 14, 38)
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
    (192, 132, 252),
    (244, 114, 182),
    (34, 211, 238),
    (253, 224, 71),
    (74, 222, 128),
    (251, 146, 60),
    (251, 113, 133),
    (165, 180, 252),
]

DEFAULT_EMOJI = ["🚀", "🏎️", "🐎", "🦄", "🐇", "🦊", "🐢", "🦖"]

SCREEN_W = 1440
SCREEN_H = 900
HEADER_H = 80
PANEL_H = 240

LEFT_GUTTER = 240        # label + tok/s + token count
RIGHT_GUTTER = 220       # big counter
TRACK_LEFT = LEFT_GUTTER
TRACK_RIGHT = SCREEN_W - RIGHT_GUTTER
TRACK_LEN = TRACK_RIGHT - TRACK_LEFT
LANE_PAD_X = 16          # card outer padding from screen edge


@dataclass
class LaneState:
    spec: "RunnerSpec"
    color: tuple[int, int, int]
    emoji: str = "🚀"
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


def _try_load_emoji_font(size: int) -> pygame.font.Font | None:
    candidates = [
        "/System/Library/Fonts/Apple Color Emoji.ttc",
        "/System/Library/Fonts/Apple Color Emoji.ttf",
        "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
        "/usr/share/fonts/truetype/twemoji/Twemoji.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                f = pygame.font.Font(p, size)
                surf = f.render("🚀", True, (255, 255, 255))
                if surf.get_width() > 0:
                    return f
            except Exception:
                continue
    return None


class Arena:
    def __init__(self, orch: "Orchestrator", target_tokens: int = 1024,
                 prompt_label: str = "build me Tetris in Python") -> None:
        self.orch = orch
        self.target_tokens = target_tokens
        self.prompt_label = prompt_label
        self.lanes: list[LaneState] = []
        for i, r in enumerate(orch.runners):
            spr = r.spec.sprite or ""
            if not spr or spr.startswith("runner_"):
                emoji = DEFAULT_EMOJI[i % len(DEFAULT_EMOJI)]
            else:
                emoji = spr
            self.lanes.append(
                LaneState(r.spec, color=LANE_COLORS[i % len(LANE_COLORS)], emoji=emoji)
            )
        self.start_time = time.time()
        self.confetti: list[list[float]] = []
        self.race_over = False
        self.race_over_at: float | None = None
        self.winner_id: str | None = None
        self.frame = 0
        self.terminal_lines: deque[tuple[float, str, tuple[int, int, int]]] = deque(maxlen=12)
        self._bg_surf: pygame.Surface | None = None
        self.dash_offset = 0.0
        self.cloud_offset = 0.0
        self.emoji_font: pygame.font.Font | None = None

    def run(self) -> None:
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        pygame.init()
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        pygame.display.set_caption("LLM Race · drawais")
        self.clock = pygame.time.Clock()
        self.font_title = pygame.font.SysFont("Helvetica", 38, bold=True)
        self.font_sub = pygame.font.SysFont("Helvetica", 20)
        self.font_label = pygame.font.SysFont("Helvetica", 22, bold=True)
        self.font_winner = pygame.font.SysFont("Helvetica", 80, bold=True)
        self.font_brand = pygame.font.SysFont("Helvetica", 20, bold=True)
        self.font_big_num = pygame.font.SysFont("Menlo", 38, bold=True)
        self.font_small_num = pygame.font.SysFont("Menlo", 15, bold=True)
        self.font_term = pygame.font.SysFont("Menlo", 14)
        self.font_term_b = pygame.font.SysFont("Menlo", 14, bold=True)
        self.emoji_font = _try_load_emoji_font(54)
        self._bg_surf = self._build_background()

        self._add_log("[boot] arena ready · 60 fps · race armed", TERMINAL_FG)
        for lane in self.lanes:
            tag = lane.emoji + "  " + (lane.spec.label or lane.spec.id)
            self._add_log(f"[runner] + {tag}", lane.color)
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
        self.dash_offset = (self.dash_offset + 4.5) % 28
        self.cloud_offset = (self.cloud_offset + 0.4) % SCREEN_W
        while True:
            try:
                ev = self.orch.queue.get_nowait()
            except Empty:
                break
            self._apply(ev)

        now = time.time()
        for lane in self.lanes:
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

        new_conf = []
        for c in self.confetti:
            c[3] += 0.18
            c[0] += c[2]
            c[1] += c[3]
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
                    ])
            return
        if ev.kind == EventKind.ERROR:
            lane.error = ev.error
            self._add_log(f"[{lane.spec.id}] ERROR · {(ev.error or '')[:64]}", RED_NEON)
            return

    def _add_log(self, line: str, color: tuple[int, int, int]) -> None:
        self.terminal_lines.append((time.time(), line, color))

    # -- layout helpers ---------------------------------------------------

    def _lane_area_top(self) -> int:
        return HEADER_H

    def _lane_area_bot(self) -> int:
        return SCREEN_H - PANEL_H

    def _lane_height(self) -> int:
        n = max(1, len(self.lanes))
        usable = self._lane_area_bot() - self._lane_area_top() - 24
        # clamp lane height between 96 and 160; if lanes don't fit, shrink
        return max(80, min(160, usable // n))

    def _lane_y(self, i: int) -> int:
        h = self._lane_height()
        top = self._lane_area_top() + 12 + i * h
        return top + h // 2

    # -- draw -------------------------------------------------------------

    def draw(self) -> None:
        if self._bg_surf is not None:
            self.screen.blit(self._bg_surf, (0, 0))
        else:
            self.screen.fill(BG_TOP)
        self._draw_clouds()

        # Header
        pygame.draw.rect(self.screen, HEADER_BG, (0, 0, SCREEN_W, HEADER_H))
        pygame.draw.line(self.screen, PANEL_BORDER, (0, HEADER_H - 1),
                         (SCREEN_W, HEADER_H - 1), 1)
        title = self.font_title.render("LLM RACE", True, WHITE)
        self.screen.blit(title, (24, 18))
        sub = self.font_sub.render("// " + self.prompt_label[:80], True, GREY)
        self.screen.blit(sub, (24 + title.get_width() + 16, 30))
        brand = self.font_brand.render("drawais", True, LANE_COLORS[0])
        self.screen.blit(brand, (SCREEN_W - 22 - brand.get_width(), 14))
        host = self.font_small_num.render(
            f"target {self.target_tokens} tok  ·  elapsed {time.time() - self.start_time:5.1f}s",
            True, DIM,
        )
        self.screen.blit(host, (SCREEN_W - 22 - host.get_width(), 44))

        # Lanes
        h = self._lane_height()
        for i, lane in enumerate(self.lanes):
            top = self._lane_area_top() + 12 + i * h
            self._draw_lane(top, h, lane)

        for c in self.confetti:
            pygame.draw.rect(self.screen, c[4], (int(c[0]), int(c[1]), 5, 5))

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
        for y in range(0, SCREEN_H, 32):
            for x in range(0, SCREEN_W, 32):
                surf.set_at((x, y), (38, 24, 60))
        rng = random.Random(42)
        for _ in range(120):
            x = rng.randint(0, SCREEN_W - 1)
            y = rng.randint(0, HEADER_H)
            c = rng.choice([(180, 160, 220), (220, 200, 240), (140, 120, 200)])
            pygame.draw.circle(surf, c, (x, y), 1)
        return surf

    def _draw_clouds(self) -> None:
        ofs = self.cloud_offset
        for cx, cy, r in [(200, 50, 60), (700, 30, 80), (1100, 60, 70)]:
            x = (cx - ofs) % (SCREEN_W + 200) - 100
            blob = pygame.Surface((r * 4, r * 2), pygame.SRCALPHA)
            pygame.draw.ellipse(blob, (60, 40, 90, 60), (0, 0, r * 4, r * 2))
            self.screen.blit(blob, (int(x), cy))

    def _draw_lane(self, top: int, lane_h: int, lane: LaneState) -> None:
        idx = self.lanes.index(lane)
        card_color = LANE_BG if (idx % 2 == 0) else LANE_BG_ALT
        card_x = LANE_PAD_X
        card_y = top
        card_w = SCREEN_W - 2 * LANE_PAD_X
        card_h = lane_h - 8
        card_rect = pygame.Rect(card_x, card_y, card_w, card_h)
        pygame.draw.rect(self.screen, card_color, card_rect, border_radius=18)
        # Active border tint when lane has progress AND not finished
        border = lane.color if (lane.progress > 0.01 and not lane.finished and not lane.error) else PANEL_BORDER
        if lane.finished:
            border = GREEN_NEON
        pygame.draw.rect(self.screen, border, card_rect, width=1, border_radius=18)

        mid = card_y + card_h // 2

        # ---- LEFT GUTTER (label + tps + tokens) ----
        # use 3 rows positioned absolutely from card top
        label = (lane.spec.label or lane.spec.id)[:22]
        label_surf = self.font_label.render(label, True, lane.color)
        self.screen.blit(label_surf, (card_x + 16, card_y + 14))
        tps_surf = self.font_small_num.render(f"{lane.instant_tps:5.1f} tok/s", True, GREY)
        self.screen.blit(tps_surf, (card_x + 16, card_y + 14 + 30))
        tc_surf = self.font_small_num.render(f"{lane.token_count:>4d} tok", True, lane.color)
        self.screen.blit(tc_surf, (card_x + 16, card_y + 14 + 30 + 22))

        # ---- TRACK ----
        track_y = mid + lane_h // 8
        pygame.draw.line(self.screen, TRACK_LINE, (TRACK_LEFT, track_y),
                         (TRACK_RIGHT, track_y), 3)
        # Animated dashes
        dash_len = 14
        gap = 14
        period = dash_len + gap
        x0 = TRACK_LEFT + int(self.dash_offset) - period
        while x0 < TRACK_RIGHT:
            seg_left = max(TRACK_LEFT, x0)
            seg_right = min(TRACK_RIGHT, x0 + dash_len)
            if seg_right > seg_left:
                pygame.draw.line(self.screen, TRACK_DASH, (seg_left, track_y),
                                 (seg_right, track_y), 3)
            x0 += period

        # Progress bar above track
        fill_w = int(lane.progress * TRACK_LEN)
        bar_h = 7
        bar_y = track_y - 22
        pygame.draw.rect(self.screen, (28, 16, 44),
                         (TRACK_LEFT, bar_y, TRACK_LEN, bar_h), border_radius=4)
        if fill_w > 0:
            pygame.draw.rect(self.screen, lane.color,
                             (TRACK_LEFT, bar_y, fill_w, bar_h), border_radius=4)

        # Start vertical line
        pygame.draw.line(self.screen, (220, 220, 220),
                         (TRACK_LEFT - 4, card_y + 12),
                         (TRACK_LEFT - 4, card_y + card_h - 12), 2)
        # Finish: small checker column right at TRACK_RIGHT (inside track)
        for ny in range(card_y + 12, card_y + card_h - 12, 8):
            for k in range(2):
                col = WHITE if (((ny // 8) + k) % 2 == 0) else (10, 10, 10)
                pygame.draw.rect(self.screen, col,
                                 (TRACK_RIGHT + 2 + k * 8, ny, 8, 8))

        # ---- SPRITE ----
        sprite_x = TRACK_LEFT + int(lane.progress * TRACK_LEN)
        if lane.error:
            err = self.font_label.render("DNF", True, RED_NEON)
            self.screen.blit(err, (sprite_x - 22, mid - 14))
        else:
            self._draw_sprite(sprite_x, mid, lane)

        # ---- RIGHT GUTTER (big tokens counter) ----
        # Counter is in the right gutter zone (TRACK_RIGHT + 24 .. SCREEN_W - 24)
        # so it never overlaps with track or sprite.
        gutter_left = TRACK_RIGHT + 24 + 18  # past the checker strip
        gutter_right = SCREEN_W - 24
        big_color = GREEN_NEON if lane.finished else (lane.color if not lane.thinking else DIM)
        big_n = self.font_big_num.render(f"{lane.token_count:>4d}", True, big_color)
        # right-align inside gutter
        bx = gutter_right - big_n.get_width()
        # clamp inside gutter
        if bx < gutter_left:
            bx = gutter_left
        by = card_y + 14
        self.screen.blit(big_n, (bx, by))
        unit = self.font_small_num.render("tokens", True, GREY)
        ux = gutter_right - unit.get_width()
        self.screen.blit(unit, (ux, by + big_n.get_height() + 2))

    def _draw_sprite(self, x: int, mid: int, lane: LaneState) -> None:
        # Speed lines (only when running, not thinking, not finished)
        if not lane.thinking and not lane.finished:
            for i in range(3):
                phase = (self.frame + i * 7) % 18
                lx = x - 32 - phase * 4
                a = max(0, 180 - phase * 12)
                line = pygame.Surface((28, 2), pygame.SRCALPHA)
                line.fill((*lane.color, a))
                self.screen.blit(line, (lx, mid - 10 + i * 8))

        # Glow halo (small enough to fit in lane card)
        halo_size = 80
        halo = pygame.Surface((halo_size, halo_size), pygame.SRCALPHA)
        for r in range(36, 8, -4):
            alpha = max(0, 30 - (36 - r))
            pygame.draw.circle(halo, (*lane.color, alpha),
                               (halo_size // 2, halo_size // 2), r)
        self.screen.blit(halo, (x - halo_size // 2, mid - halo_size // 2))

        # Character
        bob = int((self.frame // 6 + self.lanes.index(lane) * 3) % 2)
        sprite_size = 56
        if self.emoji_font is not None:
            try:
                raw = self.emoji_font.render(lane.emoji, True, (255, 255, 255))
                surf = pygame.transform.smoothscale(raw, (sprite_size, sprite_size))
                rect = surf.get_rect(center=(x, mid - bob * 2))
                self.screen.blit(surf, rect)
            except Exception:
                self._draw_face(x, mid, lane, bob)
        else:
            self._draw_face(x, mid, lane, bob)

        # Thinking bubble — drawn ABOVE the sprite (within card, won't bleed)
        if lane.thinking:
            bx, by = x + 22, mid - 30
            pygame.draw.circle(self.screen, (255, 255, 255), (bx, by), 14, 2)
            pygame.draw.circle(self.screen, (255, 255, 255), (bx - 12, by + 11), 4, 1)
            pygame.draw.circle(self.screen, (255, 255, 255), (bx - 18, by + 17), 2, 1)
            qmark = self.font_label.render("?", True, WHITE)
            self.screen.blit(qmark, (bx - 5, by - 12))

        if lane.finished:
            star = self.font_label.render("✓", True, GREEN_NEON)
            self.screen.blit(star, (x + 22, mid - 12))

    def _draw_face(self, x: int, mid: int, lane: LaneState, bob: int) -> None:
        body_y = mid - bob * 2
        pygame.draw.circle(self.screen, lane.color, (x, body_y), 22)
        pygame.draw.circle(self.screen, (10, 8, 22), (x - 7, body_y - 4), 3)
        pygame.draw.circle(self.screen, (10, 8, 22), (x + 7, body_y - 4), 3)
        pygame.draw.circle(self.screen, WHITE, (x - 6, body_y - 5), 1)
        pygame.draw.circle(self.screen, WHITE, (x + 8, body_y - 5), 1)
        pygame.draw.arc(self.screen, (10, 8, 22),
                        pygame.Rect(x - 8, body_y - 2, 16, 12),
                        math.pi, 2 * math.pi, 2)

    def _draw_panel(self) -> None:
        py = SCREEN_H - PANEL_H + 8
        pygame.draw.rect(self.screen, PANEL_BG,
                         (16, py, SCREEN_W - 32, PANEL_H - 16), border_radius=14)
        pygame.draw.rect(self.screen, PANEL_BORDER,
                         (16, py, SCREEN_W - 32, PANEL_H - 16),
                         width=1, border_radius=14)

        x0 = 32
        y0 = py + 14
        head_color = (200, 180, 240)
        header_y = y0
        head = self.font_term_b.render(
            "RUNNER".ljust(20) + "TOK".rjust(7) + "  TPS".rjust(8) +
            "  TIME".rjust(8) + "  STATUS".rjust(11),
            True, head_color,
        )
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
                status = "DNF"; stcol = RED_NEON
            elif lane.finished:
                status = "DONE"; stcol = GREEN_NEON
            elif lane.thinking:
                status = "THINK"; stcol = (200, 180, 240)
            else:
                status = "RUN"; stcol = lane.color
            line = f"{label:<20}{tok:>7d}{tps:>7.1f}{t:>7.1f}s   "
            self.screen.blit(self.font_term.render(line, True, lane.color), (x0, row_y))
            stx = x0 + self.font_term.size(line)[0]
            self.screen.blit(self.font_term_b.render(status, True, stcol), (stx, row_y))

        # Right half: log
        log_x = SCREEN_W // 2 + 16
        log_y = py + 14
        head2 = self.font_term_b.render("LOG", True, head_color)
        self.screen.blit(head2, (log_x, log_y))
        pygame.draw.line(self.screen, PANEL_BORDER,
                         (log_x, log_y + 22), (SCREEN_W - 32, log_y + 22), 1)
        recent = list(self.terminal_lines)[-10:]
        line_h = 17
        for j, (t_at, msg, color) in enumerate(recent):
            ts = self.font_term.render(f"{t_at - self.start_time:6.2f}s", True, DIM)
            self.screen.blit(ts, (log_x, log_y + 30 + j * line_h))
            content = self.font_term.render(msg[:96], True, color)
            self.screen.blit(content, (log_x + 64, log_y + 30 + j * line_h))
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
        y = (SCREEN_H - h) // 2 - 80
        backdrop = pygame.Surface((w + 80, h + 40), pygame.SRCALPHA)
        backdrop.fill((10, 6, 22, 220))
        self.screen.blit(backdrop, (x - 40, y - 20))
        ring = pygame.Rect(x - 40, y - 20, w + 80, h + 40)
        pygame.draw.rect(self.screen, LANE_COLORS[1], ring, width=2, border_radius=22)
        self.screen.blit(scaled, (x, y))
