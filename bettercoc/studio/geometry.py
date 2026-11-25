from dataclasses import dataclass
from typing import Iterable

@dataclass(frozen=True)
class CanvasFit:
    canvas_width: int
    canvas_height: int
    image_width: int
    image_height: int
    scale: float
    offset_x: float
    offset_y: float

    @property
    def drawn_width(self) -> float:
        return self.image_width * self.scale

    @property
    def drawn_height(self) -> float:
        return self.image_height * self.scale

    def contains(self, x: float, y: float) -> bool:
        return (
            self.offset_x <= x <= self.offset_x + self.drawn_width
            and self.offset_y <= y <= self.offset_y + self.drawn_height
        )


def fit_image(
    image_width: int,
    image_height: int,
    canvas_width: int,
    canvas_height: int,
) -> CanvasFit:
    image_width = max(1, int(image_width))
    image_height = max(1, int(image_height))
    canvas_width = max(1, int(canvas_width))
    canvas_height = max(1, int(canvas_height))
    scale = min(canvas_width / image_width, canvas_height / image_height)
    drawn_width = image_width * scale
    drawn_height = image_height * scale
    return CanvasFit(
        canvas_width=canvas_width,
        canvas_height=canvas_height,
        image_width=image_width,
        image_height=image_height,
        scale=scale,
        offset_x=(canvas_width - drawn_width) / 2.0,
        offset_y=(canvas_height - drawn_height) / 2.0,
    )


def image_to_widget(fit: CanvasFit, x: float, y: float) -> tuple[float, float]:
    return fit.offset_x + x * fit.scale, fit.offset_y + y * fit.scale


def widget_to_image(
    fit: CanvasFit, x: float, y: float, clamp: bool = True
) -> tuple[float, float] | None:
    image_x = (x - fit.offset_x) / fit.scale
    image_y = (y - fit.offset_y) / fit.scale
    if clamp:
        image_x = min(max(image_x, 0.0), fit.image_width - 1.0)
        image_y = min(max(image_y, 0.0), fit.image_height - 1.0)
        return image_x, image_y
    if not fit.contains(x, y):
        return None
    return image_x, image_y


def canonical_point(
    fit: CanvasFit,
    x: float,
    y: float,
    canonical: tuple[int, int],
) -> tuple[int, int] | None:
    point = widget_to_image(fit, x, y, clamp=False)
    if point is None:
        return None
    scale_x = canonical[0] / fit.image_width
    scale_y = canonical[1] / fit.image_height
    canonical_x = min(max(round(point[0] * scale_x), 0), canonical[0] - 1)
    canonical_y = min(max(round(point[1] * scale_y), 0), canonical[1] - 1)
    return canonical_x, canonical_y


def canonical_rect(
    fit: CanvasFit,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    canonical: tuple[int, int],
):
    start = widget_to_image(fit, x1, y1)
    end = widget_to_image(fit, x2, y2)
    if start is None or end is None:
        return None
    scale_x = canonical[0] / fit.image_width
    scale_y = canonical[1] / fit.image_height
    left = min(start[0], end[0]) * scale_x
    top = min(start[1], end[1]) * scale_y
    right = max(start[0], end[0]) * scale_x
    bottom = max(start[1], end[1]) * scale_y
    width = max(1, round(right) - round(left))
    height = max(1, round(bottom) - round(top))
    x = min(max(round(left), 0), canonical[0] - 1)
    y = min(max(round(top), 0), canonical[1] - 1)
    width = min(width, canonical[0] - x)
    height = min(height, canonical[1] - y)
    from bettercoc.geometry import Rect

    return Rect(x, y, width, height)


def zoomed_fit(
    fit: CanvasFit,
    zoom: float,
    pan_x: float = 0.0,
    pan_y: float = 0.0,
) -> CanvasFit:
    zoom = max(0.1, min(float(zoom), 12.0))
    base = fit_image(
        fit.image_width, fit.image_height, fit.canvas_width, fit.canvas_height
    )
    scale = base.scale * zoom
    drawn_width = fit.image_width * scale
    drawn_height = fit.image_height * scale
    offset_x = (fit.canvas_width - drawn_width) / 2.0 - pan_x
    offset_y = (fit.canvas_height - drawn_height) / 2.0 - pan_y
    return CanvasFit(
        canvas_width=fit.canvas_width,
        canvas_height=fit.canvas_height,
        image_width=fit.image_width,
        image_height=fit.image_height,
        scale=scale,
        offset_x=offset_x,
        offset_y=offset_y,
    )


def iter_overlay_points(rects: Iterable, canonical: tuple[int, int]):
    for rect in rects:
        yield rect.x, rect.y, rect.width, rect.height
