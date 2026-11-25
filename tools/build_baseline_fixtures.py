from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bettercoc.baseline import sha256_bytes, sha256_file  # noqa: E402
from bettercoc.image import load_image  # noqa: E402

FIXTURE_DIR = ROOT / "tests" / "fixtures" / "baseline"
FRAME_DIR = FIXTURE_DIR / "frames"
WEBP_QUALITY = 80

FRAMES = [
    {
        "id": "home-a",
        "source": "home-now.png",
        "state": "home",
        "tags": ["home", "normal"],
        "notes": "主城全景，金币 1,697,542 / 圣水 5,164,589 / 暗黑 207,500",
        "labels": {
            "home_attack": "hit",
            "build_button": "hit",
            "game_stop": "miss",
            "auto_battle": "miss",
            "wall_more": "miss",
            "army_attack": "miss",
            "home_popup_close": "miss",
        },
    },
    {
        "id": "home-b",
        "source": "after-leaderboard.png",
        "state": "home",
        "tags": ["home", "normal"],
        "notes": "主城，金币 234,789 / 圣水 9,400,000",
        "labels": {
            "home_attack": "hit",
            "build_button": "hit",
            "game_stop": "miss",
            "auto_battle": "miss",
            "home_popup_close": "miss",
        },
    },
    {
        "id": "home-wall-selected",
        "source": "wall-test-01.png",
        "state": "home_wall_panel",
        "tags": ["home", "wall"],
        "notes": "主城选中城墙，单墙升级面板已打开",
        "labels": {
            "home_attack": "hit",
            "build_button": "hit",
            "game_stop": "miss",
            "wall_more": "miss",
        },
    },
    {
        "id": "attack-menu-a",
        "source": "live-attack-menu.png",
        "state": "attack_menu",
        "tags": ["attack_menu", "normal"],
        "notes": "联机模式，常规战搜索对手",
        "labels": {
            "attack_find_match": "hit",
            "home_attack": "miss",
            "build_button": "hit",
            "game_stop": "miss",
        },
    },
    {
        "id": "attack-menu-side-panel",
        "source": "attack-01.png",
        "state": "attack_menu_side_panel",
        "tags": ["attack_menu", "popup"],
        "notes": "联机模式，右侧战场寻宝卡片展开",
        "labels": {
            "attack_find_match": "hit",
            "home_attack": "miss",
            "build_button": "hit",
            "game_stop": "miss",
        },
    },
    {
        "id": "army-a",
        "source": "live-army.png",
        "state": "army",
        "tags": ["army", "popup"],
        "notes": "我的军队确认页，右下角进攻按钮",
        "labels": {
            "army_attack": "hit",
            "home_attack": "miss",
            "attack_find_match": "miss",
            "build_button": "hit",
        },
    },
    {
        "id": "scout-a",
        "source": "live-scout-now.png",
        "state": "scouting",
        "tags": ["scouting", "normal"],
        "notes": "侦察界面，战利品 330,146 / 301,471 / 4,293，开战倒计时 32 秒",
        "labels": {
            "scout_next": "hit",
            "scout_cancel": "hit",
            "auto_battle": "miss",
            "home_attack": "miss",
            "battle_return_home": "miss",
            "loot_gold": "hit",
            "loot_elixir": "hit",
            "loot_dark": "hit",
        },
    },
    {
        "id": "scout-auto-battle",
        "source": "screenshots/20261124-225751-001-ensure-home-failed.png",
        "state": "scouting_auto_battle",
        "tags": ["scouting", "normal", "auto_battle"],
        "notes": "侦察界面出现自动战斗按钮；auto_battle 最佳得分 0.58 低于阈值 0.8，按钮样式与已校准模板不同",
        "labels": {
            "scout_next": "hit",
            "scout_cancel": "hit",
            "auto_battle": "miss",
            "home_attack": "miss",
        },
    },
    {
        "id": "battle-a",
        "source": "scout-04.png",
        "state": "battle",
        "tags": ["battle", "normal"],
        "notes": "战斗中，左下角放弃按钮",
        "labels": {
            "scout_cancel": "hit",
            "scout_next": "miss",
            "auto_battle": "miss",
            "home_attack": "miss",
            "battle_return_home": "miss",
        },
    },
    {
        "id": "battle-b",
        "source": "auto-result.png",
        "state": "battle",
        "tags": ["battle", "normal"],
        "notes": "战斗中，左下角结束战斗按钮",
        "labels": {
            "scout_cancel": "hit",
            "scout_next": "miss",
            "auto_battle": "miss",
            "home_attack": "miss",
        },
    },
    {
        "id": "battle-confirm-dialog",
        "source": "screenshots/20261124-225809-002-ensure-home-failed.png",
        "state": "battle_confirm",
        "tags": ["battle", "popup"],
        "notes": "放弃？确认弹窗，取消/确定按钮",
        "labels": {
            "battle_confirm": "hit",
            "scout_cancel": "hit",
            "scout_next": "miss",
            "auto_battle": "miss",
        },
    },
    {
        "id": "wall-bulk-a",
        "source": "wall-more-01.png",
        "state": "wall_bulk",
        "tags": ["wall", "popup"],
        "notes": "批量选择城墙，添加 +1/+10、金币/圣水升级按钮",
        "labels": {
            "wall_add_1": "hit",
            "wall_add_10": "hit",
            "wall_cost_gold": "hit",
            "wall_cost_elixir": "hit",
            "side_panel_close": "hit",
            "wall_confirm": "miss",
        },
    },
    {
        "id": "wall-panel-a",
        "source": "wall-entry-01.png",
        "state": "build_panel",
        "tags": ["wall", "popup"],
        "notes": "建造侧边面板，右侧建筑列表首行为城墙",
        "labels": {
            "side_panel_close": "hit",
            "wall_entry": "hit",
            "wall_more": "miss",
        },
    },
    {
        "id": "wall-list-a",
        "source": "wall-upgraded-01.png",
        "state": "build_list",
        "tags": ["wall", "popup"],
        "notes": "建造面板建筑列表，城墙入口可见",
        "labels": {
            "wall_entry": "hit",
            "side_panel_close": "hit",
        },
    },
    {
        "id": "welcome-popup-a",
        "source": "relaunch-01.png",
        "state": "welcome_popup",
        "tags": ["home", "popup"],
        "notes": "欢迎回家弹窗；X 位置比其他样式更靠上，home_popup_close 的校验点落空",
        "labels": {
            "home_popup_close": "miss",
            "home_attack": "miss",
            "game_stop": "miss",
        },
    },
    {
        "id": "welcome-popup-b",
        "source": "restart1.png",
        "state": "welcome_popup",
        "tags": ["home", "popup"],
        "notes": "欢迎回家弹窗，红底 X 关闭按钮",
        "labels": {
            "home_popup_close": "hit",
            "home_attack": "miss",
            "game_stop": "miss",
        },
    },
    {
        "id": "welcome-popup-c",
        "source": "relaunch-02.png",
        "state": "welcome_popup_overlay",
        "tags": ["home", "popup"],
        "notes": "欢迎回家弹窗叠加版本公告横幅；X 位置与校准点不同，未命中",
        "labels": {
            "home_popup_close": "miss",
            "home_attack": "miss",
        },
    },
    {
        "id": "disconnected",
        "source": "screenshots/20261124-093042-001-game-stopped.png",
        "state": "disconnect_dialog",
        "tags": ["dialog", "disconnect"],
        "notes": "还在吗？断线弹窗，重新载入游戏链接",
        "labels": {
            "game_stop": "hit",
            "home_attack": "miss",
            "home_popup_close": "miss",
            "wall_gold_button": "known_defect",
        },
    },
    {
        "id": "home-a-scale-1280x720",
        "source": "home-now.png",
        "state": "home",
        "tags": ["home", "scaled"],
        "transforms": [{"kind": "scale", "width": 1280, "height": 720}],
        "notes": "1280x720 缩放，验证归一化与 Viewport",
        "labels": {
            "home_attack": "hit",
            "build_button": "hit",
            "game_stop": "miss",
            "auto_battle": "miss",
        },
    },
    {
        "id": "home-a-scale-2560x1440",
        "source": "home-now.png",
        "state": "home",
        "tags": ["home", "scaled"],
        "transforms": [{"kind": "scale", "width": 2560, "height": 1440}],
        "notes": "2560x1440 放大，验证设备坐标换算",
        "labels": {
            "home_attack": "hit",
            "build_button": "hit",
            "game_stop": "miss",
        },
    },
    {
        "id": "home-a-crop-topleft",
        "source": "home-now.png",
        "state": "home",
        "tags": ["home", "cropped"],
        "transforms": [{"kind": "crop", "x": 0, "y": 0, "width": 1600, "height": 900}],
        "notes": "裁掉右下角，建造按钮不在画面内，战斗按钮下半部与校验区同时被裁掉",
        "labels": {
            "home_attack": "miss",
            "build_button": "hit",
        },
    },
    {
        "id": "home-a-crop-center",
        "source": "home-now.png",
        "state": "home",
        "tags": ["home", "cropped"],
        "transforms": [{"kind": "crop", "x": 160, "y": 90, "width": 1600, "height": 900}],
        "notes": "居中裁切，左下角战斗按钮被裁掉",
        "labels": {
            "home_attack": "miss",
            "build_button": "hit",
        },
    },
    {
        "id": "home-a-blur",
        "source": "home-now.png",
        "state": "home",
        "tags": ["home", "blurred"],
        "transforms": [{"kind": "blur", "sigma": 2.0}],
        "notes": "高斯模糊 sigma=2.0",
        "labels": {
            "home_attack": "hit",
            "build_button": "hit",
            "game_stop": "miss",
        },
    },
    {
        "id": "home-a-dim",
        "source": "home-now.png",
        "state": "home",
        "tags": ["home", "dimmed"],
        "transforms": [{"kind": "dim", "factor": 0.55}],
        "notes": "整体亮度 55%，模拟弹窗遮罩",
        "labels": {
            "home_attack": "miss",
            "build_button": "hit",
        },
    },
    {
        "id": "home-a-noise",
        "source": "home-now.png",
        "state": "home",
        "tags": ["home", "noise"],
        "transforms": [{"kind": "noise", "sigma": 8.0, "seed": 20261125}],
        "notes": "高斯噪声 sigma=8，固定随机种子",
        "labels": {
            "home_attack": "hit",
            "build_button": "hit",
        },
    },
    {
        "id": "scout-a-scale-1280x720",
        "source": "live-scout-now.png",
        "state": "scouting",
        "tags": ["scouting", "scaled"],
        "transforms": [{"kind": "scale", "width": 1280, "height": 720}],
        "notes": "1280x720 侦察界面",
        "labels": {
            "scout_next": "hit",
            "scout_cancel": "hit",
            "loot_gold": "hit",
        },
    },
    {
        "id": "scout-a-crop",
        "source": "live-scout-now.png",
        "state": "scouting",
        "tags": ["scouting", "cropped"],
        "transforms": [{"kind": "crop", "x": 320, "y": 180, "width": 1600, "height": 900}],
        "notes": "裁掉左上战利品面板；数字项没有存在性校验，仍会在无关区域返回数值，因此这里不标注数字项",
        "labels": {
            "scout_next": "miss",
        },
    },
    {
        "id": "scout-a-blur",
        "source": "live-scout-now.png",
        "state": "scouting",
        "tags": ["scouting", "blurred", "digits"],
        "transforms": [{"kind": "blur", "sigma": 3.0}],
        "notes": "高斯模糊 sigma=3.0，数字边缘糊化",
        "labels": {
            "scout_next": "hit",
            "scout_cancel": "hit",
        },
    },
    {
        "id": "wall-bulk-a-blur",
        "source": "wall-more-01.png",
        "state": "wall_bulk",
        "tags": ["wall", "blurred"],
        "transforms": [{"kind": "blur", "sigma": 2.0}],
        "notes": "批量选择界面高斯模糊 sigma=2.0；wall_add_1 得分 0.835、wall_add_10 得分 0.854，均低于 0.9 阈值",
        "labels": {
            "wall_add_1": "miss",
            "wall_add_10": "miss",
        },
    },
    {
        "id": "disconnected-blur",
        "source": "screenshots/20261124-093042-001-game-stopped.png",
        "state": "disconnect_dialog",
        "tags": ["dialog", "disconnect", "blurred"],
        "transforms": [{"kind": "blur", "sigma": 1.0}],
        "notes": "断线弹窗轻度模糊",
        "labels": {
            "game_stop": "hit",
        },
    },
    {
        "id": "attack-menu-a-scale-1280x720",
        "source": "live-attack-menu.png",
        "state": "attack_menu",
        "tags": ["attack_menu", "scaled"],
        "transforms": [{"kind": "scale", "width": 1280, "height": 720}],
        "notes": "1280x720 联机模式",
        "labels": {
            "attack_find_match": "hit",
            "home_attack": "miss",
        },
    },
    {
        "id": "welcome-popup-a-dim",
        "source": "relaunch-01.png",
        "state": "welcome_popup",
        "tags": ["home", "popup", "dimmed"],
        "transforms": [{"kind": "dim", "factor": 0.7}],
        "notes": "欢迎回家弹窗亮度 70%；颜色校验对亮度敏感，home_popup_close 未命中",
        "labels": {
            "home_popup_close": "miss",
            "home_attack": "miss",
        },
    },
]


def apply_transforms(image: np.ndarray, transforms: list[dict]) -> np.ndarray:
    result = image
    for transform in transforms:
        kind = transform.get("kind")
        if kind == "scale":
            width = int(transform["width"])
            height = int(transform["height"])
            shrinking = width < result.shape[1] or height < result.shape[0]
            interpolation = cv2.INTER_AREA if shrinking else cv2.INTER_LINEAR
            result = cv2.resize(result, (width, height), interpolation=interpolation)
        elif kind == "crop":
            x = int(transform["x"])
            y = int(transform["y"])
            width = int(transform["width"])
            height = int(transform["height"])
            result = result[y : y + height, x : x + width].copy()
        elif kind == "blur":
            result = cv2.GaussianBlur(
                result, (0, 0), float(transform.get("sigma", 1.0))
            )
        elif kind == "dim":
            factor = float(transform.get("factor", 1.0))
            result = np.clip(result.astype(np.float32) * factor, 0, 255).astype(np.uint8)
        elif kind == "noise":
            rng = np.random.default_rng(int(transform.get("seed", 0)))
            noise = rng.normal(0.0, float(transform.get("sigma", 5.0)), result.shape)
            result = np.clip(result.astype(np.float32) + noise, 0, 255).astype(np.uint8)
        else:
            raise ValueError(f"未知变换: {kind}")
    return result


def build(source_root: Path, fixture_dir: Path) -> dict:
    frame_dir = fixture_dir / "frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    manifest_frames = []
    for spec in FRAMES:
        source_path = source_root / spec["source"]
        if not source_path.exists():
            raise SystemExit(f"源截图不存在: {source_path}")
        image = load_image(source_path)
        transformed = apply_transforms(image, list(spec.get("transforms") or []))
        target = frame_dir / f"{spec['id']}.webp"
        result, buffer = cv2.imencode(
            ".webp", transformed, [cv2.IMWRITE_WEBP_QUALITY, WEBP_QUALITY]
        )
        if not result:
            raise SystemExit(f"webp 编码失败: {target}")
        target.write_bytes(buffer.tobytes())
        decoded = cv2.imdecode(
            np.frombuffer(buffer.tobytes(), dtype=np.uint8), cv2.IMREAD_COLOR
        )
        stored = load_image(target)
        manifest_frames.append(
            {
                "id": spec["id"],
                "file": f"frames/{target.name}",
                "state": spec["state"],
                "tags": list(spec.get("tags") or []),
                "source": {
                    "path": str(source_path.relative_to(ROOT)),
                    "sha256": sha256_file(source_path),
                    "width": int(image.shape[1]),
                    "height": int(image.shape[0]),
                },
                "transform": list(spec.get("transforms") or [{"kind": "none"}]),
                "stored": {
                    "width": int(decoded.shape[1]),
                    "height": int(decoded.shape[0]),
                    "format": "webp",
                    "quality": WEBP_QUALITY,
                    "bytes": int(len(buffer)),
                    "file_sha256": sha256_file(target),
                    "pixels_sha256": sha256_bytes(stored.tobytes()),
                },
                "labels": dict(spec.get("labels") or {}),
                "notes": spec.get("notes", ""),
            }
        )
    manifest = {
        "version": 1,
        "generator": "tools/build_baseline_fixtures.py",
        "canonical_size": [1920, 1080],
        "assets_manifest": "../../../assets/assets.yaml",
        "digits_dir": "../../../assets/digits",
        "storage": {
            "format": "webp",
            "quality": WEBP_QUALITY,
            "lossy": True,
            "note": "为控制仓库体积使用有损 webp；识别分数与原始 PNG 存在小幅差异，标签以存储文件为准",
        },
        "defaults": {
            "label_hit": "期望命中",
            "label_miss": "期望不命中",
            "label_known_defect": "期望不命中但当前命中，已知缺陷，计入基线但不算失败",
        },
        "frames": manifest_frames,
    }
    (fixture_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="生成基线固定测试集")
    parser.add_argument(
        "--source-root",
        default="runtime/mumu",
        help="历史截图目录，默认 runtime/mumu",
    )
    parser.add_argument(
        "--fixture-dir",
        default=str(FIXTURE_DIR),
        help="固定测试集输出目录",
    )
    args = parser.parse_args()
    source_root = Path(args.source_root)
    if not source_root.is_absolute():
        source_root = ROOT / source_root
    fixture_dir = Path(args.fixture_dir)
    if not fixture_dir.is_absolute():
        fixture_dir = ROOT / fixture_dir
    manifest = build(source_root, fixture_dir)
    total = sum(frame["stored"]["bytes"] for frame in manifest["frames"])
    print(f"已生成 {len(manifest['frames'])} 帧，共 {total / 1e6:.2f}MB: {fixture_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
