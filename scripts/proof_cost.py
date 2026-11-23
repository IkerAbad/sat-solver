#!/usr/bin/env python3
"""Measure DRAT proof cost and verify every UNSAT proof with drat-trim.

Both runs use the same solver binary and the same instances. The baseline run
does not emit a proof; the proof run writes text DRAT. For UNSAT instances the
proof must be accepted by drat-trim or this script fails.
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


def parse_ours_conflicts(stdout: str) -> int | None:
    match = re.search(r"^c conflicts\s+(\d+)\s*$", stdout, re.MULTILINE)
    return int(match.group(1)) if match else None


def parse_proof_clauses(stdout: str) -> int | None:
    match = re.search(r"^c proof_clauses\s+(\d+)\s*$", stdout, re.MULTILINE)
    return int(match.group(1)) if match else None


def run_solver(
    solver: str,
    cnf: Path,
    timeout: float,
    proof_path: Path | None,
) -> dict:
    command = [solver]
    if proof_path is not None:
        command.append(f"--proof={proof_path}")
    command.append(str(cnf))
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
            "proof_clauses": parse_proof_clauses(completed.stdout),
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
            "proof_clauses": None,
            "model": [],
            "stdout": "",
            "stderr": "",
            "returncode": None,
        }


def validate_model(run: dict, nvars: int, clauses: list[list[int]], label: str) -> list[str]:
    if run["status"] not in ("SAT", "UNSAT"):
        return [f"{label}: invalid status {run['status']}"]
    if run["status"] == "SAT":
        ok, message = verify.verify_model(nvars, clauses, run["model"])
        if not ok:
            return [f"{label}: invalid SAT model: {message}"]
    return []


def run_drat_trim(
    drat_trim: str, cnf: Path, proof: Path, timeout: float
) -> tuple[bool, float, str]:
    start = time.perf_counter()
    try:
        completed = subprocess.run(
            [drat_trim, str(cnf), str(proof)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = time.perf_counter() - start
        output = completed.stdout + completed.stderr
        verified = completed.returncode == 0 and "s VERIFIED" in output
        return verified, elapsed, output
    except subprocess.TimeoutExpired:
        return False, timeout, "drat-trim timed out"


def median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def format_seconds(value: float | None) -> str:
    if value is None:
        return "TO"
    if value >= 1.0:
        return f"{value:.3f}"
    if value >= 0.001:
        return f"{value:.4f}"
    return f"{value:.6f}"


def format_size(num_bytes: int | None) -> str:
    if num_bytes is None:
        return "-"
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KiB"
    return f"{num_bytes / (1024 * 1024):.2f} MiB"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--solver", required=True)
    parser.add_argument("--drat-trim", required=True)
    parser.add_argument("--suite", default="benchmarks/suite.json")
    parser.add_argument("--instances", default="benchmarks/instances")
    parser.add_argument("--proofs", default="results/proofs")
    parser.add_argument("--out-csv", default="results/proof_cost.csv")
    parser.add_argument("--out-md", default="results/proof_cost.md")
    parser.add_argument("--out-json", default="results/proof_cost.json")
    parser.add_argument("--reps", type=int, default=None)
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--drat-timeout", type=float, default=180.0)
    args = parser.parse_args()

    suite = json.loads(Path(args.suite).read_text(encoding="utf-8"))
    instances_dir = Path(args.instances)
    proofs_dir = Path(args.proofs)
    proofs_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    errors: list[str] = []

    for spec in suite["instances"]:
        name = spec["name"]
        cnf = instances_dir / f"{name}.cnf"
        if not cnf.exists():
            errors.append(f"{name}: missing {cnf}")
            continue
        nvars, clauses = verify.parse_dimacs(cnf)
        reps = args.reps if args.reps is not None else int(spec.get("reps", 3))
        timeout = args.timeout if args.timeout is not None else float(spec.get("timeout", 30))
        proof_path = proofs_dir / f"{name}.drat"

        print(f"[proof cost] {name}", file=sys.stderr)

        base_times: list[float] = []
        base_run = None
        for _ in range(reps):
            base_run = run_solver(args.solver, cnf, timeout, None)
            if base_run["status"] == "TIMEOUT":
                break
            base_times.append(base_run["time"])

        proof_times: list[float] = []
        proof_run = None
        for _ in range(reps):
            proof_path.unlink(missing_ok=True)
            proof_run = run_solver(args.solver, cnf, timeout, proof_path)
            if proof_run["status"] == "TIMEOUT":
                break
            proof_times.append(proof_run["time"])

        if base_run is None or proof_run is None:
            errors.append(f"{name}: no solver run")
            continue

        errors.extend(validate_model(base_run, nvars, clauses, f"{name} baseline"))
        errors.extend(validate_model(proof_run, nvars, clauses, f"{name} proof"))
        if base_run["status"] != proof_run["status"]:
            errors.append(
                f"{name}: status changed with proof: "
                f"{base_run['status']} -> {proof_run['status']}"
            )

        proof_size = proof_path.stat().st_size if proof_path.exists() else None
        proof_clauses = proof_run["proof_clauses"]
        verify_time = None
        verify_result = "n/a"

        if proof_run["status"] == "UNSAT":
            if not proof_path.exists() or proof_path.stat().st_size == 0:
                errors.append(f"{name}: UNSAT proof file is missing or empty")
                verify_result = "missing"
            else:
                verified, verify_time, output = run_drat_trim(
                    args.drat_trim, cnf, proof_path, args.drat_timeout
                )
                if verified:
                    verify_result = "verified"
                else:
                    errors.append(f"{name}: DRAT proof rejected")
                    verify_result = "rejected"
                    print(output, file=sys.stderr)
        elif proof_run["status"] == "SAT":
            verify_result = "SAT model checked"

        base_time = median(base_times)
        proof_time = median(proof_times)
        overhead = None
        if base_time is not None and proof_time is not None and base_time > 0:
            overhead = (proof_time - base_time) / base_time

        rows.append(
            {
                "instance": name,
                "type": spec["type"],
                "status": proof_run["status"],
                "vars": nvars,
                "clauses": len(clauses),
                "base_time_s": base_time,
                "proof_time_s": proof_time,
                "overhead_fraction": overhead,
                "proof_bytes": proof_size,
                "proof_clauses": proof_clauses,
                "drat_verified": verify_result == "verified",
                "drat_check_s": verify_time,
                "drat_result": verify_result,
            }
        )

    metadata = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "solver": args.solver,
        "drat_trim": args.drat_trim,
        "reps": args.reps,
        "timeout": args.timeout,
    }

    out_csv = Path(args.out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "instance",
        "type",
        "status",
        "vars",
        "clauses",
        "base_time_s",
        "proof_time_s",
        "overhead_fraction",
        "proof_bytes",
        "proof_clauses",
        "drat_verified",
        "drat_check_s",
        "drat_result",
    ]
    with open(out_csv, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})

    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(
        json.dumps({"metadata": metadata, "rows": rows}, indent=2) + "\n",
        encoding="utf-8",
    )

    lines = ["# DRAT proof cost", ""]
    lines.append(
        "Median end-to-end wall time without and with `--proof`, plus the text "
        "DRAT file size. UNSAT proofs are checked by drat-trim; SAT runs only "
        "produce a partial proof and are marked accordingly."
    )
    lines.append("")
    lines.append(
        "| Instance | Status | no proof s | with proof s | delta | proof size | "
        "proof clauses | DRAT check s | result |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---|")
    for row in rows:
        delta = "-"
        if row["overhead_fraction"] is not None:
            delta = f"{row['overhead_fraction'] * 100:+.1f}%"
        check_time = (
            format_seconds(row["drat_check_s"])
            if row["drat_check_s"] is not None
            else "-"
        )
        lines.append(
            "| {name} | {status} | {base} | {proof} | {delta} | {size} | {clauses} | "
            "{check} | {result} |".format(
                name=row["instance"],
                status=row["status"],
                base=format_seconds(row["base_time_s"]),
                proof=format_seconds(row["proof_time_s"]),
                delta=delta,
                size=format_size(row["proof_bytes"]),
                clauses=row["proof_clauses"] if row["proof_clauses"] is not None else "-",
                check=check_time,
                result=row["drat_result"],
            )
        )
    lines.append("")

    unsat = [row for row in rows if row["status"] == "UNSAT"]
    verified = [row for row in unsat if row["drat_verified"]]
    total_base = sum(row["base_time_s"] for row in rows if row["base_time_s"] is not None)
    total_proof = sum(row["proof_time_s"] for row in rows if row["proof_time_s"] is not None)
    total_size = sum(row["proof_bytes"] for row in rows if row["proof_bytes"] is not None)
    total_check = sum(row["drat_check_s"] for row in unsat if row["drat_check_s"] is not None)
    lines.append(
        f"UNSAT proofs verified: {len(verified)}/{len(unsat)}. "
        f"Total solve time: {total_base:.3f} s without proof, {total_proof:.3f} s with proof. "
        f"Total proof size: {format_size(total_size)}. "
        f"Total drat-trim time: {total_check:.2f} s."
    )
    lines.append("")
    lines.append(f"Generated: {metadata['timestamp']}")
    lines.append("")
    out_md = Path(args.out_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(lines), encoding="utf-8")

    if errors:
        print("\n".join(errors), file=sys.stderr)
        print(f"{len(errors)} proof cost error(s)", file=sys.stderr)
        return 1
    print(f"wrote {out_csv}, {out_md}, {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
