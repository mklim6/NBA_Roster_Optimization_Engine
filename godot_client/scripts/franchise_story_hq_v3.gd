extends VBoxContainer

signal navigate(page: String)
const DS = preload("res://scripts/design_system_v3.gd")
var summary: Dictionary = {}
var intelligence: Dictionary = {}
var report_status := "Report is loading."
var accent := Color("48b989")

func configure(payload: Dictionary) -> void:
	summary = payload.duplicate(true)
	intelligence.clear()
	report_status = "Report is loading."
	_render()

func configure_intelligence(payload: Dictionary) -> void:
	if str(payload.get("team", "")) != str(summary.get("team", {}).get("abbreviation", "")):
		return
	intelligence = payload.duplicate(true)
	report_status = ""
	_render()

func set_report_unavailable() -> void:
	intelligence.clear()
	report_status = "Team and league report unavailable. Return to HQ to retry."
	_render()

func set_unavailable(message: String) -> void:
	summary.clear()
	intelligence.clear()
	_clear()
	add_child(_label("BRIEFING UNAVAILABLE", 22, DS.GOLD))
	add_child(_label(message, 14))

func _ready() -> void:
	add_theme_constant_override("separation", 14)
	if summary.is_empty():
		add_child(_label("Preparing your franchise briefing…", 18))

func _clear() -> void:
	for child in get_children():
		remove_child(child)
		child.queue_free()

func _label(value: String, font_size: int = 15, color: Color = DS.TEXT) -> Label:
	var label := Label.new()
	label.text = value
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.add_theme_font_size_override("font_size", font_size)
	label.add_theme_color_override("font_color", color)
	return label

func _panel(title: String, detail: String, page: String, action: String) -> PanelContainer:
	var panel := PanelContainer.new()
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var style := StyleBoxFlat.new()
	style.bg_color = DS.PANEL_ALT
	style.border_color = accent.darkened(0.45)
	style.set_border_width_all(1)
	style.set_corner_radius_all(14)
	style.content_margin_left = 20
	style.content_margin_right = 20
	style.content_margin_top = 18
	style.content_margin_bottom = 18
	panel.add_theme_stylebox_override("panel", style)
	var body := VBoxContainer.new()
	body.add_theme_constant_override("separation", 10)
	panel.add_child(body)
	body.add_child(_label(title, 20, accent.lightened(0.3)))
	body.add_child(_label(detail, 15))
	if not page.is_empty():
		var button := Button.new()
		button.text = action
		button.custom_minimum_size.y = 42
		button.pressed.connect(func(): navigate.emit(page))
		body.add_child(button)
	return panel

func _render() -> void:
	_clear()
	var team: Dictionary = summary.get("team", {})
	var branding = preload("res://scripts/team_branding_v3.gd")
	accent = branding.palette(str(team.get("abbreviation", "BOS"))).get("primary", DS.TEAM_PRIMARY)
	var season: Dictionary = summary.get("season", {})
	var record: Dictionary = summary.get("record", {})
	var next_game: Dictionary = summary.get("next_game", {})
	var phase := str(season.get("phase", ""))
	var played := int(record.get("games_played", 0))
	var headline := "Your season is taking shape"
	if played == 0:
		headline = "A new chapter starts here"
	elif int(record.get("streak_length", 0)) >= 3:
		headline = "Keep the momentum" if str(record.get("streak_type", "")) == "W" else "Find your response"
	if "offseason" in phase or "draft" in phase:
		headline = "Build the next chapter"
	add_child(_label("YOUR FRANCHISE • " + str(season.get("label", "")), 12, DS.GOLD))
	add_child(_label(headline, 28))
	add_child(_label("%s • %s • %s games played" % [team.get("name", "Your team"), record.get("display", "Record unavailable"), played], 15, DS.MUTED))
	var inbox_link := Button.new()
	inbox_link.text = "OPEN FRANCHISE INBOX"
	inbox_link.custom_minimum_size.y = 42
	inbox_link.pressed.connect(func(): navigate.emit("INBOX"))
	add_child(inbox_link)
	var office: Dictionary = intelligence.get("front_office", {})
	var rotation: Dictionary = office.get("rotation", {})
	var injuries: Array = office.get("injured_players", [])
	var morale: Array = office.get("morale_watch", [])
	var destination := "GAME DAY" if not next_game.is_empty() else "SEASON"
	var move := "Prepare for " + str(next_game.get("opponent_name", "your next game")) if not next_game.is_empty() else "Review your season transition"
	var reason := "Review the matchup and game plan before advancing your franchise." if not next_game.is_empty() else "Your schedule has no next game. Check the current phase and available season actions."
	if not injuries.is_empty():
		destination = "ROSTER"
		move = "Adjust for player availability"
		reason = "%s injured players appear in the latest team report. Review roles and minutes before the next game." % injuries.size()
	elif not rotation.is_empty() and (int(rotation.get("starters", 0)) != 5 or abs(float(rotation.get("total_minutes", 0)) - 240.0) > 0.1):
		destination = "ROSTER"
		move = "Check your rotation"
		reason = "Your current rotation reports %s starters and %s total minutes. Review the allocation in Rotation Lab." % [rotation.get("starters", 0), rotation.get("total_minutes", 0)]
	add_child(_panel("YOUR NEXT MOVE • " + move, reason, destination, "OPEN " + destination))
	add_child(_label("SEASON JOURNEY", 13, DS.GOLD))
	var journey := HBoxContainer.new()
	journey.add_theme_constant_override("separation", 12)
	add_child(journey)
	journey.add_child(_panel("SEASON", "%s\n%s games played • %s wins" % [phase.replace("_", " ").capitalize(), played, record.get("wins", 0)], "SEASON", "SEASON CENTER"))
	journey.add_child(_panel("NEXT CHAPTER", "%s\n%s" % [str(summary.get("draft", {}).get("draft_year", "Upcoming")) + " draft", str(summary.get("draft", {}).get("phase", "Not available")).replace("_", " ").capitalize()], "SCOUTING", "SCOUTING BOARD"))
	var momentum = preload("res://scripts/season_momentum_v3.gd").new()
	momentum.name = "SeasonMomentum"
	add_child(momentum)
	momentum.configure(intelligence.get("momentum", {}), accent, report_status)
	add_child(_label("FRONT OFFICE DECISIONS", 13, DS.GOLD))
	var decisions := HBoxContainer.new()
	decisions.add_theme_constant_override("separation", 12)
	add_child(decisions)
	var financial: Dictionary = summary.get("financial", {})
	decisions.add_child(_panel("Manage your flexibility", "Cap room: %s%s\nReview salary rules and contracts before adding players." % [financial.get("cap_space_display", "Unavailable"), " (roster estimate)" if bool(financial.get("is_estimate", false)) else ""], "FRONT OFFICE", "REVIEW FINANCES"))
	var morale_status := "%s on morale watch" % morale.size() if office.get("chemistry", {}).get("morale_average", null) != null else "Morale not evaluated"
	var health := report_status if intelligence.is_empty() else "%s injuries reported • %s\nReview availability, workload and player roles." % [injuries.size(), morale_status]
	decisions.add_child(_panel("Protect your rotation", health, "ROSTER", "OPEN ROSTER"))
	add_child(_label("AROUND YOUR UNIVERSE", 13, DS.GOLD))
	var recent: Array = intelligence.get("league", {}).get("recent_results", [])
	var news := report_status if intelligence.is_empty() else "No completed games in the current league report. Your season story is still ahead."
	if not recent.is_empty():
		var lines := PackedStringArray()
		for item in recent.slice(0, 3):
			lines.append("%s %s — %s %s" % [item.get("away_team", "Away"), item.get("away_score", "?"), item.get("home_team", "Home"), item.get("home_score", "?")])
		news = "\n".join(lines)
	add_child(_panel("League pulse", news, "LEAGUE", "EXPLORE THE LEAGUE"))

