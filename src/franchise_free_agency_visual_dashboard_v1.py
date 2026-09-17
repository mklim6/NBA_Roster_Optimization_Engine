from __future__ import annotations

import html
import re
from typing import Any


FRANCHISE_FREE_AGENCY_VISUAL_DASHBOARD_VERSION = (
    "franchise-free-agency-visual-dashboard-v1.0-2026-09-12"
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _money(value: float | int | None) -> str:
    if value is None:
        return "Review"
    amount = float(value)
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    if amount >= 1_000_000:
        return f"{sign}${amount / 1_000_000:.1f}M"
    if amount >= 1_000:
        return f"{sign}${amount / 1_000:.0f}K"
    return f"{sign}${amount:,.0f}"


def _headshot(player_id: Any) -> str:
    resolved = _text(player_id)
    if re.fullmatch(r"\d+", resolved):
        return f"https://cdn.nba.com/headshots/nba/latest/1040x760/{resolved}.png"
    return "https://cdn.nba.com/manage/2021/08/NBA75-primary-logo-1.jpg"


def _top_targets(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    eligible = [row for row in rows if _text(row.get("player_name"))]
    return sorted(
        eligible,
        key=lambda row: (
            _number(row.get("overall"), -1.0),
            _number(row.get("potential"), -1.0),
            _text(row.get("player_name")),
        ),
        reverse=True,
    )[:3]


def render_free_agency_visual_dashboard_v1(
    *,
    state: Any,
    rows: list[dict[str, Any]],
    active_team: str,
    season: str,
    phase: str,
    payroll: float | None,
    salary_cap: float | None,
    calendar_day: int | None,
    active_negotiations: int,
    financial_source: str,
) -> None:
    import streamlit as st

    team = _text(active_team).upper() or "TEAM"
    team_state = (getattr(state, "teams", {}) or {}).get(team)
    roster_count = len(tuple(getattr(team_state, "roster_player_ids", ()) or ()))
    signings = sum(
        1
        for item in list(getattr(state, "free_agency_transaction_history", []) or [])
        if _text(
            item.get("team_abbreviation", item.get("team", ""))
            if isinstance(item, dict)
            else getattr(item, "team_abbreviation", getattr(item, "team", ""))
        ).upper()
        == team
    )
    cap_margin = (
        float(salary_cap) - float(payroll)
        if salary_cap is not None and payroll is not None
        else None
    )
    day_label = f"Day {int(calendar_day)}" if calendar_day else "Not started"
    targets = _top_targets(rows)
    target_html = "".join(
        f'''<div class="fav-target"><img src="{html.escape(_headshot(row.get('player_id')), quote=True)}" alt="{html.escape(_text(row.get('player_name')), quote=True)}"><div><div class="fav-target-rank">MARKET {index:02d}</div><div class="fav-target-name">{html.escape(_text(row.get('player_name')))}</div><div class="fav-target-meta">{html.escape(_text(row.get('position')) or '—')} · {(_number(row.get('overall'))):.1f} OVR</div></div></div>'''
        for index, row in enumerate(targets, 1)
    )
    if not target_html:
        target_html = '<div class="fav-target empty"><div><div class="fav-target-rank">MARKET</div><div class="fav-target-name">No available players</div><div class="fav-target-meta">Advance the offseason when ready</div></div></div>'

    steps = [
        ("Market open", True),
        ("Negotiations", active_negotiations > 0),
        ("Signings", signings > 0),
        ("Draft bridge", False),
    ]
    current_index = 2 if signings else 1 if active_negotiations else 0
    step_html = "".join(
        f'<div class="fav-step {"done" if done else "current" if index == current_index else ""}"><span>{index + 1:02d}</span>{html.escape(label)}</div>'
        for index, (label, done) in enumerate(steps)
    )

    st.markdown(
        f'''
<style>
/* FRANCHISE_FREE_AGENCY_VISUAL_DASHBOARD_V1 */
.fav-shell{{--fav-primary:var(--team-primary,#ef4444);--fav-secondary:var(--team-secondary,#f59e0b);margin:.65rem 0 1.15rem;color:#f7fbff}}
.fav-hero{{position:relative;overflow:hidden;display:grid;grid-template-columns:minmax(250px,.9fr) minmax(430px,1.6fr);gap:14px;padding:19px;border:1px solid color-mix(in srgb,var(--fav-primary) 35%,rgba(255,255,255,.09));border-radius:21px;background:radial-gradient(circle at 90% 0,color-mix(in srgb,var(--fav-primary) 22%,transparent),transparent 38%),linear-gradient(140deg,#09111d,#0c1421 58%,#080d16);box-shadow:0 20px 48px rgba(0,0,0,.24)}}
.fav-hero:after{{content:"";position:absolute;left:0;right:0;bottom:0;height:3px;background:linear-gradient(90deg,var(--fav-primary),#22d3ee,var(--fav-secondary),transparent)}}
.fav-command,.fav-market{{position:relative;z-index:1}}.fav-kicker{{color:#7dd3fc;font-size:.56rem;font-weight:950;letter-spacing:.15em;text-transform:uppercase}}.fav-title{{margin:.25rem 0 .4rem;color:#fff;font-size:1.25rem;font-weight:950}}.fav-copy{{max-width:460px;color:#92a3b8;font-size:.67rem;line-height:1.45}}.fav-status{{display:inline-flex;align-items:center;gap:6px;margin-top:11px;padding:5px 8px;border:1px solid rgba(52,211,153,.2);border-radius:999px;background:rgba(16,185,129,.09);color:#9ff3cb;font-size:.51rem;font-weight:950;letter-spacing:.08em}}.fav-status i{{width:6px;height:6px;border-radius:50%;background:#34d399;box-shadow:0 0 10px #34d399}}
.fav-market{{display:grid;grid-template-columns:repeat(3,1fr);gap:7px}}.fav-target{{display:flex;align-items:center;gap:8px;min-width:0;padding:9px;border:1px solid rgba(255,255,255,.07);border-radius:13px;background:rgba(255,255,255,.025)}}.fav-target img{{width:50px;height:54px;object-fit:cover;object-position:top;border-radius:9px;background:rgba(255,255,255,.04)}}.fav-target-rank{{color:#7dd3fc;font-size:.43rem;font-weight:950;letter-spacing:.1em}}.fav-target-name{{overflow:hidden;color:#fff;font-size:.61rem;font-weight:900;text-overflow:ellipsis;white-space:nowrap}}.fav-target-meta{{margin-top:2px;color:#7e90a7;font-size:.47rem;white-space:nowrap}}
.fav-ledger{{display:grid;grid-template-columns:repeat(6,1fr);gap:7px;margin-top:8px}}.fav-cell{{padding:10px 9px;border:1px solid rgba(255,255,255,.07);border-radius:12px;background:rgba(255,255,255,.018)}}.fav-cell-label{{color:#74869b;font-size:.46rem;font-weight:900;text-transform:uppercase;letter-spacing:.08em}}.fav-cell-value{{margin-top:4px;color:#f8fbff;font-size:.74rem;font-weight:950}}.fav-cell-detail{{margin-top:2px;color:#61738a;font-size:.42rem}}
.fav-rail{{display:grid;grid-template-columns:repeat(4,1fr);gap:5px;margin-top:8px;padding:7px;border:1px solid rgba(255,255,255,.065);border-radius:12px;background:rgba(255,255,255,.012)}}.fav-step{{display:flex;align-items:center;gap:7px;padding:7px;color:#687a90;font-size:.5rem;font-weight:850}}.fav-step span{{display:grid;place-items:center;width:20px;height:20px;border-radius:7px;background:rgba(255,255,255,.04);font-size:.42rem}}.fav-step.done,.fav-step.current{{color:#dce7f5}}.fav-step.done span{{background:rgba(16,185,129,.13);color:#86efac}}.fav-step.current span{{background:color-mix(in srgb,var(--fav-primary) 24%,#111827);color:#fff;box-shadow:0 0 14px color-mix(in srgb,var(--fav-primary) 20%,transparent)}}
@media(max-width:950px){{.fav-hero{{grid-template-columns:1fr}}.fav-ledger{{grid-template-columns:repeat(3,1fr)}}}}
@media(max-width:620px){{.fav-hero{{padding:14px}}.fav-market{{grid-template-columns:1fr}}.fav-target img{{width:42px;height:46px}}.fav-ledger{{grid-template-columns:repeat(2,1fr)}}.fav-rail{{grid-template-columns:1fr 1fr}}}}
@media(prefers-reduced-motion:reduce){{.fav-status i{{box-shadow:none}}}}
</style>
<div class="fav-shell"><div class="fav-hero"><div class="fav-command"><div class="fav-kicker">{html.escape(team)} · {html.escape(season or 'Offseason')} front office</div><div class="fav-title">Free Agency Command Desk</div><div class="fav-copy">See the market, financial baseline, roster size and active talks before building an offer. Contract legality remains authoritative in the preview below.</div><div class="fav-status"><i></i>{html.escape(day_label)} · {html.escape(phase.replace('_', ' ').title())}</div></div><div class="fav-market">{target_html}</div></div>
<div class="fav-ledger">
<div class="fav-cell"><div class="fav-cell-label">Guaranteed payroll</div><div class="fav-cell-value">{_money(payroll)}</div><div class="fav-cell-detail">Committed salary</div></div>
<div class="fav-cell"><div class="fav-cell-label">Salary cap</div><div class="fav-cell-value">{_money(salary_cap)}</div><div class="fav-cell-detail">{html.escape(financial_source)}</div></div>
<div class="fav-cell"><div class="fav-cell-label">Base cap margin</div><div class="fav-cell-value">{_money(cap_margin)}</div><div class="fav-cell-detail">Before holds / exceptions</div></div>
<div class="fav-cell"><div class="fav-cell-label">Rostered</div><div class="fav-cell-value">{roster_count}</div><div class="fav-cell-detail">Active team players</div></div>
<div class="fav-cell"><div class="fav-cell-label">Live talks</div><div class="fav-cell-value">{int(active_negotiations)}</div><div class="fav-cell-detail">Persistent markets</div></div>
<div class="fav-cell"><div class="fav-cell-label">Available</div><div class="fav-cell-value">{len(rows)}</div><div class="fav-cell-detail">Free-agent pool</div></div>
</div><div class="fav-rail">{step_html}</div></div>
''',
        unsafe_allow_html=True,
    )

