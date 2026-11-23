"""Tiny dependency-free SVG plotting helpers used by plot.py."""

from __future__ import annotations

import math
from pathlib import Path
from xml.sax.saxutils import escape

TEXT = "#222222"
GRID = "#e4e4e4"
AXIS = "#777777"
MUTED = "#666666"


def fmt(value: float, digits: int = 4) -> str:
    if value == 0:
        return "0"
    if abs(value) >= 1000:
        return f"{value:.0f}"
    if abs(value) >= 1:
        return f"{value:.{min(digits, 2)}f}".rstrip("0").rstrip(".")
    return f"{value:.{digits}f}".rstrip("0").rstrip(".")


def linear_ticks(lo: float, hi: float, target: int = 6) -> list[float]:
    if not math.isfinite(lo) or not math.isfinite(hi):
        return [0.0, 1.0]
    if hi <= lo:
        hi = lo + 1.0
    raw = (hi - lo) / max(1, target)
    power = 10 ** math.floor(math.log10(raw))
    step = power
    for candidate in (1, 2, 5, 10):
        if candidate * power >= raw:
            step = candidate * power
            break
    start = math.ceil(lo / step) * step
    ticks = []
    value = start
    while value <= hi + step * 0.001:
        ticks.append(round(value, 12))
        value += step
    return ticks


def log_ticks(lo: float, hi: float) -> list[float]:
    if lo <= 0:
        lo = 1e-6
    if hi <= lo:
        hi = lo * 10
    first = math.floor(math.log10(lo))
    last = math.ceil(math.log10(hi))
    ticks = []
    for exponent in range(first, last + 1):
        value = 10.0**exponent
        if lo * 0.8 <= value <= hi * 1.25:
            ticks.append(value)
    return ticks or [lo, hi]


def scale_linear(value: float, lo: float, hi: float, p0: float, p1: float) -> float:
    if hi <= lo:
        return (p0 + p1) / 2
    return p0 + (value - lo) / (hi - lo) * (p1 - p0)


def scale_log(value: float, lo: float, hi: float, p0: float, p1: float) -> float:
    value = max(value, 1e-12)
    lo = max(lo, 1e-12)
    hi = max(hi, lo * 1.0001)
    return p0 + (math.log10(value) - math.log10(lo)) / (
        math.log10(hi) - math.log10(lo)
    ) * (p1 - p0)


class SVG:
    def __init__(self, width: int = 1000, height: int = 560):
        self.width = width
        self.height = height
        self.items: list[str] = []

    def add(self, markup: str) -> None:
        self.items.append(markup)

    def rect(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        fill: str = "none",
        stroke: str = "none",
        stroke_width: float = 1,
        rx: float = 0,
    ) -> None:
        self.add(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{width:.2f}" height="{height:.2f}" '
            f'rx="{rx:.2f}" fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width:.2f}"/>'
        )

    def line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        stroke: str = AXIS,
        stroke_width: float = 1,
        dash: str | None = None,
    ) -> None:
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(
            f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
            f'stroke="{stroke}" stroke-width="{stroke_width:.2f}"{dash_attr}/>'
        )

    def circle(self, cx: float, cy: float, r: float, fill: str, stroke: str = "none") -> None:
        self.add(
            f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="1"/>'
        )

    def polyline(
        self, points: list[tuple[float, float]], stroke: str, stroke_width: float = 2
    ) -> None:
        if not points:
            return
        path = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
        self.add(
            f'<polyline points="{path}" fill="none" stroke="{stroke}" '
            f'stroke-width="{stroke_width:.2f}" stroke-linejoin="round" stroke-linecap="round"/>'
        )

    def text(
        self,
        x: float,
        y: float,
        value: str,
        size: float = 12,
        anchor: str = "start",
        fill: str = TEXT,
        weight: str = "normal",
        rotate: float | None = None,
        family: str = "sans-serif",
    ) -> None:
        transform = (
            f' transform="rotate({rotate:.1f} {x:.1f} {y:.1f})"' if rotate is not None else ""
        )
        self.add(
            f'<text x="{x:.2f}" y="{y:.2f}" font-family="{family}" font-size="{size:.1f}" '
            f'fill="{fill}" font-weight="{weight}" text-anchor="{anchor}"{transform}>'
            f"{escape(value)}</text>"
        )

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        body = "\n".join(self.items)
        document = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" '
            f'height="{self.height}" viewBox="0 0 {self.width} {self.height}">\n'
            f'<rect width="{self.width}" height="{self.height}" fill="#ffffff"/>\n'
            f"{body}\n</svg>\n"
        )
        path.write_text(document, encoding="utf-8")
