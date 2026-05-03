"""Arena — v0.2 "Synthwave devtool" UI.

Layout zones (top → bottom, no overlap):
- HEADER (72 px): title + prompt + drawais brand + global timer
- SCENE (auto): vanishing-point grid + sun disc + horizon + lane cards
- BOTTOM HUD (236 px): three columns — leaderboard | sparklines | log

Strict rules:
- One accent in motion per element (HOT_PINK / CYAN / AMBER)
- Hot-pink reserved for the lead and finish moment only
- Glow only on the lead-lane border, never on every sprite
- Pixel-art sprites with token-locked run cycle (sprite frames swap on
  every TOKEN event so the runner moves *because* of the token).
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

from llm_race.game.sprites import render_sprite, resolve_sprite_name
from llm_race.runners.base import EventKind

if TYPE_CHECKING:
    from llm_race.orchestrator import Orchestrator
    from llm_race.runners.base import RunnerSpec


# ------------------------------------------------------------------ palette
BG_DEEP = (10, 10, 18)
BG_PANEL = (20, 20, 31)
GRID = (42, 27, 61)
HOT_PINK = (255, 0, 110)
CYAN = (0, 240, 255)
AMBER = (255, 190, 11)
TEXT = (232, 232, 240)
TEXT_DIM = (130, 124, 156)
NEUTRAL_BORDER = (36, 36, 52)
BLACK = (0, 0, 0)
SUN_TOP = (255, 0, 110)
SUN_BOT = (255, 190, 11)


LANE_COLORS = [
    (255, 0, 110),    # hot pink
    (0, 240, 255),    # cyan
    (255, 190, 11),   # amber
    (131, 56, 236),   # violet
    (255, 90, 50),    # orange-red
    (60, 220, 130),   # mint
    (255, 130, 200),  # rose
    (140, 200, 255),  # ice blue
]

DEFAULT_SPRITES = ["rocket", "car", "runner", "dragon", "bot",
                   "rocket", "car", "runner"]

# ------------------------------------------------------------------ layout
SCREEN_W = 1440
SCREEN_H = 900
HEADER_H = 72
PANEL_H = 236

LEFT_GUTTER = 220
RIGHT_GUTTER = 240
TRACK_LEFT = LEFT_GUTTER
TRACK_RIGHT = SCREEN_W - RIGHT_GUTTER
TRACK_LEN = TRACK_RIGHT - TRACK_LEFT
LANE_PAD_X = 20

CARD_RADIUS = 12


@dataclass
class LaneState:
    spec: "RunnerSpec"
    color: tuple[int, int, int]
    sprite_name: str = "runner"
    sprite_frame: int = 0
    blink: bool = False
    blink_until: float = 0.0
    progress: float = 0.0
    velocity: float = 0.0
    target_progress: float = 0.0
    token_count: int = 0
    last_progress_token: int = 0
    finished: bool = False
    finish_time: float | None = None
    thinking: bool = False
    error: str | None = None
    last_event_time: float = field(default_factory=time.time)
    rolling: deque = field(default_factory=lambda: deque(maxlen=20))
    last_token_count: int = 0
    last_tok_time: float = field(default_factory=time.time)
    instant_tps: float = 0.0
    spark: deque = field(default_factory=lambda: deque(maxlen=64))
    token_flash_until: float = 0.0


# ------------------------------------------------------------------ Arena
class Arena:
    def __init__(self, orch: "Orchestrator", target_tokens: int = 1024,
                 prompt_label: str = "build me Tetris in Python") -> None:
        self.orch = orch
        self.target_tokens = target_tokens
        self.prompt_label = prompt_label
        self.lanes: list[LaneState] = []
        for i, r in enumerate(orch.runners):
            sprite_name = resolve_sprite_name(
                r.spec.sprite, fallback_index=i,
            )
            color = LANE_COLORS[i % len(LANE_COLORS)]
            self.lanes.append(LaneState(r.spec, color=color, sprite_name=sprite_name))
        self.start_time = time.time()
        self.confetti: list[list[float]] = []
        self.particles: list[list[float]] = []
        self.race_over = False
        self.race_over_at: float | None = None
        self.winner_id: str | None = None
        self.winner_idx: int | None = None
        self.frame = 0
        self.terminal_lines: deque[tuple[float, str, tuple[int, int, int]]] = deque(maxlen=14)
        self.dash_offset = 0.0
        self.parallax_offset = 0.0
        self.shake_until = 0.0
        self.shake_mag = 0
        self.lead_idx: int | None = None
        self.flash_until: float = 0.0
        self.world_freeze_until: float = 0.0

    # ------------------------------------------------------------- run
    def run(self) -> None:
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        pygame.init()
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        pygame.display.set_caption("LLM Race · drawais")
        self.clock = pygame.time.Clock()
        # Fonts: monospace everywhere. JetBrains Mono if installed, else Menlo.
        self.font_display = self._mono(28, bold=True)
        self.font_title = self._mono(28, bold=True)
        self.font_sub = self._mono(14)
        self.font_label = self._mono(13, bold=True)
        self.font_hud = self._mono(12)
        self.font_hud_b = self._mono(12, bold=True)
        self.font_num_big = self._mono(28, bold=True)
        self.font_num_xl = self._mono(46, bold=True)
        self.font_winner = self._mono(72, bold=True)
        self.font_chip = self._mono(40, bold=True)

        # Pre-render sun disc
        self._sun_surf = self._build_sun(120)
        self._grain_surf = self._build_grain(SCREEN_W, SCREEN_H, intensity=0.03)
        self._vignette_surf = self._build_vignette(SCREEN_W, SCREEN_H, strength=0.20)

        self._add_log("[boot] arena armed · 60 fps", TEXT)
        for lane in self.lanes:
            self._add_log(f"[runner] + {lane.spec.label or lane.spec.id}", lane.color)
        self.orch.start()
        self._add_log("[orch] streaming · waiting for first token", TEXT)

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
            if self.race_over and self.race_over_at and time.time() - self.race_over_at > 7.0:
                running = False
        pygame.quit()

    def _mono(self, size: int, bold: bool = False) -> pygame.font.Font:
        # Try fonts that are likely installed first; only warn if everything
        # fails. pygame.font.match_font returns None when not installed —
        # silent check, no UserWarning.
        for name in ("JetBrains Mono", "JetBrainsMono", "Berkeley Mono",
                     "Menlo", "Monaco", "Courier New"):
            try:
                path = pygame.font.match_font(name, bold=bold)
                if path:
                    return pygame.font.Font(path, size)
            except Exception:
                continue
        return pygame.font.Font(None, size)

    # ---------------------------------------------------------- update
    def update(self) -> None:
        self.frame += 1
        if time.time() < self.world_freeze_until:
            # World motion paused — but UI events still drained
            self._drain_events()
            return
        self.dash_offset = (self.dash_offset + 4.5) % 28
        self.parallax_offset = (self.parallax_offset + 1.2) % 24
        self._drain_events()

        now = time.time()
        for lane in self.lanes:
            dt = now - lane.last_tok_time
            if dt >= 0.25:
                delta = lane.token_count - lane.last_token_count
                if dt > 0:
                    instant = delta / dt
                    lane.rolling.append(instant)
                    lane.instant_tps = sum(lane.rolling) / len(lane.rolling) if lane.rolling else 0.0
                    lane.spark.append(lane.instant_tps)
                lane.last_tok_time = now
                lane.last_token_count = lane.token_count

            # eased progress
            if not (lane.error or lane.finished):
                diff = lane.target_progress - lane.progress
                lane.velocity = diff * 0.10
                lane.progress += lane.velocity

            # blink eyes ~every 2.4s
            if now > lane.blink_until and not lane.thinking:
                if random.random() < 0.012:
                    lane.blink = True
                    lane.blink_until = now + 0.13
            elif now > lane.blink_until:
                lane.blink = False

        # Particles
        new_particles = []
        for p in self.particles:
            p[3] += 0.20
            p[0] += p[2]
            p[1] += p[3]
            p[5] -= p[6]  # life
            if p[5] > 0 and p[1] < SCREEN_H + 20:
                new_particles.append(p)
        self.particles = new_particles

        # Lead detection
        order = sorted(range(len(self.lanes)),
                       key=lambda i: (-self.lanes[i].progress, self.lanes[i].spec.id))
        new_lead = order[0] if self.lanes else None
        if new_lead is not None and new_lead != self.lead_idx:
            if self.lead_idx is not None:
                # screen shake on a lead change (after the first lead is set)
                self.shake_until = now + 0.12
                self.shake_mag = 5
                lead_label = self.lanes[new_lead].spec.label or self.lanes[new_lead].spec.id
                self._add_log(f"[lead] >>> {lead_label}", HOT_PINK)
            self.lead_idx = new_lead

        if not self.race_over and all(l.finished or l.error for l in self.lanes):
            self.race_over = True
            self.race_over_at = time.time()

    def _drain_events(self) -> None:
        while True:
            try:
                ev = self.orch.queue.get_nowait()
            except Empty:
                break
            self._apply(ev)

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
            # token-locked sprite frame
            lane.sprite_frame = (lane.sprite_frame + 1) % 2
            lane.token_flash_until = time.time() + 0.06
            return
        if ev.kind == EventKind.THINK_OPEN:
            lane.thinking = True
            self._add_log(f"[{lane.spec.id}] <think>", TEXT_DIM)
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
                f"[{lane.spec.id}] FINISH · {lane.token_count} tok · {ev.elapsed:.1f}s",
                AMBER,
            )
            if self.winner_id is None:
                self.winner_id = lane.spec.label or lane.spec.id
                self.winner_idx = self.lanes.index(lane)
                # Finish moment: world freeze + radial flash + particles
                now = time.time()
                self.world_freeze_until = now + 0.6
                self.flash_until = now + 0.55
                cx = TRACK_RIGHT
                cy = self._lane_y(self.winner_idx)
                for _ in range(40):
                    angle = random.uniform(0, 2 * math.pi)
                    speed = random.uniform(2, 6)
                    color = random.choice([HOT_PINK, CYAN, AMBER])
                    self.particles.append([
                        cx, cy,
                        math.cos(angle) * speed, math.sin(angle) * speed,
                        color, 0.8, 0.012,
                    ])
                # plus confetti to fill space
                for _ in range(140):
                    self.confetti.append([
                        cx, cy,
                        random.uniform(-3.5, 3.5),
                        random.uniform(-7.5, -1.0),
                        random.choice([HOT_PINK, CYAN, AMBER, TEXT]),
                    ])
                self._add_log(f">>> WINNER {self.winner_id}  ({lane.token_count} tok)", HOT_PINK)
            return
        if ev.kind == EventKind.ERROR:
            lane.error = ev.error
            self._add_log(f"[{lane.spec.id}] ERROR · {(ev.error or '')[:80]}", HOT_PINK)
            return

    def _add_log(self, line: str, color: tuple[int, int, int]) -> None:
        self.terminal_lines.append((time.time(), line, color))

    # ------------------------------------------------------------- draw
    def draw(self) -> None:
        # Background to its own surface so the shake offset moves a single blit
        scene = pygame.Surface((SCREEN_W, SCREEN_H))
        self._draw_background(scene)
        self._draw_header(scene)
        h = self._lane_height()
        for i, lane in enumerate(self.lanes):
            top = HEADER_H + 12 + i * h
            self._draw_lane(scene, top, h, i, lane)
        # Confetti on top of lanes
        for c in self.confetti:
            c[3] += 0.20
            c[0] += c[2]
            c[1] += c[3]
            if c[1] < SCREEN_H + 20:
                pygame.draw.rect(scene, c[4], (int(c[0]), int(c[1]), 5, 5))
        # particles (drawn on top of lanes)
        for p in self.particles:
            r = max(1, int(p[5] * 4))
            pygame.draw.circle(scene, p[4], (int(p[0]), int(p[1])), r)

        # Bottom HUD
        self._draw_hud(scene)

        # Flash overlay when winner just declared
        if time.time() < self.flash_until:
            t = (self.flash_until - time.time()) / 0.55
            alpha = int(t * 110)
            flash = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
            flash.fill((*HOT_PINK, alpha))
            scene.blit(flash, (0, 0))

        # Winner banner + 1ST chip
        if self.winner_id is not None:
            self._draw_winner(scene)

        # Vignette + grain post-FX
        scene.blit(self._vignette_surf, (0, 0))
        scene.blit(self._grain_surf, (0, 0))

        # Screen-shake offset
        ox = oy = 0
        if time.time() < self.shake_until:
            ox = random.randint(-self.shake_mag, self.shake_mag)
            oy = random.randint(-self.shake_mag, self.shake_mag)
        self.screen.fill(BG_DEEP)
        self.screen.blit(scene, (ox, oy))

    # -- background scene ------------------------------------------------
    def _draw_background(self, surf: pygame.Surface) -> None:
        surf.fill(BG_DEEP)
        # vanishing-point grid (drawn into scene area only)
        scene_top = HEADER_H
        scene_bot = SCREEN_H - PANEL_H
        # horizon ~30% from scene top
        horizon_y = scene_top + int((scene_bot - scene_top) * 0.30)
        # sun disc
        sx = SCREEN_W // 2
        sun_w, sun_h = self._sun_surf.get_size()
        surf.blit(self._sun_surf, (sx - sun_w // 2, horizon_y - sun_h + 10))
        # horizon line — the only loud thing in the back
        pygame.draw.line(surf, HOT_PINK, (0, horizon_y), (SCREEN_W, horizon_y), 1)
        # vertical lines fan out from vanishing point
        vp = (sx, horizon_y)
        for i in range(-12, 13):
            x_bottom = sx + int(i * (SCREEN_W / 12))
            pygame.draw.line(surf, GRID, vp, (x_bottom, scene_bot), 1)
        # horizontal lines below horizon, parallax
        ofs = self.parallax_offset
        n_rows = 14
        for j in range(1, n_rows + 1):
            t = (j + (ofs / 24)) / n_rows
            y = horizon_y + int((scene_bot - horizon_y) * (t * t))
            if y > scene_bot:
                continue
            pygame.draw.line(surf, GRID, (0, y), (SCREEN_W, y), 1)

    def _build_sun(self, radius: int) -> pygame.Surface:
        size = radius * 2
        s = pygame.Surface((size, size), pygame.SRCALPHA)
        for r in range(radius, 0, -1):
            t = r / radius
            col = (
                int(SUN_TOP[0] * (1 - t) + SUN_BOT[0] * t),
                int(SUN_TOP[1] * (1 - t) + SUN_BOT[1] * t),
                int(SUN_TOP[2] * (1 - t) + SUN_BOT[2] * t),
            )
            alpha = int(120 * (1 - t * 0.6))
            pygame.draw.circle(s, (*col, alpha), (radius, radius), r)
        return s

    def _build_grain(self, w: int, h: int, intensity: float = 0.03) -> pygame.Surface:
        s = pygame.Surface((w, h), pygame.SRCALPHA)
        rng = random.Random(0xCAFE)
        density = int(w * h * intensity)
        for _ in range(density):
            x = rng.randint(0, w - 1)
            y = rng.randint(0, h - 1)
            v = rng.randint(20, 60)
            s.set_at((x, y), (v, v, v, 30))
        return s

    def _build_vignette(self, w: int, h: int, strength: float = 0.20) -> pygame.Surface:
        s = pygame.Surface((w, h), pygame.SRCALPHA)
        cx, cy = w / 2, h / 2
        max_d = math.hypot(cx, cy)
        for y in range(0, h, 4):
            for x in range(0, w, 4):
                d = math.hypot(x - cx, y - cy) / max_d
                a = int(255 * strength * (d ** 2.4))
                pygame.draw.rect(s, (0, 0, 0, a), (x, y, 4, 4))
        return s

    # -- header ----------------------------------------------------------
    def _draw_header(self, surf: pygame.Surface) -> None:
        pygame.draw.rect(surf, BG_DEEP, (0, 0, SCREEN_W, HEADER_H))
        pygame.draw.line(surf, HOT_PINK, (0, HEADER_H - 1), (SCREEN_W, HEADER_H - 1), 1)
        title = self.font_title.render("LLM RACE", True, TEXT)
        surf.blit(title, (28, 22))
        # accent dot
        pygame.draw.circle(surf, HOT_PINK, (28 + title.get_width() + 16, 38), 4)
        sub_text = self.prompt_label[:80]
        sub = self.font_sub.render(sub_text, True, TEXT_DIM)
        surf.blit(sub, (28 + title.get_width() + 30, 32))
        brand = self.font_label.render("drawais", True, HOT_PINK)
        surf.blit(brand, (SCREEN_W - 24 - brand.get_width(), 18))
        elapsed = time.time() - self.start_time
        host = self.font_hud.render(
            f"target {self.target_tokens}t  ·  elapsed {elapsed:5.1f}s",
            True, TEXT_DIM,
        )
        surf.blit(host, (SCREEN_W - 24 - host.get_width(), 44))

    # -- lane card -------------------------------------------------------
    def _lane_height(self) -> int:
        n = max(1, len(self.lanes))
        usable = (SCREEN_H - PANEL_H) - HEADER_H - 24
        return max(80, min(140, usable // n))

    def _lane_y(self, i: int) -> int:
        h = self._lane_height()
        return HEADER_H + 12 + i * h + h // 2

    def _draw_lane(self, surf: pygame.Surface, top: int, lane_h: int,
                   idx: int, lane: LaneState) -> None:
        is_lead = (self.lead_idx == idx) and not lane.finished and not lane.error
        card_x = LANE_PAD_X
        card_y = top
        card_w = SCREEN_W - 2 * LANE_PAD_X
        card_h = lane_h - 8
        rect = pygame.Rect(card_x, card_y, card_w, card_h)
        pygame.draw.rect(surf, BG_PANEL, rect, border_radius=CARD_RADIUS)
        # Border
        if lane.finished:
            border = AMBER
        elif lane.error:
            border = HOT_PINK
        elif is_lead:
            # lead glow — only place glow is allowed
            for k in range(8, 0, -2):
                glow_rect = pygame.Rect(card_x - k, card_y - k,
                                        card_w + k * 2, card_h + k * 2)
                a = max(0, 50 - k * 4)
                glow = pygame.Surface((glow_rect.w, glow_rect.h), pygame.SRCALPHA)
                pygame.draw.rect(glow, (*HOT_PINK, a), glow.get_rect(),
                                 width=2, border_radius=CARD_RADIUS + k)
                surf.blit(glow, glow_rect.topleft)
            border = HOT_PINK
        else:
            border = NEUTRAL_BORDER
        pygame.draw.rect(surf, border, rect,
                         width=2 if is_lead or lane.finished else 1,
                         border_radius=CARD_RADIUS)

        mid = card_y + card_h // 2

        # ---- LEFT GUTTER ----
        label = (lane.spec.label or lane.spec.id)[:20]
        label_color = HOT_PINK if is_lead else (AMBER if lane.finished else lane.color)
        label_surf = self.font_label.render(label, True, label_color)
        surf.blit(label_surf, (card_x + 14, card_y + 12))
        # status chip
        status, status_color = self._status_for(lane, is_lead)
        chip_surf = self.font_hud_b.render(status, True, status_color)
        chip_x = card_x + 14
        chip_y = card_y + 30
        chip_w = chip_surf.get_width() + 10
        pygame.draw.rect(surf, (28, 28, 42), (chip_x, chip_y, chip_w, 16),
                         border_radius=4)
        pygame.draw.rect(surf, status_color, (chip_x, chip_y, chip_w, 16),
                         width=1, border_radius=4)
        surf.blit(chip_surf, (chip_x + 5, chip_y + 1))
        # tokens (small)
        tok_str = f"{lane.token_count} tok"
        surf.blit(self.font_hud.render(tok_str, True, TEXT_DIM),
                  (card_x + 14, card_y + 50))

        # ---- TRACK BED ----
        track_y = mid + lane_h // 8
        # base line
        pygame.draw.line(surf, GRID, (TRACK_LEFT, track_y), (TRACK_RIGHT, track_y), 2)
        # animated dashes
        dash_len = 14
        gap = 14
        period = dash_len + gap
        x0 = TRACK_LEFT + int(self.dash_offset) - period
        while x0 < TRACK_RIGHT:
            seg_left = max(TRACK_LEFT, x0)
            seg_right = min(TRACK_RIGHT, x0 + dash_len)
            if seg_right > seg_left:
                pygame.draw.line(surf, lane.color, (seg_left, track_y),
                                 (seg_right, track_y), 2)
            x0 += period

        # progress bar above track
        fill_w = int(lane.progress * TRACK_LEN)
        bar_h = 5
        bar_y = track_y - 18
        pygame.draw.rect(surf, (28, 28, 42),
                         (TRACK_LEFT, bar_y, TRACK_LEN, bar_h), border_radius=2)
        if fill_w > 0:
            bar_color = HOT_PINK if is_lead else lane.color
            pygame.draw.rect(surf, bar_color,
                             (TRACK_LEFT, bar_y, fill_w, bar_h), border_radius=2)

        # start vertical line
        pygame.draw.line(surf, TEXT_DIM,
                         (TRACK_LEFT - 4, card_y + 12),
                         (TRACK_LEFT - 4, card_y + card_h - 12), 1)
        # finish strip — checker
        for ny in range(card_y + 12, card_y + card_h - 12, 8):
            for k in range(2):
                col = TEXT if (((ny // 8) + k) % 2 == 0) else BLACK
                pygame.draw.rect(surf, col,
                                 (TRACK_RIGHT + 2 + k * 8, ny, 8, 8))

        # ---- SPRITE ----
        sx = TRACK_LEFT + int(lane.progress * TRACK_LEN)
        sy = mid
        if lane.error:
            err = self.font_label.render("DNF", True, HOT_PINK)
            surf.blit(err, (sx - 22, mid - 10))
        else:
            self._draw_sprite(surf, sx, sy, lane, idx)

        # ---- RIGHT GUTTER (sparkline + tps) ----
        gutter_left = TRACK_RIGHT + 24 + 18
        gutter_right = SCREEN_W - 22
        # sparkline 64x18 at top
        spark_w = 64
        spark_h = 16
        spark_x = gutter_right - spark_w
        spark_y = card_y + 14
        self._draw_sparkline(surf, spark_x, spark_y, spark_w, spark_h, lane, is_lead)
        # tabular tps numerics, big
        tps_color = HOT_PINK if is_lead else (AMBER if not lane.thinking else TEXT_DIM)
        tps_text = f"{lane.instant_tps:5.1f}"
        tps_surf = self.font_num_xl.render(tps_text, True, tps_color)
        tx = gutter_right - tps_surf.get_width()
        ty = card_y + card_h - tps_surf.get_height() - 6
        surf.blit(tps_surf, (tx, ty))
        unit = self.font_hud.render("tok/s", True, TEXT_DIM)
        surf.blit(unit, (gutter_right - unit.get_width(), ty + tps_surf.get_height() - 18))

    def _status_for(self, lane: LaneState, is_lead: bool) -> tuple[str, tuple[int, int, int]]:
        if lane.error:
            return ("DNF", HOT_PINK)
        if lane.finished:
            return ("DONE", AMBER)
        if lane.thinking:
            return ("THINK", CYAN)
        if is_lead:
            return ("LEAD", HOT_PINK)
        return ("RUN", lane.color)

    def _draw_sprite(self, surf: pygame.Surface, x: int, y: int,
                     lane: LaneState, idx: int) -> None:
        # token-tick flash: 1-frame cyan outline
        flash = time.time() < lane.token_flash_until
        # speed lines (if running and not thinking)
        if not lane.thinking and not lane.finished:
            for i in range(3):
                phase = (self.frame + i * 7) % 18
                lx = x - 36 - phase * 4
                a = max(0, 130 - phase * 9)
                line = pygame.Surface((26, 2), pygame.SRCALPHA)
                line.fill((*lane.color, a))
                surf.blit(line, (lx, y - 8 + i * 6))

        sprite = render_sprite(lane.sprite_name, lane.color,
                               frame=lane.sprite_frame, blink=lane.blink)
        rect = sprite.get_rect(center=(x, y))
        surf.blit(sprite, rect)
        if flash:
            outline = pygame.Surface(sprite.get_size(), pygame.SRCALPHA)
            pygame.draw.rect(outline, (*CYAN, 200), outline.get_rect(), 2)
            surf.blit(outline, rect)

        # Thinking bubble (above sprite, contained)
        if lane.thinking:
            bx, by = x + 24, y - 28
            pygame.draw.circle(surf, TEXT, (bx, by), 12, 1)
            pygame.draw.circle(surf, TEXT, (bx - 12, by + 10), 3, 1)
            pygame.draw.circle(surf, TEXT, (bx - 18, by + 16), 2, 1)
            qm = self.font_label.render("?", True, TEXT)
            surf.blit(qm, (bx - 4, by - 9))

    def _draw_sparkline(self, surf: pygame.Surface, x: int, y: int,
                        w: int, h: int, lane: LaneState, is_lead: bool) -> None:
        # frame
        pygame.draw.rect(surf, (28, 28, 42), (x, y, w, h), border_radius=3)
        if not lane.spark:
            return
        vals = list(lane.spark)
        m = max(vals) or 1.0
        col = HOT_PINK if is_lead else CYAN
        n = len(vals)
        if n < 2:
            pygame.draw.line(surf, col, (x + 1, y + h - 2), (x + w - 2, y + h - 2), 1)
            return
        step = (w - 4) / (n - 1)
        pts = [(x + 2 + int(i * step),
                y + h - 2 - int((v / m) * (h - 4)))
               for i, v in enumerate(vals)]
        pygame.draw.lines(surf, col, False, pts, 2)

    # -- bottom HUD ------------------------------------------------------
    def _draw_hud(self, surf: pygame.Surface) -> None:
        py = SCREEN_H - PANEL_H
        # top divider
        pygame.draw.line(surf, HOT_PINK, (0, py), (SCREEN_W, py), 1)
        pygame.draw.rect(surf, BG_PANEL, (0, py + 1, SCREEN_W, PANEL_H - 1))

        # 3 columns
        col_w = (SCREEN_W - 32 - 32) // 3
        col_h = PANEL_H - 28
        col_y = py + 14

        # column 1 — leaderboard
        x1 = 16
        self._hud_column_header(surf, x1, col_y, "LEADERBOARD")
        order = sorted(range(len(self.lanes)),
                       key=lambda i: (-self.lanes[i].progress, self.lanes[i].spec.id))
        for rank, i in enumerate(order):
            row_y = col_y + 24 + rank * 28
            lane = self.lanes[i]
            # position chip
            chip = self.font_hud_b.render(f"{rank + 1}", True, BG_DEEP)
            chip_color = (HOT_PINK if rank == 0 else
                          (CYAN if rank == 1 else (AMBER if rank == 2 else TEXT_DIM)))
            pygame.draw.rect(surf, chip_color, (x1, row_y, 22, 20), border_radius=4)
            cx = x1 + 11 - chip.get_width() // 2
            cy = row_y + 10 - chip.get_height() // 2
            surf.blit(chip, (cx, cy))
            # label
            label = (lane.spec.label or lane.spec.id)[:20]
            lab = self.font_hud_b.render(label, True, lane.color)
            surf.blit(lab, (x1 + 30, row_y + 2))
            # tps
            tps = self.font_hud.render(f"{lane.instant_tps:5.1f} tok/s", True, TEXT_DIM)
            surf.blit(tps, (x1 + 30, row_y + 16))

        # column 2 — sparklines
        x2 = 32 + col_w
        self._hud_column_header(surf, x2, col_y, "TELEMETRY")
        # avg tps
        avg_tps = sum(l.instant_tps for l in self.lanes) / max(1, len(self.lanes))
        # gap to leader (token count)
        if len(self.lanes) >= 2:
            sorted_by_tok = sorted(self.lanes, key=lambda l: -l.token_count)
            gap = sorted_by_tok[0].token_count - sorted_by_tok[1].token_count
        else:
            gap = 0
        total_tok = sum(l.token_count for l in self.lanes)
        # mini gauges
        gauge_y = col_y + 28
        gauges = [
            ("avg tok/s", f"{avg_tps:5.1f}", CYAN, avg_tps, 60.0),
            ("gap (tok)", f"{gap}", AMBER, gap, 200.0),
            ("total tok", f"{total_tok}", HOT_PINK, total_tok, max(1, self.target_tokens * len(self.lanes))),
        ]
        for j, (name, val, color, cur, mx) in enumerate(gauges):
            row_y = gauge_y + j * 38
            n_lab = self.font_hud.render(name.upper(), True, TEXT_DIM)
            surf.blit(n_lab, (x2, row_y))
            v_lab = self.font_num_big.render(val, True, color)
            surf.blit(v_lab, (x2 + 110, row_y - 4))
            # mini bar
            bar_w = col_w - 200
            pygame.draw.rect(surf, (28, 28, 42),
                             (x2 + 0, row_y + 22, bar_w, 4), border_radius=2)
            pct = max(0.0, min(1.0, cur / max(0.001, mx)))
            pygame.draw.rect(surf, color,
                             (x2 + 0, row_y + 22, int(bar_w * pct), 4),
                             border_radius=2)

        # column 3 — log
        x3 = 32 + 2 * col_w + 16
        self._hud_column_header(surf, x3, col_y, "LOG")
        recent = list(self.terminal_lines)[-9:]
        line_h = 17
        for j, (t_at, msg, color) in enumerate(recent):
            ts = self.font_hud.render(f"{t_at - self.start_time:5.2f}s", True, TEXT_DIM)
            surf.blit(ts, (x3, col_y + 24 + j * line_h))
            content = self.font_hud.render(msg[:80], True, color)
            surf.blit(content, (x3 + 56, col_y + 24 + j * line_h))
        # blinking caret
        if (self.frame // 30) % 2 == 0:
            cy = col_y + 24 + len(recent) * line_h
            pygame.draw.rect(surf, CYAN, (x3 + 56, cy + 2, 7, 12))

    def _hud_column_header(self, surf: pygame.Surface, x: int, y: int, text: str) -> None:
        head = self.font_hud_b.render(text, True, TEXT)
        surf.blit(head, (x, y))
        underline_w = 80
        pygame.draw.rect(surf, HOT_PINK, (x, y + 16, underline_w, 1))

    # -- winner ---------------------------------------------------------
    def _draw_winner(self, surf: pygame.Surface) -> None:
        # 1ST chip slides in above winner
        if self.winner_idx is None:
            return
        elapsed_since = time.time() - (self.race_over_at or time.time())
        slide_t = max(0.0, min(1.0, elapsed_since / 0.6))
        eased = 1 - (1 - slide_t) ** 3
        cy = self._lane_y(self.winner_idx) - int(60 * (1 - eased)) - 60
        cx = TRACK_RIGHT - 30
        chip_w = 80
        chip_h = 56
        pygame.draw.rect(surf, HOT_PINK, (cx, cy, chip_w, chip_h),
                         border_radius=10)
        pygame.draw.rect(surf, BG_DEEP, (cx + 3, cy + 3, chip_w - 6, chip_h - 6),
                         width=1, border_radius=8)
        chip_text = self.font_chip.render("1ST", True, BG_DEEP)
        surf.blit(chip_text,
                  (cx + (chip_w - chip_text.get_width()) // 2,
                   cy + (chip_h - chip_text.get_height()) // 2))

        # Banner
        if self.race_over_at is None:
            return
        # Pulsing bar + winner text, only after the chip arrives
        if elapsed_since < 0.4:
            return
        msg = "WINNER  ·  " + (self.winner_id or "")
        text = self.font_winner.render(msg, True, HOT_PINK)
        w = text.get_width()
        h = text.get_height()
        x = (SCREEN_W - w) // 2
        y = (SCREEN_H - h) // 2 - 80
        backdrop = pygame.Surface((w + 80, h + 32), pygame.SRCALPHA)
        backdrop.fill((10, 6, 22, 230))
        surf.blit(backdrop, (x - 40, y - 16))
        ring = pygame.Rect(x - 40, y - 16, w + 80, h + 32)
        pygame.draw.rect(surf, HOT_PINK, ring, width=2, border_radius=14)
        surf.blit(text, (x, y))
