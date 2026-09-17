from __future__ import annotations

import html
from typing import Any, Callable


FRANCHISE_OPENING_NIGHT_UX_VERSION = "franchise-opening-night-ux-v1.1-durable-source-2026-09-11"


def _text(value: Any) -> str:
    return str(value or "").strip()


def is_opening_offseason(state: Any) -> bool:
    """Return True only for the untouched pre-Game-1 opening offseason.

    The first completed season also has transition_count == 0 and no archived
    season_history until closeout. Completed games therefore distinguish that
    legitimate first offseason from the initial opening-night setup.
    """
    phase = _text(
        getattr(
            getattr(state, "phase", None),
            "value",
            getattr(state, "phase", ""),
        )
    ).lower()
    completed_games = dict(getattr(state, "completed_games", {}) or {})
    return (
        phase == "offseason"
        and int(getattr(state, "transition_count", 0) or 0) == 0
        and not list(getattr(state, "season_history", ()) or ())
        and not completed_games
    )


def _friendly_blocker(raw: str) -> str:
    value = _text(raw)
    if value.startswith("active_free_agency_markets_remain"):
        return "Finish the remaining free-agency market activity"
    if value.startswith("pending_rfa_offer_sheets_remain"):
        return "Resolve the remaining restricted free-agent offer sheets"
    mapping = {
        "source_phase_is_not_offseason": "Return to the opening offseason state",
        "current_day_is_not_zero": "Reset to the opening-night calendar checkpoint",
        "not_the_opening_franchise_offseason": "This save is already beyond the first offseason",
        "season_history_already_exists": "This franchise already has season history",
        "current_regular_season_schedule_is_not_1230_games": "Create the full 1,230-game regular-season schedule",
        "current_regular_season_schedule_has_non_scheduled_games": "Restore the untouched opening schedule",
        "current_regular_season_schedule_has_recorded_scores": "Restore the untouched opening schedule",
        "standings_are_not_zero_zero": "Restore opening-night standings",
        "postseason_state_is_not_absent": "Clear the stray postseason state",
        "draft_state_already_exists": "Finish or clear the active draft state",
    }
    return mapping.get(value, value.replace("_", " ").strip().capitalize())


def _roster_readiness(state: Any) -> tuple[int, int, tuple[tuple[str, int], ...]]:
    teams = dict(getattr(state, "teams", {}) or {})
    minimum = int(
        getattr(
            getattr(state, "settings", None),
            "minimum_game_players",
            8,
        )
        or 8
    )
    blockers: list[tuple[str, int]] = []
    for team, team_state in sorted(teams.items()):
        count = len(tuple(getattr(team_state, "roster_player_ids", ()) or ()))
        if count < minimum:
            blockers.append((str(team), count))
    return len(teams) - len(blockers), len(teams), tuple(blockers)


def inject_opening_night_visuals_v1(*, primary: str, secondary: str) -> None:
    import streamlit as st

    st.markdown(
        f"""
<style>
/* FRANCHISE_OPENING_NIGHT_UX_V1 */
:root {{ --fon-primary:{primary}; --fon-secondary:{secondary}; }}
.fon-shell {{
  margin:.45rem 0 1.05rem;
  padding:22px 24px 20px;
  border:1px solid color-mix(in srgb,var(--fon-primary) 28%,rgba(255,255,255,.08));
  border-radius:24px;
  background:
    radial-gradient(circle at 100% 0%,color-mix(in srgb,var(--fon-primary) 18%,transparent),transparent 34%),
    radial-gradient(circle at 0% 110%,color-mix(in srgb,var(--fon-secondary) 12%,transparent),transparent 38%),
    linear-gradient(145deg,rgba(11,18,30,.98),rgba(6,10,18,.985));
  box-shadow:0 24px 64px rgba(0,0,0,.28);
}}
.fon-top {{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(280px,.7fr);gap:18px;align-items:center}}
.fon-kicker {{color:#7dd3fc;font-size:.52rem;font-weight:1000;letter-spacing:.16em;text-transform:uppercase}}
.fon-title {{margin-top:6px;color:#fff;font-size:1.72rem;line-height:1.03;font-weight:1000;letter-spacing:-.035em}}
.fon-copy {{margin-top:9px;color:#93a4ba;font-size:.63rem;line-height:1.55;font-weight:680;max-width:760px}}
.fon-state {{display:inline-flex;align-items:center;gap:7px;margin-top:13px;padding:7px 10px;border-radius:999px;background:rgba(245,158,11,.075);border:1px solid rgba(245,158,11,.22);color:#fde68a;font-size:.49rem;font-weight:950;letter-spacing:.07em;text-transform:uppercase}}
.fon-dot {{width:7px;height:7px;border-radius:999px;background:#f59e0b;box-shadow:0 0 13px rgba(245,158,11,.72)}}
.fon-team {{display:flex;justify-content:flex-end;align-items:center;gap:14px}}
.fon-team img {{width:86px;height:86px;object-fit:contain;filter:drop-shadow(0 13px 24px rgba(0,0,0,.36))}}
.fon-team-name {{color:#fff;font-size:1.03rem;font-weight:1000;text-align:right}}
.fon-team-meta {{margin-top:4px;color:#73849a;font-size:.52rem;font-weight:850;text-align:right}}
.fon-checks {{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-top:18px}}
.fon-check {{padding:11px 12px;border:1px solid rgba(255,255,255,.07);border-radius:14px;background:rgba(255,255,255,.022)}}
.fon-check-label {{color:#7e90a6;font-size:.46rem;font-weight:950;letter-spacing:.09em;text-transform:uppercase}}
.fon-check-value {{margin-top:5px;color:#fff;font-size:.75rem;font-weight:1000}}
.fon-check.good {{border-color:rgba(34,197,94,.2);background:rgba(34,197,94,.045)}}
.fon-check.warn {{border-color:rgba(245,158,11,.24);background:rgba(245,158,11,.05)}}
.fon-blockers {{margin-top:12px;padding:11px 13px;border-radius:13px;border:1px solid rgba(245,158,11,.22);background:rgba(245,158,11,.055);color:#fcdca7;font-size:.55rem;line-height:1.5;font-weight:760}}
.fon-confirm {{margin:.35rem 0 .5rem;padding:14px 16px;border-radius:16px;border:1px solid color-mix(in srgb,var(--fon-primary) 30%,rgba(255,255,255,.08));background:linear-gradient(120deg,color-mix(in srgb,var(--fon-primary) 10%,rgba(255,255,255,.02)),rgba(255,255,255,.015));color:#cbd8e8;font-size:.58rem;line-height:1.5}}
@media(max-width:900px) {{.fon-top{{grid-template-columns:1fr}}.fon-team{{justify-content:flex-start}}.fon-team-name,.fon-team-meta{{text-align:left}}.fon-checks{{grid-template-columns:repeat(2,1fr)}}}}
</style>
""",
        unsafe_allow_html=True,
    )


def render_opening_night_launchpad_v1(
    *,
    state: Any,
    trade_state: Any,
    active_team: str,
    team_name_resolver: Callable[[str], str],
    team_logo_resolver: Callable[[str], str],
) -> bool:
    """Render the first-season activation experience.

    Returns True when this is the opening offseason and the normal in-season
    Game Flow console should be suppressed.
    """
    import streamlit as st
    from franchise_opening_regular_season_transition_v1 import (
        OpeningRegularSeasonTransitionError,
        commit_opening_regular_season_live,
        preview_opening_regular_season,
    )
    from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint

    if not is_opening_offseason(state):
        return False

    try:
        preview = preview_opening_regular_season(state, trade_state)
    except Exception as exc:
        st.error(f"Opening-night readiness could not be checked: {exc}")
        return True

    schedule_count = len(dict(getattr(state, "schedule", {}) or {}))
    game_ready, total_teams, roster_blockers = _roster_readiness(state)
    season = _text(getattr(getattr(state, "settings", None), "season_label", "")) or "2026-27"
    team = _text(active_team).upper()
    team_name = _text(team_name_resolver(team)) or team
    team_logo = _text(team_logo_resolver(team))

    backend_blockers = tuple(preview.blockers or ())
    ready = (
        bool(preview.can_commit)
        and not backend_blockers
        and not roster_blockers
        and schedule_count == 1230
    )

    checks = [
        ("Schedule", f"{schedule_count:,} / 1,230", schedule_count == 1230),
        ("League rosters", f"{game_ready} / {total_teams} ready", not roster_blockers),
        ("FA markets", f"{int(preview.active_free_agency_market_count)} active", int(preview.active_free_agency_market_count) == 0),
        ("RFA sheets", f"{int(preview.pending_offer_sheet_count)} pending", int(preview.pending_offer_sheet_count) == 0),
    ]
    check_html = "".join(
        '<div class="fon-check {}"><div class="fon-check-label">{}</div><div class="fon-check-value">{}</div></div>'.format(
            "good" if good else "warn",
            html.escape(label),
            html.escape(value),
        )
        for label, value, good in checks
    )

    blocker_copy: list[str] = [_friendly_blocker(item) for item in backend_blockers]
    blocker_copy.extend(
        f"{team_code} needs {max(0, int(getattr(getattr(state, 'settings', None), 'minimum_game_players', 8) or 8) - count)} more game-ready player(s)"
        for team_code, count in roster_blockers
    )
    blocker_html = (
        '<div class="fon-blockers"><strong>Before opening night:</strong> '
        + html.escape(" · ".join(blocker_copy))
        + "</div>"
        if blocker_copy
        else ""
    )

    st.markdown(
        '<div class="fon-shell">'
        '<div class="fon-top">'
        '<div>'
        '<div class="fon-kicker">OPENING NIGHT SETUP</div>'
        f'<div class="fon-title">Your {html.escape(season)} season is staged and ready to launch.</div>'
        '<div class="fon-copy">The schedule is already built, but the league clock has not started yet. '
        'Open the regular season once and Game Day, Quick Sim, calendar advancement and the live season timeline become active.</div>'
        '<div class="fon-state"><span class="fon-dot"></span> PRESEASON SETUP · LEAGUE CLOCK PAUSED</div>'
        '</div>'
        '<div class="fon-team">'
        f'<div><div class="fon-team-name">{html.escape(team_name)}</div><div class="fon-team-meta">Your franchise · opening-night setup</div></div>'
        f'<img src="{html.escape(team_logo, quote=True)}" alt="{html.escape(team_name, quote=True)}">'
        '</div></div>'
        f'<div class="fon-checks">{check_html}</div>'
        f'{blocker_html}'
        '</div>',
        unsafe_allow_html=True,
    )

    confirm_key = f"franchise_opening_night_quick_confirm_v1::{season}"

    if not ready:
        st.button(
            f"Start {season} regular season",
            type="primary",
            width="stretch",
            disabled=True,
            key=f"franchise_opening_night_blocked_v1::{season}",
        )
        st.caption("Finish the highlighted setup items above. The season will not advance until every readiness check is green.")
        st.session_state.pop(confirm_key, None)
        return True

    if not bool(st.session_state.get(confirm_key, False)):
        if st.button(
            f"Start {season} regular season",
            type="primary",
            width="stretch",
            key=f"franchise_opening_night_prepare_v1::{season}",
        ):
            st.session_state[confirm_key] = True
            st.rerun()
        st.caption("This is the one-time action that turns the prepared schedule into the live regular season.")
        return True

    st.markdown(
        '<div class="fon-confirm"><strong>Ready for opening night.</strong> '
        'This preserves the existing 1,230-game schedule, current rosters, contracts and ownership. '
        'It simply activates the regular-season phase and league clock.</div>',
        unsafe_allow_html=True,
    )
    confirm_cols = st.columns([1.6, 1])
    commit_clicked = confirm_cols[0].button(
        f"Begin {season} now",
        type="primary",
        width="stretch",
        key=f"franchise_opening_night_commit_v1::{season}",
    )
    cancel_clicked = confirm_cols[1].button(
        "Keep preparing",
        width="stretch",
        key=f"franchise_opening_night_cancel_v1::{season}",
    )
    if cancel_clicked:
        st.session_state.pop(confirm_key, None)
        st.rerun()

    if commit_clicked:
        checkpoint = load_franchise_checkpoint(allow_backup=False)
        if checkpoint is None:
            st.error("The durable Franchise checkpoint could not be loaded.")
            return True
        # The durable checkpoint is the authority for this irreversible boundary.
        # A Streamlit session can legitimately hold an older in-memory snapshot after
        # launching/replacing the active franchise, so comparing that page snapshot to
        # the freshly loaded checkpoint creates a false stale-preview failure.
        live_preview = preview_opening_regular_season(
            checkpoint.simulation_state,
            checkpoint.trade_state,
        )
        live_ready_count, live_team_count, live_roster_blockers = _roster_readiness(
            checkpoint.simulation_state
        )
        live_schedule_count = len(
            dict(getattr(checkpoint.simulation_state, "schedule", {}) or {})
        )
        if (
            not live_preview.can_commit
            or live_preview.blockers
            or live_roster_blockers
            or live_schedule_count != 1230
        ):
            st.session_state.pop(confirm_key, None)
            reasons = [_friendly_blocker(item) for item in tuple(live_preview.blockers or ())]
            reasons.extend(
                f"{team_code} is below the game-ready roster floor"
                for team_code, _count in live_roster_blockers
            )
            if live_schedule_count != 1230:
                reasons.append(f"schedule has {live_schedule_count:,} of 1,230 games")
            detail = " · ".join(reasons) if reasons else "opening-night readiness changed"
            st.error(
                "Opening-night setup changed in the durable save. "
                f"Review the updated readiness checks: {detail}."
            )
            return True
        try:
            with st.spinner("Opening the regular season and syncing the league calendar..."):
                commit_opening_regular_season_live(
                    confirmation_token=live_preview.confirmation_token,
                    expected_fingerprint=live_preview.source_fingerprint,
                )
        except OpeningRegularSeasonTransitionError as exc:
            st.error(f"The regular season was not opened: {exc}")
            return True
        except Exception as exc:
            st.error(f"The regular season could not be opened: {exc}")
            return True
        st.session_state.pop(confirm_key, None)
        st.session_state["franchise_notice"] = (
            f"{season} is live. Opening night is ready in Game Day."
        )
        st.rerun()

    return True
