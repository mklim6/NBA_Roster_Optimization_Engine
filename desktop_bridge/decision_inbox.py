"""Read-only decision cards derived from the saved franchise snapshot."""
from __future__ import annotations
from typing import Any


def build_decision_inbox(state: Any, team: str, office: dict, game: dict, draft: dict) -> dict:
    season = str(getattr(getattr(state, "settings", None), "season_label", ""))
    day = int(getattr(state, "current_day_index", 0))
    cards: list[dict] = []

    def add(key, category, priority, title, detail, destination, player_id="", **extra):
        cards.append(dict(id=key, category=category, priority=priority, title=title,
                          detail=detail, destination=destination, player_id=player_id, **extra))

    queue = getattr(state, "franchise_cpu_incoming_trade_offers_v1", None)
    queue_loaded = isinstance(queue, dict) and queue.get("season") == season
    for offer in (queue.get("offers", []) if queue_loaded else []):
        if not isinstance(offer, dict) or offer.get("status") != "pending" or offer.get("user_team") != team or offer.get("season") != season:
            continue
        expires = offer.get("expires_day")
        if expires is None or int(expires) < day:
            continue
        incoming = ", ".join(str(x) for x in offer.get("cpu_sends_names", [])) or "Package names unavailable"
        outgoing = ", ".join(str(x) for x in offer.get("user_sends_names", [])) or "Package names unavailable"
        add("offer:" + str(offer.get("offer_id", "")), "Offers", "Action", f"{offer.get('cpu_team', 'CPU')} has a saved offer",
            f"Receive: {incoming}\nSend: {outgoing}\nExpires after league day {expires}. Review the package in Trade Center; this card does not resolve the offer.",
            "TRADES", expires_day=int(expires), offer_id=str(offer.get("offer_id", "")))

    for row in office.get("team_health", {}).get("injuries", []):
        pid = str(row.get("player_id", ""))
        add("injury:" + pid, "Availability", "Action", str(row.get("name", "Player")) + " • availability",
            f"{row.get('status', 'Availability report')}\nReview roles and minutes before your next game.", "ROSTER", pid, name=row.get("name", "Player"))
    for row in office.get("morale", {}).get("attention", []):
        pid = str(row.get("player_id", ""))
        add("morale:" + pid, "Player roles", "Watch", str(row.get("name", "Player")) + " • role concern",
            f"{row.get('status') or 'Reported concern'}\nExpected role: {row.get('expected_role') or 'Unavailable'}. Review expectations and conversation options in Locker Room.",
            "LOCKER ROOM", pid, name=row.get("name", "Player"))
    for i, alert in enumerate(game.get("coaching_alerts", [])):
        add("coaching:" + str(i), "Game preparation", "Watch", str(alert.get("title", "Coaching alert")),
            str(alert.get("detail", "Review your current game plan.")), "GAME DAY")
    rotation = office.get("rotation", {})
    total = rotation.get("total_target_minutes")
    starters = rotation.get("starters")
    if (starters is not None and starters != 5) or (total is not None and abs(float(total)-240.0) > 0.1):
        add("rotation", "Game preparation", "Action", "Your rotation needs a review",
            f"Reported starters: {starters if starters is not None else 'Unavailable'} • Target minutes: {total if total is not None else 'Unavailable'}\nCheck the lineup and allocation in Rotation Lab.", "ROSTER")
    phase = draft.get("phase", "")
    pick = draft.get("current_pick") or {}
    if phase == "draft_in_progress" and pick.get("owner_team") == team:
        add("draft:pick", "Season decisions", "Action", "Your franchise is on the clock",
            f"Pick #{pick.get('overall_pick', '?')}. Compare scouting reports, then preview your selection in Scouting & Draft.", "SCOUTING")
    if phase == "draft_complete":
        add("draft:complete", "Season decisions", "Next", "Review your post-draft roster",
            "Check the remaining roster gate and available next-season actions in Season Center.", "SEASON")
    next_game = game.get("next_game") or {}
    if next_game:
        add("next_game", "Game preparation", "Next", "Prepare for " + str(next_game.get("opponent_name", next_game.get("opponent", "your next opponent"))),
            f"League day {next_game.get('day_index', '?')} • Review availability and your game plan before simulation.", "GAME DAY")
    weights = {"Action": 0, "Watch": 1, "Next": 2}
    cards.sort(key=lambda card: (weights[card["priority"]], card.get("expires_day", 10**9), card["id"]))
    return dict(team=team, season=season, day_index=day, cards=cards, read_only=True,
                offer_queue_status="loaded" if queue_loaded else "not_initialized",
                review_only=True)
