from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Any, Callable, Mapping


FRANCHISE_OFFSEASON_HEADQUARTERS_VERSION = (
    "franchise-offseason-headquarters-v1.2-presentation-scale-2026-09-12"
)


@dataclass(frozen=True)
class OffseasonStageV1:
    key: str
    label: str
    kicker: str
    detail: str
    status: str
    icon: str
    target_section: str


@dataclass(frozen=True)
class OffseasonHeadquartersModelV1:
    season_label: str
    team_code: str
    team_name: str
    current_key: str
    current_label: str
    current_detail: str
    recommended_label: str
    recommended_detail: str
    recommended_target: str
    progress_pct: float
    opening_offseason: bool
    offseason_day: int
    roster_count: int
    free_agent_count: int
    rights_count: int
    active_negotiations: int
    team_signings: int
    blocking_count: int
    draft_phase: str
    stages: tuple[OffseasonStageV1, ...]


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(getattr(value, "value", value) or "").strip()


def _status(value: Any) -> str:
    return _text(value).lower().replace(" ", "_")


def _rows(value: Any) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in list(value or ()):
        if isinstance(row, Mapping):
            output.append(dict(row))
        elif hasattr(row, "__dict__"):
            output.append(dict(vars(row)))
    return output


def _draft_phase(payload: Mapping[str, Any] | None) -> str:
    if not isinstance(payload, Mapping):
        return ""
    return _status(payload.get("phase", ""))


def _postseason_stage(postseason_state: Any) -> str:
    return _status(getattr(postseason_state, "stage", "")) if postseason_state is not None else ""


def _postseason_complete(postseason_state: Any) -> bool:
    return _postseason_stage(postseason_state) == "complete"


def _completed_game_count(state: Any) -> int:
    return len(dict(getattr(state, "completed_games", {}) or {}))


def _season_history_count(state: Any) -> int:
    return len(list(getattr(state, "season_history", ()) or ()))


def _opening_offseason(
    state: Any,
    *,
    postseason_state: Any,
    draft_state_payload: Mapping[str, Any] | None,
) -> bool:
    return (
        _status(getattr(state, "phase", "")) == "offseason"
        and _season_history_count(state) == 0
        and _completed_game_count(state) == 0
        and not _draft_phase(draft_state_payload)
        and _postseason_stage(postseason_state) in {"", "not_started"}
    )


def _calendar_info(state: Any) -> tuple[int, int]:
    payload = getattr(state, "free_agency_market_calendar_v1", None)
    if not isinstance(payload, Mapping):
        return 0, 0
    day = int(payload.get("offseason_day", 0) or 0)
    markets = payload.get("active_markets", {}) or {}
    active = len(markets) if isinstance(markets, Mapping) else 0
    return day, active


def _team_roster_count(state: Any, team_code: str) -> int:
    team = (getattr(state, "teams", {}) or {}).get(team_code)
    return len(tuple(getattr(team, "roster_player_ids", ()) or ())) if team is not None else 0


def _team_signing_count(state: Any, team_code: str) -> int:
    count = 0
    for item in list(getattr(state, "free_agency_transaction_history", ()) or ()):
        if isinstance(item, Mapping):
            code = _text(item.get("team_abbreviation", item.get("team", ""))).upper()
        else:
            code = _text(
                getattr(item, "team_abbreviation", getattr(item, "team", ""))
            ).upper()
        if code == team_code:
            count += 1
    return count


def _rights_count(state: Any, team_code: str) -> int:
    rows = _rows(getattr(state, "offseason_rfa_rights_qo_decisions_v1", ()))
    rows += _rows(getattr(state, "offseason_non_rfa_rights_decisions_v1", ()))
    if not rows:
        return 0
    team_rows = [
        row
        for row in rows
        if _text(row.get("prior_team", "")).upper() == team_code
    ]
    return len(team_rows) if team_rows else len(rows)


def _free_agent_count(state: Any) -> int:
    ids = tuple(getattr(state, "free_agent_player_ids", ()) or ())
    if ids:
        return len(ids)
    return len(_rows(getattr(state, "offseason_free_agent_amount_candidates_v1", ())))


def _current_stage_key(
    *,
    opening_offseason: bool,
    postseason_complete: bool,
    draft_phase: str,
    offseason_day: int,
    active_negotiations: int,
    team_signings: int,
) -> str:
    if opening_offseason:
        return "roster_finalization"
    if draft_phase in {"lottery_ready", "lottery_complete"}:
        return "lottery" if draft_phase == "lottery_ready" else "scouting"
    if draft_phase == "scouting":
        return "scouting"
    if draft_phase == "draft_in_progress":
        return "draft"
    if draft_phase == "draft_complete":
        if offseason_day >= 25:
            return "roster_finalization"
        if active_negotiations > 0 or team_signings > 0 or offseason_day > 1:
            return "free_agency"
        return "rights"
    if postseason_complete:
        return "season_review"
    return "season_review"


def build_offseason_headquarters_model_v1(
    *,
    state: Any,
    active_team: str,
    postseason_state: Any = None,
    draft_state_payload: Mapping[str, Any] | None = None,
    team_name_resolver: Callable[[str], str] | None = None,
    blocking_count: int = 0,
) -> OffseasonHeadquartersModelV1:
    """Build a read-only presentation model from the durable franchise state."""
    team_code = _text(active_team).upper() or "TEAM"
    team_name = (
        team_name_resolver(team_code)
        if team_name_resolver is not None
        else team_code
    )
    season_label = _text(getattr(getattr(state, "settings", None), "season_label", "")) or "Current season"
    draft_phase = _draft_phase(draft_state_payload)
    opening = _opening_offseason(
        state,
        postseason_state=postseason_state,
        draft_state_payload=draft_state_payload,
    )
    postseason_done = _postseason_complete(postseason_state)
    offseason_day, active_negotiations = _calendar_info(state)
    roster_count = _team_roster_count(state, team_code)
    free_agent_count = _free_agent_count(state)
    rights_count = _rights_count(state, team_code)
    team_signings = _team_signing_count(state, team_code)

    current_key = _current_stage_key(
        opening_offseason=opening,
        postseason_complete=postseason_done,
        draft_phase=draft_phase,
        offseason_day=offseason_day,
        active_negotiations=active_negotiations,
        team_signings=team_signings,
    )

    order = (
        "season_review",
        "lottery",
        "scouting",
        "draft",
        "rights",
        "free_agency",
        "roster_finalization",
        "opening_night",
    )
    labels = {
        "season_review": "Season Review",
        "lottery": "Draft Lottery",
        "scouting": "Scouting",
        "draft": "Draft Night",
        "rights": "Rights & Re-Signings",
        "free_agency": "Free Agency",
        "roster_finalization": "Roster Finalization",
        "opening_night": "Opening Night",
    }
    kickers = {
        "season_review": "01 · CLOSE THE BOOK",
        "lottery": "02 · ORDER THE BOARD",
        "scouting": "03 · BUILD THE BOARD",
        "draft": "04 · MAKE THE PICKS",
        "rights": "05 · KEEP THE CORE",
        "free_agency": "06 · ATTACK THE MARKET",
        "roster_finalization": "07 · SET THE TEAM",
        "opening_night": "08 · START THE YEAR",
    }
    icons = {
        "season_review": "🏆",
        "lottery": "🎱",
        "scouting": "🔎",
        "draft": "🎙️",
        "rights": "🤝",
        "free_agency": "✍️",
        "roster_finalization": "📋",
        "opening_night": "🏀",
    }
    targets = {
        "season_review": "League & Offseason",
        "lottery": "Draft Room",
        "scouting": "Draft Room",
        "draft": "Draft Room",
        "rights": "Free Agency",
        "free_agency": "Free Agency",
        "roster_finalization": "Team Management",
        "opening_night": "League & Offseason",
    }

    prospects = 0
    if isinstance(draft_state_payload, Mapping):
        prospects = len(list(draft_state_payload.get("prospects", ()) or ()))

    detail = {
        "season_review": (
            "Championship decided. Review awards, the completed season and the front-office plan for the next cycle."
            if postseason_done
            else "Close the competitive season and review the franchise before the offseason clock starts."
        ),
        "lottery": (
            "Lottery is ready. Establish the official order for the next draft."
            if draft_phase == "lottery_ready"
            else "The lottery establishes the order before the scouting board becomes the focus."
        ),
        "scouting": (
            f"{prospects} prospects are on the board. Scout uncertainty, fit and upside before Draft Night."
            if prospects
            else "Build the draft board from scouting estimates before the picks begin."
        ),
        "draft": (
            "Draft Night is live. Make the controlled-team selections and let the existing two-round engine handle the league."
            if draft_phase == "draft_in_progress"
            else "Turn the scouting board into two rounds of franchise assets."
        ),
        "rights": (
            f"{rights_count} rights record{'s' if rights_count != 1 else ''} are visible for this team/context. Handle return talks and qualifying-offer decisions in the existing negotiation workspace."
            if rights_count
            else "Review return candidates, rights and qualifying-offer context before committing long-term money."
        ),
        "free_agency": (
            f"Day {offseason_day or 1} · {active_negotiations} live negotiation{'s' if active_negotiations != 1 else ''} · {free_agent_count} available player{'s' if free_agent_count != 1 else ''}."
        ),
        "roster_finalization": (
            f"{roster_count} players are currently rostered. Use Team Management and Trade Center to shape the opening-night group."
        ),
        "opening_night": (
            "When the draft and roster build are complete, use the existing season-boundary controls to archive the year, apply development and generate the next schedule."
        ),
    }

    current_index = order.index(current_key)

    def stage_status(key: str) -> str:
        if opening:
            if key in {"season_review", "lottery", "scouting", "draft", "rights", "free_agency"}:
                return "not_required"
            if key == "roster_finalization":
                return "current"
            return "upcoming"
        idx = order.index(key)
        if idx < current_index:
            return "complete"
        if idx == current_index:
            return "current"
        return "upcoming"

    stages = tuple(
        OffseasonStageV1(
            key=key,
            label=labels[key],
            kicker=kickers[key],
            detail=detail[key],
            status=stage_status(key),
            icon=icons[key],
            target_section=targets[key],
        )
        for key in order
    )

    progress_complete = sum(
        1 for stage in stages if stage.status in {"complete", "not_required"}
    )
    progress_pct = max(0.0, min(100.0, progress_complete / max(1, len(stages) - 1) * 100.0))

    recommendations = {
        "season_review": (
            "Enter the Draft Lottery",
            "Review the completed season, then move into the Draft Room to establish the next draft order.",
            "Draft Room",
        ),
        "lottery": (
            "Run the Draft Lottery",
            "Set the order and unlock the scouting phase in the existing Draft Room.",
            "Draft Room",
        ),
        "scouting": (
            "Build your draft board",
            "Scout the class, compare uncertainty and team needs, then advance to Draft Night.",
            "Draft Room",
        ),
        "draft": (
            "Finish Draft Night",
            "Complete the live two-round draft before the next-season transition can unlock.",
            "Draft Room",
        ),
        "rights": (
            "Talk to your own players",
            "Use the negotiation room for re-signings, rights context and qualifying-offer decisions.",
            "Free Agency",
        ),
        "free_agency": (
            "Work the market",
            "Negotiate, compare fair value, advance the explicit offseason calendar and monitor CPU competition.",
            "Free Agency",
        ),
        "roster_finalization": (
            "Set the opening-night roster",
            "Review depth, roles and roster balance. Trade Center remains available for the final move.",
            "Team Management",
        ),
        "opening_night": (
            "Open the next season",
            "Use the authoritative season-boundary controls in League Hub when the roster is ready.",
            "League & Offseason",
        ),
    }
    rec_label, rec_detail, rec_target = recommendations[current_key]

    return OffseasonHeadquartersModelV1(
        season_label=season_label,
        team_code=team_code,
        team_name=_text(team_name) or team_code,
        current_key=current_key,
        current_label=labels[current_key],
        current_detail=detail[current_key],
        recommended_label=rec_label,
        recommended_detail=rec_detail,
        recommended_target=rec_target,
        progress_pct=progress_pct,
        opening_offseason=opening,
        offseason_day=offseason_day,
        roster_count=roster_count,
        free_agent_count=free_agent_count,
        rights_count=rights_count,
        active_negotiations=active_negotiations,
        team_signings=team_signings,
        blocking_count=max(0, int(blocking_count or 0)),
        draft_phase=draft_phase,
        stages=stages,
    )


def inject_franchise_offseason_headquarters_visuals_v1(
    *, primary: str = "#CE1141", secondary: str = "#0b1020"
) -> None:
    import streamlit as st

    primary = html.escape(primary or "#CE1141")
    secondary = html.escape(secondary or "#0b1020")
    st.markdown(
        f"""
<style>
/* FRANCHISE_OFFSEASON_HEADQUARTERS_V1 */
.ohq-shell{{--ohq-primary:{primary};--ohq-secondary:{secondary};margin:.7rem 0 1.35rem;color:#f8fafc}}
.ohq-hero{{position:relative;overflow:hidden;padding:20px;border:1px solid color-mix(in srgb,var(--ohq-primary) 38%,#283547);border-radius:23px;background:radial-gradient(circle at 85% -5%,color-mix(in srgb,var(--ohq-primary) 26%,transparent),transparent 38%),linear-gradient(135deg,#07101c,#0b1320 58%,#11131c);box-shadow:0 22px 54px rgba(0,0,0,.24)}}
.ohq-hero:after{{content:"";position:absolute;left:0;right:0;bottom:0;height:3px;background:linear-gradient(90deg,var(--ohq-primary),#22d3ee,var(--ohq-secondary),transparent)}}
.ohq-top{{position:relative;z-index:1;display:flex;justify-content:space-between;align-items:flex-end;gap:18px}}.ohq-kicker{{font-size:.57rem;font-weight:950;letter-spacing:.16em;text-transform:uppercase;color:#7dd3fc}}.ohq-title{{margin:.3rem 0 .35rem;color:#fff;font-size:1.48rem;font-weight:950;line-height:1.05}}.ohq-copy{{max-width:760px;color:#93a4ba;font-size:.68rem;line-height:1.48}}.ohq-now{{min-width:220px;text-align:right}}.ohq-now small{{display:block;color:#72849b;font-size:.48rem;font-weight:950;letter-spacing:.12em;text-transform:uppercase}}.ohq-now strong{{display:block;margin-top:4px;color:#fff;font-size:.88rem}}.ohq-now span{{display:block;margin-top:3px;color:#8fa1b7;font-size:.52rem}}
.ohq-progress{{height:6px;margin-top:14px;border-radius:999px;overflow:hidden;background:#172131}}.ohq-progress span{{display:block;height:100%;border-radius:inherit;background:linear-gradient(90deg,var(--ohq-primary),#22d3ee,#34d399)}}
.ohq-rail{{display:grid;grid-template-columns:repeat(8,minmax(0,1fr));gap:6px;margin-top:8px}}.ohq-stage{{min-height:105px;padding:10px 9px;border:1px solid rgba(255,255,255,.07);border-radius:14px;background:#09111b}}.ohq-stage.complete{{border-color:rgba(74,222,128,.26);background:linear-gradient(180deg,rgba(22,163,74,.10),#09111b)}}.ohq-stage.current{{border-color:var(--ohq-primary);background:linear-gradient(180deg,color-mix(in srgb,var(--ohq-primary) 20%,#111827),#09111b);box-shadow:0 0 24px color-mix(in srgb,var(--ohq-primary) 17%,transparent)}}.ohq-stage.not_required{{opacity:.52}}.ohq-stage.upcoming{{opacity:.7}}.ohq-icon{{font-size:1rem}}.ohq-state{{margin-top:5px;color:#66798f;font-size:.39rem;font-weight:950;letter-spacing:.11em;text-transform:uppercase}}.ohq-stage.current .ohq-state{{color:#fda4af}}.ohq-stage.complete .ohq-state{{color:#86efac}}.ohq-stage-name{{margin-top:4px;color:#f8fafc;font-size:.56rem;font-weight:900;line-height:1.2}}.ohq-stage-copy{{margin-top:4px;color:#71839a;font-size:.42rem;line-height:1.35}}
.ohq-board{{display:grid;grid-template-columns:1.25fr .75fr;gap:8px;margin-top:8px}}.ohq-focus,.ohq-metrics{{border:1px solid rgba(255,255,255,.07);border-radius:15px;background:#08101a;padding:12px 13px}}.ohq-focus-label,.ohq-metric-label{{color:#6f8299;font-size:.44rem;font-weight:950;letter-spacing:.1em;text-transform:uppercase}}.ohq-focus-title{{margin-top:4px;color:#fff;font-size:.75rem;font-weight:950}}.ohq-focus-copy{{margin-top:4px;color:#8fa1b7;font-size:.53rem;line-height:1.4}}.ohq-metrics{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}}.ohq-metric{{min-width:0}}.ohq-metric-value{{margin-top:3px;color:#fff;font-size:.72rem;font-weight:950}}.ohq-metric-note{{margin-top:2px;color:#64758b;font-size:.4rem}}
.ohq-actions{{display:grid;grid-template-columns:repeat(4,1fr);gap:7px;margin-top:8px}}.ohq-action{{padding:10px;border:1px solid rgba(255,255,255,.065);border-radius:13px;background:rgba(255,255,255,.018)}}.ohq-action strong{{display:block;color:#eef6ff;font-size:.56rem}}.ohq-action span{{display:block;margin-top:3px;color:#71849a;font-size:.43rem;line-height:1.35}}
.ohq-preview{{padding:14px 15px;margin:.5rem 0 1rem;border:1px solid color-mix(in srgb,var(--ohq-primary) 34%,#273448);border-radius:17px;background:linear-gradient(135deg,#08111c,#0b1320)}}.ohq-preview-row{{display:flex;justify-content:space-between;align-items:center;gap:12px}}.ohq-preview-title{{color:#fff;font-size:.78rem;font-weight:950}}.ohq-preview-copy{{margin-top:3px;color:#8496ad;font-size:.5rem}}.ohq-preview-step{{text-align:right;color:#7dd3fc;font-size:.46rem;font-weight:950;letter-spacing:.1em;text-transform:uppercase}}
@media(max-width:1180px){{.ohq-rail{{grid-template-columns:repeat(4,minmax(0,1fr))}}.ohq-board{{grid-template-columns:1fr}}}}
@media(max-width:760px){{.ohq-top,.ohq-preview-row{{align-items:flex-start;flex-direction:column}}.ohq-now,.ohq-preview-step{{text-align:left}}.ohq-rail{{grid-template-columns:repeat(2,minmax(0,1fr))}}.ohq-metrics{{grid-template-columns:repeat(2,1fr)}}.ohq-actions{{grid-template-columns:1fr 1fr}}}}
@media(max-width:440px){{.ohq-hero{{padding:14px}}.ohq-stage{{min-height:92px}}.ohq-actions{{grid-template-columns:1fr}}.ohq-metrics{{grid-template-columns:1fr 1fr}}}}
@media(prefers-reduced-motion:reduce){{.ohq-stage.current{{box-shadow:none}}}}
</style>
        """,
        unsafe_allow_html=True,
    )


def _stage_html(stage: OffseasonStageV1) -> str:
    state_label = {
        "complete": "Complete",
        "current": "Now",
        "upcoming": "Upcoming",
        "not_required": "Not required",
    }.get(stage.status, stage.status)
    return (
        f'<div class="ohq-stage {html.escape(stage.status)}">'
        f'<div class="ohq-icon">{html.escape(stage.icon)}</div>'
        f'<div class="ohq-state">{html.escape(state_label)} · {html.escape(stage.kicker)}</div>'
        f'<div class="ohq-stage-name">{html.escape(stage.label)}</div>'
        f'<div class="ohq-stage-copy">{html.escape(stage.detail)}</div>'
        "</div>"
    )


def render_franchise_offseason_headquarters_v1(
    *,
    state: Any,
    active_team: str,
    postseason_state: Any = None,
    draft_state_payload: Mapping[str, Any] | None = None,
    team_name_resolver: Callable[[str], str] | None = None,
    set_section: Callable[[str], None] | None = None,
    blocking_count: int = 0,
) -> OffseasonHeadquartersModelV1 | None:
    import streamlit as st

    if _status(getattr(state, "phase", "")) != "offseason":
        return None

    model = build_offseason_headquarters_model_v1(
        state=state,
        active_team=active_team,
        postseason_state=postseason_state,
        draft_state_payload=draft_state_payload,
        team_name_resolver=team_name_resolver,
        blocking_count=blocking_count,
    )
    stages_html = "".join(_stage_html(stage) for stage in model.stages)
    day_label = f"Day {model.offseason_day}" if model.offseason_day else "Calendar ready"
    blocker_note = (
        f"{model.blocking_count} blocker{'s' if model.blocking_count != 1 else ''} require attention"
        if model.blocking_count
        else "No current franchise blockers"
    )

    st.markdown(
        f'''<div class="ohq-shell"><div class="ohq-hero"><div class="ohq-top"><div><div class="ohq-kicker">{html.escape(model.team_code)} · {html.escape(model.season_label)} · offseason headquarters</div><div class="ohq-title">Build the next version of {html.escape(model.team_name)}</div><div class="ohq-copy">A single front-office path connects the season review, lottery, scouting, Draft Night, player retention, free agency and roster finalization. Every card below routes into the existing durable franchise systems rather than creating a parallel simulation.</div></div><div class="ohq-now"><small>Current chapter</small><strong>{html.escape(model.current_label)}</strong><span>{html.escape(day_label)} · {html.escape(blocker_note)}</span></div></div><div class="ohq-progress"><span style="width:{model.progress_pct:.2f}%"></span></div></div><div class="ohq-rail">{stages_html}</div><div class="ohq-board"><div class="ohq-focus"><div class="ohq-focus-label">Recommended next action</div><div class="ohq-focus-title">{html.escape(model.recommended_label)}</div><div class="ohq-focus-copy">{html.escape(model.recommended_detail)}</div></div><div class="ohq-metrics"><div class="ohq-metric"><div class="ohq-metric-label">Roster</div><div class="ohq-metric-value">{model.roster_count}</div><div class="ohq-metric-note">players</div></div><div class="ohq-metric"><div class="ohq-metric-label">Free agents</div><div class="ohq-metric-value">{model.free_agent_count}</div><div class="ohq-metric-note">market pool</div></div><div class="ohq-metric"><div class="ohq-metric-label">Live talks</div><div class="ohq-metric-value">{model.active_negotiations}</div><div class="ohq-metric-note">negotiations</div></div><div class="ohq-metric"><div class="ohq-metric-label">Rights</div><div class="ohq-metric-value">{model.rights_count}</div><div class="ohq-metric-note">context rows</div></div><div class="ohq-metric"><div class="ohq-metric-label">Signings</div><div class="ohq-metric-value">{model.team_signings}</div><div class="ohq-metric-note">this offseason</div></div><div class="ohq-metric"><div class="ohq-metric-label">Draft</div><div class="ohq-metric-value">{html.escape(model.draft_phase.replace('_', ' ').title() or 'Pending')}</div><div class="ohq-metric-note">lifecycle</div></div></div></div><div class="ohq-actions"><div class="ohq-action"><strong>Draft Room</strong><span>Lottery, scouting and Draft Night.</span></div><div class="ohq-action"><strong>Free Agency</strong><span>Re-signings, rights, offers and market calendar.</span></div><div class="ohq-action"><strong>Trade Center</strong><span>Use the live franchise trade engine for the final move.</span></div><div class="ohq-action"><strong>Team Management</strong><span>Review depth, rotation and opening-night roster shape.</span></div></div></div>''',
        unsafe_allow_html=True,
    )

    if set_section is not None:
        primary_col, draft_col, market_col, roster_col, trade_col = st.columns(
            [1.55, 1.0, 1.0, 1.0, 1.0]
        )
        if primary_col.button(
            model.recommended_label,
            type="primary",
            width="stretch",
            key="offseason_hq_primary_action_v1",
        ):
            set_section(model.recommended_target)
            st.rerun()
        if draft_col.button(
            "Draft Room",
            width="stretch",
            key="offseason_hq_draft_action_v1",
        ):
            set_section("Draft Room")
            st.rerun()
        if market_col.button(
            "Free Agency",
            width="stretch",
            key="offseason_hq_fa_action_v1",
        ):
            set_section("Free Agency")
            st.rerun()
        if roster_col.button(
            "Roster",
            width="stretch",
            key="offseason_hq_roster_action_v1",
        ):
            set_section("Team Management")
            st.rerun()
        if trade_col.button(
            "Trade Center",
            width="stretch",
            key="offseason_hq_trade_action_v1",
        ):
            set_section("Trade Center")
            st.rerun()

    if model.current_key == "roster_finalization" and model.draft_phase == "draft_complete":
        st.caption(
            "Draft complete. The authoritative Open next season control remains below in League Hub so the existing atomic season-boundary transition stays unchanged."
        )
    elif model.opening_offseason:
        st.caption(
            "Opening-season setup does not require lottery, scouting, Draft Night or prior-season retention steps. Finalize the roster, then use the existing Opening Night controls."
        )
    return model


def render_franchise_offseason_headquarters_preview_v1(
    *,
    state: Any,
    active_team: str,
    postseason_state: Any = None,
    draft_state_payload: Mapping[str, Any] | None = None,
    team_name_resolver: Callable[[str], str] | None = None,
    set_section: Callable[[str], None] | None = None,
    blocking_count: int = 0,
) -> OffseasonHeadquartersModelV1 | None:
    import streamlit as st

    if _status(getattr(state, "phase", "")) != "offseason":
        return None
    model = build_offseason_headquarters_model_v1(
        state=state,
        active_team=active_team,
        postseason_state=postseason_state,
        draft_state_payload=draft_state_payload,
        team_name_resolver=team_name_resolver,
        blocking_count=blocking_count,
    )
    st.markdown(
        f'''<div class="ohq-shell ohq-preview"><div class="ohq-preview-row"><div><div class="ohq-kicker">OFFSEASON HEADQUARTERS · {html.escape(model.season_label)}</div><div class="ohq-preview-title">{html.escape(model.current_label)} · {html.escape(model.recommended_label)}</div><div class="ohq-preview-copy">{html.escape(model.recommended_detail)}</div></div><div class="ohq-preview-step">{model.progress_pct:.0f}% · {html.escape(model.current_key.replace('_', ' '))}</div></div><div class="ohq-progress"><span style="width:{model.progress_pct:.2f}%"></span></div></div>''',
        unsafe_allow_html=True,
    )
    if set_section is not None and st.button(
        "Open Offseason Headquarters",
        width="stretch",
        key="offseason_hq_preview_open_v1",
    ):
        set_section("League & Offseason")
        st.rerun()
    return model


# ---------------------------------------------------------------------------
# FRANCHISE_OFFSEASON_HEADQUARTERS_V1_1_FRONT_OFFICE_COMMAND
# Presentation-only enhancement. The durable lifecycle/transaction systems
# remain authoritative.
# ---------------------------------------------------------------------------

_inject_franchise_offseason_headquarters_visuals_v1_base = (
    inject_franchise_offseason_headquarters_visuals_v1
)


def _ohq_v11_financial_snapshot(
    state: Any,
    team_code: str,
) -> tuple[float | None, float | None, float | None]:
    try:
        from franchise_free_agency_transaction_v1_1 import team_guaranteed_payroll
        from franchise_free_agency_financial_bridge_v1_2 import (
            resolve_free_agency_financial_environment,
        )

        payroll, _detail = team_guaranteed_payroll(state, team_code)
        environment = resolve_free_agency_financial_environment(state)
        cap = getattr(environment, "salary_cap", None)
        payroll_value = float(payroll) if payroll is not None else None
        cap_value = float(cap) if cap is not None else None
        cap_space = (
            cap_value - payroll_value
            if cap_value is not None and payroll_value is not None
            else None
        )
        return payroll_value, cap_value, cap_space
    except Exception:
        return None, None, None


def _ohq_v11_future_pick_count(state: Any) -> int:
    try:
        from franchise_draft_engine_v1 import future_user_picks

        return len(list(future_user_picks(state, include_current=True) or ()))
    except Exception:
        return 0


def _ohq_v11_player_name(state: Any, player_id: Any) -> str:
    player = (getattr(state, "players", {}) or {}).get(str(player_id or ""))
    if player is None:
        return str(player_id or "Player")
    for attr in ("display_name", "name", "player_name"):
        value = _text(getattr(player, attr, ""))
        if value:
            return value
    first = _text(getattr(player, "first_name", ""))
    last = _text(getattr(player, "last_name", ""))
    return " ".join(item for item in (first, last) if item) or str(
        player_id or "Player"
    )


def _ohq_v11_recent_activity(
    state: Any,
    team_code: str,
    *,
    limit: int = 4,
) -> tuple[str, ...]:
    output: list[str] = []
    history = list(
        getattr(
            state,
            "free_agency_transaction_history",
            (),
        )
        or ()
    )
    for raw in reversed(history):
        if isinstance(raw, Mapping):
            row = dict(raw)
        elif hasattr(raw, "__dict__"):
            row = dict(vars(raw))
        else:
            continue
        code = _text(
            row.get(
                "team_abbreviation",
                row.get(
                    "team",
                    row.get("prior_team", ""),
                ),
            )
        ).upper()
        if code and code != team_code:
            continue

        name = _ohq_v11_player_name(
            state,
            row.get("player_id", ""),
        )
        pieces = [f"Signed {name}"]
        salary = row.get(
            "annual_salary",
            row.get("contract_salary"),
        )
        years = row.get("years")
        try:
            if salary is not None:
                pieces.append(
                    f"${float(salary) / 1_000_000:.1f}M"
                )
        except Exception:
            pass
        try:
            if years is not None:
                pieces.append(f"{int(years)} yr")
        except Exception:
            pass

        output.append(" · ".join(pieces))
        if len(output) >= limit:
            break

    if not output:
        output.append(
            "No committed team transactions yet this offseason."
        )
    return tuple(output)


def _ohq_v11_money(value: float | None) -> str:
    if value is None:
        return "—"
    sign = "-" if float(value) < 0 else ""
    return (
        f"{sign}${abs(float(value)) / 1_000_000:.1f}M"
    )


def _ohq_v11_next_checkpoint(
    current_key: str,
) -> tuple[str, str]:
    payload = {
        "season_review": (
            "Draft Lottery",
            "Close the completed season and establish the official draft order.",
        ),
        "lottery": (
            "Scouting Board",
            "Once the order is set, shift from lottery position to prospect evaluation.",
        ),
        "scouting": (
            "Draft Night",
            "Finish the board before the live two-round draft begins.",
        ),
        "draft": (
            "Retention Window",
            "Complete the draft before turning to rights and re-signing decisions.",
        ),
        "rights": (
            "Free Agency Market",
            "Resolve core retention decisions before attacking outside targets.",
        ),
        "free_agency": (
            "Roster Finalization",
            "Exit the market with a legal, balanced opening-night roster.",
        ),
        "roster_finalization": (
            "Opening Night",
            "Finish roster construction before the authoritative season transition.",
        ),
        "opening_night": (
            "Next Season",
            "Use the existing season-boundary control after every offseason decision is complete.",
        ),
    }
    return payload.get(
        current_key,
        (
            "Next Offseason Step",
            "Continue through the authoritative franchise lifecycle.",
        ),
    )


def _ohq_v11_decisions(
    model: OffseasonHeadquartersModelV1,
) -> tuple[tuple[str, str, str], ...]:
    label_map = {
        "season_review": "Review completed season",
        "lottery": "Establish draft order",
        "scouting": "Build prospect board",
        "draft": "Complete Draft Night",
        "rights": "Resolve player retention",
        "free_agency": "Work free-agent market",
        "roster_finalization": "Finalize opening-night roster",
        "opening_night": "Open next season",
    }
    return tuple(
        (
            stage.key,
            label_map.get(stage.key, stage.label),
            stage.status,
        )
        for stage in model.stages
    )


def _ohq_v11_priorities(
    *,
    model: OffseasonHeadquartersModelV1,
    cap_space: float | None,
    future_pick_count: int,
) -> tuple[tuple[str, str], ...]:
    rows: list[tuple[str, str]] = []

    if model.blocking_count:
        rows.append(
            (
                "Resolve franchise blockers",
                (
                    f"{model.blocking_count} blocking event"
                    f"{'s' if model.blocking_count != 1 else ''} "
                    "requires attention before the cleanest offseason handoff."
                ),
            )
        )

    if model.current_key in {
        "lottery",
        "scouting",
        "draft",
    }:
        rows.append(
            (
                "Maximize draft position",
                (
                    f"{future_pick_count} controlled future pick asset"
                    f"{'s' if future_pick_count != 1 else ''} "
                    "are visible to the draft layer."
                    if future_pick_count
                    else
                    "Use the existing Draft Room to turn scouting information into controlled draft decisions."
                ),
            )
        )
    elif model.current_key in {
        "rights",
        "free_agency",
    }:
        rows.append(
            (
                "Protect roster value",
                (
                    f"{model.rights_count} rights-context row"
                    f"{'s' if model.rights_count != 1 else ''} and "
                    f"{model.free_agent_count} market player"
                    f"{'s' if model.free_agent_count != 1 else ''} are visible."
                ),
            )
        )
    else:
        rows.append(
            (
                "Set the rotation foundation",
                (
                    f"{model.roster_count} players are currently on "
                    "the controlled-team roster."
                ),
            )
        )

    if model.roster_count < 14:
        rows.append(
            (
                "Add roster depth",
                (
                    f"The roster currently has {model.roster_count} players. "
                    "Keep roster construction active before Opening Night."
                ),
            )
        )
    elif model.roster_count > 15:
        rows.append(
            (
                "Trim roster pressure",
                (
                    f"The roster currently has {model.roster_count} players. "
                    "Review the final roster and trade options."
                ),
            )
        )
    else:
        rows.append(
            (
                "Preserve roster balance",
                (
                    f"The roster currently sits at {model.roster_count} players. "
                    "Review role and positional balance before the season transition."
                ),
            )
        )

    if cap_space is not None:
        if cap_space >= 0:
            cap_text = (
                f"{_ohq_v11_money(cap_space)} in simple "
                "guaranteed-payroll cap space"
            )
        else:
            cap_text = (
                f"{_ohq_v11_money(cap_space)} versus the "
                "simple salary-cap line"
            )
        rows.append(
            (
                "Manage financial flexibility",
                (
                    f"{cap_text}. Full CBA legality remains authoritative "
                    "inside the transaction workspaces."
                ),
            )
        )

    return tuple(rows[:3])


def inject_franchise_offseason_headquarters_visuals_v1(
    *,
    primary: str = "#CE1141",
    secondary: str = "#0b1020",
) -> None:
    import streamlit as st

    _inject_franchise_offseason_headquarters_visuals_v1_base(
        primary=primary,
        secondary=secondary,
    )
    st.markdown(
        """
<style>
/* FRANCHISE_OFFSEASON_HEADQUARTERS_V1_1_FRONT_OFFICE_COMMAND */
.ohq-v11-grid{display:grid;grid-template-columns:1.2fr .8fr;gap:8px;margin-top:8px}
.ohq-v11-panel{border:1px solid rgba(255,255,255,.07);border-radius:15px;background:#08101a;padding:13px}
.ohq-v11-panel-title{color:#7dd3fc;font-size:.47rem;font-weight:950;letter-spacing:.12em;text-transform:uppercase}
.ohq-v11-checks{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px;margin-top:8px}
.ohq-v11-check{padding:9px;border-radius:12px;border:1px solid rgba(255,255,255,.06);background:#0a131f}
.ohq-v11-check.complete{border-color:rgba(74,222,128,.25)}
.ohq-v11-check.current{border-color:var(--ohq-primary);background:color-mix(in srgb,var(--ohq-primary) 11%,#0a131f)}
.ohq-v11-check.not_required{opacity:.5}
.ohq-v11-check-state{font-size:.38rem;font-weight:950;letter-spacing:.1em;text-transform:uppercase;color:#708399}
.ohq-v11-check.current .ohq-v11-check-state{color:#fda4af}
.ohq-v11-check.complete .ohq-v11-check-state{color:#86efac}
.ohq-v11-check-label{margin-top:3px;color:#f8fafc;font-size:.49rem;font-weight:850;line-height:1.25}
.ohq-v11-priority{padding:9px 0;border-bottom:1px solid rgba(255,255,255,.055)}
.ohq-v11-priority:last-child{border-bottom:0}
.ohq-v11-priority strong{display:block;color:#f8fafc;font-size:.55rem}
.ohq-v11-priority span{display:block;margin-top:3px;color:#7f91a6;font-size:.45rem;line-height:1.4}
.ohq-v11-activity{padding:7px 0;color:#a4b2c3;font-size:.47rem;border-bottom:1px solid rgba(255,255,255,.05)}
.ohq-v11-activity:last-child{border-bottom:0}
.ohq-v11-finance{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:8px}
.ohq-v11-fin-card{padding:10px;border-radius:12px;background:#0a131f;border:1px solid rgba(255,255,255,.055)}
.ohq-v11-fin-card small{display:block;color:#687a91;font-size:.38rem;font-weight:950;letter-spacing:.1em;text-transform:uppercase}
.ohq-v11-fin-card strong{display:block;margin-top:4px;color:#fff;font-size:.66rem}
@media(max-width:1180px){
  .ohq-v11-grid{grid-template-columns:1fr}
  .ohq-v11-checks{grid-template-columns:repeat(2,minmax(0,1fr))}
}
@media(max-width:760px){
  .ohq-v11-finance{grid-template-columns:repeat(2,1fr)}
}
@media(max-width:440px){
  .ohq-v11-checks{grid-template-columns:1fr 1fr}
}

/* FRANCHISE_OFFSEASON_HEADQUARTERS_V1_2_PRESENTATION_SCALE */
.ohq-shell{margin:1.05rem 0 1.8rem}
.ohq-hero{padding:28px 30px;border-radius:26px}
.ohq-kicker{font-size:.72rem;letter-spacing:.15em}
.ohq-title{margin:.45rem 0 .5rem;font-size:2.05rem;line-height:1.02}
.ohq-copy{max-width:880px;font-size:.88rem;line-height:1.58}
.ohq-now{min-width:250px}
.ohq-now small{font-size:.61rem}
.ohq-now strong{font-size:1.12rem}
.ohq-now span{font-size:.68rem}
.ohq-progress{height:8px;margin-top:18px}

.ohq-rail{grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-top:12px}
.ohq-stage{min-height:132px;padding:15px 14px;border-radius:17px}
.ohq-icon{font-size:1.25rem}
.ohq-state{margin-top:7px;font-size:.53rem}
.ohq-stage-name{margin-top:6px;font-size:.77rem;line-height:1.25}
.ohq-stage-copy{margin-top:6px;font-size:.61rem;line-height:1.48}

.ohq-board{grid-template-columns:1.2fr .8fr;gap:12px;margin-top:12px}
.ohq-focus,.ohq-metrics{padding:17px 18px;border-radius:18px}
.ohq-focus-label,.ohq-metric-label{font-size:.59rem}
.ohq-focus-title{margin-top:6px;font-size:1.02rem}
.ohq-focus-copy{margin-top:6px;font-size:.72rem;line-height:1.52}

.ohq-v11-finance{gap:10px;margin-top:12px}
.ohq-v11-fin-card{padding:15px 16px;border-radius:15px}
.ohq-v11-fin-card small{font-size:.53rem}
.ohq-v11-fin-card strong{margin-top:6px;font-size:.96rem}

.ohq-v11-panel{padding:18px 19px;border-radius:18px}
.ohq-v11-panel-title{font-size:.63rem}
.ohq-v11-checks{grid-template-columns:repeat(4,minmax(0,1fr));gap:9px;margin-top:11px}
.ohq-v11-check{min-height:72px;padding:12px 13px;border-radius:14px}
.ohq-v11-check-state{font-size:.50rem}
.ohq-v11-check-label{margin-top:6px;font-size:.68rem;line-height:1.33}
.ohq-v11-grid{grid-template-columns:1.15fr .85fr;gap:12px;margin-top:12px}
.ohq-v11-priority{padding:13px 0}
.ohq-v11-priority strong{font-size:.74rem}
.ohq-v11-priority span{margin-top:5px;font-size:.62rem;line-height:1.5}
.ohq-v11-activity{padding:11px 0;font-size:.64rem;line-height:1.48}

.ohq-actions{gap:10px;margin-top:12px}
.ohq-action{padding:14px 15px;border-radius:15px}
.ohq-action strong{font-size:.73rem}
.ohq-action span{margin-top:5px;font-size:.59rem;line-height:1.45}

@media(max-width:1180px){
  .ohq-rail{grid-template-columns:repeat(2,minmax(0,1fr))}
  .ohq-board,.ohq-v11-grid{grid-template-columns:1fr}
  .ohq-v11-checks{grid-template-columns:repeat(2,minmax(0,1fr))}
}
@media(max-width:760px){
  .ohq-hero{padding:21px}
  .ohq-title{font-size:1.65rem}
  .ohq-copy{font-size:.82rem}
  .ohq-stage{min-height:118px}
  .ohq-v11-finance{grid-template-columns:repeat(2,1fr)}
}
@media(max-width:520px){
  .ohq-rail,.ohq-v11-checks,.ohq-actions{grid-template-columns:1fr}
  .ohq-stage{min-height:auto}
  .ohq-v11-finance{grid-template-columns:1fr 1fr}
}
</style>
        """,
        unsafe_allow_html=True,
    )


def render_franchise_offseason_headquarters_v1(
    *,
    state: Any,
    active_team: str,
    postseason_state: Any = None,
    draft_state_payload: Mapping[str, Any] | None = None,
    team_name_resolver: Callable[[str], str] | None = None,
    set_section: Callable[[str], None] | None = None,
    blocking_count: int = 0,
) -> OffseasonHeadquartersModelV1 | None:
    import streamlit as st

    if _status(getattr(state, "phase", "")) != "offseason":
        return None

    model = build_offseason_headquarters_model_v1(
        state=state,
        active_team=active_team,
        postseason_state=postseason_state,
        draft_state_payload=draft_state_payload,
        team_name_resolver=team_name_resolver,
        blocking_count=blocking_count,
    )
    stages_html = "".join(
        _stage_html(stage)
        for stage in model.stages
    )
    day_label = (
        f"Day {model.offseason_day}"
        if model.offseason_day
        else "Calendar ready"
    )
    blocker_note = (
        (
            f"{model.blocking_count} blocker"
            f"{'s' if model.blocking_count != 1 else ''} require attention"
        )
        if model.blocking_count
        else "No current franchise blockers"
    )

    payroll, salary_cap, cap_space = (
        _ohq_v11_financial_snapshot(
            state,
            model.team_code,
        )
    )
    future_pick_count = _ohq_v11_future_pick_count(
        state
    )
    recent_activity = _ohq_v11_recent_activity(
        state,
        model.team_code,
    )
    next_checkpoint, next_detail = (
        _ohq_v11_next_checkpoint(
            model.current_key
        )
    )
    priorities = _ohq_v11_priorities(
        model=model,
        cap_space=cap_space,
        future_pick_count=future_pick_count,
    )
    decisions = _ohq_v11_decisions(model)

    status_labels = {
        "complete": "Complete",
        "current": "Now",
        "upcoming": "Upcoming",
        "not_required": "Not required",
    }
    decisions_html = "".join(
        (
            f'<div class="ohq-v11-check {html.escape(status)}">'
            f'<div class="ohq-v11-check-state">'
            f'{html.escape(status_labels.get(status, status))}'
            f"</div>"
            f'<div class="ohq-v11-check-label">'
            f"{html.escape(label)}"
            f"</div></div>"
        )
        for _key, label, status in decisions
    )
    priorities_html = "".join(
        (
            '<div class="ohq-v11-priority">'
            f"<strong>{html.escape(label)}</strong>"
            f"<span>{html.escape(detail)}</span>"
            "</div>"
        )
        for label, detail in priorities
    )
    activity_html = "".join(
        (
            '<div class="ohq-v11-activity">'
            f"{html.escape(item)}"
            "</div>"
        )
        for item in recent_activity
    )

    st.markdown(
        f"""
<div class="ohq-shell">
  <div class="ohq-hero">
    <div class="ohq-top">
      <div>
        <div class="ohq-kicker">{html.escape(model.team_code)} · {html.escape(model.season_label)} · offseason headquarters</div>
        <div class="ohq-title">Build the next version of {html.escape(model.team_name)}</div>
        <div class="ohq-copy">One guided command screen for the whole offseason. This presentation reads the durable franchise state and routes into the systems that already own every real transaction.</div>
      </div>
      <div class="ohq-now">
        <small>Current chapter</small>
        <strong>{html.escape(model.current_label)}</strong>
        <span>{html.escape(day_label)} · {html.escape(blocker_note)}</span>
      </div>
    </div>
    <div class="ohq-progress"><span style="width:{model.progress_pct:.2f}%"></span></div>
  </div>

  <div class="ohq-rail">{stages_html}</div>

  <div class="ohq-board">
    <div class="ohq-focus">
      <div class="ohq-focus-label">Primary front-office objective</div>
      <div class="ohq-focus-title">{html.escape(model.recommended_label)}</div>
      <div class="ohq-focus-copy">{html.escape(model.recommended_detail)}</div>
    </div>
    <div class="ohq-focus">
      <div class="ohq-focus-label">Next checkpoint</div>
      <div class="ohq-focus-title">{html.escape(next_checkpoint)}</div>
      <div class="ohq-focus-copy">{html.escape(next_detail)}</div>
    </div>
  </div>

  <div class="ohq-v11-finance">
    <div class="ohq-v11-fin-card"><small>Roster</small><strong>{model.roster_count}</strong></div>
    <div class="ohq-v11-fin-card"><small>Guaranteed payroll</small><strong>{html.escape(_ohq_v11_money(payroll))}</strong></div>
    <div class="ohq-v11-fin-card"><small>Simple cap space</small><strong>{html.escape(_ohq_v11_money(cap_space))}</strong></div>
    <div class="ohq-v11-fin-card"><small>Controlled picks</small><strong>{future_pick_count if future_pick_count else "—"}</strong></div>
  </div>

  <div class="ohq-v11-panel" style="margin-top:8px">
    <div class="ohq-v11-panel-title">Decision checklist</div>
    <div class="ohq-v11-checks">{decisions_html}</div>
  </div>

  <div class="ohq-v11-grid">
    <div class="ohq-v11-panel">
      <div class="ohq-v11-panel-title">Front office priorities</div>
      {priorities_html}
    </div>
    <div class="ohq-v11-panel">
      <div class="ohq-v11-panel-title">Recent team activity</div>
      {activity_html}
    </div>
  </div>

  <div class="ohq-actions">
    <div class="ohq-action"><strong>Draft Room</strong><span>Lottery, scouting and Draft Night.</span></div>
    <div class="ohq-action"><strong>Free Agency</strong><span>Re-signings, rights, offers and market calendar.</span></div>
    <div class="ohq-action"><strong>Trade Center</strong><span>Use the live franchise trade engine for the final move.</span></div>
    <div class="ohq-action"><strong>Team Management</strong><span>Review depth, rotation and opening-night roster shape.</span></div>
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )

    if set_section is not None:
        (
            primary_col,
            draft_col,
            market_col,
            roster_col,
            trade_col,
        ) = st.columns(
            [1.65, 1.0, 1.0, 1.0, 1.0]
        )
        if primary_col.button(
            (
                "Continue Offseason · "
                f"{model.recommended_label}"
            ),
            type="primary",
            width="stretch",
            key="offseason_hq_primary_action_v11",
        ):
            set_section(
                model.recommended_target
            )
            st.rerun()
        if draft_col.button(
            "Draft Room",
            width="stretch",
            key="offseason_hq_draft_action_v11",
        ):
            set_section("Draft Room")
            st.rerun()
        if market_col.button(
            "Free Agency",
            width="stretch",
            key="offseason_hq_fa_action_v11",
        ):
            set_section("Free Agency")
            st.rerun()
        if roster_col.button(
            "Roster",
            width="stretch",
            key="offseason_hq_roster_action_v11",
        ):
            set_section("Team Management")
            st.rerun()
        if trade_col.button(
            "Trade Center",
            width="stretch",
            key="offseason_hq_trade_action_v11",
        ):
            set_section("Trade Center")
            st.rerun()

    if (
        model.current_key
        == "roster_finalization"
        and model.draft_phase
        == "draft_complete"
    ):
        st.caption(
            "Draft complete. The authoritative Open next season control remains below in League Hub so the existing atomic season-boundary transition stays unchanged."
        )
    elif model.opening_offseason:
        st.caption(
            "Opening-season setup skips prior-season review, lottery, scouting, Draft Night and retention. Finalize the roster, then use the existing Opening Night controls."
        )

    return model
