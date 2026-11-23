from __future__ import annotations

import random
import shutil
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml
from PIL import Image, ImageDraw, ImageFont

from .assets import AssetStore
from .config import Config
from .context import Context
from .geometry import Rect
from .image import save_image
from .logging_utils import setup_logging
from .tasks.base import TaskResult
from .tasks.raid import RaidTask
from .vision import Vision

WIDTH = 1920
HEIGHT = 1080

HOME_ATTACK = Rect(1630, 815, 220, 230)
WALL_SEGMENTS = [Rect(240 + index * 140, 760, 120, 90) for index in range(4)]
WALL_PANEL = Rect(160, 680, 820, 330)
WALL_UPGRADE = Rect(560, 860, 330, 100)
WALL_CLOSE = Rect(900, 700, 60, 60)
FIND_MATCH = Rect(660, 620, 600, 130)
SCOUT_NEXT = Rect(60, 930, 300, 110)
SCOUT_ATTACK = Rect(1490, 930, 370, 110)
BATTLE_END = Rect(1540, 28, 340, 84)
RETURN_HOME = Rect(740, 740, 440, 110)
OK_BUTTON = Rect(860, 620, 200, 80)

FONT_CANDIDATES = (
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


@lru_cache(maxsize=32)
def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in FONT_CANDIDATES:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size=size)


def _text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    size: int,
    fill: tuple[int, int, int],
    anchor: str = "mm",
) -> None:
    draw.text(xy, text, font=_font(size), fill=fill, anchor=anchor)


def _button(
    draw: ImageDraw.ImageDraw,
    rect: Rect,
    label: str,
    fill: tuple[int, int, int],
    size: int = 52,
    outline: tuple[int, int, int] | None = None,
) -> None:
    draw.rounded_rectangle(
        [rect.x, rect.y, rect.right, rect.bottom],
        radius=18,
        fill=fill,
        outline=outline,
        width=3 if outline else 1,
    )
    _text(draw, rect.center, label, size, (255, 255, 255))


def _background() -> Image.Image:
    top = np.array([46, 92, 62], dtype=np.float32)
    bottom = np.array([22, 54, 40], dtype=np.float32)
    rows = np.linspace(0.0, 1.0, HEIGHT, dtype=np.float32)[:, None, None]
    grid = (top[None, None, :] * (1.0 - rows) + bottom[None, None, :] * rows)
    image = np.repeat(grid, WIDTH, axis=1).astype(np.uint8)
    for x in range(0, WIDTH, 96):
        image[:, x : x + 2] = np.minimum(image[:, x : x + 2] + 8, 255)
    for y in range(120, HEIGHT, 96):
        image[y : y + 2, :] = np.minimum(image[y : y + 2, :] + 8, 255)
    return Image.fromarray(image[:, :, ::-1])


def _base_scene(gold: int, elixir: int, dark: int, title: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = _background()
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, WIDTH, 96], fill=(18, 26, 38))
    draw.ellipse([28, 22, 78, 72], fill=(240, 194, 64))
    _text(draw, (100, 48), f"{gold:,}", 38, (255, 230, 160), anchor="lm")
    draw.ellipse([300, 22, 350, 72], fill=(190, 90, 220))
    _text(draw, (372, 48), f"{elixir:,}", 38, (235, 190, 255), anchor="lm")
    draw.ellipse([580, 22, 630, 72], fill=(60, 70, 90))
    _text(draw, (652, 48), f"{dark:,}", 38, (190, 210, 235), anchor="lm")
    _text(draw, (WIDTH - 40, 48), title, 40, (220, 235, 245), anchor="rm")
    return image, draw


def _draw_village(draw: ImageDraw.ImageDraw, wall_level: int) -> None:
    draw.rounded_rectangle([780, 380, 1140, 650], radius=20, fill=(120, 96, 70))
    draw.rounded_rectangle([820, 420, 1100, 610], radius=12, fill=(168, 132, 92))
    _text(draw, (960, 360), "TOWN HALL", 34, (235, 225, 200))
    for segment in WALL_SEGMENTS:
        draw.rounded_rectangle(
            [segment.x, segment.y, segment.right, segment.bottom],
            radius=8,
            fill=(150, 116, 78),
            outline=(96, 70, 44),
            width=4,
        )
        for offset in (30, 60, 90):
            draw.line(
                [segment.x + offset, segment.y, segment.x + offset, segment.bottom],
                fill=(110, 82, 52),
                width=3,
            )
        _text(draw, segment.center, str(wall_level), 28, (255, 240, 210))
    draw.ellipse([1500, 780, 1660, 860], fill=(34, 44, 58))
    _text(draw, (1580, 820), "BUILDER", 22, (180, 200, 220))


def _draw_attack_button(draw: ImageDraw.ImageDraw) -> None:
    center = (HOME_ATTACK.x + HOME_ATTACK.width // 2, HOME_ATTACK.y + 88)
    draw.ellipse(
        [center[0] - 84, center[1] - 84, center[0] + 84, center[1] + 84],
        fill=(40, 96, 178),
        outline=(220, 235, 255),
        width=5,
    )
    draw.line([center[0] - 42, center[1] - 42, center[0] + 42, center[1] + 42], fill=(255, 255, 255), width=12)
    draw.line([center[0] - 42, center[1] + 42, center[0] + 42, center[1] - 42], fill=(255, 255, 255), width=12)
    _text(draw, (center[0], HOME_ATTACK.bottom - 26), "ATTACK", 30, (240, 248, 255))


class MockGame:
    def __init__(self) -> None:
        self.state = "home"
        self.gold = 60_000
        self.elixir = 40_000
        self.dark = 2_000
        self.wall_level = 5
        self.wall_cost = 55_000
        self.upgrades = 0
        self.raids = 0
        self.next_count = 0
        self.taps: list[tuple[str, int, int]] = []
        self.seen_states: list[str] = []

    def frame(self) -> np.ndarray:
        if self.state not in self.seen_states:
            self.seen_states.append(self.state)
        image, draw = _base_scene(self.gold, self.elixir, self.dark, "MOCK VILLAGE")
        if self.state == "home":
            _draw_village(draw, self.wall_level)
            _draw_attack_button(draw)
        elif self.state == "attack_menu":
            _draw_village(draw, self.wall_level)
            overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 170))
            image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle([520, 260, 1400, 820], radius=28, fill=(30, 42, 58))
            _text(draw, (960, 340), "ATTACK", 64, (235, 242, 250))
            _button(draw, FIND_MATCH, "FIND A MATCH", (58, 160, 92))
            _text(draw, (960, 560), "MULTIPLAYER", 34, (150, 170, 190))
        elif self.state == "scouting":
            draw.rectangle([0, 96, WIDTH, HEIGHT], fill=(88, 112, 74))
            draw.rounded_rectangle([780, 360, 1160, 670], radius=20, fill=(132, 104, 74))
            draw.rounded_rectangle([840, 400, 1100, 600], radius=14, fill=(190, 150, 104))
            draw.rounded_rectangle([40, 130, 940, 250], radius=16, fill=(20, 30, 44))
            _text(draw, (70, 190), "LOOT", 32, (210, 225, 240), anchor="lm")
            draw.ellipse([230, 158, 280, 208], fill=(240, 194, 64))
            _text(draw, (300, 190), f"{self.gold + 420000:,}", 34, (255, 230, 160), anchor="lm")
            draw.ellipse([600, 158, 650, 208], fill=(190, 90, 220))
            _text(draw, (670, 190), f"{self.elixir + 380000:,}", 34, (235, 190, 255), anchor="lm")
            _button(draw, SCOUT_NEXT, "NEXT", (70, 90, 120))
            _button(draw, SCOUT_ATTACK, "ATTACK!", (190, 62, 62))
            _text(draw, (960, 1015), f"SKIP {self.next_count}", 28, (220, 230, 240))
        elif self.state == "battle":
            draw.rectangle([0, 96, WIDTH, HEIGHT], fill=(96, 120, 80))
            draw.rounded_rectangle([700, 300, 1240, 720], radius=24, fill=(140, 110, 78))
            for index in range(3):
                center_x = 150 + index * 130
                draw.ellipse(
                    [center_x - 54, 926, center_x + 54, 1034],
                    fill=(44, 58, 78),
                    outline=(220, 230, 245),
                    width=4,
                )
                _text(draw, (center_x, 980), f"T{index + 1}", 30, (235, 240, 250))
            _button(draw, BATTLE_END, "END BATTLE", (180, 48, 48), size=32)
            _text(draw, (960, 150), "BATTLE", 54, (245, 250, 255))
        elif self.state == "results":
            overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 190))
            image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle([560, 260, 1360, 900], radius=30, fill=(26, 36, 52))
            _text(draw, (960, 370), "VICTORY", 84, (255, 214, 92))
            for index in range(3):
                draw.ellipse([860 + index * 80, 430, 920 + index * 80, 490], fill=(255, 214, 92))
            _text(draw, (960, 560), f"LOOT  +{420000:,} GOLD", 36, (250, 230, 180))
            _text(draw, (960, 620), f"      +{380000:,} ELIXIR", 36, (240, 190, 255))
            _button(draw, RETURN_HOME, "RETURN HOME", (58, 160, 92))
        elif self.state == "wall_panel":
            _draw_village(draw, self.wall_level)
            draw.rounded_rectangle(
                [WALL_PANEL.x, WALL_PANEL.y, WALL_PANEL.right, WALL_PANEL.bottom],
                radius=24,
                fill=(24, 34, 48),
                outline=(90, 110, 135),
                width=4,
            )
            _text(draw, (WALL_PANEL.x + 40, WALL_PANEL.y + 48), "WALL", 44, (235, 242, 250), anchor="lm")
            _text(draw, (WALL_PANEL.x + 40, WALL_PANEL.y + 118), f"LEVEL {self.wall_level}", 34, (150, 175, 200), anchor="lm")
            _text(draw, (WALL_PANEL.x + 40, WALL_PANEL.y + 188), f"COST {self.wall_cost:,}", 34, (245, 205, 120), anchor="lm")
            affordable = self.gold >= self.wall_cost
            _button(
                draw,
                WALL_UPGRADE,
                "UPGRADE" if affordable else "NEED LOOT",
                (58, 160, 92) if affordable else (92, 98, 108),
            )
            draw.line([WALL_CLOSE.x + 12, WALL_CLOSE.y + 12, WALL_CLOSE.right - 12, WALL_CLOSE.bottom - 12], fill=(220, 230, 240), width=6)
            draw.line([WALL_CLOSE.x + 12, WALL_CLOSE.bottom - 12, WALL_CLOSE.right - 12, WALL_CLOSE.y + 12], fill=(220, 230, 240), width=6)
        else:
            _text(draw, (960, 540), self.state.upper(), 70, (255, 255, 255))
        return np.array(image)[:, :, ::-1].copy()

    def tap(self, x: int, y: int) -> None:
        self.taps.append((self.state, x, y))
        if self.state == "home":
            if HOME_ATTACK.contains(x, y):
                self.state = "attack_menu"
                return
            if any(segment.contains(x, y) for segment in WALL_SEGMENTS):
                self.state = "wall_panel"
                return
        elif self.state == "attack_menu":
            if FIND_MATCH.contains(x, y):
                self.state = "scouting"
                self.next_count = 0
                return
        elif self.state == "scouting":
            if SCOUT_NEXT.contains(x, y):
                self.next_count += 1
                return
            if SCOUT_ATTACK.contains(x, y):
                self.state = "battle"
                return
        elif self.state == "battle":
            if BATTLE_END.contains(x, y):
                self.state = "results"
                return
        elif self.state == "results":
            if RETURN_HOME.contains(x, y):
                self.gold += 420_000
                self.elixir += 380_000
                self.dark += 2_000
                self.raids += 1
                self.state = "home"
                return
        elif self.state == "wall_panel":
            if WALL_UPGRADE.contains(x, y):
                if self.gold >= self.wall_cost:
                    self.gold -= self.wall_cost
                    self.wall_level += 1
                    self.upgrades += 1
                    self.wall_cost = int(self.wall_cost * 1.12)
                return
            if WALL_CLOSE.contains(x, y):
                self.state = "home"
                return
            if any(segment.contains(x, y) for segment in WALL_SEGMENTS):
                return

    def back(self) -> None:
        self.taps.append((self.state, -1, -1))
        if self.state in ("attack_menu", "scouting", "wall_panel", "battle", "results"):
            self.state = "home"


class MockCapture:
    description = "mock"

    def __init__(self, game: MockGame) -> None:
        self.game = game

    def grab(self) -> np.ndarray:
        return self.game.frame()

    def close(self) -> None:
        return None


class MockController:
    def __init__(self, game: MockGame) -> None:
        self.game = game

    def tap(self, x: int, y: int) -> None:
        self.game.tap(x, y)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        return None

    def key(self, code: int | str) -> None:
        if str(code) == "4":
            self.game.back()


@dataclass
class DemoResult:
    result: TaskResult
    game: MockGame
    root: Path
    asset_root: Path


def _crop(frame: np.ndarray, rect: Rect) -> np.ndarray:
    return frame[rect.y : rect.bottom, rect.x : rect.right].copy()


def build_demo_assets(game: MockGame, root: Path) -> Path:
    template_root = root / "templates"
    template_root.mkdir(parents=True, exist_ok=True)
    game.state = "home"
    home = game.frame()
    game.state = "wall_panel"
    panel = game.frame()
    game.state = "attack_menu"
    attack = game.frame()
    game.state = "scouting"
    scouting = game.frame()
    game.state = "battle"
    battle = game.frame()
    game.state = "results"
    results = game.frame()
    crops = {
        "home_attack": _crop(home, HOME_ATTACK),
        "wall_panel": _crop(panel, Rect(190, 700, 220, 60)),
        "wall_upgrade": _crop(panel, WALL_UPGRADE),
        "attack_find_match": _crop(attack, FIND_MATCH),
        "scout_next": _crop(scouting, SCOUT_NEXT),
        "scout_attack": _crop(scouting, SCOUT_ATTACK),
        "battle_end": _crop(battle, BATTLE_END),
        "battle_return_home": _crop(results, RETURN_HOME),
    }
    for name, image in crops.items():
        save_image(template_root / f"{name}.png", image)
    manifest = root / "assets.yaml"
    manifest.write_text(
        "\n".join(
            [
                "version: 1",
                "template_root: templates",
                "defaults:",
                "  threshold: 0.86",
                "  grayscale: true",
                "  method: ccoeff_normed",
                "assets:",
                "  home_attack:",
                "    file: home_attack.png",
                "  wall_panel:",
                "    file: wall_panel.png",
                "  wall_upgrade:",
                "    file: wall_upgrade.png",
                "    grayscale: false",
                "    threshold: 0.8",
                "  wall_upgrade_available:",
                "    type: color",
                "    space: hsv",
                "    lower: [35, 90, 80]",
                "    upper: [85, 255, 255]",
                "    min_ratio: 0.25",
                "  attack_find_match:",
                "    file: attack_find_match.png",
                "  scout_next:",
                "    file: scout_next.png",
                "  scout_attack:",
                "    file: scout_attack.png",
                "  battle_end:",
                "    file: battle_end.png",
                "  battle_return_home:",
                "    file: battle_return_home.png",
            ]
        ),
        encoding="utf-8",
    )
    game.state = "home"
    return manifest


def demo_config(manifest: Path, root: Path, cycles: int) -> Config:
    data = {
        "device": {"adb_path": "adb", "serial": None},
        "capture": {"backend": "static", "folder": None, "loop": True},
        "control": {"backend": "none", "tap_jitter": 0, "delay_ms": [0, 0]},
        "vision": {
            "assets": str(manifest),
            "canonical_size": [WIDTH, HEIGHT],
            "ocr": {"backend": "none", "lang": "eng", "psm": 6, "tesseract_cmd": None},
        },
        "runtime": {
            "log_dir": str(root / "logs"),
            "screenshot_dir": str(root / "screenshots"),
            "debug": False,
            "dry_run": False,
        },
        "task": {
            "name": "raid",
            "raid": {
                "max_cycles": cycles,
                "max_runtime_min": 5,
                "max_errors": 2,
                "match_timeout": 5,
                "battle_start_timeout": 5,
                "battle_timeout": 10,
                "result_timeout": 5,
                "end_battle_after_deploy": True,
                "loot_check": False,
                "max_next": 0,
                "min_gold": 0,
                "min_elixir": 0,
                "min_dark": 0,
                "auto_battle": False,
                "army": {
                    "troop_slots": [[150, 980], [280, 980]],
                    "deploy_points": [[760, 480], [960, 520], [1160, 560]],
                    "waves": 1,
                    "tap_delay_ms": 20,
                },
            },
        },
    }
    return Config.from_dict(data)


def run_demo(root: str | Path = "runtime/demo", cycles: int = 3) -> DemoResult:
    root_path = Path(root).resolve()
    if root_path.exists():
        if root_path.name != "demo":
            raise ValueError("demo 输出目录必须以 demo 结尾，避免误删其他目录")
        shutil.rmtree(root_path)
    root_path.mkdir(parents=True, exist_ok=True)
    game = MockGame()
    manifest = build_demo_assets(game, root_path)
    config = demo_config(manifest, root_path, cycles)
    (root_path / "config.yaml").write_text(
        yaml.safe_dump(config.data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    logger = setup_logging("INFO", root_path / "logs")
    assets = AssetStore(manifest)
    vision = Vision(assets)
    context = Context(
        config=config,
        vision=vision,
        capture=MockCapture(game),
        controller=MockController(game),
        logger=logger,
        canonical=(WIDTH, HEIGHT),
        dry_run=False,
        jitter=0,
        tap_delay=(0.0, 0.0),
        rng=random.Random(7),
    )
    screens = root_path / "screens"
    screens.mkdir(parents=True, exist_ok=True)
    for state in ("home", "wall_panel", "attack_menu", "scouting", "battle", "results"):
        game.state = state
        save_image(screens / f"{state}.png", game.frame())
    game.state = "home"
    result = RaidTask().run(context)
    context.save_screenshot("final-home")
    return DemoResult(result=result, game=game, root=root_path, asset_root=manifest.parent)
