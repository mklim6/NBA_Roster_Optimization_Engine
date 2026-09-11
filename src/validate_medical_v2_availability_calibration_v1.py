from __future__ import annotations

import json
import random
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from simulation_injury_fatigue_v1 import InjuryFatigueConfig
from simulation_medical_injury_v2 import choose_medical_injury_outcome


VALIDATOR_VERSION = "medical-v2-availability-calibration-validator-v1-2026-08-10"
OUTPUT = ROOT / "outputs" / "medical_v2_availability_calibration_validation_v1.json"


def sample_mix(existing_issue: bool, seed: int, samples: int = 50000):
    rng = random.Random(seed)
    counts = Counter()
    unavailable = 0
    for _ in range(samples):
        outcome = choose_medical_injury_outcome(
            rng,
            existing_issue=existing_issue,
            preferred_region="ankle" if existing_issue else "",
        )
        counts[outcome.severity] += 1
        if str(outcome.status.value) in {"out", "doubtful"}:
            unavailable += 1
    rates = {
        key: counts[key] / samples
        for key in ("soreness", "minor", "moderate", "major")
    }
    rates["unavailable"] = unavailable / samples
    return rates


def main() -> int:
    config = InjuryFatigueConfig()
    fresh = sample_mix(False, 20260810)
    existing = sample_mix(True, 20260811)

    checks = {
        "validator_version_is_current": (
            VALIDATOR_VERSION
            == "medical-v2-availability-calibration-validator-v1-2026-08-10"
        ),
        "base_risk_is_calibrated": abs(
            config.base_player_game_injury_risk - 0.00380
        ) < 1e-12,
        "maximum_event_probability_is_calibrated": abs(
            config.maximum_event_probability - 0.035
        ) < 1e-12,
        "fresh_soreness_share_is_targeted": 0.45 <= fresh["soreness"] <= 0.51,
        "fresh_minor_share_is_targeted": 0.29 <= fresh["minor"] <= 0.35,
        "fresh_moderate_share_is_targeted": 0.145 <= fresh["moderate"] <= 0.185,
        "fresh_major_share_is_targeted": 0.025 <= fresh["major"] <= 0.045,
        "existing_issue_increases_moderate_plus_share": (
            existing["moderate"] + existing["major"]
            > fresh["moderate"] + fresh["major"] + 0.07
        ),
        "existing_issue_increases_unavailable_share": (
            existing["unavailable"] > fresh["unavailable"]
        ),
    }

    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "script": VALIDATOR_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "summary": {
            "base_player_game_injury_risk": config.base_player_game_injury_risk,
            "maximum_event_probability": config.maximum_event_probability,
            "fresh_event_mix": {k: round(v, 4) for k, v in fresh.items()},
            "existing_issue_event_mix": {
                k: round(v, 4) for k, v in existing.items()
            },
        },
        "passed": not failed,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))

    if failed:
        raise AssertionError(
            "Medical V2 availability calibration failed: "
            + ", ".join(failed)
        )

    print()
    print("MEDICAL V2 AVAILABILITY CALIBRATION VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
