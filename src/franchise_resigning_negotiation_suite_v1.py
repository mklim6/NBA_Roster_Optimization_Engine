from __future__ import annotations

import hashlib
import html
import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from franchise_generated_player_portraits_v1 import player_image_url
from franchise_ui_branding_v1 import team_colors, team_logo_url, team_name

FRANCHISE_RESIGNING_NEGOTIATION_SUITE_VERSION = (
    "franchise-resigning-negotiation-suite-v1.1-dialogue-variety-2026-09-11"
)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _team(value: Any) -> str:
    return _clean(value).upper()


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _money(value: Any) -> str:
    number = _num(value)
    if number is None:
        return "—"
    if abs(number) >= 1_000_000:
        return f"${number / 1_000_000:.1f}M"
    if abs(number) >= 1_000:
        return f"${number / 1_000:.0f}K"
    return f"${number:,.0f}"


def _e(value: Any) -> str:
    return html.escape(_clean(value), quote=True)


def _player(state: Any, player_id: str) -> Any | None:
    return getattr(state, "players", {}).get(_clean(player_id))


def _completed_games(state: Any) -> list[Any]:
    raw = getattr(state, "completed_games", {}) or {}
    if isinstance(raw, Mapping):
        games = list(raw.values())
    elif isinstance(raw, Iterable) and not isinstance(raw, (str, bytes)):
        games = list(raw)
    else:
        games = []

    def key(game: Any) -> tuple[int, str]:
        try:
            day = int(getattr(game, "day_index", 0) or 0)
        except (TypeError, ValueError):
            day = 0
        gid = _clean(getattr(game, "game_id", ""))
        return day, gid

    games.sort(key=key, reverse=True)
    return games


@dataclass(frozen=True)
class PriorTeamContext:
    team: str
    source: str
    appearance_count: int


def prior_team_context_v1(
    state: Any,
    player_row: Mapping[str, Any],
    *,
    max_games: int = 28,
) -> PriorTeamContext:
    explicit = _team(player_row.get("prior_team"))
    if explicit:
        return PriorTeamContext(explicit, "verified offseason market", 0)

    player_id = _clean(player_row.get("player_id"))
    if not player_id:
        return PriorTeamContext("", "unavailable", 0)

    appearances: dict[str, int] = {}
    latest_team = ""
    for game in _completed_games(state)[:max_games]:
        for row in list(getattr(game, "player_box_scores", ()) or ()):
            if _clean(getattr(row, "player_id", "")) != player_id:
                continue
            code = _team(getattr(row, "team_abbreviation", ""))
            if not code:
                continue
            if not latest_team:
                latest_team = code
            appearances[code] = appearances.get(code, 0) + 1
            break

    if not latest_team:
        return PriorTeamContext("", "unavailable", 0)
    return PriorTeamContext(
        latest_team,
        "recent saved game appearances",
        int(appearances.get(latest_team, 0)),
    )


def returning_candidate_rows_v1(
    state: Any,
    rows: Iterable[Mapping[str, Any]],
    *,
    active_team: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    active = _team(active_team)
    candidates: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        context = prior_team_context_v1(state, row)
        if context.team != active:
            continue
        row["_prior_team_source"] = context.source
        row["_prior_team_appearances"] = context.appearance_count
        candidates.append(row)

    candidates.sort(
        key=lambda row: (
            -float(_num(row.get("overall")) or -1.0),
            -float(_num(row.get("potential")) or -1.0),
            _clean(row.get("player_name")).casefold(),
        )
    )
    return candidates[: max(0, int(limit))]


def inject_resigning_negotiation_styles_v1() -> None:
    import streamlit as st

    st.markdown(
        """
<style>
.rsn-board {
  border: 1px solid rgba(244,63,94,.33);
  border-radius: 24px;
  padding: 18px 20px 20px;
  margin: 8px 0 22px;
  background:
    radial-gradient(circle at 88% 0%, rgba(225,29,72,.18), transparent 32%),
    linear-gradient(135deg, rgba(8,18,33,.97), rgba(20,12,26,.97));
}
.rsn-eyebrow {
  color: #7dd3fc;
  font-weight: 900;
  font-size: .72rem;
  letter-spacing: .18em;
  text-transform: uppercase;
}
.rsn-board h3, .rsn-room h2 { margin: 5px 0 4px; }
.rsn-board-copy, .rsn-subtle {
  color: #94a3b8;
  font-size: .84rem;
}
.rsn-board-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
  margin-top: 14px;
}
.rsn-watch {
  min-width: 0;
  border: 1px solid rgba(148,163,184,.16);
  border-radius: 17px;
  padding: 10px;
  background: rgba(5,12,23,.76);
}
.rsn-watch-top {
  height: 92px;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  overflow: hidden;
  border-radius: 12px;
  background: linear-gradient(180deg, rgba(56,189,248,.08), rgba(244,63,94,.08));
}
.rsn-watch-top img { width: 100%; height: 100%; object-fit: contain; object-position: center bottom; }
.rsn-watch-name { color: #f8fafc; font-weight: 900; margin-top: 8px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.rsn-watch-meta { color: #94a3b8; font-size: .72rem; margin-top: 2px; }
.rsn-watch-money { color: #f8fafc; font-size: .76rem; margin-top: 7px; font-weight: 800; }
.rsn-room {
  --rsn-primary: #e11d48;
  --rsn-secondary: #111827;
  position: relative;
  overflow: hidden;
  border: 1px solid rgba(244,63,94,.48);
  border-radius: 25px;
  margin: 6px 0 17px;
  padding: 19px;
  background:
    radial-gradient(circle at 84% 16%, color-mix(in srgb, var(--rsn-primary) 28%, transparent), transparent 34%),
    linear-gradient(135deg, rgba(5,12,24,.98), rgba(24,11,25,.97));
}
.rsn-room-grid {
  display: grid;
  grid-template-columns: 155px minmax(0,1fr);
  gap: 18px;
  align-items: stretch;
}
.rsn-portrait {
  min-height: 190px;
  border-radius: 19px;
  border: 1px solid rgba(255,255,255,.09);
  background: linear-gradient(180deg, rgba(255,255,255,.05), rgba(0,0,0,.18));
  display: flex;
  align-items: flex-end;
  justify-content: center;
  overflow: hidden;
}
.rsn-portrait img { width: 100%; height: 100%; object-fit: contain; object-position: center bottom; }
.rsn-room-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.rsn-room-title { font-size: 1.65rem; color: #f8fafc; font-weight: 950; line-height: 1.02; }
.rsn-room-meta { color: #a7b4c7; margin-top: 5px; font-size: .82rem; }
.rsn-team-lockup { display: flex; align-items: center; gap: 8px; color: #e2e8f0; font-weight: 900; font-size: .78rem; }
.rsn-team-lockup img { width: 37px; height: 37px; object-fit: contain; }
.rsn-opening-quote, .rsn-quote {
  position: relative;
  margin-top: 14px;
  padding: 14px 16px 14px 20px;
  border-left: 3px solid #38bdf8;
  border-radius: 0 14px 14px 0;
  background: rgba(15,23,42,.72);
  color: #f8fafc;
  font-weight: 800;
  font-size: .93rem;
  line-height: 1.42;
}
.rsn-room-stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0,1fr));
  gap: 8px;
  margin-top: 13px;
}
.rsn-stat, .rsn-reaction-stat {
  border: 1px solid rgba(148,163,184,.14);
  border-radius: 13px;
  padding: 9px 10px;
  background: rgba(2,6,23,.53);
}
.rsn-stat small, .rsn-reaction-stat small {
  display: block;
  color: #718096;
  font-weight: 900;
  letter-spacing: .10em;
  text-transform: uppercase;
  font-size: .58rem;
}
.rsn-stat b, .rsn-reaction-stat b {
  display: block;
  color: #f8fafc;
  margin-top: 4px;
  font-size: .91rem;
}
.rsn-reaction {
  border: 1px solid rgba(56,189,248,.31);
  border-radius: 23px;
  margin: 10px 0 15px;
  padding: 18px;
  background:
    radial-gradient(circle at 94% 4%, rgba(56,189,248,.12), transparent 30%),
    linear-gradient(135deg, rgba(5,12,24,.98), rgba(17,10,24,.98));
}
.rsn-reaction-head { display:flex; justify-content:space-between; align-items:center; gap:12px; }
.rsn-mood {
  display:inline-flex;
  align-items:center;
  gap:6px;
  border-radius:999px;
  padding:6px 10px;
  font-size:.64rem;
  letter-spacing:.10em;
  font-weight:950;
  border:1px solid rgba(255,255,255,.12);
}
.rsn-mood.good { color:#6ee7b7; background:rgba(16,185,129,.10); }
.rsn-mood.mid { color:#fcd34d; background:rgba(245,158,11,.10); }
.rsn-mood.bad { color:#fda4af; background:rgba(244,63,94,.10); }
.rsn-interest-row { display:grid; grid-template-columns: 1fr auto; gap:10px; align-items:center; margin-top:13px; }
.rsn-interest-track { height:10px; border-radius:99px; background:#111827; overflow:hidden; }
.rsn-interest-fill { height:100%; border-radius:99px; background:linear-gradient(90deg,#38bdf8,#e11d48); }
.rsn-interest-label { color:#cbd5e1; font-size:.72rem; font-weight:900; white-space:nowrap; }
.rsn-reaction-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; margin-top:13px; }
.rsn-factors { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:7px; margin-top:12px; }
.rsn-factor { border:1px solid rgba(148,163,184,.13); border-radius:12px; padding:8px; background:rgba(2,6,23,.48); }
.rsn-factor span { display:block; color:#718096; font-size:.55rem; letter-spacing:.08em; text-transform:uppercase; font-weight:900; }
.rsn-factor b { display:block; color:#e2e8f0; margin-top:3px; }
.rsn-priority { margin-top:9px; color:#94a3b8; font-size:.71rem; }
@media (max-width: 1100px) {
  .rsn-board-grid { grid-template-columns: repeat(3,minmax(0,1fr)); }
  .rsn-reaction-grid { grid-template-columns: repeat(2,minmax(0,1fr)); }
}
@media (max-width: 760px) {
  .rsn-board-grid { grid-template-columns: repeat(2,minmax(0,1fr)); }
  .rsn-room-grid { grid-template-columns: 1fr; }
  .rsn-portrait { min-height: 230px; }
  .rsn-factors { grid-template-columns: repeat(2,minmax(0,1fr)); }
}
</style>
        """,
        unsafe_allow_html=True,
    )


def _image_for_row(state: Any, row: Mapping[str, Any], team: str) -> str:
    player = _player(state, _clean(row.get("player_id")))
    synthetic = bool(getattr(player, "synthetic", False)) if player is not None else bool(row.get("synthetic"))
    return player_image_url(
        row.get("player_id"),
        team=team,
        player_name=_clean(row.get("player_name")),
        generated=synthetic,
    )


def render_resigning_watchlist_v1(
    state: Any,
    rows: Iterable[Mapping[str, Any]],
    *,
    active_team: str,
) -> None:
    import streamlit as st

    candidates = returning_candidate_rows_v1(state, rows, active_team=active_team, limit=5)
    if not candidates:
        return

    inject_resigning_negotiation_styles_v1()
    cards = []
    for row in candidates:
        pid = _clean(row.get("player_id"))
        image = _image_for_row(state, row, active_team)
        benchmark = _num(row.get("free_agent_amount"))
        prior = _num(row.get("last_salary"))
        money_label = (
            f"Market benchmark {_money(benchmark)}"
            if benchmark is not None and benchmark > 0
            else (
                f"Prior salary {_money(prior)}"
                if prior is not None and prior > 0
                else "Market value after preview"
            )
        )
        source = _clean(row.get("_prior_team_source"))
        source_label = "VERIFIED RETURN" if source == "verified offseason market" else "RECENT TEAM"
        cards.append(
            f"""
<div class="rsn-watch">
  <div class="rsn-watch-top"><img src="{_e(image)}" alt="{_e(row.get('player_name'))}"></div>
  <div class="rsn-watch-name">{_e(row.get('player_name'))}</div>
  <div class="rsn-watch-meta">{_e(row.get('position'))} · OVR {_e(row.get('overall'))} · {source_label}</div>
  <div class="rsn-watch-money">{_e(money_label)}</div>
</div>
            """
        )

    st.markdown(
        f"""
<div class="rsn-board">
  <div class="rsn-eyebrow">Re-signing watchlist</div>
  <h3>Players with a recent {_e(team_name(active_team))} connection</h3>
  <div class="rsn-board-copy">Prior-team context uses verified offseason evidence when available, otherwise recent saved game appearances. It is presentation context only and never changes contract rights or legality.</div>
  <div class="rsn-board-grid">{''.join(cards)}</div>
</div>
        """,
        unsafe_allow_html=True,
    )


def _stable_pick(options: tuple[str, ...] | list[str], seed: str) -> str:
    """Choose presentation copy deterministically without affecting decisions."""
    if not options:
        return ""
    digest = hashlib.sha256(_clean(seed).encode("utf-8")).digest()
    index = int.from_bytes(digest[:8], "big") % len(options)
    return options[index]


def _presentation_voice(seed: str) -> str:
    """Cosmetic phrasing family only. This is not a player attribute."""
    return _stable_pick(
        (
            "direct",
            "measured",
            "confident",
            "businesslike",
            "collaborative",
            "competitive",
        ),
        f"voice|{seed}",
    )


_INTRO_LINES = {
    ("returning", False): (
        "I know what this organization is about. If the role and the contract line up, I’m open to staying.",
        "I’m definitely willing to hear you out. I want to know how you see me fitting here going forward.",
        "Coming back is on the table. Show me the plan for my role and a deal that reflects it.",
        "We’ve already built something here. If the next contract makes sense, I’d like to keep the conversation going.",
        "I’m comfortable here, but this is still an important contract. Let’s see how serious the team is about bringing me back.",
        "I’m open to returning. I just want the offer to match the role you expect me to play.",
        "I know the situation here well. Give me a reason to keep calling this home.",
        "Staying would be easy to picture, but I still need the basketball fit and the numbers to make sense.",
        "I’m listening. If you want me back, show me what that looks like in the contract and in the rotation.",
        "I’ve got history here. Now I want to see whether the next deal matches where I am in my career.",
        "I’m not looking to make this complicated. If the value is right and the role is clear, we can get somewhere.",
        "There’s definitely a path to me staying. I want to hear how the front office values the next few years.",
    ),
    ("returning", True): (
        "We’ve talked enough to know where both sides stand. Move the deal toward what I’m looking for and we can keep this going.",
        "I’m still interested in staying, but I need the next offer to reflect the value we’ve been discussing.",
        "The door is open. I’m just looking for more clarity on the money, role and security before I commit.",
        "I like the idea of coming back. Now it’s about getting the details close enough for both sides.",
        "We’re in the conversation. I want to see whether the team is willing to bridge the remaining gap.",
        "I haven’t ruled anything out. If the next offer shows real commitment, we can move this forward.",
        "I know what staying here would mean. I’m weighing that against what the market may give me.",
        "There’s still a deal to be made here. I just need the contract to feel like the team really wants me back.",
        "I’m listening, and I’m not far away emotionally. The next proposal needs to make sense on paper too.",
        "We’ve got some common ground. I want to see if the front office can turn that into a contract I’m comfortable signing.",
        "I’m taking the talks seriously. Give me the right combination of value and role and I’m ready to keep pushing toward a deal.",
        "I’m not shutting the door on a return. I want the next offer to answer the questions we still have.",
    ),
    ("market", False): (
        "I’m listening. Tell me what the role looks like and show me how much you value bringing me in.",
        "I’m open to the conversation. Money matters, but I’m looking at the whole situation.",
        "You’ve got my attention. I want to hear the basketball plan and what kind of commitment you’re willing to make.",
        "I’m willing to talk. Show me where I fit and what the organization thinks that role is worth.",
        "I’m keeping an open mind. The contract, the opportunity and the direction of the team all matter to me.",
        "I’m interested enough to hear the pitch. Now show me why this would be the right move.",
        "There are a few things I care about here. Give me a clear role and a serious offer and we can build from there.",
        "I’m not coming in with a decision already made. Make the case for why I should choose this team.",
        "I’m ready to listen. I want to see how the role, the money and the team situation fit together.",
        "This is a real option for me. I just need to see a proposal that makes the whole picture work.",
        "I’m considering everything right now. Show me what separates this opportunity from the others.",
        "I’m at the table. Let’s see whether the offer matches what I’m looking for at this point in my career.",
    ),
    ("market", True): (
        "We’ve started the conversation. I’m still weighing this offer against the rest of the market.",
        "I’m interested, but I’m not ready to rush it. I want to see how this situation stacks up against my other options.",
        "The talks are real. I’m looking closely at the value, the role and how competitive this team can be.",
        "I’m still engaged here. The next offer could move this from an option to something serious.",
        "You’re in the mix. I’m deciding whether the contract and the basketball fit are strong enough to commit.",
        "I haven’t made up my mind yet. I want to see whether this organization is willing to push the deal forward.",
        "This is still a live conversation. I’m comparing the total situation, not just one number.",
        "I like parts of what I’m hearing. I’m waiting to see whether the full package gets to where I need it.",
        "We’re talking for a reason. Show me another step toward what I’m looking for and this can get interesting.",
        "I’m keeping this team in consideration. The details of the next proposal are going to matter.",
        "There’s enough here to keep negotiating. I’m still deciding how it compares to the other opportunities.",
        "I’m listening closely. If the next move addresses what matters most to me, we could get somewhere.",
    ),
}


def _intro_quote(
    *,
    returning: bool,
    has_persistent_market: bool,
    seed: str,
) -> str:
    family = "returning" if returning else "market"
    base = _stable_pick(
        _INTRO_LINES[(family, bool(has_persistent_market))],
        f"intro|{seed}|{family}|{int(bool(has_persistent_market))}",
    )
    voice = _presentation_voice(seed)

    # Light cosmetic variation in cadence. It never changes negotiation inputs.
    if voice == "direct" and not base.endswith("."):
        return base + "."
    if voice == "competitive" and not returning and "option" not in base.lower():
        return base
    return base


def _weakest_factor(decision: Any) -> tuple[str, float]:
    factors = [
        ("money", float(getattr(decision, "salary_score", 0.0) or 0.0)),
        ("role", float(getattr(decision, "role_score", 0.0) or 0.0)),
        ("winning", float(getattr(decision, "winning_score", 0.0) or 0.0)),
        ("security", float(getattr(decision, "security_score", 0.0) or 0.0)),
        ("career fit", float(getattr(decision, "career_fit_score", 0.0) or 0.0)),
    ]
    return min(factors, key=lambda item: item[1])


def _strength_factor(decision: Any) -> tuple[str, float]:
    factors = [
        ("money", float(getattr(decision, "salary_score", 0.0) or 0.0)),
        ("role", float(getattr(decision, "role_score", 0.0) or 0.0)),
        ("winning", float(getattr(decision, "winning_score", 0.0) or 0.0)),
        ("security", float(getattr(decision, "security_score", 0.0) or 0.0)),
        ("career fit", float(getattr(decision, "career_fit_score", 0.0) or 0.0)),
    ]
    return max(factors, key=lambda item: item[1])


def _reason_fragment(factor: str, *, positive: bool) -> str:
    positive_map = {
        "money": (
            "the money is in a range I can respect",
            "the financial commitment feels serious",
            "the value is much closer to what I had in mind",
            "the numbers show me you’re taking this seriously",
        ),
        "role": (
            "I like the opportunity you’re presenting",
            "the role makes sense for where I am",
            "I can see a real place for myself in this rotation",
            "the basketball opportunity is appealing",
        ),
        "winning": (
            "I like the direction of the team",
            "the chance to compete matters to me",
            "I can see a competitive path here",
            "the winning situation is a real positive",
        ),
        "security": (
            "the security in the deal matters",
            "I like the commitment in the structure",
            "the contract gives me meaningful stability",
            "the term makes the offer feel more serious",
        ),
        "career fit": (
            "this feels like a good basketball fit",
            "the situation makes sense for this stage of my career",
            "I can see how this move fits the bigger picture for me",
            "the overall fit is working in your favor",
        ),
    }
    negative_map = {
        "money": (
            "the money is still light for me",
            "the value doesn’t match what I think I can get",
            "the financial side is the biggest gap right now",
            "I need the numbers to show more commitment",
        ),
        "role": (
            "I’m not sold on the role yet",
            "I need a clearer basketball opportunity",
            "the role isn’t where I want it to be",
            "I’m not sure the minutes and responsibility line up with what I’m looking for",
        ),
        "winning": (
            "I still have questions about the competitive situation",
            "I’m weighing whether this is the right place to win",
            "the team direction is something I’m still thinking about",
            "I need to feel better about the chance to compete",
        ),
        "security": (
            "I want more security in the structure",
            "the commitment level still feels a little short",
            "I’m looking for a deal that gives me more stability",
            "the term isn’t giving me enough certainty yet",
        ),
        "career fit": (
            "I’m not fully convinced this is the right fit",
            "I still have questions about how this move fits my career",
            "the overall situation isn’t lining up for me yet",
            "I need the full basketball fit to make more sense",
        ),
    }
    pool = positive_map if positive else negative_map
    return _stable_pick(pool.get(factor, pool["career fit"]), f"reason|{factor}|{int(positive)}")


def _dialogue(
    decision: Any,
    negotiation: Any,
    *,
    returning: bool,
    seed: str = "",
) -> str:
    status = _clean(getattr(decision, "status", "")).lower()
    response = (
        _clean(getattr(negotiation, "player_response", "")).lower()
        if negotiation is not None
        else ""
    )
    counter = _num(getattr(decision, "counter_salary", None))
    user_winner = (
        bool(getattr(negotiation, "user_is_winner", False))
        if negotiation is not None
        else False
    )
    weak_factor, weak_score = _weakest_factor(decision)
    strong_factor, strong_score = _strength_factor(decision)
    weak_reason = _reason_fragment(weak_factor, positive=False)
    strong_reason = _reason_fragment(strong_factor, positive=True)

    key = (
        f"{seed}|status={status}|response={response}|returning={int(returning)}|"
        f"counter={counter}|weak={weak_factor}:{weak_score:.1f}|"
        f"strong={strong_factor}:{strong_score:.1f}"
    )

    if response == "ready_to_sign" and user_winner:
        pool = (
            "I’m good with where we landed. Let’s get the paperwork done.",
            "That works for me. I’m ready to make this official.",
            "We got to a place I’m comfortable with. I’m ready to sign.",
            "I’ve seen enough. This is the situation I want, so let’s finish it.",
            "I’m ready to commit. Let’s get this across the line.",
            "The deal and the situation both work for me. I’m ready.",
            "I’m comfortable saying yes to this. Let’s lock it in.",
            "We found the middle ground I was looking for. I’m ready to sign.",
            "I’m done shopping this around. Let’s make it official.",
            "This feels right. I’m ready to move forward with the deal.",
        )
        if returning:
            pool = pool + (
                "I wanted to find a way to stay, and we did. Let’s get it done.",
                "I’m happy we found a path to keep this going. I’m ready to stay.",
                "Keeping this together matters to me. I’m ready to come back.",
                "I’m comfortable running it back. Let’s make the return official.",
            )
        return _stable_pick(pool, "ready|" + key)

    if response == "ready_to_sign" and not user_winner:
        pool = (
            "I’m ready to choose another offer. If you want to change that, the next move has to be significant.",
            "Another team has me ready to commit. You’d need to clearly beat the situation I have now.",
            "I’m close to going elsewhere. If you still want me, this is the time to make your strongest push.",
            "I have an offer I’m prepared to take. You’d need to give me a real reason to change course.",
            "The market has moved. I’m leaning toward another situation unless your offer changes quickly.",
            "I’m prepared to sign somewhere else. Your next proposal would have to separate itself.",
            "Another team is ahead right now. If you want back into this, I need to see a better package.",
            "I’ve got a situation I’m comfortable taking. You’ll need to top it if you want me here.",
        )
        return _stable_pick(pool, "elsewhere|" + key)

    if response == "hold":
        pool = (
            f"I like the offer, and {strong_reason}. I’m just not ready to close the market yet.",
            f"This is a strong conversation. {strong_reason.capitalize()}, but I want a little more time before I commit.",
            "You’re in a good position with me. I want to see how the market develops before I make the final call.",
            "I’m encouraged by where this stands. I’m going to hold for now and compare the full picture.",
            "I like a lot of this. I’m not saying no, I just want to let the process play out a little longer.",
            "This is one of the better situations I’m considering. I’m going to keep it open for another round.",
            "We’re in a good place. I want to stay patient and make sure I’m choosing the right situation.",
            f"You’ve given me something real to think about. {strong_reason.capitalize()}, so this is very much alive.",
        )
        return _stable_pick(pool, "hold|" + key)

    if response == "counter_market":
        if counter is not None:
            pool = (
                f"We’re close. Get to about {_money(counter)} per year and I’ll feel a lot better about the deal.",
                f"I can see a path here, but I’m looking for roughly {_money(counter)} per year on this structure.",
                f"This is moving in the right direction. Around {_money(counter)} annually is where I’d want to land.",
                f"I’m not far off. Bring the annual value to about {_money(counter)} and we can keep pushing toward yes.",
                f"The conversation is real. I’d counter at approximately {_money(counter)} per year.",
                f"I’m interested, but {_money(counter)} per year is closer to the value I’m looking for.",
                f"Meet me around {_money(counter)} annually and this starts to feel like a deal I can sign.",
                f"We’ve narrowed the gap. My number right now is about {_money(counter)} per season.",
                f"I’d like to keep this moving. If you can get near {_money(counter)} per year, we’re getting serious.",
                f"You’re within range. I’d come back at about {_money(counter)} annually and see if we can finish it.",
            )
            return _stable_pick(pool, "counter_market|" + key)
        return _stable_pick(
            (
                f"We’re still apart, and {weak_reason}. Improve that part of the offer and I’ll keep listening.",
                f"I’m not closing the door, but {weak_reason}. That needs to move.",
                "There’s enough here to keep talking, but the total package still needs another step.",
                "I’m interested enough to counter, not interested enough to accept. Show me something stronger.",
                "We’re in negotiating range, but not signing range yet. I need more from the next proposal.",
                "I can work with parts of this, but the offer still needs to improve before I’m comfortable.",
                "This isn’t a no. It’s a request for the team to come closer to where I value the deal.",
                f"I’m willing to keep talking. Right now, {weak_reason}.",
            ),
            "counter_market_none|" + key,
        )

    if response == "exploring_market":
        pool = (
            "I’m keeping my options open. I want to know what the rest of the market looks like before I decide.",
            "I’m not ready to commit yet. I need to compare this with the other situations available to me.",
            "I’m still listening around the league. I don’t want to make the decision before I know my full market.",
            f"I’m going to keep exploring. Right now, {weak_reason}.",
            "This offer keeps you in the conversation, but I’m going to see what else develops.",
            "I appreciate the interest, but I’m not at the point where I want to shut down other conversations.",
            "I’m taking this seriously, but I need to let the market tell me what my options really are.",
            "I’m going to stay patient. If this is still the best overall situation after I look around, we can revisit it.",
            "There’s enough here to consider, but not enough for me to stop taking calls.",
            "I want to see the full board before I choose a team. Keep the offer alive and we’ll see where it goes.",
        )
        return _stable_pick(pool, "explore|" + key)

    if response == "no_acceptable_offer":
        return _stable_pick(
            (
                "Nothing on the table is where I need it to be right now.",
                "I don’t have an offer I’m comfortable accepting at this point.",
                "The market hasn’t produced a deal that makes sense for me yet.",
                "I’m willing to wait. I don’t see a contract I want to sign right now.",
                "I’m not forcing a decision just to get one done. The offers need to improve.",
                "There isn’t a proposal I’m ready to say yes to yet.",
                f"I’m holding off. At the moment, {weak_reason}.",
                "I’d rather keep waiting than sign something I don’t believe in.",
            ),
            "noacceptable|" + key,
        )

    if status == "accept":
        pool = (
            f"This is a serious offer. {strong_reason.capitalize()}, and I’m comfortable moving it forward.",
            f"I like the direction of this. {strong_reason.capitalize()}, so you’ve got my attention.",
            "This is in the range where I can genuinely see myself saying yes.",
            "You’ve put together a proposal I can take seriously. Let’s keep it moving.",
            "This is the kind of offer that keeps me at the table.",
            f"I’m comfortable with the overall package. {strong_reason.capitalize()}.",
            "This gives me a lot of what I’m looking for. I’m willing to move forward with the talks.",
            "You’re showing me real interest with this offer. I’m responding to that.",
            "This is competitive. I’m willing to treat it like a real path to a deal.",
            "I can work with this. There’s enough value and fit here to keep progressing.",
            "This is a good starting point for me. I’m taking the proposal seriously.",
            "You’ve got my attention with this one. I’m willing to see where the negotiation goes.",
        )
        if returning:
            pool = pool + (
                "This feels like a real attempt to keep me here. I’m willing to work toward a return.",
                "I can see myself staying on this framework. Let’s keep working.",
                "If the goal is to bring me back, this is the kind of offer that makes that realistic.",
                "This gives me a reason to seriously consider staying.",
            )
        return _stable_pick(pool, "accept|" + key)

    if status == "counter":
        if counter is not None:
            pool = (
                f"We’re not far apart. My counter is about {_money(counter)} per year.",
                f"I’m willing to keep talking. I’d move this to around {_money(counter)} annually.",
                f"You’re in the neighborhood. I’d be more comfortable at about {_money(counter)} per season.",
                f"This is close enough to negotiate. My number is around {_money(counter)} a year.",
                f"I’m not rejecting the idea. Get this to roughly {_money(counter)} annually and we have something.",
                f"I see the effort. I’d counter at about {_money(counter)} per year.",
                f"Let’s keep working. Around {_money(counter)} annually is where I think the deal should be.",
                f"We can bridge this. I’d want the annual value closer to {_money(counter)}.",
                f"I’m open to meeting in the middle. My side is looking for about {_money(counter)} per year.",
                f"This is negotiable. Bring it near {_money(counter)} annually and I’ll feel much better.",
            )
            return _stable_pick(pool, "counter|" + key)
        return _stable_pick(
            (
                f"We can keep talking, but {weak_reason}.",
                "I’m not walking away, but I need the next proposal to improve.",
                "This is close enough for a counter, not close enough for a yes.",
                "There’s a deal somewhere in here. I need the team to move a little more.",
                f"I like parts of it, but {weak_reason}.",
                "I’m willing to negotiate. I’m just not ready to take this version of the offer.",
                "Keep the conversation going, but come back with something stronger.",
                "I’m still at the table. The next offer needs to close more of the gap.",
            ),
            "counter_none|" + key,
        )

    if status == "decline":
        utility = float(getattr(decision, "utility_score", 0.0) or 0.0)
        threshold = float(getattr(decision, "acceptance_threshold", 0.0) or 0.0)
        salary_score = float(getattr(decision, "salary_score", 100.0) or 100.0)
        severe = utility <= threshold - 20.0 or salary_score < 35.0
        if severe:
            pool = (
                f"We’re nowhere near a deal right now. {weak_reason.capitalize()}.",
                "That offer isn’t close enough for me to take seriously as a signing point.",
                f"I need a major change before this goes anywhere. Right now, {weak_reason}.",
                "I don’t feel properly valued by this proposal. We’d need a substantial reset.",
                "This is too far from what I’m looking for. I’m not comfortable moving forward on these terms.",
                f"We’re too far apart. The biggest issue is that {weak_reason}.",
                "I’d rather test the market than accept something at this level.",
                "This doesn’t reflect the kind of commitment I’m looking for. You’d have to come back much stronger.",
                "I’m not seeing enough here to keep this version of the offer alive.",
                f"This one misses the mark for me. In particular, {weak_reason}.",
            )
            return _stable_pick(pool, "decline_severe|" + key)
        return _stable_pick(
            (
                f"I’m not there yet. {weak_reason.capitalize()}.",
                "I appreciate the offer, but I need more from the total package.",
                "This isn’t enough for me to say yes right now.",
                f"I’m going to pass on this version. The main issue is that {weak_reason}.",
                "I’m still open to the right deal, but this proposal isn’t it.",
                "There are parts I can understand, but overall I’m not comfortable accepting this.",
                "I’d need a better fit between the value, role and security before I could agree.",
                f"This doesn’t quite work for me. Right now, {weak_reason}.",
                "I’m not closing the door forever, but I’m saying no to this offer.",
                "The gap is still too wide for me to accept this version.",
            ),
            "decline|" + key,
        )

    return _stable_pick(
        (
            "I’m listening. Let’s see what the full offer looks like once everything checks out.",
            "I’m open to the conversation. Get the proposal through the formal checks and we’ll go from there.",
            "Let’s keep talking. I want to see the complete structure before I react too strongly.",
            "I’m at the table. Show me the finalized proposal and I’ll give you a real answer.",
            "There’s a conversation to have here. Let’s get the full offer in front of me.",
            "I’m willing to listen. Once the contract details are set, we can talk seriously.",
        ),
        "fallback|" + key,
    )


def render_negotiation_room_intro_v1(
    state: Any,
    player_row: Mapping[str, Any],
    *,
    signing_team: str,
    persistent_record: Any = None,
) -> dict[str, Any]:
    import streamlit as st

    inject_resigning_negotiation_styles_v1()
    team = _team(signing_team)
    context = prior_team_context_v1(state, player_row)
    returning = bool(team and context.team == team)
    player_id = _clean(player_row.get("player_id"))
    name = _clean(player_row.get("player_name")) or player_id
    image = _image_for_row(state, player_row, team or context.team)
    colors = team_colors(team) if team else ("#e11d48", "#111827")
    primary = colors[0] if colors else "#e11d48"
    secondary = colors[1] if len(colors) > 1 else "#111827"
    prior_salary = _num(player_row.get("last_salary"))
    benchmark = _num(player_row.get("free_agent_amount"))

    mode = "RE-SIGNING NEGOTIATION" if returning else "PLAYER NEGOTIATION"
    context_line = (
        f"Return talks · prior-team context: {context.source}"
        if returning
        else (
            f"Recent team context: {team_name(context.team)} · {context.source}"
            if context.team
            else "Open-market discussion"
        )
    )
    if context.source == "recent saved game appearances" and context.appearance_count:
        context_line += f" · {context.appearance_count} recent appearance(s)"

    benchmark_label = _money(benchmark) if benchmark is not None and benchmark > 0 else "After preview"
    prior_label = _money(prior_salary) if prior_salary is not None and prior_salary > 0 else "—"
    talks = "Open" if persistent_record is not None else "Not opened"

    st.markdown(
        f"""
<div class="rsn-room" style="--rsn-primary:{_e(primary)};--rsn-secondary:{_e(secondary)};">
  <div class="rsn-room-grid">
    <div class="rsn-portrait"><img src="{_e(image)}" alt="{_e(name)}"></div>
    <div>
      <div class="rsn-room-head">
        <div>
          <div class="rsn-eyebrow">{mode}</div>
          <div class="rsn-room-title">{_e(name)}</div>
          <div class="rsn-room-meta">{_e(player_row.get('position'))} · Age {_e(player_row.get('age'))} · OVR {_e(player_row.get('overall'))} · POT {_e(player_row.get('potential'))}</div>
          <div class="rsn-room-meta">{_e(context_line)}</div>
        </div>
        <div class="rsn-team-lockup">
          <img src="{_e(team_logo_url(team))}" alt="{_e(team_name(team))}">
          <span>{_e(team_name(team))}</span>
        </div>
      </div>
      <div class="rsn-opening-quote">“{_e(_intro_quote(
          returning=returning,
          has_persistent_market=persistent_record is not None,
          seed=f"{player_id}|{team}|{name}",
      ))}”</div>
      <div class="rsn-room-stats">
        <div class="rsn-stat"><small>Prior salary</small><b>{_e(prior_label)}</b></div>
        <div class="rsn-stat"><small>Market benchmark</small><b>{_e(benchmark_label)}</b></div>
        <div class="rsn-stat"><small>Negotiation</small><b>{talks}</b></div>
      </div>
    </div>
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )
    return {
        "returning": returning,
        "prior_team": context.team,
        "prior_team_source": context.source,
    }


def _priority_labels(profile: Any) -> list[tuple[str, float]]:
    rows = [
        ("Money", float(getattr(profile, "money_weight", 0.0) or 0.0)),
        ("Role", float(getattr(profile, "role_weight", 0.0) or 0.0)),
        ("Winning", float(getattr(profile, "winning_weight", 0.0) or 0.0)),
        ("Security", float(getattr(profile, "security_weight", 0.0) or 0.0)),
        ("Career fit", float(getattr(profile, "career_fit_weight", 0.0) or 0.0)),
    ]
    rows.sort(key=lambda item: (-item[1], item[0]))
    return rows


def _mood(decision: Any, negotiation: Any) -> tuple[str, str]:
    utility = float(getattr(decision, "utility_score", 0.0) or 0.0)
    threshold = float(getattr(decision, "acceptance_threshold", 0.0) or 0.0)
    status = _clean(getattr(decision, "status", "")).lower()
    response = _clean(getattr(negotiation, "player_response", "")).lower() if negotiation is not None else ""

    if response == "ready_to_sign":
        if bool(getattr(negotiation, "user_is_winner", False)):
            return "READY TO SIGN", "good"
        return "READY ELSEWHERE", "bad"
    if response == "hold":
        return "VERY INTERESTED", "good"
    if status == "accept":
        return ("THRILLED", "good") if utility >= threshold + 8.0 else ("SATISFIED", "good")
    if status == "counter" or response == "counter_market":
        return "WANTS A COUNTER", "mid"
    if status == "decline":
        if utility <= threshold - 25.0 and float(getattr(decision, "salary_score", 100.0) or 100.0) < 35.0:
            return "INSULTED", "bad"
        return "UNSATISFIED", "bad"
    if response == "exploring_market":
        return "TESTING THE MARKET", "mid"
    return "LISTENING", "mid"



def _clear_preview_session(st: Any) -> None:
    for key in (
        "fa_ui_preview",
        "fa_ui_preview_signature",
        "fa_ui_preview_hypothetical",
        "fa_player_decision",
        "fa_shared_market",
        "fa_negotiation_round",
    ):
        st.session_state.pop(key, None)


def _stage_salary(st: Any, value: float) -> None:
    target = max(1.0, round(float(value) / 250_000.0) * 250_000.0)
    st.session_state["fa_resign_suite_pending_salary"] = target
    _clear_preview_session(st)
    st.rerun()


def render_player_reaction_v1(
    state: Any,
    player_row: Mapping[str, Any],
    *,
    signing_team: str,
    decision: Any,
    negotiation: Any = None,
    annual_salary: float,
    years: int,
) -> None:
    import streamlit as st

    if decision is None:
        return

    inject_resigning_negotiation_styles_v1()
    context = prior_team_context_v1(state, player_row)
    returning = bool(_team(signing_team) and context.team == _team(signing_team))
    mood, mood_class = _mood(decision, negotiation)
    utility = float(getattr(decision, "utility_score", 0.0) or 0.0)
    threshold = float(getattr(decision, "acceptance_threshold", 0.0) or 0.0)
    gap = utility - threshold
    market_ref = float(getattr(decision, "market_salary_reference", 0.0) or 0.0)
    counter = _num(getattr(decision, "counter_salary", None))
    total = float(annual_salary) * int(years)
    offer_vs_market = (
        (float(annual_salary) / market_ref - 1.0) * 100.0
        if market_ref > 0
        else 0.0
    )
    fill = max(0.0, min(100.0, utility))

    factors = [
        ("Money", getattr(decision, "salary_score", 0.0)),
        ("Role", getattr(decision, "role_score", 0.0)),
        ("Winning", getattr(decision, "winning_score", 0.0)),
        ("Security", getattr(decision, "security_score", 0.0)),
        ("Career fit", getattr(decision, "career_fit_score", 0.0)),
    ]
    factor_html = "".join(
        f'<div class="rsn-factor"><span>{_e(label)}</span><b>{float(value or 0.0):.0f}/100</b></div>'
        for label, value in factors
    )
    priorities = _priority_labels(getattr(decision, "preference_profile", None))
    priority_text = " · ".join(
        f"{label} {weight * 100.0:.0f}%"
        for label, weight in priorities[:3]
    )

    response_label = (
        _clean(getattr(negotiation, "player_response", "")).replace("_", " ").title()
        if negotiation is not None
        else _clean(getattr(decision, "status", "")).title()
    )
    counter_text = _money(counter) if counter is not None else "None"
    delta_text = f"{offer_vs_market:+.1f}%"

    st.markdown(
        f"""
<div class="rsn-reaction">
  <div class="rsn-reaction-head">
    <div>
      <div class="rsn-eyebrow">Player response</div>
      <h3 style="margin:4px 0 0;color:#f8fafc">{_e(player_row.get('player_name'))}</h3>
    </div>
    <div class="rsn-mood {mood_class}">{_e(mood)}</div>
  </div>
  <div class="rsn-quote">“{_e(_dialogue(
      decision,
      negotiation,
      returning=returning,
      seed=(
          f"{_clean(player_row.get('player_id'))}|{_team(signing_team)}|"
          f"{float(annual_salary):.2f}|{int(years)}|"
          f"{_clean(getattr(negotiation, 'round_number', 'preview'))}"
      ),
  ))}”</div>
  <div class="rsn-interest-row">
    <div class="rsn-interest-track"><div class="rsn-interest-fill" style="width:{fill:.1f}%"></div></div>
    <div class="rsn-interest-label">Interest {utility:.1f}/100 · Yes line {threshold:.1f} · Gap {gap:+.1f}</div>
  </div>
  <div class="rsn-reaction-grid">
    <div class="rsn-reaction-stat"><small>Your offer</small><b>{_e(_money(annual_salary))}/yr × {int(years)}y</b></div>
    <div class="rsn-reaction-stat"><small>Total value</small><b>{_e(_money(total))}</b></div>
    <div class="rsn-reaction-stat"><small>Model fair value</small><b>{_e(_money(market_ref))}/yr · {delta_text}</b></div>
    <div class="rsn-reaction-stat"><small>Player counter</small><b>{_e(counter_text)}</b></div>
  </div>
  <div class="rsn-factors">{factor_html}</div>
  <div class="rsn-priority">Negotiation priorities · {_e(priority_text)} · Current response: {_e(response_label)}</div>
</div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns(3)
    if counter is not None:
        if c1.button(
            f"Meet counter · {_money(counter)}",
            width="stretch",
            key=f"fa_rsn_meet_counter_{_clean(player_row.get('player_id'))}",
            help="Changes only the offer input. It does not sign the player or commit a transaction.",
        ):
            _stage_salary(st, counter)
    else:
        c1.button(
            "No counter available",
            width="stretch",
            disabled=True,
            key=f"fa_rsn_no_counter_{_clean(player_row.get('player_id'))}",
        )

    if market_ref > 0:
        if c2.button(
            f"Match fair value · {_money(market_ref)}",
            width="stretch",
            key=f"fa_rsn_match_market_{_clean(player_row.get('player_id'))}",
            help="Uses the current player-decision model's market salary reference.",
        ):
            _stage_salary(st, market_ref)
    else:
        c2.button(
            "Fair value unavailable",
            width="stretch",
            disabled=True,
            key=f"fa_rsn_no_market_{_clean(player_row.get('player_id'))}",
        )

    bump = max(float(annual_salary) * 1.05, float(annual_salary) + 250_000.0)
    if c3.button(
        f"Improve offer 5% · {_money(bump)}",
        width="stretch",
        key=f"fa_rsn_bump_{_clean(player_row.get('player_id'))}",
        help="Changes only the offer input. The revised offer must be previewed and pass legality again.",
    ):
        _stage_salary(st, bump)

    if getattr(decision, "rationale", None):
        with st.expander("Agent notes · why the player reacted this way", expanded=False):
            for item in tuple(getattr(decision, "rationale", ()) or ()):
                st.markdown(f"- {_clean(item)}")
            st.caption(
                "Dialogue is a presentation of the existing deterministic player-decision model. "
                "Phrase style and wording vary cosmetically by player and offer state, but do not "
                "change acceptance, counter, decline, market interest, or any hidden player value."
            )
