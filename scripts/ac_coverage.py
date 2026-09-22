"""AC01-AC44 coverage and evidence mapping (A11, wave 5; spec §22, COVERAGE_MATRIX §2).

The matrix in ``COVERAGE_MATRIX.md`` says who *owns* an AC. This script answers the other half: which test
actually exercises it and what that test did in a given run. It never decides the verdict itself - it joins
two facts:

1. **mapping** - every ``ACnn`` token that appears in a test function (name, docstring or body) or in the
   module docstring of a test file, found with the AST, so a rename cannot silently orphan an AC;
2. **result** - the outcome of those tests in one pytest run, read from a JUnit XML
   (``pytest --junitxml=...``). No XML -> the result column stays ``NOT_RUN``: "a test exists" and "the test
   passed" are different states (AGENTS §7).

An AC with no test is reported as ``NO_TEST`` with its owner from COVERAGE_MATRIX, not silently dropped, and
field ACs (Android: AC27 field part, AC32) are flagged ``FIELD`` because this repository cannot prove them.

Usage::

    py -m pytest -q --junitxml=junit.xml            # the authoritative run
    py scripts/ac_coverage.py --junit junit.xml --format md > matrix.md
    py scripts/ac_coverage.py --format json          # mapping only
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = REPO_ROOT / "tests"
# Case-insensitive, and an underscore counts as a boundary: a test *named* after its AC writes it lowercase
# inside an identifier (``test_ac07_...``), where ``\b`` would not match.
AC_RE = re.compile(r"(?<![A-Za-z0-9])AC(\d{2})(?![A-Za-z0-9])", re.IGNORECASE)
# "AC02-AC12" / "AC02–AC12" names a range: that file covers both ends and everything between.
AC_RANGE_RE = re.compile(r"(?<![A-Za-z0-9])AC(\d{2})\s*[-–]\s*AC(\d{2})(?![A-Za-z0-9])", re.IGNORECASE)
ALL_ACS = tuple(f"AC{n:02d}" for n in range(1, 45))
# Acceptance items this repository cannot prove: the Android field part belongs to the Android developer
# (spec §10.5, AGENTS §7) and is never reported as passed here.
FIELD_ACS = {"AC32": "Android field evidence (AC32) - out of stage-2 backend scope", }
PARTIAL_FIELD_ACS = {"AC27": "backend part here; force-stop/battery-saver field part is the Android developer's"}
# Acceptance items proven by a procedure, not by the test suite.
PROCEDURE_ACS = {
    "AC40": "restore drill (scripts/restore_drill.sh) - DRILL evidence, not a pytest node",
}


@dataclass
class TestNode:
    nodeid: str
    acs: set[str] = field(default_factory=set)


def _acs_in(text: str) -> set[str]:
    found = {f"AC{value}" for value in AC_RE.findall(text)}
    for start, end in AC_RANGE_RE.findall(text):
        found.update(f"AC{n:02d}" for n in range(int(start), int(end) + 1))
    return found


def _function_acs(node: ast.FunctionDef | ast.AsyncFunctionDef, source: str) -> set[str]:
    segment = ast.get_source_segment(source, node) or ""
    return _acs_in(f"{node.name}\n{segment}")


def collect(tests_dir: Path = TESTS_DIR) -> tuple[dict[str, TestNode], dict[str, set[str]]]:
    """Return (nodeid -> TestNode, ac -> set of file-level references)."""
    nodes: dict[str, TestNode] = {}
    file_level: dict[str, set[str]] = defaultdict(set)
    for path in sorted(tests_dir.rglob("test_*.py")):
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:  # pragma: no cover - a broken test file is a separate failure
            print(f"warning: cannot parse {path}: {exc}", file=sys.stderr)
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        module_doc = ast.get_docstring(tree) or ""
        for ac in _acs_in(module_doc):
            file_level[ac].add(rel)
        for item in ast.walk(tree):
            if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef) and item.name.startswith("test_"):
                nodeid = f"{rel}::{item.name}"
                nodes[nodeid] = TestNode(nodeid=nodeid, acs=_function_acs(item, source))
    return nodes, dict(file_level)


def read_junit(path: Path) -> dict[str, str]:
    """nodeid -> PASS | FAIL | ERROR | SKIP, keyed like ``tests/pg/x.py::test_y``."""
    results: dict[str, str] = {}
    root = ElementTree.parse(path).getroot()
    for case in root.iter("testcase"):
        classname, name = case.get("classname", ""), case.get("name", "")
        file_attr = case.get("file")
        parts = classname.split(".")
        if file_attr:
            nodeid = f"{file_attr}::{name}"
        else:
            # pytest's junitxml has no "file" attribute by default: the classname is the dotted module path
            # (plus the class name for class-based tests), so rebuild the path from the part that ends in a
            # module of the tests package.
            module_parts = parts[:-1] if parts and parts[-1][:1].isupper() else parts
            nodeid = f"{'/'.join(module_parts)}.py::{name}"
        verdict = "PASS"
        if case.find("failure") is not None:
            verdict = "FAIL"
        elif case.find("error") is not None:
            verdict = "ERROR"
        elif case.find("skipped") is not None:
            verdict = "SKIP"
        key = nodeid.replace("\\", "/")
        results[key] = verdict
        # A parametrised test appears as "test_x[case]"; the mapping knows the function, so the base name
        # carries the worst verdict of its cases (one failing case must not be hidden by a passing one).
        base = key.split("[", 1)[0]
        if base != key:
            order = {"PASS": 0, "SKIP": 1, "FAIL": 2, "ERROR": 3}
            if order[verdict] >= order.get(results.get(base, "PASS"), 0):
                results[base] = verdict
    return results


def build(junit: Path | None) -> list[dict[str, object]]:
    nodes, file_level = collect()
    results = read_junit(junit) if junit else {}
    by_ac: dict[str, list[str]] = defaultdict(list)
    for node in nodes.values():
        for ac in node.acs:
            by_ac[ac].append(node.nodeid)

    tests_by_file: dict[str, list[str]] = defaultdict(list)
    for nodeid in results or {}:
        tests_by_file[nodeid.split("::", 1)[0]].append(nodeid)
    all_test_nodeids = {node.nodeid for node in nodes.values()}
    for nodeid in all_test_nodeids:
        path = nodeid.split("::", 1)[0]
        if nodeid not in tests_by_file[path]:
            tests_by_file[path].append(nodeid)

    rows: list[dict[str, object]] = []
    for ac in ALL_ACS:
        tests = sorted(by_ac.get(ac, []))
        files = sorted(file_level.get(ac, []))
        if not tests:
            # The AC is named in a test file's module docstring: its tests are the evidence for it.
            tests = sorted({nodeid for f in files for nodeid in tests_by_file.get(f, [])})
        verdicts = {test: results.get(test, "NOT_RUN") for test in tests}
        if ac in FIELD_ACS:
            status = "FIELD"
        elif not tests:
            status = "NO_TEST" if ac not in PROCEDURE_ACS else "PROCEDURE"
        elif not results:
            status = "NOT_RUN"
        elif any(v in {"FAIL", "ERROR"} for v in verdicts.values()):
            status = "FAIL"
        elif all(v == "SKIP" for v in verdicts.values()):
            status = "SKIPPED"
        elif any(v == "NOT_RUN" for v in verdicts.values()):
            status = "PARTIAL"
        else:
            status = "PASS"
        note = FIELD_ACS.get(ac) or PARTIAL_FIELD_ACS.get(ac) or PROCEDURE_ACS.get(ac, "")
        rows.append(
            {
                "ac": ac,
                "status": status,
                "tests": tests,
                "verdicts": verdicts,
                "files": files,
                "note": note,
            }
        )
    return rows


def render_md(rows: list[dict[str, object]], *, max_tests: int = 2) -> str:
    """Compact table: status, how many tests carry the AC, the first few by name, and the note.

    A test named after its AC (``test_ac07_...``) is listed first: it is the direct evidence, the rest of the
    file's tests are the context the module docstring claims for that AC.
    """
    lines = ["| AC | Holat | Testlar | Dalil (birinchi nomlar) | Izoh |", "|---|---|---|---|---|"]
    for row in rows:
        tests = row["tests"]
        assert isinstance(tests, list)
        ac_token = str(row["ac"]).lower()
        ordered = sorted(tests, key=lambda test: (ac_token not in test.lower(), test))
        shown = "<br>".join(f"`{test}`" for test in ordered[:max_tests]) if ordered else "—"
        if len(ordered) > max_tests:
            shown += f"<br>… +{len(ordered) - max_tests}"
        lines.append(f"| {row['ac']} | {row['status']} | {len(tests)} | {shown} | {row['note']} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    # Windows consoles default to a legacy code page; this report is Markdown and must stay UTF-8 when
    # redirected into a file (a cp1252 em dash silently corrupts the document).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junit", type=Path, default=None, help="pytest --junitxml output of the run to join")
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--fail-on", default="", help="comma-separated statuses that make this script exit 1")
    args = parser.parse_args(argv)

    rows = build(args.junit)
    print(render_md(rows) if args.format == "md" else json.dumps(rows, indent=2, ensure_ascii=False))
    bad = {value.strip() for value in args.fail_on.split(",") if value.strip()}
    return 1 if bad and any(row["status"] in bad for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
