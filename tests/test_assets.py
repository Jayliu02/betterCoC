import unittest

import numpy as np
import yaml

from bettercoc.assets import AssetStore
from bettercoc.errors import ConfigError, MissingAssetError
from bettercoc.image import save_image
from bettercoc.spec import Kind
from support import make_temp_dir


class AssetStoreTest(unittest.TestCase):
    def setUp(self):
        self.root = make_temp_dir("assets")
        templates = self.root / "templates"
        templates.mkdir()
        save_image(templates / "btn.png", np.zeros((20, 30, 3), dtype=np.uint8))
        data = {
            "version": 1,
            "template_root": "templates",
            "defaults": {"threshold": 0.8},
            "assets": {
                "btn": {"file": "btn.png"},
                "btn_roi": {"file": "btn.png", "roi": [1, 2, 100, 60]},
                "green": {
                    "type": "color",
                    "lower": [40, 80, 80],
                    "upper": [80, 255, 255],
                    "min_ratio": 0.2,
                },
                "loot": {"type": "ocr", "roi": [0, 0, 100, 40], "regex": r"\d+"},
            },
        }
        (self.root / "assets.yaml").write_text(
            yaml.safe_dump(data, allow_unicode=True), encoding="utf-8"
        )
        self.store = AssetStore(self.root / "assets.yaml")

    def test_parse_specs(self):
        self.assertEqual(self.store.names(), ["btn", "btn_roi", "green", "loot"])
        btn = self.store.recognition("btn")
        self.assertIs(btn.kind, Kind.TEMPLATE)
        self.assertEqual(btn.threshold, 0.8)
        self.assertIsNotNone(self.store.template(btn).image)
        self.assertEqual(self.store.recognition("btn_roi").roi.width, 100)
        self.assertIs(self.store.recognition("green").kind, Kind.COLOR)
        self.assertIs(self.store.recognition("loot").kind, Kind.OCR)

    def test_missing_asset_name(self):
        with self.assertRaises(MissingAssetError):
            self.store.recognition("absent")

    def test_missing_file(self):
        self.store.entries["gone"] = {"file": "gone.png"}
        self.assertIn("gone", " ".join(self.store.missing_files()))

    def test_invalid_threshold(self):
        self.store.entries["bad"] = {"file": "btn.png", "threshold": 2}
        with self.assertRaises(ConfigError):
            self.store.recognition("bad")

    def test_validate(self):
        self.assertEqual(self.store.validate(), [])
        self.assertEqual(self.store.missing_files(), [])


if __name__ == "__main__":
    unittest.main()
