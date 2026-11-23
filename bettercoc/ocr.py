from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from typing import Protocol, Sequence

import cv2
from PIL import Image

from .errors import OcrUnavailable
from .geometry import Rect
from .image import Screen
from .result import Match
from .spec import Recognition


class OcrBackend(Protocol):
    name: str

    def available(self) -> bool: ...

    def read(self, screen: Screen, spec: Recognition) -> list[Match]: ...


class NullOcr:
    name = "none"

    def available(self) -> bool:
        return False

    def read(self, screen: Screen, spec: Recognition) -> list[Match]:
        raise OcrUnavailable(
            "OCR 未启用。安装 pytesseract 与 Tesseract-OCR，或在配置中关闭 OCR 流程。"
        )


@dataclass
class TesseractOcr:
    lang: str = "eng"
    psm: int = 6
    tesseract_cmd: str | None = None
    name: str = "tesseract"

    def __post_init__(self) -> None:
        self._checked = False
        self._ready = False

    def _load(self):
        import pytesseract

        if self.tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = self.tesseract_cmd
        return pytesseract

    def available(self) -> bool:
        if self._checked:
            return self._ready
        self._checked = True
        if shutil.which("tesseract") is None and not self.tesseract_cmd:
            self._ready = False
            return False
        try:
            import pytesseract

            if self.tesseract_cmd:
                pytesseract.pytesseract.tesseract_cmd = self.tesseract_cmd
            pytesseract.get_tesseract_version()
            self._ready = True
        except Exception:
            self._ready = False
        return self._ready

    def read(self, screen: Screen, spec: Recognition) -> list[Match]:
        if not self.available():
            raise OcrUnavailable(
                "Tesseract 不可用。确认已安装 Tesseract-OCR 并在 PATH 中，或设置 vision.ocr.tesseract_cmd。"
            )
        try:
            pytesseract = self._load()
        except ImportError as exc:
            raise OcrUnavailable("缺少 pytesseract，请先安装: pip install pytesseract") from exc

        roi = spec.roi or Rect(0, 0, screen.width, screen.height)
        roi = roi.clamp(screen.width, screen.height)
        region = screen.crop(roi)
        if region.size == 0:
            return []
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        scale = spec.upscale if spec.upscale > 0 else 1.0
        if scale != 1.0:
            gray = cv2.resize(
                gray,
                (max(1, round(gray.shape[1] * scale)), max(1, round(gray.shape[0] * scale))),
                interpolation=cv2.INTER_CUBIC,
            )
        if spec.binarize:
            _, gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if spec.invert:
            gray = cv2.bitwise_not(gray)
        rgb = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)
        image = Image.fromarray(rgb)
        lang = spec.lang or self.lang
        psm = spec.psm or self.psm
        try:
            data = pytesseract.image_to_data(
                image,
                lang=lang,
                config=f"--psm {psm}",
                output_type=pytesseract.Output.DICT,
            )
        except Exception as exc:
            raise OcrUnavailable(f"Tesseract 识别失败: {exc}") from exc

        groups: dict[tuple[int, int, int], list[int]] = {}
        for index, raw_text in enumerate(data.get("text", [])):
            text = str(raw_text or "").strip()
            if not text:
                continue
            try:
                confidence = float(data["conf"][index])
            except (TypeError, ValueError):
                confidence = -1.0
            if confidence < 0:
                continue
            key = (
                int(data["block_num"][index]),
                int(data["par_num"][index]),
                int(data["line_num"][index]),
            )
            groups.setdefault(key, []).append(index)

        matches: list[Match] = []
        for indices in groups.values():
            words = [str(data["text"][index]).strip() for index in indices]
            text = " ".join(word for word in words if word)
            if not text:
                continue
            left = min(int(data["left"][index]) for index in indices)
            top = min(int(data["top"][index]) for index in indices)
            right = max(
                int(data["left"][index]) + int(data["width"][index]) for index in indices
            )
            bottom = max(
                int(data["top"][index]) + int(data["height"][index]) for index in indices
            )
            confidences = []
            for index in indices:
                try:
                    value = float(data["conf"][index])
                except (TypeError, ValueError):
                    continue
                if value >= 0:
                    confidences.append(value / 100.0)
            score = sum(confidences) / len(confidences) if confidences else 0.0
            matches.append(
                Match(
                    rect=Rect(
                        roi.x + round(left / scale),
                        roi.y + round(top / scale),
                        max(1, round((right - left) / scale)),
                        max(1, round((bottom - top) / scale)),
                    ),
                    score=score,
                    text=text,
                    name=spec.name,
                )
            )
        matches.sort(key=lambda item: (item.rect.y, item.rect.x))
        return matches


def create_ocr(
    backend: str = "auto",
    lang: str = "eng",
    psm: int = 6,
    tesseract_cmd: str | None = None,
) -> OcrBackend:
    if backend in ("none", "off", "disabled"):
        return NullOcr()
    if backend in ("auto", "tesseract"):
        return TesseractOcr(lang=lang, psm=psm, tesseract_cmd=tesseract_cmd)
    raise OcrUnavailable(f"未知 OCR 后端: {backend}")


def filter_text(matches: Sequence[Match], spec: Recognition) -> list[Match]:
    result: list[Match] = []
    regex = re.compile(spec.regex, re.IGNORECASE) if spec.regex else None
    for match in matches:
        text = (match.text or "").strip()
        if not text:
            continue
        folded = text.casefold()
        if spec.text_all and not all(item.casefold() in folded for item in spec.text_all):
            continue
        if spec.text_any and not any(item.casefold() in folded for item in spec.text_any):
            continue
        if regex is not None and regex.search(text) is None:
            continue
        result.append(match)
    return result


_NUMBER_PATTERN = re.compile(r"(\d[\d,.\s]*)\s*([KkMmBb万亿]?)")


def parse_number(text: str | None) -> int | None:
    if not text:
        return None
    match = _NUMBER_PATTERN.search(text)
    if match is None:
        return None
    raw = match.group(1).strip().replace(" ", "")
    suffix = match.group(2)
    if raw.count(",") > 1:
        raw = raw.replace(",", "")
    elif "," in raw and "." not in raw:
        raw = raw.replace(",", "")
    else:
        raw = raw.replace(",", "")
    try:
        value = float(raw)
    except ValueError:
        return None
    multiplier = {
        "k": 1_000,
        "m": 1_000_000,
        "b": 1_000_000_000,
        "万": 10_000,
        "亿": 100_000_000,
        "": 1,
    }.get(suffix.lower(), 1)
    return int(round(value * multiplier))
