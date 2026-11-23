from __future__ import annotations

import argparse
from pathlib import Path

import cv2

from bettercoc.digits import glyph_boxes, normalize_glyph, white_mask

ROIS = {
    "own_gold": ((1600, 50, 240, 55), "5670108"),
    "own_elixir": ((1600, 120, 240, 55), "5980352"),
    "loot_gold": ((70, 125, 250, 50), "914447"),
    "loot_elixir": ((70, 195, 250, 50), "959567"),
    "loot_dark": ((70, 265, 200, 50), "6313"),
}


def build(image_path: Path, output: Path) -> None:
    image = cv2.imread(str(image_path))
    if image is None:
        raise SystemExit(f"cannot read {image_path}")
    output.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for name, (rect, labels) in ROIS.items():
        x, y, width, height = rect
        region = image[y : y + height, x : x + width]
        mask = white_mask(region)
        boxes = glyph_boxes(mask)
        if len(boxes) != len(labels):
            print(f"{name}: {len(boxes)} boxes vs {len(labels)} labels")
        for index, (box, label) in enumerate(zip(boxes, labels)):
            bx, by, bw, bh = box
            glyph = mask[by : by + bh, bx : bx + bw]
            normalized = normalize_glyph(glyph)
            counts[label] = counts.get(label, 0) + 1
            target = output / f"{label}-{counts[label]:02d}.png"
            cv2.imwrite(str(target), normalized)
    print("saved", sum(counts.values()), "templates", counts)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", default="assets/digits")
    args = parser.parse_args()
    build(Path(args.image), Path(args.output))


if __name__ == "__main__":
    main()
