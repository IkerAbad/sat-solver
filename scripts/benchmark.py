#!/usr/bin/env python3
"""Run the benchmark suite against a reference SAT solver.

The script never trusts a solver's answer on its own: every SAT model is
checked clause by clause by verify.py, both solvers must agree on SAT/UNSAT,
and small UNSAT answers are confirmed with an independent Python DPLL.
"""

from __future__ import annotations

import argparse
import csv
import json
import platform
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import verify


def parse_ours_conflicts(stdout: str) -> int | None:
    match = re.search(r"^c conflicts\s+(\d+)\s*$", stdout, re.MULTILINE)
    return int(match.group(1)) if match else None


def parse_reference_conflicts(stdout: str) -> int | None:
    match = re.search(r"^conflicts\s*:\s*(\d+)", stdout, re.MULTILINE)
    return int(match.group(1)) if match else None


def run_ours(
    solver: str,
    cnf: Path,
    heuristic: str,
    timeout: float,
    trace_path: Path | None = None,
) -> dict:
    command = [solver, f"--heuristic={heuristic}", str(cnf)]
    if trace_path is not None:
        command += [f"--trace={trace_path}", "--trace-stride=4"]
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
            "conflicts": parse_ours_conflicts(completed.stdout),
            "model": verify.parse_model(completed.stdout),
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "returncode": completed.returncode,
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "TIMEOUT",
            "time": timeout,
            "conflicts": None,
            "model": [],
            "stdout": "",
            "stderr": "",
            "returncode": None,
        }


def run_reference(
    reference: str, cnf: Path, timeout: float, work_dir: Path
) -> dict:
    result_file = work_dir / f"{cnf.stem}.reference.out"
    result_file.unlink(missing_ok=True)
    command = [reference, str(cnf), str(result_file)]
    start = time.perf_counter()
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout
        )
        elapsed = time.perf_counter() - start
        output = ""
        if result_file.exists():
            output = result_file.read_text(encoding="utf-8", errors="replace")
        status = verify.parse_status(output)
        return {
            "status": status or "UNKNOWN",
            "time": elapsed,
            "conflicts": parse_reference_conflicts(completed.stdout),
            "model": verify.parse_model(output),
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "returncode": completed.returncode,
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "TIMEOUT",
            "time": timeout,
            "conflicts": None,
            "model": [],
            "stdout": "",
            "stderr": "",
            "returncode": None,
        }
    finally:
        result_file.unlink(missing_ok=True)


def validate_run(
    label: str,
    run: dict,
    nvars: int,
    clauses: list[list[int]],
    allow_timeout: bool,
) -> list[str]:
    errors: list[str] = []
    status = run["status"]
    if status == "TIMEOUT":
        if not allow_timeout:
            errors.append(f"{label}: timed out")
        return errors

    if status not in ("SAT", "UNSAT"):
        errors.append(f"{label}: no valid status (got {status})")
        return errors

    if status == "SAT":
        ok, message = verify.verify_model(nvars, clauses, run["model"])
        if not ok:
            errors.append(f"{label}: invalid SAT model: {message}")
    return errors


def measure_runs(runner, reps: int, timeout: float) -> tuple[list[float], list[int], dict]:
    times: list[float] = []
    conflicts: list[int] = []
    last = None
    for _ in range(reps):
        run = runner()
        last = run
        if run["status"] == "TIMEOUT":
            break
        times.append(run["time"])
        if run["conflicts"] is not None:
            conflicts.append(run["conflicts"])
        if run["status"] not in ("SAT", "UNSAT"):
            break
    return times, conflicts, last or {
        "status": "UNKNOWN",
        "time": timeout,
        "conflicts": None,
        "model": [],
    }


def median_or_none(values: list[int]) -> float | None:
    return statistics.median(values) if values else None


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "instance",
        "type",
        "vars",
        "clauses",
        "status",
        "heuristic",
        "solver",
        "time_s",
        "conflicts",
        "runs",
        "verified",
        "note",
    ]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})


def format_time(value: float | None) -> str:
    if value is None:
        return "TO"
    if value >= 1.0:
        return f"{value:.3f}"
    if value >= 0.001:
        return f"{value:.4f}"
    return f"{value:.6f}"


def format_conflicts(value) -> str:
    if value is None or value == "":
        return "-"
    return str(int(round(float(value))))


def ratio_text(ours: float | None, reference: float | None) -> str:
    if ours is None or reference is None or reference <= 0:
        return "n/a"
    return f"{ours / reference:.2f}x"


def write_compare_markdown(path: Path, rows: list[dict], metadata: dict) -> None:
    by_instance: dict[str, dict[str, dict]] = {}
    order: list[str] = []
    for row in rows:
        name = row["instance"]
        if name not in by_instance:
            by_instance[name] = {}
            order.append(name)
        by_instance[name][row["solver"]] = row

    lines: list[str] = []
    lines.append("# Benchmark: satsolver vs MiniSat")
    lines.append("")
    lines.append(
        "End-to-end wall time, median of the successful repetitions. "
        "`TO` means the timeout was reached. Every SAT model was checked "
        "independently; SAT/UNSAT answers must agree."
    )
    lines.append("")

    current_type = None
    for name in order:
        ours = by_instance[name].get("satsolver", {})
        reference = by_instance[name].get("minisat", {})
        kind = ours.get("type", reference.get("type", ""))
        if kind != current_type:
            lines.append(f"## {kind}")
            lines.append("")
            lines.append(
                "| Instance | Status | satsolver s | satsolver conflicts | "
                "MiniSat s | MiniSat conflicts | Time ratio |"
            )
            lines.append("|---|---:|---:|---:|---:|---:|---:|")
            current_type = kind
        lines.append(
            "| {name} | {status} | {ot} | {oc} | {rt} | {rc} | {ratio} |".format(
                name=name,
                status=ours.get("status", reference.get("status", "")),
                ot=format_time(ours.get("time_s")),
                oc=format_conflicts(ours.get("conflicts")),
                rt=format_time(reference.get("time_s")),
                rc=format_conflicts(reference.get("conflicts")),
                ratio=ratio_text(ours.get("time_s"), reference.get("time_s")),
            )
        )
    lines.append("")

    ours_times = [row["time_s"] for row in rows if row["solver"] == "satsolver" and row["time_s"] is not None]
    ref_times = [row["time_s"] for row in rows if row["solver"] == "minisat" and row["time_s"] is not None]
    wins = sum(
        1
        for name in order
        if by_instance[name].get("satsolver", {}).get("time_s") is not None
        and by_instance[name].get("minisat", {}).get("time_s") is not None
        and by_instance[name]["satsolver"]["time_s"]
        < by_instance[name]["minisat"]["time_s"]
    )
    lines.append(
        f"Totals: satsolver {sum(ours_times):.3f} s, MiniSat {sum(ref_times):.3f} s, "
        f"satsolver faster on {wins}/{len(order)} instances."
    )
    lines.append("")
    lines.append(f"Generated: {metadata['timestamp']}")
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def write_heuristics_markdown(path: Path, rows: list[dict], heuristics: list[str]) -> None:
    grouped: dict[str, dict[str, dict]] = {}
    order: list[str] = []
    for row in rows:
        name = row["instance"]
        if name not in grouped:
            grouped[name] = {}
            order.append(name)
        grouped[name][row["heuristic"]] = row

    lines = ["# Decision heuristic comparison", ""]
    lines.append(
        "Median wall time and conflicts. `TO` means the timeout was reached. "
        "All SAT models were verified independently."
    )
    lines.append("")
    header = "| Instance | " + " | ".join(heuristics) + " |"
    lines.append(header)
    lines.append("|---|" + "---|" * len(heuristics))
    for name in order:
        cells = []
        for heuristic in heuristics:
            row = grouped[name].get(heuristic, {})
            cells.append(
                f"{format_time(row.get('time_s'))} s / "
                f"{format_conflicts(row.get('conflicts'))}"
            )
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["compare", "heuristics"], default="compare")
    parser.add_argument("--solver", required=True)
    parser.add_argument("--reference", default="minisat")
    parser.add_argument("--suite", default="benchmarks/suite.json")
    parser.add_argument("--instances", default="benchmarks/instances")
    parser.add_argument("--heuristics", default="vsids,vmtf,random")
    parser.add_argument("--reps", type=int, default=None)
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--out-csv", default="results/compare.csv")
    parser.add_argument("--out-md", default="results/compare.md")
    parser.add_argument("--out-json", default="results/compare.json")
    parser.add_argument("--trace-dir", default="results/traces")
    parser.add_argument("--work-dir", default="results/tmp")
    args = parser.parse_args()

    suite = json.loads(Path(args.suite).read_text(encoding="utf-8"))
    specs = suite["instances"]
    spec_by_name = {spec["name"]: spec for spec in specs}
    instances_dir = Path(args.instances)
    work_dir = Path(args.work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    trace_dir = Path(args.trace_dir)
    trace_dir.mkdir(parents=True, exist_ok=True)

    if args.mode == "heuristics":
        selected = [spec for spec in specs if spec.get("heuristics", False)] or specs
        heuristics = [item.strip() for item in args.heuristics.split(",") if item.strip()]
    else:
        selected = specs
        heuristics = ["vsids"]

    rows: list[dict] = []
    errors: list[str] = []

    for spec in selected:
        name = spec["name"]
        cnf = instances_dir / f"{name}.cnf"
        if not cnf.exists():
            errors.append(f"{name}: missing {cnf}")
            continue
        nvars, clauses = verify.parse_dimacs(cnf)
        reps = args.reps if args.reps is not None else int(spec.get("reps", 3))
        timeout = args.timeout if args.timeout is not None else float(spec.get("timeout", 30))

        if args.mode == "compare":
            print(f"[compare] {name}", file=sys.stderr)
            run = {}
            times, conflicts, run = measure_runs(
                lambda: run_ours(args.solver, cnf, "vsids", timeout), reps, timeout
            )
            ours_time = statistics.median(times) if times else None
            errors.extend(
                validate_run(
                    f"{name} satsolver",
                    run,
                    nvars,
                    clauses,
                    allow_timeout=False,
                )
            )

            ref_times, ref_conflicts, ref_run = measure_runs(
                lambda: run_reference(args.reference, cnf, timeout, work_dir),
                reps,
                timeout,
            )
            ref_time = statistics.median(ref_times) if ref_times else None
            errors.extend(
                validate_run(
                    f"{name} reference",
                    ref_run,
                    nvars,
                    clauses,
                    allow_timeout=True,
                )
            )

            ours_status = run["status"]
            ref_status = ref_run["status"]
            if ours_status in ("SAT", "UNSAT") and ref_status in ("SAT", "UNSAT"):
                if ours_status != ref_status:
                    errors.append(
                        f"{name}: status mismatch: satsolver={ours_status}, "
                        f"MiniSat={ref_status}"
                    )

            note = "status agreement"
            if ours_status == "UNSAT" and nvars <= 26:
                dpll = verify.dpll_solve(nvars, clauses, timeout=10.0)
                if dpll is True:
                    errors.append(f"{name}: independent DPLL says SAT, solver says UNSAT")
                    note = "DPLL disagrees"
                elif dpll is False:
                    note = "DPLL-confirmed UNSAT"
                else:
                    note = "DPLL timeout"

            verified = not any(error.startswith(name + " ") for error in errors)
            rows.append(
                {
                    "instance": name,
                    "type": spec["type"],
                    "vars": nvars,
                    "clauses": len(clauses),
                    "status": ours_status,
                    "heuristic": "vsids",
                    "solver": "satsolver",
                    "time_s": ours_time,
                    "conflicts": median_or_none(conflicts),
                    "runs": len(times),
                    "verified": verified,
                    "note": note,
                }
            )
            rows.append(
                {
                    "instance": name,
                    "type": spec["type"],
                    "vars": nvars,
                    "clauses": len(clauses),
                    "status": ref_status,
                    "heuristic": "vsids",
                    "solver": "minisat",
                    "time_s": ref_time,
                    "conflicts": median_or_none(ref_conflicts),
                    "runs": len(ref_times),
                    "verified": verified,
                    "note": "reference",
                }
            )
        else:
            print(f"[heuristics] {name}", file=sys.stderr)
            for heuristic in heuristics:
                trace_path = None
                if spec.get("trace", False):
                    trace_path = trace_dir / f"{name}_{heuristic}.csv"
                times, conflicts, run = measure_runs(
                    lambda h=heuristic, t=trace_path: run_ours(
                        args.solver, cnf, h, timeout, t
                    ),
                    reps,
                    timeout,
                )
                errors.extend(
                    validate_run(
                        f"{name} {heuristic}",
                        run,
                        nvars,
                        clauses,
                        allow_timeout=True,
                    )
                )
                rows.append(
                    {
                        "instance": name,
                        "type": spec["type"],
                        "vars": nvars,
                        "clauses": len(clauses),
                        "status": run["status"],
                        "heuristic": heuristic,
                        "solver": "satsolver",
                        "time_s": statistics.median(times) if times else None,
                        "conflicts": median_or_none(conflicts),
                        "runs": len(times),
                        "verified": run["status"] in ("SAT", "UNSAT")
                        and not any(
                            error.startswith(f"{name} {heuristic} ") for error in errors
                        ),
                        "note": "",
                    }
                )

    metadata = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "mode": args.mode,
        "solver": args.solver,
        "reference": args.reference,
        "platform": platform.platform(),
        "processor": platform.processor(),
        "python": platform.python_version(),
        "repetitions": args.reps,
        "timeout": args.timeout,
    }

    write_csv(Path(args.out_csv), rows)
    Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_json).write_text(
        json.dumps({"metadata": metadata, "rows": rows}, indent=2) + "\n",
        encoding="utf-8",
    )
    if args.mode == "compare":
        write_compare_markdown(Path(args.out_md), rows, metadata)
    else:
        write_heuristics_markdown(Path(args.out_md), rows, heuristics)

    if errors:
        print("\n".join(errors), file=sys.stderr)
        print(f"{len(errors)} validation error(s)", file=sys.stderr)
        return 1
    print(f"wrote {args.out_csv}, {args.out_md}, {args.out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
