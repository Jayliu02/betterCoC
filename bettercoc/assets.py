from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigError, MissingAssetError
from .geometry import Rect
from .image import load_image
from .spec import Kind, PointCheck, Recognition
from .template import Template, build_mask


def _as_tuple(value: Any, cast) -> tuple:
    if value is None:
        return ()
    if isinstance(value, str):
        return (cast(value),)
    return tuple(cast(item) for item in value)


class AssetStore:
    def __init__(self, manifest_path: str | Path) -> None:
        self.manifest_path = Path(manifest_path).resolve()
        if not self.manifest_path.exists():
            raise ConfigError(f"资源清单不存在: {self.manifest_path}")
        with self.manifest_path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        if not isinstance(data, dict) or not isinstance(data.get("assets"), dict):
            raise ConfigError(f"资源清单格式错误: {self.manifest_path}")
        self.data = data
        self.base_dir = self.manifest_path.parent
        self.template_root = self.base_dir / str(data.get("template_root", "templates"))
        self.defaults: dict[str, Any] = data.get("defaults") or {}
        self.entries: dict[str, Any] = data["assets"]
        self._specs: dict[str, Recognition] = {}
        self._templates: dict[tuple[str, bool, tuple[int, int, int] | None, int], Template] = {}

    def names(self) -> list[str]:
        return sorted(self.entries)

    def has(self, name: str) -> bool:
        return name in self.entries

    def recognition(self, name: str) -> Recognition:
        if name in self._specs:
            return self._specs[name]
        if name not in self.entries:
            available = ", ".join(self.names()) or "无"
            raise MissingAssetError(f"资源清单中没有识别项 {name}，可用: {available}")
        spec = self._parse(name, self.entries[name])
        self._specs[name] = spec
        return spec

    def template(self, spec: Recognition) -> Template:
        if not spec.file:
            raise MissingAssetError(f"识别项 {spec.name} 没有模板文件")
        path = (self.template_root / spec.file).resolve()
        key = (str(path), spec.use_alpha, spec.mask_color, spec.mask_tolerance)
        if key in self._templates:
            return self._templates[key]
        if not path.exists():
            raise MissingAssetError(
                f"模板文件不存在: {path}\n"
                f"用 `bettercoc assets add --name {spec.name} --rect x,y,w,h` 从截图生成。"
            )
        image = load_image(path)
        bgr, mask = build_mask(
            image, spec.use_alpha, spec.mask_color, spec.mask_tolerance
        )
        template = Template(name=spec.name, image=bgr, mask=mask)
        self._templates[key] = template
        return template

    def _parse(self, name: str, raw: Any) -> Recognition:
        if isinstance(raw, str):
            raw = {"file": raw}
        if not isinstance(raw, dict):
            raise ConfigError(f"识别项 {name} 必须是对象或文件路径")
        options = dict(self.defaults)
        options.update(raw)
        try:
            kind = Kind(str(options.get("type", "template")).lower())
        except ValueError as exc:
            raise ConfigError(
                f"识别项 {name} 的类型无效: {options.get('type')}"
            ) from exc
        common = {
            "name": name,
            "kind": kind,
            "roi": Rect.from_value(options["roi"]) if options.get("roi") else None,
        }
        if kind is Kind.TEMPLATE:
            return Recognition(
                **common,
                threshold=float(options.get("threshold", 0.86)),
                grayscale=bool(options.get("grayscale", True)),
                method=str(options.get("method", "ccoeff_normed")),
                scales=_as_tuple(options.get("scales", [1.0]), float),
                file=str(options["file"]) if options.get("file") else None,
                use_alpha=bool(options.get("use_alpha", True)),
                mask_color=_as_tuple(options["mask_color"], int)
                if options.get("mask_color")
                else None,
                mask_tolerance=int(options.get("mask_tolerance", 12)),
            )
        if kind is Kind.OCR:
            return Recognition(
                **common,
                text_any=_as_tuple(options.get("text_any"), str),
                text_all=_as_tuple(options.get("text_all"), str),
                regex=str(options["regex"]) if options.get("regex") else None,
                lang=str(options["lang"]) if options.get("lang") else None,
                psm=int(options.get("psm", 6)),
                upscale=float(options.get("upscale", 2.0)),
                binarize=bool(options.get("binarize", False)),
                invert=bool(options.get("invert", False)),
            )
        if kind is Kind.DIGITS:
            return Recognition(**common)
        if kind is Kind.POINT:
            return self._parse_point(name, options, common)
        return Recognition(
            **common,
            space=str(options.get("space", "hsv")).lower(),
            lower=_as_tuple(options.get("lower", [0, 0, 0]), int),
            upper=_as_tuple(options.get("upper", [255, 255, 255]), int),
            min_area=int(options.get("min_area", 150)),
            min_ratio=float(options.get("min_ratio", 0.05)),
        )

    def _parse_point(
        self, name: str, options: dict[str, Any], common: dict[str, Any]
    ) -> Recognition:
        raw = options.get("point")
        try:
            point = (int(raw[0]), int(raw[1]))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ConfigError(
                f"识别项 {name} 的 point 需要 [x, y]: {raw!r}"
            ) from exc
        check = None
        raw_check = options.get("check")
        if raw_check is not None:
            if not isinstance(raw_check, dict):
                raise ConfigError(f"识别项 {name} 的 check 必须是对象")
            try:
                raw_color = raw_check["color"]
                if raw_color and isinstance(raw_color[0], (list, tuple)):
                    colors = tuple(
                        tuple(int(value) for value in color) for color in raw_color
                    )
                else:
                    colors = (tuple(int(value) for value in raw_color),)
                check = PointCheck(
                    roi=Rect.from_value(raw_check["roi"]),
                    colors=colors,
                    tolerance=int(raw_check.get("tolerance", 25)),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ConfigError(
                    f"识别项 {name} 的 check 格式错误: {raw_check!r}"
                ) from exc
        return Recognition(**common, point=point, check=check)

    def missing_files(self) -> list[str]:
        missing = []
        for name in self.names():
            spec = self.recognition(name)
            if spec.kind is Kind.TEMPLATE and spec.file:
                path = self.template_root / spec.file
                if not path.exists():
                    missing.append(f"{name}: {path}")
        return missing

    def validate(self) -> list[str]:
        issues: list[str] = []
        for name in self.names():
            try:
                self.recognition(name)
            except Exception as exc:
                issues.append(f"{name}: {exc}")
        return issues
