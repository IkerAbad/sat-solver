#!/usr/bin/env python3
"""Create dependency-free SVG figures from benchmark CSVs and solver traces."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

from svgplot import (
    AXIS,
    GRID,
    MUTED,
    TEXT,
    SVG,
    fmt,
    linear_ticks,
    log_ticks,
    scale_linear,
    scale_log,
)

COLORS = {
    "vsids": "#1f77b4",
    "vmtf": "#2ca02c",
    "random": "#d62728",
    "satsolver": "#1f77b4",
    "minisat": "#ff7f0e",
}


def load_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        for key in ("vars", "clauses", "conflicts", "runs"):
            try:
                row[key] = int(float(row[key])) if row.get(key) not in (None, "") else None
            except ValueError:
                row[key] = None
        try:
            row["time_s"] = float(row["time_s"]) if row.get("time_s") else None
        except ValueError:
            row["time_s"] = None
    return rows


def unique_in_order(values):
    seen = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def legend(svg: SVG, entries: list[tuple[str, str]], x: float, y: float) -> None:
    for label, color in entries:
        svg.circle(x, y - 4, 5, color)
        svg.text(x + 10, y, label, size=12, fill=TEXT)
        x += 24 + 7 * len(label)


def plot_benchmark(rows: list[dict], out: Path) -> None:
    by_instance: dict[str, dict[str, dict]] = {}
    order = []
    for row in rows:
        name = row["instance"]
        if name not in by_instance:
            by_instance[name] = {}
            order.append(name)
        by_instance[name][row["solver"]] = row

    usable = [
        name
        for name in order
        if by_instance[name].get("satsolver", {}).get("time_s")
        or by_instance[name].get("minisat", {}).get("time_s")
    ]
    if not usable:
        return

    times = []
    for name in usable:
        for solver in ("satsolver", "minisat"):
            value = by_instance[name].get(solver, {}).get("time_s")
            if value and value > 0:
                times.append(value)
    lo = min(times) * 0.7
    hi = max(times) * 1.5

    width = 1000
    row_height = 27
    top = 95
    bottom = 55
    height = top + len(usable) * row_height + bottom
    left = 215
    right = 95
    x0 = left
    x1 = width - right

    svg = SVG(width, height)
    svg.text(24, 30, "Solve time against MiniSat", size=20, weight="bold")
    svg.text(
        24,
        52,
        "Median end-to-end wall time per instance, logarithmic scale. Left is faster.",
        size=12,
        fill=MUTED,
    )
    legend(svg, [("satsolver", COLORS["satsolver"]), ("MiniSat", COLORS["minisat"])], 24, 75)

    ticks = log_ticks(lo, hi)
    for tick in ticks:
        x = scale_log(tick, lo, hi, x0, x1)
        svg.line(x, top - 8, x, height - bottom + 4, stroke=GRID, stroke_width=1)
        svg.text(x, height - bottom + 20, fmt(tick), size=11, anchor="middle", fill=MUTED)
    svg.text((x0 + x1) / 2, height - 16, "wall time (s)", size=12, anchor="middle", fill=MUTED)

    for index, name in enumerate(usable):
        y = top + index * row_height + 12
        svg.text(left - 12, y + 4, name, size=11, anchor="end", fill=TEXT)
        ours = by_instance[name].get("satsolver", {}).get("time_s")
        reference = by_instance[name].get("minisat", {}).get("time_s")
        points = []
        if ours:
            points.append((scale_log(ours, lo, hi, x0, x1), y))
        if reference:
            points.append((scale_log(reference, lo, hi, x0, x1), y))
        if len(points) == 2:
            svg.line(points[0][0], y, points[1][0], y, stroke="#cfcfcf", stroke_width=2)
        if ours:
            svg.circle(points[0][0], y, 5, COLORS["satsolver"])
        if reference:
            svg.circle(points[-1][0], y, 5, COLORS["minisat"])
        if ours and reference and reference > 0:
            ratio = ours / reference
            label = f"{ratio:.2f}x"
            color = "#2a7f3f" if ratio < 1 else "#b03030" if ratio > 1.05 else MUTED
            svg.text(width - 20, y + 4, label, size=11, anchor="end", fill=color)

    svg.line(x0, height - bottom + 4, x1, height - bottom + 4, stroke=AXIS, stroke_width=1)
    svg.save(out)


def plot_heuristics(rows: list[dict], out: Path) -> None:
    grouped: dict[str, dict[str, dict]] = {}
    order = []
    for row in rows:
        name = row["instance"]
        if name not in grouped:
            grouped[name] = {}
            order.append(name)
        grouped[name][row["heuristic"]] = row
    heuristics = [h for h in ("vsids", "vmtf", "random") if any(h in grouped[n] for n in order)]
    if not heuristics:
        return

    values = [
        row["time_s"]
        for name in order
        for row in grouped[name].values()
        if row.get("time_s") and row["time_s"] > 0
    ]
    lo = min(values) * 0.7
    hi = max(values) * 1.7

    width = 1000
    group_height = 54
    top = 100
    bottom = 55
    height = top + len(order) * group_height + bottom
    left = 220
    right = 75
    x0 = left
    x1 = width - right

    svg = SVG(width, height)
    svg.text(24, 30, "Decision heuristic comparison", size=20, weight="bold")
    svg.text(
        24,
        52,
        "Median end-to-end wall time, logarithmic scale. Lower is better.",
        size=12,
        fill=MUTED,
    )
    legend(svg, [(h, COLORS[h]) for h in heuristics], 24, 78)

    ticks = log_ticks(lo, hi)
    for tick in ticks:
        x = scale_log(tick, lo, hi, x0, x1)
        svg.line(x, top - 8, x, height - bottom + 4, stroke=GRID, stroke_width=1)
        svg.text(x, height - bottom + 20, fmt(tick), size=11, anchor="middle", fill=MUTED)
    svg.text((x0 + x1) / 2, height - 16, "wall time (s)", size=12, anchor="middle", fill=MUTED)

    bar_height = 11
    gap = 3
    for index, name in enumerate(order):
        base_y = top + index * group_height + 8
        svg.text(left - 12, base_y + 19, name, size=11, anchor="end", fill=TEXT)
        for h_index, heuristic in enumerate(heuristics):
            row = grouped[name].get(heuristic, {})
            y = base_y + h_index * (bar_height + gap)
            value = row.get("time_s")
            if not value:
                svg.text(x1 - 2, y + bar_height - 2, "TO", size=10, anchor="end", fill="#b03030")
                continue
            x = scale_log(value, lo, hi, x0, x1)
            svg.rect(x0, y, max(1.5, x - x0), bar_height, fill=COLORS.get(heuristic, "#777777"), rx=2)
            svg.text(min(x + 5, x1 - 2), y + bar_height - 2, f"{value:.3f} s", size=9, fill=MUTED)

    svg.line(x0, height - bottom + 4, x1, height - bottom + 4, stroke=AXIS, stroke_width=1)
    svg.save(out)


def convert_trace(path: Path) -> tuple[str, list[dict]]:
    rows = []
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            try:
                rows.append(
                    {
                        "conflicts": int(row["conflicts"]),
                        "level": int(row["level"]),
                        "trail": int(row["trail"]),
                        "learnts": int(row["learnts"]),
                        "time": float(row["time_ms"]) / 1000.0,
                    }
                )
            except (KeyError, ValueError):
                continue
    return path.stem, rows


def load_trace_group(trace_dir: Path, instance: str | None) -> tuple[str | None, dict[str, list[dict]]]:
    if not trace_dir.exists():
        return None, {}
    groups: dict[str, dict[str, list[dict]]] = {}
    for path in sorted(trace_dir.glob("*.csv")):
        stem, rows = convert_trace(path)
        if not rows:
            continue
        for heuristic in ("vsids", "vmtf", "random"):
            suffix = "_" + heuristic
            if stem.endswith(suffix):
                name = stem[: -len(suffix)]
                groups.setdefault(name, {})[heuristic] = rows
                break
    if not groups:
        return None, {}
    if instance is None:
        instance = max(groups, key=lambda key: (len(groups[key]), key))
    selected = groups.get(instance, {})
    ordered = {
        heuristic: selected[heuristic]
        for heuristic in ("vsids", "vmtf", "random")
        if heuristic in selected
    }
    return instance, ordered


def downsample(points: list[tuple[float, float]], limit: int = 2500) -> list[tuple[float, float]]:
    if len(points) <= limit:
        return points
    stride = max(1, len(points) // limit)
    result = points[::stride]
    if result[-1] != points[-1]:
        result.append(points[-1])
    return result


def line_chart(
    series: dict[str, list[tuple[float, float]]],
    out: Path,
    title: str,
    subtitle: str,
    xlabel: str,
    ylabel: str,
    x_log: bool = False,
) -> None:
    if not series:
        return
    all_points = [point for points in series.values() for point in points]
    xs = [p[0] for p in all_points]
    ys = [p[1] for p in all_points]
    xlo, xhi = min(xs), max(xs)
    ylo, yhi = min(ys), max(ys)
    if xhi <= xlo:
        xhi = xlo + 1
    if yhi <= ylo:
        yhi = ylo + 1
    if x_log:
        xlo = max(xlo, 1e-6)
        xhi = max(xhi, xlo * 1.1)
    else:
        pad = (xhi - xlo) * 0.04
        xlo -= pad
        xhi += pad
    ypad = (yhi - ylo) * 0.06
    ylo = max(0.0, ylo - ypad)
    yhi += ypad

    width = 1000
    height = 560
    left = 90
    right = 35
    top = 105
    bottom = 70
    x0, x1 = left, width - right
    y0, y1 = height - bottom, top

    svg = SVG(width, height)
    svg.text(24, 30, title, size=20, weight="bold")
    svg.text(24, 52, subtitle, size=12, fill=MUTED)
    legend(svg, [(name, COLORS.get(name, "#777777")) for name in series], 24, 78)

    if x_log:
        xticks = log_ticks(xlo, xhi)
        xmap = lambda value: scale_log(value, xlo, xhi, x0, x1)
    else:
        xticks = linear_ticks(xlo, xhi)
        xmap = lambda value: scale_linear(value, xlo, xhi, x0, x1)
    yticks = linear_ticks(ylo, yhi)

    for tick in yticks:
        y = scale_linear(tick, ylo, yhi, y0, y1)
        svg.line(x0, y, x1, y, stroke=GRID, stroke_width=1)
        svg.text(x0 - 10, y + 4, fmt(tick), size=11, anchor="end", fill=MUTED)
    for tick in xticks:
        x = xmap(tick)
        svg.line(x, y0, x, y1, stroke=GRID, stroke_width=1)
        svg.text(x, y0 + 20, fmt(tick), size=11, anchor="middle", fill=MUTED)

    svg.line(x0, y0, x1, y0, stroke=AXIS, stroke_width=1)
    svg.line(x0, y0, x0, y1, stroke=AXIS, stroke_width=1)
    svg.text((x0 + x1) / 2, height - 18, xlabel, size=12, anchor="middle", fill=MUTED)
    svg.text(18, (y0 + y1) / 2, ylabel, size=12, anchor="middle", fill=MUTED, rotate=-90)

    for name, points in series.items():
        mapped = [(xmap(x), scale_linear(y, ylo, yhi, y0, y1)) for x, y in downsample(points)]
        svg.polyline(mapped, COLORS.get(name, "#777777"), 2)
    svg.save(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compare-csv", default="results/compare.csv")
    parser.add_argument("--heuristics-csv", default="results/heuristics.csv")
    parser.add_argument("--traces", default="results/traces")
    parser.add_argument("--trace-instance", default=None)
    parser.add_argument("--out", default="docs/figures")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    compare_path = Path(args.compare_csv)
    if compare_path.exists():
        plot_benchmark(load_csv(compare_path), out_dir / "benchmark.svg")
        print(f"wrote {out_dir / 'benchmark.svg'}")

    heuristics_path = Path(args.heuristics_csv)
    if heuristics_path.exists():
        plot_heuristics(load_csv(heuristics_path), out_dir / "heuristics.svg")
        print(f"wrote {out_dir / 'heuristics.svg'}")

    instance, group = load_trace_group(Path(args.traces), args.trace_instance)
    if instance and group:
        series_time = {
            name: [(row["time"], row["conflicts"]) for row in rows]
            for name, rows in group.items()
        }
        series_depth = {
            name: [(row["conflicts"], row["level"]) for row in rows]
            for name, rows in group.items()
        }
        line_chart(
            series_time,
            out_dir / "conflicts_over_time.svg",
            f"Conflicts over time: {instance}",
            "Cumulative conflicts against elapsed solve time, one line per heuristic.",
            "solve time (s)",
            "conflicts",
        )
        line_chart(
            series_depth,
            out_dir / "search_depth.svg",
            f"Search depth: {instance}",
            "Decision level at every traced conflict. Drops are backjumps or restarts.",
            "conflicts",
            "decision level",
        )
        print(f"wrote {out_dir / 'conflicts_over_time.svg'}")
        print(f"wrote {out_dir / 'search_depth.svg'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
