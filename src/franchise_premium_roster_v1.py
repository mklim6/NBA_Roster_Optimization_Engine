from __future__ import annotations

import html
import itertools
from typing import Any, Callable, Iterable


FRANCHISE_PREMIUM_ROSTER_VERSION = "franchise-premium-roster-v1.1-2026-09-11"


def _escape(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clean_position(value: Any) -> str:
    raw = str(value or "").upper().replace("/", "-").replace(" ", "")
    aliases = {
        "POINTGUARD": "PG",
        "SHOOTINGGUARD": "SG",
        "SMALLFORWARD": "SF",
        "POWERFORWARD": "PF",
        "CENTER": "C",
        "GUARD": "G",
        "FORWARD": "F",
    }
    return aliases.get(raw, raw or "UNK")


def _position_tokens(value: Any) -> set[str]:
    position = _clean_position(value)
    tokens = {token for token in position.replace("_", "-").split("-") if token}
    expanded = set(tokens)
    if "G" in tokens:
        expanded.update({"PG", "SG"})
    if "F" in tokens:
        expanded.update({"SF", "PF"})
    if "GF" in tokens or "FG" in tokens:
        expanded.update({"PG", "SG", "SF", "PF"})
    if "FC" in tokens or "CF" in tokens:
        expanded.update({"SF", "PF", "C"})
    for token in list(tokens):
        if token.startswith("PG"):
            expanded.add("PG")
        if token.startswith("SG"):
            expanded.add("SG")
        if token.startswith("SF"):
            expanded.add("SF")
        if token.startswith("PF"):
            expanded.add("PF")
        if token == "C" or token.endswith("C"):
            expanded.add("C")
    return expanded


def _position_cost(position: Any, slot: str) -> float:
    tokens = _position_tokens(position)
    if slot in tokens:
        return 0.0
    adjacency = {
        "PG": ("SG", "SF"),
        "SG": ("PG", "SF"),
        "SF": ("SG", "PF"),
        "PF": ("SF", "C"),
        "C": ("PF", "SF"),
    }
    if any(other in tokens for other in adjacency[slot]):
        return 1.6
    if slot in {"PG", "SG"} and any(t in tokens for t in {"PG", "SG", "G"}):
        return 0.8
    if slot in {"SF", "PF"} and any(t in tokens for t in {"SF", "PF", "F"}):
        return 0.8
    return 4.0


def archetype_label_v1(player: Any) -> str:
    skills = dict(getattr(player, "skill_ratings", {}) or {})
    scoring = _num(skills.get("scoring_rating"), getattr(player, "overall_rating", 75.0))
    shooting = _num(skills.get("shooting_rating"), getattr(player, "overall_rating", 75.0))
    playmaking = _num(skills.get("playmaking_rating"), getattr(player, "overall_rating", 75.0))
    rebounding = _num(skills.get("rebounding_rating"), getattr(player, "overall_rating", 75.0))
    defense = _num(skills.get("defense_rating"), getattr(player, "overall_rating", 75.0))
    efficiency = _num(skills.get("efficiency_rating"), getattr(player, "overall_rating", 75.0))
    tokens = _position_tokens(getattr(player, "position", ""))

    if shooting >= 78 and defense >= 76 and abs(shooting - defense) <= 8:
        return "3-and-D"
    if playmaking >= 80 and scoring >= 77 and tokens.intersection({"PG", "SG"}):
        return "Primary Creator"
    if defense >= 80 and rebounding >= 78 and tokens.intersection({"PF", "C"}):
        return "Rim Protector"
    if shooting >= 82 and scoring >= 78:
        return "Three-Level Scorer"
    if shooting >= max(scoring, playmaking, rebounding, defense, efficiency):
        return "Sharpshooter"
    if playmaking >= max(scoring, shooting, rebounding, defense, efficiency):
        return "Floor General"
    if defense >= max(scoring, shooting, playmaking, rebounding, efficiency):
        return "Defensive Anchor" if tokens.intersection({"PF", "C"}) else "Perimeter Stopper"
    if rebounding >= max(scoring, shooting, playmaking, defense, efficiency):
        return "Glass Cleaner"
    if efficiency >= max(scoring, shooting, playmaking, rebounding, defense):
        return "Efficient Connector"
    return "Shot Creator"


def role_label_v1(row: dict[str, Any]) -> str:
    starter = bool(row.get("starter"))
    in_rotation = bool(row.get("in_rotation"))
    minutes = _num(row.get("minutes"))
    overall = _num(row.get("overall"))
    order = int(_num(row.get("rotation_order"), 99))
    if starter and (overall >= 87 or minutes >= 34):
        return "Franchise Star"
    if starter:
        return "Starter"
    if in_rotation and order <= 6:
        return "Sixth Man"
    if in_rotation and minutes >= 20:
        return "Core Rotation"
    if in_rotation:
        return "Rotation"
    return "Reserve"


def contract_label_v1(player: Any) -> tuple[str, str]:
    contract = getattr(player, "contract", None)
    salary = getattr(contract, "salary", None) if contract is not None else None
    years = getattr(contract, "years_remaining", None) if contract is not None else None
    option = str(getattr(contract, "option_type", "") or "").strip()
    status = str(getattr(contract, "status", "") or "").replace("_", " ").strip()

    if salary is None:
        money = "Salary N/A"
    else:
        value = _num(salary)
        money = f"${value / 1_000_000:.1f}M" if abs(value) >= 1_000_000 else f"${value:,.0f}"

    if years is None:
        if status in {"two_way", "exhibit_10"}:
            term = status.replace("_", " ").title()
        elif status == "free_agent_pool":
            term = "Free Agent"
        else:
            term = "Term N/A"
    else:
        years_i = max(0, int(years))
        if years_i == 0:
            term = "Expiring"
        elif years_i == 1:
            term = "1Y · Expiring"
        else:
            term = f"{years_i}Y LEFT"
    if option:
        term = f"{term} · {option.replace('_', ' ').title()}"
    return money, term


def development_label_v1(player: Any) -> tuple[str, str]:
    direction = str(getattr(player, "development_direction", "Stable") or "Stable").strip()
    lowered = direction.lower()
    if any(word in lowered for word in ("up", "rise", "improv", "positive", "growth", "develop")):
        arrow = "↗"
    elif any(word in lowered for word in ("down", "declin", "negative", "regress")):
        arrow = "↘"
    else:
        arrow = "→"
    potential = getattr(player, "potential_rating", None)
    if potential is None:
        return f"{arrow} {direction}", "POT —"
    return f"{arrow} {direction}", f"POT {_num(potential):.0f}"


def recent_form_v1(state: Any, player_id: str, team: str, limit: int = 5) -> list[dict[str, float]]:
    schedule = dict(getattr(state, "schedule", {}) or {})
    completed = dict(getattr(state, "completed_games", {}) or {})
    games: list[tuple[int, Any]] = []
    for game_id, game in completed.items():
        if team not in {str(getattr(game, "home_team", "")), str(getattr(game, "away_team", ""))}:
            continue
        scheduled = schedule.get(game_id)
        day_index = int(getattr(scheduled, "day_index", 0) or 0)
        games.append((day_index, game))
    games.sort(key=lambda item: item[0], reverse=True)

    form: list[dict[str, float]] = []
    for day_index, game in games:
        line = next(
            (
                row
                for row in tuple(getattr(game, "player_box_scores", ()) or ())
                if str(getattr(row, "player_id", "")) == str(player_id)
            ),
            None,
        )
        if line is None or _num(getattr(line, "minutes", 0.0)) <= 0:
            continue
        form.append(
            {
                "day": float(day_index),
                "points": _num(getattr(line, "points", 0)),
                "rebounds": _num(getattr(line, "rebounds", 0)),
                "assists": _num(getattr(line, "assists", 0)),
                "minutes": _num(getattr(line, "minutes", 0.0)),
            }
        )
        if len(form) >= limit:
            break
    return list(reversed(form))


def _sparkline_html(form: list[dict[str, float]]) -> str:
    if not form:
        return '<div class="fpr-form-empty">NO GAME FORM YET</div>'
    values = [max(0.0, _num(row.get("points"))) for row in form]
    peak = max(max(values), 1.0)
    bars = []
    for row, value in zip(form, values):
        height = 22 + int(58 * value / peak)
        bars.append(
            '<span class="fpr-spark-bar" '
            f'style="height:{height}%" title="{value:.0f} PTS"></span>'
        )
    average = sum(values) / len(values)
    return (
        '<div class="fpr-form-wrap">'
        '<div class="fpr-form-label">RECENT FORM</div>'
        '<div class="fpr-spark">' + ''.join(bars) + '</div>'
        f'<div class="fpr-form-avg">{average:.1f} PPG</div>'
        '</div>'
    )


def _health_class(status: str) -> str:
    lowered = str(status or "").lower()
    if lowered in {"healthy", "available", "probable"}:
        return "good"
    if lowered in {"questionable", "day_to_day", "day-to-day", "limited"}:
        return "warn"
    if lowered in {"doubtful", "out", "inactive"}:
        return "bad"
    return "neutral"


def _premium_card_html(
    *,
    state: Any,
    team: str,
    row: dict[str, Any],
    player: Any,
    player_headshot_resolver: Callable[..., str],
    compact: bool = False,
) -> str:
    player_id = str(row.get("player_id", ""))
    name = str(row.get("player", getattr(player, "player_name", "Player")))
    position = str(row.get("position", getattr(player, "position", "—")))
    overall = _num(row.get("overall", getattr(player, "overall_rating", 0.0)))
    minutes = _num(row.get("minutes"))
    fatigue = _num(row.get("fatigue"))
    availability = str(row.get("availability", "available") or "available")
    role = role_label_v1(row)
    archetype = archetype_label_v1(player)
    money, term = contract_label_v1(player)
    development, potential = development_label_v1(player)
    form = recent_form_v1(state, player_id, team)
    image = str(player_headshot_resolver(player_id, team, name) or "")
    age = getattr(player, "age", None)
    age_copy = f"AGE {_num(age):.0f}" if age is not None else "AGE —"
    health_class = _health_class(availability)
    fatigue_class = "bad" if fatigue >= 75 else "warn" if fatigue >= 50 else "good"
    compact_class = " fpr-card-compact" if compact else ""
    return (
        f'<article class="fpr-player-card{compact_class}">'
        '<div class="fpr-card-photo">'
        + (f'<img src="{_escape(image)}" alt="{_escape(name)}">' if image else '<div class="fpr-photo-fallback">NBA</div>')
        + f'<div class="fpr-ovr"><b>{overall:.0f}</b><span>OVR</span></div>'
        + '</div>'
        '<div class="fpr-card-body">'
        '<div class="fpr-card-topline">'
        f'<span>{_escape(position)} · {_escape(age_copy)}</span>'
        f'<span class="fpr-health {health_class}">{_escape(availability.upper())}</span>'
        '</div>'
        f'<h3>{_escape(name)}</h3>'
        '<div class="fpr-badges">'
        f'<span>{_escape(role)}</span><span>{_escape(archetype)}</span>'
        '</div>'
        '<div class="fpr-card-metrics">'
        f'<div><small>MIN</small><strong>{minutes:.1f}</strong></div>'
        f'<div><small>CONTRACT</small><strong>{_escape(money)}</strong><em>{_escape(term)}</em></div>'
        f'<div><small>DEVELOPMENT</small><strong>{_escape(development)}</strong><em>{_escape(potential)}</em></div>'
        f'<div><small>FATIGUE</small><strong class="fpr-fatigue-{fatigue_class}">{fatigue:.0f}</strong><em>/ 100</em></div>'
        '</div>'
        + _sparkline_html(form)
        + '</div></article>'
    )


def assign_depth_chart_v1(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    rows_list = list(rows)
    starters = [row for row in rows_list if bool(row.get("starter"))]
    if len(starters) < 5:
        seen = {str(row.get("player_id")) for row in starters}
        additions = sorted(
            [row for row in rows_list if str(row.get("player_id")) not in seen],
            key=lambda row: (-_num(row.get("minutes")), -_num(row.get("overall"))),
        )
        starters.extend(additions[: 5 - len(starters)])
    starters = sorted(starters, key=lambda row: (-_num(row.get("minutes")), -_num(row.get("overall"))))[:5]
    slots = ("PG", "SG", "SF", "PF", "C")
    if len(starters) < 5:
        return {slots[i]: row for i, row in enumerate(starters)}

    best_perm: tuple[dict[str, Any], ...] | None = None
    best_cost = float("inf")
    for permutation in itertools.permutations(starters, 5):
        cost = sum(_position_cost(row.get("position"), slot) for slot, row in zip(slots, permutation))
        if cost < best_cost:
            best_cost = cost
            best_perm = permutation
    return {slot: row for slot, row in zip(slots, best_perm or tuple(starters))}


def _court_player_html(
    *,
    slot: str,
    row: dict[str, Any],
    team: str,
    player_headshot_resolver: Callable[..., str],
) -> str:
    player_id = str(row.get("player_id", ""))
    name = str(row.get("player", "Player"))
    image = str(player_headshot_resolver(player_id, team, name) or "")
    overall = _num(row.get("overall"))
    minutes = _num(row.get("minutes"))
    return (
        f'<div class="fpr-court-player fpr-slot-{slot.lower()}">'
        f'<div class="fpr-slot-label">{slot}</div>'
        '<div class="fpr-court-avatar">'
        + (f'<img src="{_escape(image)}" alt="{_escape(name)}">' if image else '<div class="fpr-court-fallback">NBA</div>')
        + f'<span>{overall:.0f}</span></div>'
        f'<b>{_escape(name)}</b>'
        f'<small>{minutes:.1f} MIN</small>'
        '</div>'
    )


def _depth_summary(rows: list[dict[str, Any]]) -> list[tuple[str, str]]:
    groups = {"Guard": [], "Wing": [], "Big": []}
    for row in rows:
        tokens = _position_tokens(row.get("position"))
        if tokens.intersection({"PG", "SG"}):
            groups["Guard"].append(row)
        if tokens.intersection({"SF", "PF"}):
            groups["Wing"].append(row)
        if tokens.intersection({"PF", "C"}):
            groups["Big"].append(row)
    result: list[tuple[str, str]] = []
    for label, group in groups.items():
        ordered = sorted(group, key=lambda row: -_num(row.get("overall")))
        if not ordered:
            result.append((label, "NO DEPTH"))
            continue
        top = _num(ordered[0].get("overall"))
        second = _num(ordered[1].get("overall")) if len(ordered) > 1 else 0.0
        if len(ordered) < 2 or second < 72:
            status = "THIN"
        elif top >= 86 and second >= 78:
            status = "ELITE"
        elif top >= 80 and second >= 75:
            status = "STRONG"
        else:
            status = "WATCH"
        result.append((label, status))
    return result


def inject_franchise_premium_roster_visuals_v1(*, primary: str, secondary: str) -> None:
    import streamlit as st

    st.markdown(
        f"""
<style>
:root {{ --fpr-primary:{_escape(primary)}; --fpr-secondary:{_escape(secondary)}; }}
.fpr-shell {{ margin:.35rem 0 1.4rem; }}
.fpr-header {{ display:flex; align-items:end; justify-content:space-between; gap:16px; margin:0 0 14px; }}
.fpr-kicker {{ color:#7dd3fc; font-size:11px; letter-spacing:.16em; font-weight:800; text-transform:uppercase; }}
.fpr-title {{ margin:3px 0 0; font-size:29px; line-height:1.02; font-weight:900; color:#f8fafc; }}
.fpr-subtitle {{ margin:6px 0 0; color:#93a4b8; font-size:13px; max-width:780px; }}
.fpr-team-chip {{ display:flex; align-items:center; gap:9px; border:1px solid rgba(255,255,255,.11); background:rgba(10,16,26,.88); border-radius:14px; padding:8px 12px; color:#dce7f7; font-weight:800; }}
.fpr-team-chip img {{ width:30px; height:30px; object-fit:contain; }}
.fpr-court-shell {{ position:relative; border:1px solid color-mix(in srgb,var(--fpr-primary) 52%,rgba(255,255,255,.13)); border-radius:24px; overflow:hidden; min-height:455px; background:linear-gradient(145deg,rgba(9,17,28,.96),rgba(11,13,22,.99)); box-shadow:0 22px 60px rgba(0,0,0,.24); }}
.fpr-court {{ position:absolute; inset:18px; border:2px solid rgba(255,255,255,.12); border-radius:22px; background:radial-gradient(circle at 50% 14%,color-mix(in srgb,var(--fpr-primary) 26%,transparent) 0 15%,transparent 16%),linear-gradient(90deg,transparent 49.8%,rgba(255,255,255,.08) 50%,transparent 50.2%),linear-gradient(180deg,color-mix(in srgb,var(--fpr-secondary) 7%,transparent),transparent 42%); }}
.fpr-court:before {{ content:""; position:absolute; left:50%; top:0; transform:translateX(-50%); width:260px; height:184px; border:2px solid rgba(255,255,255,.12); border-top:0; border-radius:0 0 140px 140px; }}
.fpr-court:after {{ content:""; position:absolute; left:50%; top:36px; transform:translateX(-50%); width:86px; height:4px; border-radius:4px; background:var(--fpr-primary); box-shadow:0 0 24px color-mix(in srgb,var(--fpr-primary) 80%,transparent); }}
.fpr-court-player {{ position:absolute; z-index:2; width:150px; text-align:center; color:#f8fafc; transform:translate(-50%,-50%); }}
.fpr-slot-c {{ left:50%; top:22%; }} .fpr-slot-pf {{ left:25%; top:42%; }} .fpr-slot-sf {{ left:75%; top:42%; }} .fpr-slot-sg {{ left:28%; top:66%; }} .fpr-slot-pg {{ left:72%; top:66%; }}
.fpr-court-avatar {{ position:relative; width:88px; height:88px; margin:0 auto 7px; border-radius:50%; overflow:hidden; border:2px solid color-mix(in srgb,var(--fpr-primary) 68%,white 12%); background:#101827; box-shadow:0 12px 28px rgba(0,0,0,.32); }}
.fpr-court-avatar img {{ width:100%; height:100%; object-fit:cover; object-position:50% 12%; }}
.fpr-court-avatar span {{ position:absolute; right:2px; bottom:2px; min-width:30px; height:30px; display:grid; place-items:center; border-radius:50%; background:#f8fafc; color:#0b1220; font-weight:950; font-size:13px; }}
.fpr-court-fallback {{ height:100%; display:grid; place-items:center; font-weight:900; color:#6b7c92; }}
.fpr-slot-label {{ display:inline-block; margin-bottom:4px; padding:2px 7px; border-radius:999px; background:var(--fpr-primary); color:white; font-size:9px; font-weight:950; letter-spacing:.1em; }}
.fpr-court-player b {{ display:block; font-size:13px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.fpr-court-player small {{ color:#90a1b5; font-size:10px; }}
.fpr-depth-ribbon {{ position:absolute; left:24px; right:24px; bottom:14px; display:grid; grid-template-columns:repeat(3,1fr); gap:8px; z-index:3; }}
.fpr-depth-pill {{ display:flex; justify-content:space-between; align-items:center; gap:8px; padding:8px 11px; border-radius:12px; border:1px solid rgba(255,255,255,.09); background:rgba(6,11,20,.88); color:#9fb0c5; font-size:10px; text-transform:uppercase; letter-spacing:.1em; }}
.fpr-depth-pill strong {{ color:#f8fafc; font-size:11px; }}
.fpr-section-title {{ margin:20px 0 9px; color:#edf5ff; font-size:15px; font-weight:900; letter-spacing:.02em; }}
.fpr-card-grid {{ display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:10px; }}
.fpr-player-card {{ min-width:0; border:1px solid rgba(255,255,255,.10); border-radius:18px; overflow:hidden; background:linear-gradient(155deg,color-mix(in srgb,var(--fpr-primary) 18%,#0b111c),#0a0e17 58%,color-mix(in srgb,var(--fpr-secondary) 9%,#0a0e17)); box-shadow:0 14px 34px rgba(0,0,0,.20); }}
.fpr-card-photo {{ position:relative; height:150px; background:radial-gradient(circle at 50% 60%,color-mix(in srgb,var(--fpr-primary) 40%,transparent),transparent 65%); overflow:hidden; }}
.fpr-card-photo img {{ width:100%; height:100%; object-fit:contain; object-position:50% 100%; filter:drop-shadow(0 12px 12px rgba(0,0,0,.30)); }}
.fpr-photo-fallback {{ height:100%; display:grid; place-items:center; color:#607086; font-size:24px; font-weight:950; }}
.fpr-ovr {{ position:absolute; top:10px; right:10px; width:48px; height:48px; border-radius:13px; background:#f8fafc; color:#0b1220; display:flex; flex-direction:column; align-items:center; justify-content:center; box-shadow:0 8px 22px rgba(0,0,0,.28); }}
.fpr-ovr b {{ font-size:20px; line-height:18px; }} .fpr-ovr span {{ font-size:7px; font-weight:900; letter-spacing:.14em; }}
.fpr-card-body {{ padding:10px 11px 11px; }}
.fpr-card-topline {{ display:flex; align-items:center; justify-content:space-between; gap:6px; color:#92a4ba; font-size:9px; font-weight:800; letter-spacing:.08em; }}
.fpr-health {{ border-radius:999px; padding:3px 6px; border:1px solid rgba(255,255,255,.1); }} .fpr-health.good {{ color:#6ee7b7; }} .fpr-health.warn {{ color:#fde68a; }} .fpr-health.bad {{ color:#fca5a5; }} .fpr-health.neutral {{ color:#cbd5e1; }}
.fpr-card-body h3 {{ margin:5px 0 6px; color:#fff; font-size:15px; line-height:1.1; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.fpr-badges {{ display:flex; flex-wrap:wrap; gap:5px; min-height:24px; }} .fpr-badges span {{ padding:3px 7px; border-radius:999px; background:rgba(255,255,255,.07); border:1px solid rgba(255,255,255,.07); color:#c9d6e5; font-size:8px; font-weight:850; text-transform:uppercase; letter-spacing:.06em; }}
.fpr-card-metrics {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:6px; margin-top:8px; }}
.fpr-card-metrics div {{ min-height:45px; border-radius:10px; background:rgba(2,6,12,.42); border:1px solid rgba(255,255,255,.055); padding:7px 8px; }}
.fpr-card-metrics small {{ display:block; color:#63758b; font-size:7px; font-weight:900; letter-spacing:.11em; }}
.fpr-card-metrics strong {{ display:block; color:#eef6ff; font-size:12px; margin-top:2px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.fpr-card-metrics em {{ display:block; color:#8295aa; font-size:8px; font-style:normal; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.fpr-fatigue-good {{ color:#6ee7b7 !important; }} .fpr-fatigue-warn {{ color:#fde68a !important; }} .fpr-fatigue-bad {{ color:#fca5a5 !important; }}
.fpr-form-wrap {{ display:grid; grid-template-columns:auto 1fr auto; align-items:end; gap:6px; margin-top:8px; }}
.fpr-form-label {{ color:#63758b; font-size:7px; font-weight:900; letter-spacing:.1em; }}
.fpr-spark {{ height:30px; display:flex; align-items:end; gap:3px; }} .fpr-spark-bar {{ flex:1; min-width:4px; max-width:12px; border-radius:3px 3px 1px 1px; background:linear-gradient(180deg,var(--fpr-primary),var(--fpr-secondary)); opacity:.95; }}
.fpr-form-avg {{ color:#d8e5f3; font-size:9px; font-weight:850; white-space:nowrap; }} .fpr-form-empty {{ margin-top:10px; color:#53657a; font-size:8px; font-weight:850; letter-spacing:.1em; }}
.fpr-reserve-strip {{ display:flex; gap:8px; flex-wrap:wrap; }} .fpr-reserve-chip {{ display:flex; align-items:center; gap:8px; min-width:180px; padding:7px 9px; border-radius:12px; background:rgba(9,14,23,.82); border:1px solid rgba(255,255,255,.075); }} .fpr-reserve-chip img {{ width:36px; height:36px; border-radius:50%; object-fit:cover; object-position:50% 12%; background:#101827; }} .fpr-reserve-chip b {{ display:block; color:#eef6ff; font-size:10px; }} .fpr-reserve-chip span {{ display:block; color:#71849a; font-size:8px; }}
.fpr-card-compact .fpr-card-photo {{ height:132px; }}
@media (max-width:1350px) {{ .fpr-card-grid {{ grid-template-columns:repeat(4,minmax(0,1fr)); }} }}
@media (max-width:1100px) {{ .fpr-card-grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} .fpr-court-player {{ width:128px; }} }}
</style>
""",
        unsafe_allow_html=True,
    )


def render_franchise_premium_roster_v1(
    *,
    state: Any,
    team: str,
    rotation_rows: list[dict[str, Any]],
    team_name_resolver: Callable[[str], str],
    team_logo_resolver: Callable[[str], str],
    team_colors_resolver: Callable[[str], tuple[str, str]],
    player_headshot_resolver: Callable[..., str],
) -> None:
    import streamlit as st

    resolved_team = str(team).strip().upper()
    players = dict(getattr(state, "players", {}) or {})
    primary, secondary = team_colors_resolver(resolved_team)
    team_name = team_name_resolver(resolved_team)
    logo = team_logo_resolver(resolved_team)
    rows = sorted(
        list(rotation_rows),
        key=lambda row: (int(_num(row.get("rotation_order"), 99)), -_num(row.get("overall"))),
    )

    st.markdown('<div class="fpr-shell">', unsafe_allow_html=True)
    st.markdown(
        (
            '<div class="fpr-header">'
            '<div><div class="fpr-kicker">ROSTER COMMAND CENTER</div>'
            f'<div class="fpr-title">{_escape(team_name)} Depth Chart</div>'
            '<div class="fpr-subtitle">Starters, bench hierarchy, contracts, development, health, workload, and recent simulated form in one personnel view.</div>'
            '</div>'
            f'<div class="fpr-team-chip"><img src="{_escape(logo)}" alt="{_escape(team_name)}"><span>{_escape(resolved_team)}</span></div>'
            '</div>'
        ),
        unsafe_allow_html=True,
    )

    depth = assign_depth_chart_v1(rows)
    court_players = ''.join(
        _court_player_html(
            slot=slot,
            row=row,
            team=resolved_team,
            player_headshot_resolver=player_headshot_resolver,
        )
        for slot, row in depth.items()
    )
    depth_ribbon = ''.join(
        f'<div class="fpr-depth-pill"><span>{_escape(label)} DEPTH</span><strong>{_escape(status)}</strong></div>'
        for label, status in _depth_summary(rows)
    )
    st.markdown(
        f'<div class="fpr-court-shell" style="--fpr-primary:{_escape(primary)};--fpr-secondary:{_escape(secondary)};">'
        '<div class="fpr-court"></div>'
        + court_players
        + f'<div class="fpr-depth-ribbon">{depth_ribbon}</div>'
        + '</div>',
        unsafe_allow_html=True,
    )

    starter_ids = {str(row.get("player_id")) for row in depth.values()}
    bench = [row for row in rows if bool(row.get("in_rotation")) and str(row.get("player_id")) not in starter_ids]
    reserves = [row for row in rows if not bool(row.get("in_rotation"))]

    if bench:
        st.markdown('<div class="fpr-section-title">Second unit & rotation</div>', unsafe_allow_html=True)
        cards = []
        for row in bench:
            player = players.get(str(row.get("player_id")))
            if player is None:
                continue
            cards.append(
                _premium_card_html(
                    state=state,
                    team=resolved_team,
                    row=row,
                    player=player,
                    player_headshot_resolver=player_headshot_resolver,
                )
            )
        st.markdown('<div class="fpr-card-grid">' + ''.join(cards) + '</div>', unsafe_allow_html=True)

    if reserves:
        st.markdown('<div class="fpr-section-title">Reserves & development depth</div>', unsafe_allow_html=True)
        chips = []
        for row in reserves:
            player_id = str(row.get("player_id", ""))
            player = players.get(player_id)
            name = str(row.get("player", getattr(player, "player_name", "Player")))
            image = str(player_headshot_resolver(player_id, resolved_team, name) or "")
            overall = _num(row.get("overall"))
            availability = str(row.get("availability", "available"))
            chips.append(
                '<div class="fpr-reserve-chip">'
                + (f'<img src="{_escape(image)}" alt="{_escape(name)}">' if image else '')
                + f'<div><b>{_escape(name)}</b><span>{_escape(row.get("position", "—"))} · {overall:.0f} OVR · {_escape(availability)}</span></div>'
                + '</div>'
            )
        st.markdown('<div class="fpr-reserve-strip">' + ''.join(chips) + '</div>', unsafe_allow_html=True)

    with st.expander("Premium player card gallery", expanded=False):
        gallery = []
        for row in rows:
            player = players.get(str(row.get("player_id")))
            if player is None:
                continue
            gallery.append(
                _premium_card_html(
                    state=state,
                    team=resolved_team,
                    row=row,
                    player=player,
                    player_headshot_resolver=player_headshot_resolver,
                    compact=True,
                )
            )
        st.markdown('<div class="fpr-card-grid">' + ''.join(gallery) + '</div>', unsafe_allow_html=True)

    st.caption(
        "Player cards use the live franchise state. Contract figures, development direction, "
        "health/fatigue, role/minutes, and recent form are derived from the save. "
        "Morale is intentionally not fabricated because the current franchise state does not store a morale variable."
    )
    st.markdown('</div>', unsafe_allow_html=True)
