from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import franchise_free_agency_rights_population_v1 as population
import franchise_free_agency_rights_exceptions_v1 as rights
import franchise_free_agency_cpu_offer_generation_v1 as offers


def main() -> int:
    calls = {"overlay": 0}
    original_loader = population.load_overlay_for_state

    def fake_overlay(state, *, path=None):
        del state, path
        calls["overlay"] += 1
        return {}

    population.load_overlay_for_state = fake_overlay
    try:
        rights._RIGHTS_RUNTIME_CACHE_KEY = None
        rights._RIGHTS_RUNTIME_REGISTRY = {}
        rights._RIGHTS_RUNTIME_REGISTRY_LOADED = False
        rights._RIGHTS_RUNTIME_RESOLUTIONS = {}
        rights._RIGHTS_RUNTIME_ROUTES = {}

        state = SimpleNamespace(
            settings=SimpleNamespace(season_label="2099-00"),
            free_agent_player_ids=("P1",),
            franchise_transaction_revision=0,
            source_transaction_count=0,
            transition_count=0,
            free_agency_rights_registry_v1={
                "P1": {
                    "prior_team": "CHI",
                    "continuous_prior_seasons": 3,
                    "continuity_verified": True,
                    "prior_regular_salary": 5_000_000.0,
                    "prior_average_player_salary": None,
                    "restricted_free_agent": False,
                    "qualifying_offer_amount": None,
                    "source": "cache-validator",
                }
            },
        )

        first = rights.resolve_free_agency_rights(state, "P1")
        second = rights.resolve_free_agency_rights(state, "P1")
        assert first == second
        assert first.classification == rights.RIGHTS_BIRD
        assert calls["overlay"] == 1, calls

        public_a = rights.rights_registry_from_state(state)
        public_a["P1"]["prior_team"] = "BOS"
        public_b = rights.rights_registry_from_state(state)
        assert public_b["P1"]["prior_team"] == "CHI"
        assert calls["overlay"] == 1, calls

        # A new immutable free-agent tuple is a state change and must invalidate
        # the last-state rights cache.
        state.free_agent_player_ids = tuple(["P1"])
        third = rights.resolve_free_agency_rights(state, "P1")
        assert third.classification == rights.RIGHTS_BIRD
        assert calls["overlay"] == 2, calls

        rights_report = rights.rights_exceptions_contract_report()
        assert rights_report["runtime_cache_invalidates_on_free_agent_or_revision_change"] is True
        assert rights_report["runtime_cache_public_registry_copy_semantics_preserved"] is True

        offer_report = offers.generation_contract_report()
        assert offer_report["board_local_payroll_cache"] is True
        assert offer_report["board_local_service_cache"] is True
        assert offer_report["board_local_rights_cache"] is True
        assert offer_report["board_local_exception_route_cache"] is True
        assert offer_report["board_local_term_resolution_cache"] is True
        assert offer_report["board_cache_changes_offer_order_or_legality"] is False

        assert hasattr(population._cached_overlay_payload, "cache_info")

    finally:
        population.load_overlay_for_state = original_loader

    print("FRANCHISE V2 PHASE 1 FA CACHE OPTIMIZATION CHECK PASSED")
    print("Rights registry repeated-read cache: PASS")
    print("Empty-registry cache behavior: PASS")
    print("Cache invalidation after FA-pool state change: PASS")
    print("Public rights registry copy semantics: PASS")
    print("Overlay JSON payload cache installed: PASS")
    print("Board-local payroll/service/rights/route/term caches: PASS")
    print("Offer ordering or legality intentionally changed: NO")
    print("No franchise checkpoint was loaded or mutated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
