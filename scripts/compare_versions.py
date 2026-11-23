#!/usr/bin/env python3
"""Measure two solver builds and MiniSat in one interleaved session.

This is the harness used for before/after performance experiments. Baseline,
candidate and reference runs are interleaved per repetition so that shared
machine load affects all three. Every SAT model is checked and all three
solvers must agree on SAT/UNSAT.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import verify


def parse_conflicts(stdout: str) -> int | None:
    match = re.search(r"^c conflicts\s+(\d+)\s*$", stdout, re.MULTILINE)
    return int(match.group(1)) if match else None


def parse_reference_conflicts(stdout: str) -> int | None:
    match = re.search(r"^conflicts\s*:\s*(\d+)", stdout, re.MULTILINE)
    return int(match.group(1)) if match else None


def run_solver(binary: str, arguments: list[str], cnf: Path, timeout: float) -> dict:
    command = [binary] + arguments + [str(cnf)]
    start = time.perf_counter()
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout
        )
        elapsed = time.perf_counter() - start
        status = verify.parse_status(completed.stdout)
        return {
            "status": status or "UNKNOWN",
            "time": elapsed,
            "conflicts": parse_conflicts(completed.stdout),
            "model": verify.parse_model(completed.stdout),
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "TIMEOUT",
            "time": timeout,
            "conflicts": None,
            "model": [],
            "stdout": "",
            "stderr": "",
        }


def run_reference(binary: str, cnf: Path, timeout: float, work_dir: Path) -> dict:
    result_file = work_dir / f"{cnf.stem}.reference.out"
    result_file.unlink(missing_ok=True)
    start = time.perf_counter()
    try:
        completed = subprocess.run(
            [binary, str(cnf), str(result_file)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = time.perf_counter() - start
        output = result_file.read_text(encoding="utf-8", errors="replace") if result_file.exists() else ""
        status = verify.parse_status(output)
        return {
            "status": status or "UNKNOWN",
            "time": elapsed,
            "conflicts": parse_reference_conflicts(completed.stdout),
            "model": verify.parse_model(output),
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "TIMEOUT",
            "time": timeout,
            "conflicts": None,
            "model": [],
            "stdout": "",
            "stderr": "",
        }
    finally:
        result_file.unlink(missing_ok=True)


def validate(label: str, run: dict, nvars: int, clauses: list[list[int]]) -> list[str]:
    if run["status"] not in ("SAT", "UNSAT"):
        return [f"{label}: status {run['status']}"]
    if run["status"] == "SAT":
        ok, message = verify.verify_model(nvars, clauses, run["model"])
        if not ok:
            return [f"{label}: invalid SAT model: {message}"]
    return []


def median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def fmt_time(value: float | None) -> str:
    if value is None:
        return "TO"
    if value >= 1.0:
        return f"{value:.3f}"
    if value >= 0.001:
        return f"{value:.4f}"
    return f"{value:.6f}"


def fmt_conflicts(value: int | None) -> str:
    return "-" if value is None else f"{int(value):,}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, help="old solver binary")
    parser.add_argument("--candidate", required=True, help="new solver binary")
    parser.add_argument("--candidate-args", default="", help="extra candidate arguments")
    parser.add_argument("--reference", default="minisat")
    parser.add_argument("--suite", default="benchmarks/suite.json")
    parser.add_argument("--instances", default="benchmarks/instances")
    parser.add_argument("--reps", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--out-csv", default="results/before_after.csv")
    parser.add_argument("--out-md", default="results/before_after.md")
    parser.add_argument("--out-json", default="results/before_after.json")
    parser.add_argument("--work-dir", default="results/tmp")
    args = parser.parse_args()

    import shlex

    candidate_args = shlex.split(args.candidate_args)
    suite = json.loads(Path(args.suite).read_text(encoding="utf-8"))["instances"]
    instances_dir = Path(args.instances)
    work_dir = Path(args.work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    errors: list[str] = []

    for spec in suite:
        name = spec["name"]
        cnf = instances_dir / f"{name}.cnf"
        if not cnf.exists():
            errors.append(f"{name}: missing {cnf}")
            continue
        nvars, clauses = verify.parse_dimacs(cnf)
        print(f"[before/after] {name}", file=sys.stderr)

        before_times, after_times, reference_times = [], [], []
        before_conflicts, after_conflicts, reference_conflicts = [], [], []
        last = None
        for _ in range(args.reps):
            before = run_solver(args.baseline, [], cnf, args.timeout)
            after = run_solver(args.candidate, candidate_args, cnf, args.timeout)
            reference = run_reference(args.reference, cnf, args.timeout, work_dir)
            last = (before, after, reference)
            if "TIMEOUT" in (before["status"], after["status"]):
                break
            before_times.append(before["time"])
            after_times.append(after["time"])
            reference_times.append(reference["time"])
            if before["conflicts"] is not None:
                before_conflicts.append(before["conflicts"])
            if after["conflicts"] is not None:
                after_conflicts.append(after["conflicts"])
            if reference["conflicts"] is not None:
                reference_conflicts.append(reference["conflicts"])

        if last is None:
            continue
        before, after, reference = last
        errors.extend(validate(f"{name} before", before, nvars, clauses))
        errors.extend(validate(f"{name} after", after, nvars, clauses))
        errors.extend(validate(f"{name} MiniSat", reference, nvars, clauses))
        if not (before["status"] == after["status"] == reference["status"]):
            errors.append(
                f"{name}: status mismatch {before['status']}/{after['status']}/{reference['status']}"
            )

        rows.append(
            {
                "instance": name,
                "type": spec["type"],
                "status": after["status"],
                "before_time_s": median(before_times),
                "after_time_s": median(after_times),
                "reference_time_s": median(reference_times),
                "before_conflicts": median(before_conflicts),
                "after_conflicts": median(after_conflicts),
                "reference_conflicts": median(reference_conflicts),
                "reps": len(after_times),
            }
        )

    out_csv = Path(args.out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "instance",
        "type",
        "status",
        "before_time_s",
        "after_time_s",
        "reference_time_s",
        "before_conflicts",
        "after_conflicts",
        "reference_conflicts",
        "reps",
    ]
    with open(out_csv, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})

    metadata = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "baseline": args.baseline,
        "candidate": args.candidate,
        "candidate_args": candidate_args,
        "reference": args.reference,
        "reps": args.reps,
    }
    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(
        json.dumps({"metadata": metadata, "rows": rows}, indent=2) + "\n",
        encoding="utf-8",
    )

    lines = ["# Before/after experiment", ""]
    lines.append(
        "Interleaved runs on the same machine: old build, new build and MiniSat "
        "in every repetition. Median wall time. All SAT models checked and all "
        "three solvers agreed on SAT/UNSAT."
    )
    lines.append("")
    lines.append(
        "| Instance | Status | before s | after s | MiniSat s | after/before | "
        "after/MiniSat | before conflicts | after conflicts |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in rows:
        before_time = row["before_time_s"]
        after_time = row["after_time_s"]
        reference_time = row["reference_time_s"]
        speedup = (
            f"{before_time / after_time:.2f}x"
            if before_time and after_time and after_time > 0
            else "n/a"
        )
        ratio = (
            f"{after_time / reference_time:.2f}x"
            if after_time and reference_time and reference_time > 0
            else "n/a"
        )
        lines.append(
            "| {name} | {status} | {before} | {after} | {reference} | {speedup} | "
            "{ratio} | {bc} | {ac} |".format(
                name=row["instance"],
                status=row["status"],
                before=fmt_time(before_time),
                after=fmt_time(after_time),
                reference=fmt_time(reference_time),
                speedup=speedup,
                ratio=ratio,
                bc=fmt_conflicts(row["before_conflicts"]),
                ac=fmt_conflicts(row["after_conflicts"]),
            )
        )

    total_before = sum(row["before_time_s"] for row in rows if row["before_time_s"])
    total_after = sum(row["after_time_s"] for row in rows if row["after_time_s"])
    total_reference = sum(
        row["reference_time_s"] for row in rows if row["reference_time_s"]
    )
    improved = sum(
        1
        for row in rows
        if row["before_time_s"]
        and row["after_time_s"]
        and row["after_time_s"] < row["before_time_s"]
    )
    lines.append("")
    lines.append(
        f"Totals: {total_before:.3f} s before, {total_after:.3f} s after, "
        f"{total_reference:.3f} s for MiniSat. After is faster on {improved}/{len(rows)} instances."
    )
    lines.append("")
    lines.append(f"Generated: {metadata['timestamp']}")
    lines.append("")
    out_md = Path(args.out_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(lines), encoding="utf-8")

    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"wrote {out_csv}, {out_md}, {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
