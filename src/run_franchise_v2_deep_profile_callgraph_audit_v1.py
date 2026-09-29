from __future__ import annotations

import argparse
import json
import pstats
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE_ROOT = ROOT / "outputs" / "v2_deep_season_performance_profile_v1"
VERSION = "franchise-v2-deep-profile-callgraph-audit-v1-2026-09-28"


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def clean_path(value: str) -> str:
    try:
        return str(Path(value).resolve().relative_to(ROOT.resolve()))
    except Exception:
        return str(value)


def normalize_edge(value: Any) -> dict[str, float | int]:
    if isinstance(value, tuple):
        if len(value) >= 4:
            cc, nc, tt, ct = value[:4]
            return {
                "primitive_calls": int(cc),
                "total_calls": int(nc),
                "self_time_s": float(tt),
                "cumulative_time_s": float(ct),
            }
        if len(value) == 3:
            nc, tt, ct = value
            return {
                "primitive_calls": int(nc),
                "total_calls": int(nc),
                "self_time_s": float(tt),
                "cumulative_time_s": float(ct),
            }
        if len(value) == 2:
            nc, ct = value
            return {
                "primitive_calls": int(nc),
                "total_calls": int(nc),
                "self_time_s": 0.0,
                "cumulative_time_s": float(ct),
            }
    try:
        n = int(value)
    except Exception:
        n = 0
    return {
        "primitive_calls": n,
        "total_calls": n,
        "self_time_s": 0.0,
        "cumulative_time_s": 0.0,
    }


def func_row(func: tuple[str, int, str], stats: pstats.Stats) -> dict[str, Any]:
    filename, line, name = func
    cc, nc, tt, ct, _ = stats.stats[func]
    return {
        "file": clean_path(filename),
        "line": int(line),
        "function": str(name),
        "primitive_calls": int(cc),
        "total_calls": int(nc),
        "self_time_s": float(tt),
        "cumulative_time_s": float(ct),
    }


def edge_row(
    func: tuple[str, int, str],
    edge: Any,
) -> dict[str, Any]:
    filename, line, name = func
    row = {
        "file": clean_path(filename),
        "line": int(line),
        "function": str(name),
    }
    row.update(normalize_edge(edge))
    return row


def find_funcs(stats: pstats.Stats, name: str) -> list[tuple[str, int, str]]:
    return [
        func
        for func in stats.stats
        if func[2] == name
    ]


def projectish(row: dict[str, Any]) -> bool:
    text = f"{row['file']} {row['function']}".lower()
    return (
        str(row["file"]).lower().startswith("src")
        or "franchise_" in text
        or "simulation_" in text
        or "run_franchise_" in text
    )


def direct_callers(
    target: tuple[str, int, str],
    stats: pstats.Stats,
) -> list[dict[str, Any]]:
    callers = stats.stats[target][4]
    rows = [edge_row(func, edge) for func, edge in callers.items()]
    return sorted(rows, key=lambda row: row["cumulative_time_s"], reverse=True)


def direct_callees(
    target: tuple[str, int, str],
    stats: pstats.Stats,
) -> list[dict[str, Any]]:
    stats.calc_callees()
    mapping = getattr(stats, "all_callees", {}).get(target, {})
    rows = [edge_row(func, edge) for func, edge in mapping.items()]
    return sorted(rows, key=lambda row: row["cumulative_time_s"], reverse=True)


def external_deepcopy_roots(
    deepcopy_target: tuple[str, int, str],
    stats: pstats.Stats,
    *,
    max_depth: int = 8,
) -> list[dict[str, Any]]:
    # Walk upward through Python's copy.py implementation until we reach
    # non-copy.py callers. This avoids reporting _deepcopy_dict/_reconstruct as
    # the answer when the real question is which project operation triggered it.
    frontier: list[tuple[tuple[str, int, str], float, int]] = [
        (deepcopy_target, float("inf"), 0)
    ]
    seen_edges: set[tuple[tuple[str, int, str], tuple[str, int, str]]] = set()
    roots: dict[tuple[str, int, str], dict[str, Any]] = {}

    while frontier:
        current, inherited_ct, depth = frontier.pop()
        if depth >= max_depth:
            continue

        for caller, raw_edge in stats.stats[current][4].items():
            edge_key = (caller, current)
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)

            edge = normalize_edge(raw_edge)
            edge_ct = float(edge["cumulative_time_s"])
            contribution = min(inherited_ct, edge_ct) if inherited_ct != float("inf") else edge_ct
            caller_file = str(caller[0]).replace("\\", "/").lower()
            is_copy_internal = caller_file.endswith("/copy.py") or caller_file.endswith("copy.py")

            if is_copy_internal:
                frontier.append((caller, contribution, depth + 1))
                continue

            row = roots.setdefault(
                caller,
                {
                    "file": clean_path(caller[0]),
                    "line": int(caller[1]),
                    "function": str(caller[2]),
                    "estimated_deepcopy_cumulative_s": 0.0,
                    "paths": 0,
                },
            )
            row["estimated_deepcopy_cumulative_s"] += contribution
            row["paths"] += 1

    return sorted(
        roots.values(),
        key=lambda row: row["estimated_deepcopy_cumulative_s"],
        reverse=True,
    )


def choose_latest_pstats(root: Path) -> Path:
    matches = sorted(
        root.glob("profile_*/deep_season_profile.pstats"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not matches:
        raise FileNotFoundError(
            f"No deep_season_profile.pstats found under {root}"
        )
    return matches[0]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze the latest deep-season pstats without rerunning the simulation."
    )
    parser.add_argument("--pstats", type=Path, default=None)
    parser.add_argument("--profile-root", type=Path, default=DEFAULT_PROFILE_ROOT)
    parser.add_argument("--top", type=int, default=30)
    args = parser.parse_args()

    pstats_path = args.pstats or choose_latest_pstats(args.profile_root)
    pstats_path = pstats_path.resolve()
    out_dir = pstats_path.parent / f"callgraph_audit_{stamp()}"
    out_dir.mkdir(parents=True, exist_ok=False)

    stats = pstats.Stats(str(pstats_path))

    target_names = [
        "deepcopy",
        "save_franchise_checkpoint",
        "commit_cpu_contract_legal_free_agency_preview_live",
        "execute_cpu_free_agency_round_durably",
        "build_cpu_free_agency_execution_plan",
        "build_free_agency_durable_candidate",
        "build_trade_state_free_agency_candidate",
        "encode_checkpoint",
        "write_encoded_checkpoint",
        "load_checkpoint_path",
        "load_franchise_checkpoint",
    ]

    targets: dict[str, list[dict[str, Any]]] = {}
    raw_targets: dict[str, list[tuple[str, int, str]]] = {}

    for name in target_names:
        funcs = find_funcs(stats, name)
        raw_targets[name] = funcs
        targets[name] = [func_row(func, stats) for func in funcs]

    analyses: dict[str, Any] = {}

    for name, funcs in raw_targets.items():
        rows = []
        for func in funcs:
            rows.append(
                {
                    "function": func_row(func, stats),
                    "callers": direct_callers(func, stats)[: args.top],
                    "callees": direct_callees(func, stats)[: args.top],
                }
            )
        analyses[name] = rows

    deepcopy_roots: list[dict[str, Any]] = []
    if raw_targets.get("deepcopy"):
        # Prefer Python stdlib copy.py's deepcopy.
        candidate = sorted(
            raw_targets["deepcopy"],
            key=lambda f: stats.stats[f][3],
            reverse=True,
        )[0]
        deepcopy_roots = external_deepcopy_roots(candidate, stats)

    report = {
        "version": VERSION,
        "pstats": str(pstats_path),
        "targets": targets,
        "analyses": analyses,
        "external_deepcopy_roots": deepcopy_roots[: args.top],
    }

    json_path = out_dir / "deep_profile_callgraph_audit.json"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines: list[str] = []
    lines.append("=" * 110)
    lines.append("FRANCHISE V2 DEEP PROFILE CALLGRAPH AUDIT")
    lines.append("=" * 110)
    lines.append(f"PStats: {pstats_path}")
    lines.append("Simulation rerun: NO")
    lines.append("Production mutation: NO")

    lines.append("")
    lines.append("EXTERNAL ROOTS OF copy.deepcopy")
    lines.append("-" * 110)
    for i, row in enumerate(deepcopy_roots[: args.top], start=1):
        lines.append(
            f"{i:>2}. {row['estimated_deepcopy_cumulative_s']:10.3f}s est deepcopy | "
            f"{row['paths']:>3} paths | "
            f"{row['file']}:{row['line']}::{row['function']}"
        )

    for name in target_names:
        entries = analyses.get(name, [])
        if not entries:
            continue
        for entry in entries:
            fn = entry["function"]
            lines.append("")
            lines.append(
                f"TARGET {name}: {fn['file']}:{fn['line']}::{fn['function']} "
                f"[calls={fn['total_calls']}, self={fn['self_time_s']:.3f}s, "
                f"cum={fn['cumulative_time_s']:.3f}s]"
            )
            lines.append("  Top callers:")
            for row in entry["callers"][:15]:
                lines.append(
                    f"    {row['cumulative_time_s']:10.3f}s cum | "
                    f"{row['total_calls']:>10} calls | "
                    f"{row['file']}:{row['line']}::{row['function']}"
                )
            lines.append("  Top callees:")
            for row in entry["callees"][:15]:
                lines.append(
                    f"    {row['cumulative_time_s']:10.3f}s cum | "
                    f"{row['total_calls']:>10} calls | "
                    f"{row['file']}:{row['line']}::{row['function']}"
                )

    text = "\n".join(lines) + "\n"
    txt_path = out_dir / "deep_profile_callgraph_audit.txt"
    txt_path.write_text(text, encoding="utf-8")

    print(text)
    print(f"JSON: {json_path}")
    print(f"TXT:  {txt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
