from __future__ import annotations
import csv, io, json, pickle, hashlib, tempfile, zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

VERSION = "fa-non-rfa-rights-evidence-completion-v1-2026-08-15"
SEASON_LABEL = "2026-27"
EXPECTED_CHECKPOINT_SHA256 = "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"

def clean(v): return str(v or "").strip()
def pid(v):
    t=clean(v)
    return t[:-2] if t.endswith(".0") and t[:-2].isdigit() else t

def sha256_file(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def object_digest(v):
    try: payload=pickle.dumps(v,pickle.HIGHEST_PROTOCOL)
    except Exception: payload=repr(v).encode()
    return hashlib.sha256(payload).hexdigest()

def latest(root, pattern):
    xs=[p for p in root.rglob(pattern) if p.is_file()]
    if not xs: raise RuntimeError(f"Missing required audit: {pattern}")
    return max(xs,key=lambda p:p.stat().st_mtime)

def read_csv(z,suffix):
    n=next((n for n in z.namelist() if n.endswith(suffix)),"")
    if not n: raise RuntimeError(f"ZIP missing {suffix}")
    t=z.read(n).decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(t))) if t.strip() else []

def read_json(z,suffix):
    n=next((n for n in z.namelist() if n.endswith(suffix)),"")
    if not n: raise RuntimeError(f"ZIP missing {suffix}")
    return json.loads(z.read(n).decode("utf-8-sig"))

def write_csv(path, rows):
    if not rows:
        path.write_text("",encoding="utf-8"); return
    fields=[]; seen=set()
    for r in rows:
        for k in r:
            if k not in seen: seen.add(k); fields.append(k)
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)

def main():
    root=Path.cwd().resolve()
    rec_zip=latest(root,"fa_full_market_owner_rights_reconciliation_v1_0_2_2026-27_*.zip")
    cont_zip=latest(root,"fa_non_rfa_rights_continuity_reconstruction_v1_2026-27_*.zip")

    with zipfile.ZipFile(rec_zip) as z:
        rec_summary=read_json(z,"owner_rights_reconciliation_summary.json")
        rec_rows=read_csv(z,"full_market_owner_rights_reconciliation_226.csv")
    with zipfile.ZipFile(cont_zip) as z:
        cont_summary=read_json(z,"rights_continuity_reconstruction_summary.json")
        auto=read_csv(z,"rights_continuity_automatic_48.csv")
        unresolved=read_csv(z,"rights_continuity_unresolved_15.csv")

    if not rec_summary.get("passed"): raise RuntimeError("Upstream reconciliation not passed.")
    if not cont_summary.get("passed"): raise RuntimeError("Continuity reconstruction not passed.")
    if int(cont_summary.get("backtest_match_count",-1)) != 55 or int(cont_summary.get("backtest_mismatch_count",-1)) != 0:
        raise RuntimeError("Backtest is not exactly 55/55.")
    if len(auto)!=48 or len(unresolved)!=15:
        raise RuntimeError("Expected 48 automatic and 15 unresolved target rows.")

    non_rfa=[r for r in rec_rows if clean(r.get("exact_rfa_free_agent_amount_available")).lower() not in {"true","1","yes"}]
    if len(non_rfa)!=162: raise RuntimeError(f"Expected 162 non-RFAs, got {len(non_rfa)}.")

    auto_by={pid(r["player_id"]):r for r in auto}
    unres_ids={pid(r["player_id"]) for r in unresolved}
    completed=[]; conflicts=[]

    for r in non_rfa:
        p=pid(r["player_id"])
        existing=clean(r.get("reconciled_rights_classification"))
        proposed=clean(auto_by.get(p,{}).get("proposed_rights_classification"))
        if existing and proposed and existing != proposed:
            conflicts.append({"player_id":p,"player_name":r.get("player_name",""),"existing":existing,"proposed":proposed})
        final=existing or proposed
        mode=("reconciled_existing_v1_0_2" if existing else "continuity_reconstruction_v1_55_of_55_backtested" if proposed else "unresolved")
        completed.append({
            "player_id":p,
            "player_name":clean(r.get("player_name")),
            "prior_team":clean(r.get("resolved_prior_team")),
            "final_rights_classification":final,
            "evidence_mode":mode,
            "continuity_reason":clean(auto_by.get(p,{}).get("resolution_reason")),
            "continuity_start":clean(auto_by.get(p,{}).get("continuity_start")),
            "rights_resolved":bool(final),
            "classification_applied_to_simulation":False,
        })

    resolved=[r for r in completed if r["rights_resolved"]]
    unresolved_out=[r for r in completed if not r["rights_resolved"]]
    counts=Counter(r["final_rights_classification"] for r in resolved)

    import simulation_franchise_checkpoint_v1 as cp
    cp_path=Path(cp.DEFAULT_CHECKPOINT_PATH)
    before_hash=sha256_file(cp_path)
    checkpoint=cp.load_franchise_checkpoint()
    before_state=object_digest(checkpoint.simulation_state)
    if before_hash != EXPECTED_CHECKPOINT_SHA256: raise RuntimeError("Checkpoint mismatch.")

    checks=[]
    def add(cid, ok, detail):
        checks.append({"check_id":cid,"status":"PASS" if ok else "FAIL","severity":"strict","detail":detail})
        print(f"  {cid}: {'PASS' if ok else 'FAIL'}")

    print("="*120)
    print("2026 NON-RFA RIGHTS EVIDENCE COMPLETION V1")
    print("="*120)
    add("upstream_reconciliation_passed", bool(rec_summary.get("passed")), "Owner/rights reconciliation passed.")
    add("continuity_backtest_is_exact_55_of_55", int(cont_summary.get("backtest_match_count",-1))==55 and int(cont_summary.get("backtest_mismatch_count",-1))==0, "55 matches, 0 mismatches.")
    add("exact_48_automatic_rows_frozen", len(auto)==48, f"automatic={len(auto)}")
    add("no_existing_rights_overwritten", len(conflicts)==0, f"conflicts={len(conflicts)}")
    add("exact_147_of_162_non_rfa_rights_resolved", len(resolved)==147, f"resolved={len(resolved)}/162")
    add("exact_15_non_rfa_rights_unresolved", len(unresolved_out)==15 and {r["player_id"] for r in unresolved_out}==unres_ids, f"unresolved={len(unresolved_out)}")
    add("resolved_classification_distribution_expected", counts==Counter({"not_applicable":54,"non_bird":42,"bird":40,"early_bird":11}), repr(dict(counts)))
    add("rights_not_applied_to_simulation", all(not r["classification_applied_to_simulation"] for r in completed), "Evidence completion only.")

    after_state=object_digest(checkpoint.simulation_state)
    after_hash=sha256_file(cp_path)
    add("loaded_simulation_state_unchanged", after_state==before_state, after_state)
    add("checkpoint_file_unchanged", after_hash==before_hash==EXPECTED_CHECKPOINT_SHA256, after_hash)

    failed=[r["check_id"] for r in checks if r["status"]=="FAIL"]
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id=f"fa_non_rfa_rights_evidence_completion_v1_{SEASON_LABEL}_{stamp}"
    out=root/"outputs"/"audits"; out.mkdir(parents=True,exist_ok=True)
    audit_zip=out/f"{export_id}.zip"
    summary={
        "version":VERSION,
        "non_rfa_count":162,
        "previously_resolved_count":99,
        "newly_frozen_continuity_count":48,
        "resolved_count":len(resolved),
        "unresolved_count":len(unresolved_out),
        "classification_counts":dict(sorted(counts.items())),
        "backtest_match_count":55,
        "backtest_mismatch_count":0,
        "classifications_applied":0,
        "state_mutation_performed":False,
        "checkpoint_write_performed":False,
        "passed":not failed,
        "failed_checks":failed,
        "next_slice":"Target the remaining 15 fail-closed rights timelines individually while keeping prior-salary completion as a separate workstream."
    }
    with tempfile.TemporaryDirectory(prefix="fa_non_rfa_rights_complete_") as td:
        ex=Path(td)/export_id; ex.mkdir()
        write_csv(ex/"non_rfa_rights_completed_162.csv",completed)
        write_csv(ex/"non_rfa_rights_resolved_147.csv",resolved)
        write_csv(ex/"non_rfa_rights_unresolved_15.csv",unresolved_out)
        write_csv(ex/"non_rfa_rights_completion_conflicts.csv",conflicts)
        write_csv(ex/"non_rfa_rights_completion_checks.csv",checks)
        (ex/"non_rfa_rights_completion_summary.json").write_text(json.dumps(summary,indent=2,sort_keys=True),encoding="utf-8")
        (ex/"README.txt").write_text("Read-only evidence completion. Freezes 48 backtested continuity classifications on top of 99 already-resolved non-RFA rights rows. No simulation mutation.",encoding="utf-8")
        with zipfile.ZipFile(audit_zip,"w",zipfile.ZIP_DEFLATED) as z:
            for p in sorted(ex.iterdir()): z.write(p,arcname=f"{export_id}/{p.name}")
    if failed: raise RuntimeError("Non-RFA Rights Evidence Completion V1 failed: "+", ".join(failed))
    print("")
    print("NON-RFA RIGHTS EVIDENCE COMPLETION V1 PASSED")
    print(f"Resolved non-RFA rights: {len(resolved)}/162")
    print(f"Still unresolved:        {len(unresolved_out)}/162")
    print("Checkpoint write:        NOT PERFORMED")
    print(f"Audit ZIP: {audit_zip}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
