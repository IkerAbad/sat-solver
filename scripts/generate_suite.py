#!/usr/bin/env python3
"""Generate the deterministic benchmark suite from benchmarks/suite.json."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def generator_command(satgen: str, spec: dict, out_path: Path) -> list[str]:
    kind = spec["type"]
    command = [satgen]
    if kind == "random3":
        command += [
            "random3",
            "--vars",
            str(spec["vars"]),
            "--ratio",
            str(spec["ratio"]),
            "--seed",
            str(spec["seed"]),
        ]
    elif kind == "php":
        command += [
            "php",
            "--pigeons",
            str(spec["pigeons"]),
            "--holes",
            str(spec["holes"]),
        ]
    elif kind == "coloring":
        command += [
            "coloring",
            "--vertices",
            str(spec["vertices"]),
            "--colors",
            str(spec["colors"]),
            "--edge-prob",
            str(spec["edge_prob"]),
            "--seed",
            str(spec["seed"]),
        ]
        if spec.get("planted", False):
            command.append("--planted")
    else:
        raise ValueError(f"unknown instance type: {kind}")
    command += ["--out", str(out_path)]
    return command


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--satgen", required=True, help="path to the satgen binary")
    parser.add_argument("--suite", default="benchmarks/suite.json")
    parser.add_argument("--out", default="benchmarks/instances")
    args = parser.parse_args()

    suite_path = Path(args.suite)
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    instances = suite["instances"]
    names = [item["name"] for item in instances]
    if len(names) != len(set(names)):
        raise ValueError("duplicate instance names in suite")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    for spec in instances:
        path = out_dir / f"{spec['name']}.cnf"
        command = generator_command(args.satgen, spec, path)
        subprocess.run(command, check=True)
        print(f"generated {path}")

    print(f"{len(instances)} instances in {out_dir}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (subprocess.CalledProcessError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
