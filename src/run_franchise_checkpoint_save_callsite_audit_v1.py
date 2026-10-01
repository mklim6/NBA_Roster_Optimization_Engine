from __future__ import annotations

import ast
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUT_ROOT = ROOT / "outputs" / "v2_checkpoint_save_callsite_audit_v1"
VERSION = "franchise-checkpoint-save-callsite-audit-v1-2026-09-28"


@dataclass
class Callsite:
    file: str
    line: int
    function: str
    copy_payload: str
    force_replace: str
    return_verified: str
    verify_encoded_bytes_only: str
    existing_checkpoint: str
    expected_existing_sha256: str
    reason: str
    context: list[str]


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def expr(node: ast.AST | None, source: str) -> str:
    if node is None:
        return "<omitted>"
    return (ast.get_source_segment(source, node) or ast.dump(node, include_attributes=False)).strip()


def call_name(node: ast.Call) -> str:
    fn = node.func
    if isinstance(fn, ast.Name):
        return fn.id
    if isinstance(fn, ast.Attribute):
        parts = []
        cur: ast.AST | None = fn
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        return ".".join(reversed(parts))
    return "<unknown>"


def enclosing_function(tree: ast.AST, line: int) -> str:
    best = ("<module>", None)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", node.lineno)
            if node.lineno <= line <= end:
                span = end - node.lineno
                if best[1] is None or span < best[1]:
                    best = (node.name, span)
    return best[0]


def context(lines: list[str], line: int, radius: int = 4) -> list[str]:
    start = max(1, line - radius)
    end = min(len(lines), line + radius)
    return [f"{n:05d}: {lines[n-1]}" for n in range(start, end + 1)]


def classify(row: Callsite) -> str:
    if row.copy_payload == "False":
        if row.verify_encoded_bytes_only == "True":
            if row.existing_checkpoint != "<omitted>" and row.expected_existing_sha256 != "<omitted>":
                return "FASTEST_EXISTING_EVIDENCE"
            return "FAST_BYTE_VERIFY"
        return "NO_COPY_SEMANTIC_VERIFY"
    if row.copy_payload == "True":
        return "EXPLICIT_DEEPCOPY"
    return "DEFAULT_DEEPCOPY"


def analyze(path: Path) -> tuple[list[Callsite], list[dict[str, Any]], list[str]]:
    source = path.read_text(encoding="utf-8", errors="replace")
    lines = source.splitlines()
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [], [], [f"{path}: {exc}"]

    save_calls: list[Callsite] = []
    deepcopy_calls: list[dict[str, Any]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = call_name(node)

        if name.endswith("save_franchise_checkpoint"):
            kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
            save_calls.append(
                Callsite(
                    file=str(path.relative_to(ROOT)),
                    line=node.lineno,
                    function=enclosing_function(tree, node.lineno),
                    copy_payload=expr(kwargs.get("copy_payload"), source),
                    force_replace=expr(kwargs.get("force_replace"), source),
                    return_verified=expr(kwargs.get("_return_verified"), source),
                    verify_encoded_bytes_only=expr(kwargs.get("_verify_encoded_bytes_only"), source),
                    existing_checkpoint=expr(kwargs.get("_existing_checkpoint"), source),
                    expected_existing_sha256=expr(kwargs.get("_expected_existing_sha256"), source),
                    reason=expr(kwargs.get("reason"), source),
                    context=context(lines, node.lineno),
                )
            )

        if name in {"copy.deepcopy", "deepcopy"}:
            deepcopy_calls.append(
                {
                    "file": str(path.relative_to(ROOT)),
                    "line": node.lineno,
                    "function": enclosing_function(tree, node.lineno),
                    "expression": expr(node, source),
                    "context": context(lines, node.lineno, radius=3),
                }
            )

    return save_calls, deepcopy_calls, []


def main() -> int:
    out_dir = OUTPUT_ROOT / f"audit_{utc_stamp()}"
    out_dir.mkdir(parents=True, exist_ok=False)

    preferred = [
        "simulation_franchise_checkpoint_v1.py",
        "franchise_free_agency_cpu_execution_v1.py",
        "franchise_free_agency_transaction_v1.py",
        "franchise_free_agency_transaction_v1_1.py",
        "franchise_free_agency_live_signing_v1.py",
    ]

    paths: list[Path] = []
    for name in preferred:
        p = SRC / name
        if p.exists():
            paths.append(p)

    for p in SRC.glob("*.py"):
        if p in paths:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "save_franchise_checkpoint" in text:
            paths.append(p)

    save_calls: list[Callsite] = []
    deepcopy_calls: list[dict[str, Any]] = []
    errors: list[str] = []

    for path in sorted(set(paths)):
        calls, copies, errs = analyze(path)
        save_calls.extend(calls)
        deepcopy_calls.extend(copies)
        errors.extend(errs)

    rows = []
    for call in sorted(save_calls, key=lambda r: (r.file, r.line)):
        row = asdict(call)
        row["classification"] = classify(call)
        rows.append(row)

    counts: dict[str, int] = {}
    for row in rows:
        counts[row["classification"]] = counts.get(row["classification"], 0) + 1

    fa_rows = [
        row for row in rows
        if "free_agency" in row["file"].lower()
        or "free_agency" in row["function"].lower()
        or "free_agency" in row["reason"].lower()
    ]
    risky_fa = [
        row for row in fa_rows
        if row["classification"] in {"DEFAULT_DEEPCOPY", "EXPLICIT_DEEPCOPY"}
    ]

    report = {
        "version": VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "files_scanned": [str(p.relative_to(ROOT)) for p in sorted(set(paths))],
        "save_call_count": len(rows),
        "classification_counts": counts,
        "free_agency_save_call_count": len(fa_rows),
        "free_agency_copying_call_count": len(risky_fa),
        "save_calls": rows,
        "deepcopy_calls_in_scanned_files": deepcopy_calls,
        "parse_errors": errors,
    }

    json_path = out_dir / "checkpoint_save_callsite_audit.json"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines = [
        "=" * 88,
        "V2 CHECKPOINT SAVE CALLSITE AUDIT",
        "=" * 88,
        f"Version: {VERSION}",
        f"Files scanned: {len(report['files_scanned'])}",
        f"save_franchise_checkpoint calls: {len(rows)}",
        f"Free Agency save calls: {len(fa_rows)}",
        f"Free Agency calls still copying: {len(risky_fa)}",
        "",
        "Classification counts:",
    ]
    for key in sorted(counts):
        lines.append(f"  {key:<28} {counts[key]}")
    lines.append("")
    lines.append("All save callsites:")
    for row in rows:
        lines.append(
            f"  {row['classification']:<28} {row['file']}:{row['line']} :: {row['function']}"
        )
        lines.append(
            "    "
            f"copy_payload={row['copy_payload']} | "
            f"byte_verify={row['verify_encoded_bytes_only']} | "
            f"existing={row['existing_checkpoint']} | "
            f"existing_sha={row['expected_existing_sha256']}"
        )
        lines.append(f"    reason={row['reason']}")

    lines.append("")
    lines.append("Free Agency save calls still paying deepcopy:")
    if not risky_fa:
        lines.append("  NONE")
    else:
        for row in risky_fa:
            lines.append(
                f"  {row['file']}:{row['line']} :: {row['function']} [{row['classification']}]"
            )
            for ctx in row["context"]:
                lines.append(f"      {ctx}")

    lines.append("")
    lines.append(f"JSON: {json_path}")
    lines.append("=" * 88)
    summary = "\n".join(lines) + "\n"

    summary_path = out_dir / "checkpoint_save_callsite_audit_summary.txt"
    summary_path.write_text(summary, encoding="utf-8")
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
