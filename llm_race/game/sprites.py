"""24x24 hand-drawn pixel-art runner sprites with 2-frame run cycles.

Five variants — runner, rocket, car, dragon, bot — each with a frame-A and
frame-B for the run animation. Color is parameterized so each lane gets a
unique tint while reusing the same shape data. Three colors max per sprite
(base, light, dark) following the Pico-8 discipline.
"""
from __future__ import annotations

from typing import Callable

import pygame

SPRITE_RES = 24      # 24x24 native pixel art
DISPLAY_SIZE = 60    # scaled to 60px on screen


def _lighten(c: tuple[int, int, int], k: float = 0.35) -> tuple[int, int, int]:
    return tuple(min(255, int(v + (255 - v) * k)) for v in c)  # type: ignore[return-value]


def _darken(c: tuple[int, int, int], k: float = 0.45) -> tuple[int, int, int]:
    return tuple(max(0, int(v * (1 - k))) for v in c)  # type: ignore[return-value]


def _runner(surf: pygame.Surface, color, frame: int, blink: bool) -> None:
    base = color
    light = _lighten(color)
    dark = _darken(color)
    eye = (10, 8, 22)

    # head 8x8
    pygame.draw.rect(surf, base, (8, 3, 8, 8))
    pygame.draw.rect(surf, light, (8, 3, 8, 2))
    # eyes
    if blink:
        pygame.draw.rect(surf, eye, (10, 7, 2, 1))
        pygame.draw.rect(surf, eye, (13, 7, 2, 1))
    else:
        pygame.draw.rect(surf, eye, (10, 6, 1, 2))
        pygame.draw.rect(surf, eye, (13, 6, 1, 2))
    # body 10x6
    pygame.draw.rect(surf, dark, (7, 11, 10, 6))
    pygame.draw.rect(surf, base, (7, 11, 10, 1))
    # arms (frame-dependent — swing alternation)
    if frame == 0:
        pygame.draw.rect(surf, base, (5, 12, 2, 4))
        pygame.draw.rect(surf, base, (17, 12, 2, 4))
    else:
        pygame.draw.rect(surf, base, (4, 13, 3, 3))
        pygame.draw.rect(surf, base, (17, 13, 3, 3))
    # legs (frame-dependent)
    if frame == 0:
        pygame.draw.rect(surf, dark, (8, 17, 3, 6))
        pygame.draw.rect(surf, dark, (13, 17, 3, 6))
    else:
        pygame.draw.rect(surf, dark, (6, 17, 3, 4))
        pygame.draw.rect(surf, dark, (15, 17, 3, 4))


def _rocket(surf: pygame.Surface, color, frame: int, blink: bool) -> None:
    base = color
    light = _lighten(color)
    dark = _darken(color)
    flame_a = (255, 190, 11)
    flame_b = (255, 70, 50)
    eye = (10, 8, 22)

    # nose cone
    pygame.draw.polygon(surf, light, [(12, 1), (8, 7), (16, 7)])
    # body 8x10
    pygame.draw.rect(surf, base, (8, 7, 8, 10))
    # window
    pygame.draw.rect(surf, eye, (11, 9, 3, 3))
    if not blink:
        pygame.draw.rect(surf, light, (11, 9, 1, 1))
    # fins
    pygame.draw.polygon(surf, dark, [(8, 13), (4, 17), (8, 17)])
    pygame.draw.polygon(surf, dark, [(16, 13), (20, 17), (16, 17)])
    # flame, frame-dependent
    if frame == 0:
        pygame.draw.polygon(surf, flame_a, [(10, 17), (14, 17), (12, 22)])
        pygame.draw.polygon(surf, flame_b, [(11, 17), (13, 17), (12, 20)])
    else:
        pygame.draw.polygon(surf, flame_a, [(10, 17), (14, 17), (12, 23)])
        pygame.draw.polygon(surf, flame_b, [(11, 17), (13, 17), (12, 21)])


def _car(surf: pygame.Surface, color, frame: int, blink: bool) -> None:
    base = color
    light = _lighten(color)
    dark = _darken(color)
    eye = (10, 8, 22)
    glass = (210, 230, 255) if not blink else (160, 180, 220)

    # body main
    pygame.draw.rect(surf, base, (3, 11, 18, 7))
    # roof
    pygame.draw.rect(surf, dark, (7, 6, 11, 5))
    # window
    pygame.draw.rect(surf, glass, (8, 7, 9, 3))
    # headlight (right side, direction of travel)
    pygame.draw.rect(surf, (255, 240, 180), (20, 13, 1, 2))
    # detail line
    pygame.draw.rect(surf, light, (3, 11, 18, 1))
    # wheels — rotation indicated by spoke shift
    if frame == 0:
        pygame.draw.rect(surf, eye, (5, 17, 4, 4))
        pygame.draw.rect(surf, eye, (15, 17, 4, 4))
        pygame.draw.rect(surf, light, (6, 18, 2, 2))
        pygame.draw.rect(surf, light, (16, 18, 2, 2))
    else:
        pygame.draw.rect(surf, eye, (5, 17, 4, 4))
        pygame.draw.rect(surf, eye, (15, 17, 4, 4))
        pygame.draw.rect(surf, light, (6, 19, 2, 1))
        pygame.draw.rect(surf, light, (16, 19, 2, 1))


def _dragon(surf: pygame.Surface, color, frame: int, blink: bool) -> None:
    base = color
    light = _lighten(color)
    dark = _darken(color)
    eye = (10, 8, 22)

    # body
    pygame.draw.rect(surf, base, (4, 11, 14, 6))
    pygame.draw.rect(surf, light, (4, 11, 14, 1))
    # tail
    pygame.draw.rect(surf, dark, (1, 12, 3, 3))
    # head
    pygame.draw.rect(surf, base, (16, 8, 6, 6))
    # horn
    pygame.draw.rect(surf, light, (18, 6, 1, 2))
    # eye
    if blink:
        pygame.draw.rect(surf, eye, (19, 11, 2, 1))
    else:
        pygame.draw.rect(surf, eye, (19, 10, 2, 2))
    # mouth
    pygame.draw.rect(surf, dark, (20, 12, 2, 1))
    # wings — frame-dependent
    if frame == 0:
        pygame.draw.polygon(surf, light, [(7, 11), (4, 6), (10, 9)])
        pygame.draw.polygon(surf, dark, [(13, 11), (10, 6), (16, 9)])
    else:
        pygame.draw.polygon(surf, light, [(7, 11), (4, 4), (10, 8)])
        pygame.draw.polygon(surf, dark, [(13, 11), (10, 4), (16, 8)])
    # legs
    if frame == 0:
        pygame.draw.rect(surf, dark, (6, 17, 2, 4))
        pygame.draw.rect(surf, dark, (12, 17, 2, 4))
    else:
        pygame.draw.rect(surf, dark, (5, 17, 2, 3))
        pygame.draw.rect(surf, dark, (13, 17, 2, 3))


def _bot(surf: pygame.Surface, color, frame: int, blink: bool) -> None:
    base = color
    light = _lighten(color)
    dark = _darken(color)
    eye = (10, 8, 22)

    # antenna
    pygame.draw.rect(surf, light, (12, 0, 1, 3))
    pygame.draw.rect(surf, (255, 70, 110), (11, 0, 3, 2))
    # head
    pygame.draw.rect(surf, base, (6, 3, 12, 8))
    pygame.draw.rect(surf, light, (6, 3, 12, 1))
    # eyes (LED)
    if blink:
        pygame.draw.rect(surf, eye, (9, 6, 2, 1))
        pygame.draw.rect(surf, eye, (13, 6, 2, 1))
    else:
        pygame.draw.rect(surf, (0, 240, 255), (9, 6, 2, 2))
        pygame.draw.rect(surf, (0, 240, 255), (13, 6, 2, 2))
    # mouth
    pygame.draw.rect(surf, dark, (10, 9, 4, 1))
    # body
    pygame.draw.rect(surf, dark, (5, 11, 14, 7))
    pygame.draw.rect(surf, base, (8, 13, 8, 3))
    # arms
    if frame == 0:
        pygame.draw.rect(surf, base, (3, 12, 2, 5))
        pygame.draw.rect(surf, base, (19, 12, 2, 5))
    else:
        pygame.draw.rect(surf, base, (2, 13, 3, 3))
        pygame.draw.rect(surf, base, (19, 13, 3, 3))
    # legs
    if frame == 0:
        pygame.draw.rect(surf, dark, (7, 18, 3, 5))
        pygame.draw.rect(surf, dark, (14, 18, 3, 5))
    else:
        pygame.draw.rect(surf, dark, (5, 18, 3, 4))
        pygame.draw.rect(surf, dark, (16, 18, 3, 4))


SPRITE_FNS: dict[str, Callable] = {
    "runner": _runner,
    "rocket": _rocket,
    "car": _car,
    "dragon": _dragon,
    "bot": _bot,
}


def render_sprite(name: str, color: tuple[int, int, int],
                  frame: int = 0, blink: bool = False,
                  size: int = DISPLAY_SIZE) -> pygame.Surface:
    """Render a sprite at the requested display size with nearest-neighbour
    upscaling so the pixel-art stays crisp."""
    name = name if name in SPRITE_FNS else "runner"
    base = pygame.Surface((SPRITE_RES, SPRITE_RES), pygame.SRCALPHA)
    SPRITE_FNS[name](base, color, frame % 2, blink)
    return pygame.transform.scale(base, (size, size))


# Resolve a free-text sprite hint (from YAML) into a known sprite name.
EMOJI_TO_NAME = {
    "🚀": "rocket",
    "🏎️": "car",
    "🏎": "car",
    "🚗": "car",
    "🐎": "runner",  # horse → use runner; we render bipedal
    "🐇": "runner",
    "🦊": "runner",
    "🦄": "dragon",
    "🐢": "runner",
    "🦖": "dragon",
    "🤖": "bot",
}


def resolve_sprite_name(hint: str | None, fallback_index: int = 0) -> str:
    fallbacks = ["runner", "rocket", "car", "dragon", "bot"]
    if not hint:
        return fallbacks[fallback_index % len(fallbacks)]
    h = hint.strip()
    if h in SPRITE_FNS:
        return h
    if h in EMOJI_TO_NAME:
        return EMOJI_TO_NAME[h]
    return fallbacks[fallback_index % len(fallbacks)]
