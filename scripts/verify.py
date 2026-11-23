#!/usr/bin/env python3
"""Independent DIMACS/model checker and small-instance DPLL reference.

This file intentionally shares no code with the C++ solver.  SAT models are
checked clause by clause; UNSAT answers for small formulas can be confirmed
with a plain recursive DPLL search.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path


def parse_dimacs(path: str | Path) -> tuple[int, list[list[int]]]:
    lines: list[str] = []
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.lstrip()
            if not stripped or stripped.startswith("c"):
                continue
            lines.append(line)
    tokens = " ".join(lines).split()
    if not tokens or tokens[0] != "p":
        raise ValueError("missing DIMACS problem line")
    if len(tokens) < 4 or tokens[1] != "cnf":
        raise ValueError("invalid DIMACS header")
    nvars = int(tokens[2])
    nclauses = int(tokens[3])
    clauses: list[list[int]] = []
    current: list[int] = []
    for token in tokens[4:]:
        if token == "%":
            break
        literal = int(token)
        if literal == 0:
            clauses.append(current)
            current = []
        else:
            if abs(literal) < 1 or abs(literal) > nvars:
                raise ValueError(f"literal out of range: {literal}")
            current.append(literal)
    if current:
        raise ValueError("unterminated clause")
    if len(clauses) != nclauses:
        raise ValueError(f"header declares {nclauses} clauses, found {len(clauses)}")
    return nvars, clauses


def parse_status(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("s "):
            if "UNSAT" in stripped:
                return "UNSAT"
            if "SAT" in stripped:
                return "SAT"
            if "UNKNOWN" in stripped:
                return "UNKNOWN"
        if stripped in ("SAT", "UNSAT", "UNKNOWN"):
            return stripped
    return None


def parse_model(text: str) -> list[int]:
    literals: list[int] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("c"):
            continue
        if stripped.startswith("s "):
            continue
        if stripped.startswith("v"):
            body = stripped[1:]
        elif stripped in ("SAT", "UNSAT", "UNKNOWN"):
            continue
        else:
            body = stripped
        for token in body.split():
            try:
                literal = int(token)
            except ValueError:
                continue
            if literal == 0:
                break
            literals.append(literal)
    return literals


def verify_model(nvars: int, clauses: list[list[int]], literals: list[int]) -> tuple[bool, str]:
    assignment: dict[int, int] = {}
    for literal in literals:
        variable = abs(literal)
        value = 1 if literal > 0 else -1
        if variable < 1 or variable > nvars:
            return False, f"model literal out of range: {literal}"
        if variable in assignment and assignment[variable] != value:
            return False, f"contradictory model literals for variable {variable}"
        assignment[variable] = value
    missing = [v for v in range(1, nvars + 1) if v not in assignment]
    if missing:
        return False, f"model leaves {len(missing)} variable(s) unassigned"
    for index, clause in enumerate(clauses):
        if not any((assignment[abs(lit)] > 0) == (lit > 0) for lit in clause):
            return False, f"clause {index + 1} is not satisfied"
    return True, "model satisfies every clause"


def dpll_solve(
    nvars: int, clauses: list[list[int]], timeout: float = 5.0
) -> bool | None:
    """Plain DPLL with unit propagation.  Returns None when the deadline hits."""
    deadline = time.monotonic() + timeout
    assignment = [0] * (nvars + 1)

    def search(values: list[int]) -> bool:
        if time.monotonic() > deadline:
            raise TimeoutError
        values = values[:]
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError
            units: list[int] = []
            all_satisfied = True
            for clause in clauses:
                satisfied = False
                unassigned: list[int] = []
                for literal in clause:
                    value = values[abs(literal)]
                    if value == 0:
                        unassigned.append(literal)
                    elif (value > 0) == (literal > 0):
                        satisfied = True
                        break
                if satisfied:
                    continue
                all_satisfied = False
                if not unassigned:
                    return False
                if len(unassigned) == 1:
                    units.append(unassigned[0])
            if all_satisfied:
                return True
            if not units:
                break
            for literal in units:
                variable = abs(literal)
                wanted = 1 if literal > 0 else -1
                if values[variable] not in (0, wanted):
                    return False
                values[variable] = wanted

        counts: dict[int, int] = {}
        for clause in clauses:
            if any(
                values[abs(lit)] != 0 and (values[abs(lit)] > 0) == (lit > 0)
                for lit in clause
            ):
                continue
            for literal in clause:
                variable = abs(literal)
                if values[variable] == 0:
                    counts[variable] = counts.get(variable, 0) + 1
        if not counts:
            return True
        variable = max(counts, key=counts.get)
        for wanted in (1, -1):
            branch = values[:]
            branch[variable] = wanted
            if search(branch):
                return True
        return False

    try:
        return search(assignment)
    except TimeoutError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cnf", required=True, help="DIMACS CNF file")
    parser.add_argument("--model", default=None, help="literal string or solver output")
    parser.add_argument("--model-file", default=None, help="file with model/output")
    parser.add_argument("--solve", action="store_true", help="run independent DPLL")
    parser.add_argument("--timeout", type=float, default=10.0, help="DPLL timeout")
    args = parser.parse_args()

    nvars, clauses = parse_dimacs(args.cnf)
    if args.solve:
        result = dpll_solve(nvars, clauses, args.timeout)
        print("SAT" if result is True else "UNSAT" if result is False else "UNKNOWN")
        return 0 if result is not None else 2

    text = args.model or ""
    if args.model_file:
        text = Path(args.model_file).read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        print("no model supplied", file=sys.stderr)
        return 2
    literals = parse_model(text)
    ok, message = verify_model(nvars, clauses, literals)
    print(("VERIFIED: " if ok else "INVALID: ") + message)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
