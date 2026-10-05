extends VBoxContainer

signal navigate(page: String)

const DS = preload("res://scripts/design_system_v3.gd")
const Branding = preload("res://scripts/team_branding_v3.gd")
const VERSION := "v3-visual-overhaul-50a3-command-deck-v1.0.0-2026-10-05"

var summary: Dictionary = {}
var intelligence: Dictionary = {}
var report_status := "Team report is loading."
var accent := Color("48b989")


func _ready() -> void:
	add_theme_constant_override("separation", 10)
	if summary.is_empty():
		add_child(_label("Preparing your front-office briefing…", 15, DS.MUTED))


func configure(payload: Dictionary) -> void:
	summary = payload.duplicate(true)
	intelligence.clear()
	report_status = "Team report is loading."
	_render()


func configure_intelligence(payload: Dictionary) -> void:
	if str(payload.get("team", "")) != str(summary.get("team", {}).get("abbreviation", "")):
		return
	intelligence = payload.duplicate(true)
	report_status = ""
	_render()


func set_report_unavailable() -> void:
	intelligence.clear()
	report_status = "Live team report unavailable. Return to Home to retry."
	_render()


func set_unavailable(message: String) -> void:
	summary.clear()
	intelligence.clear()
	_clear()
	var panel := _surface_panel(Color(DS.BAD, 0.055), Color(DS.BAD, 0.24), 12)
	var body := VBoxContainer.new()
	body.add_theme_constant_override("separation", 5)
	panel.add_child(body)
	body.add_child(_label("BRIEFING UNAVAILABLE", 13, DS.BAD))
	body.add_child(_label(message, 11, DS.MUTED))
	add_child(panel)


func _clear() -> void:
	for child in get_children():
		remove_child(child)
		child.queue_free()


func _label(value: String, font_size: int = 13, color: Color = DS.TEXT) -> Label:
	var label := Label.new()
	label.text = value
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.add_theme_font_size_override("font_size", font_size)
	label.add_theme_color_override("font_color", color)
	return label


func _surface_panel(fill: Color, border: Color, radius: int = 12) -> PanelContainer:
	var panel := PanelContainer.new()
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var style := DS.style_box(fill, radius, border, 1, 0.08)
	style.content_margin_left = 14
	style.content_margin_right = 14
	style.content_margin_top = 12
	style.content_margin_bottom = 12
	panel.add_theme_stylebox_override("panel", style)
	return panel


func _action(text_value: String, page: String, primary: bool = false) -> Button:
	var button := Button.new()
	button.text = text_value
	button.custom_minimum_size = Vector2(112, 34)
	button.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	button.add_theme_font_size_override("font_size", 10)

	var fill := accent if primary else DS.PANEL_ALT
	var border := accent if primary else Color(DS.BORDER, 0.72)
	var foreground := Branding.readable_foreground(accent) if primary else DS.TEXT
	button.add_theme_color_override("font_color", foreground)
	button.add_theme_color_override("font_hover_color", DS.TEXT_STRONG)
	button.add_theme_stylebox_override(
		"normal",
		DS.style_box(fill, 8, border, 1, 0.10 if primary else 0.0)
	)
	button.add_theme_stylebox_override(
		"hover",
		DS.style_box(
			Branding.hover_color(accent) if primary else DS.PANEL_HOVER,
			8,
			accent.lightened(0.20),
			1,
			0.12
		)
	)
	button.pressed.connect(func(): navigate.emit(page))
	return button


func _stat_card(title_text: String, value_text: String, detail_text: String, page: String) -> PanelContainer:
	var panel := _surface_panel(Color(DS.PANEL_ALT, 0.72), Color(DS.SOFT_BORDER, 0.78), 11)
	panel.custom_minimum_size = Vector2(0, 74)
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL

	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 4)
	panel.add_child(box)

	box.add_child(_label(title_text, 9, accent.lightened(0.34)))
	var value := _label(value_text, 16, DS.TEXT_STRONG)
	value.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	box.add_child(value)
	box.add_child(_label(detail_text, 10, DS.MUTED))

	var spacer := Control.new()
	spacer.size_flags_vertical = Control.SIZE_EXPAND_FILL
	box.add_child(spacer)

	var link := Button.new()
	link.text = "OPEN " + page
	link.flat = true
	link.alignment = HORIZONTAL_ALIGNMENT_LEFT
	link.custom_minimum_size.y = 24
	link.add_theme_font_size_override("font_size", 9)
	link.add_theme_color_override("font_color", accent.lightened(0.34))
	link.add_theme_color_override("font_hover_color", DS.TEXT_STRONG)
	link.pressed.connect(func(): navigate.emit(page))
	box.add_child(link)
	return panel


func _render() -> void:
	_clear()
	if summary.is_empty():
		add_child(_label("Preparing your front-office briefing…", 15, DS.MUTED))
		return

	var team: Dictionary = summary.get("team", {})
	var season: Dictionary = summary.get("season", {})
	var record: Dictionary = summary.get("record", {})
	var next_game: Dictionary = summary.get("next_game", {})
	var draft: Dictionary = summary.get("draft", {})
	var financial: Dictionary = summary.get("financial", {})

	accent = Branding.palette(str(team.get("abbreviation", "BOS"))).get("primary", DS.TEAM_PRIMARY)

	var office: Dictionary = intelligence.get("front_office", {})
	var rotation: Dictionary = office.get("rotation", {})
	var injuries: Array = office.get("injured_players", [])
	var morale: Array = office.get("morale_watch", [])

	# Streamlit-style command deck: one compact explanatory strip, then the
	# actionable franchise content. The hero above already carries the drama.
	var command_panel := _surface_panel(Color(DS.PANEL, 0.46), Color(DS.SOFT_BORDER, 0.42), 10)
	add_child(command_panel)
	var command_row := HBoxContainer.new()
	command_row.add_theme_constant_override("separation", 10)
	command_panel.add_child(command_row)
	var command_copy := VBoxContainer.new()
	command_copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	command_copy.add_theme_constant_override("separation", 1)
	command_row.add_child(command_copy)
	command_copy.add_child(_label("COMMAND DECK", 12, DS.TEXT_STRONG))
	command_copy.add_child(_label("Your next decision, season pulse, roster health and fastest path forward.", 9, DS.MUTED))
	command_row.add_child(_action("INBOX", "INBOX"))

	# Preserve the old decision logic, but present it as one strong strip rather than a large card stack.
	var destination := "GAME DAY" if not next_game.is_empty() else "SEASON"
	var move := "Prepare for " + str(next_game.get("opponent_name", "your next game")) if not next_game.is_empty() else "Review your season transition"
	var reason := "Review the matchup and game plan before advancing your franchise." if not next_game.is_empty() else "Your schedule has no next game. Review the current phase and available season actions."

	if not injuries.is_empty():
		destination = "ROSTER"
		move = "Adjust for player availability"
		reason = "%s injured player(s) appear in the latest team report. Review roles and minutes before advancing." % injuries.size()
	elif not rotation.is_empty() and (
		int(rotation.get("starters", 0)) != 5
		or abs(float(rotation.get("total_minutes", 0)) - 240.0) > 0.1
	):
		destination = "ROSTER"
		move = "Check your rotation"
		reason = "The latest rotation reports %s starters and %s total minutes. Review the allocation before Game Day." % [
			rotation.get("starters", 0),
			rotation.get("total_minutes", 0),
		]

	var next_panel := _surface_panel(Color(accent, 0.070), Color(accent, 0.34), 12)
	next_panel.custom_minimum_size = Vector2(0, 66)
	add_child(next_panel)

	var next_row := HBoxContainer.new()
	next_row.add_theme_constant_override("separation", 16)
	next_panel.add_child(next_row)

	var next_copy := VBoxContainer.new()
	next_copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	next_copy.add_theme_constant_override("separation", 3)
	next_row.add_child(next_copy)
	next_copy.add_child(_label("YOUR NEXT MOVE", 9, accent.lightened(0.40)))
	next_copy.add_child(_label(move, 15, DS.TEXT_STRONG))
	next_copy.add_child(_label(reason, 10, DS.MUTED))
	next_row.add_child(_action("OPEN " + destination, destination, true))

	# Streamlit-style information density: three equal, compact cards with no wasted vertical space.
	var snapshot := GridContainer.new()
	snapshot.columns = 3
	snapshot.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	snapshot.add_theme_constant_override("h_separation", 10)
	snapshot.add_theme_constant_override("v_separation", 10)
	add_child(snapshot)

	var record_detail := str(record.get("conference_rank_display", "Live standings"))
	if record.get("streak", null) != null:
		record_detail += " • " + str(record.get("streak"))

	snapshot.add_child(
		_stat_card(
			"SEASON",
			str(record.get("display", "N/A")),
			record_detail,
			"SEASON"
		)
	)

	var cap_text := str(financial.get("cap_space_display", "N/A"))
	var payroll_text := str(financial.get("payroll_display", "Payroll unavailable"))
	snapshot.add_child(
		_stat_card(
			"FLEXIBILITY",
			cap_text,
			"Payroll " + payroll_text,
			"FRONT OFFICE"
		)
	)

	var health_value := "%s unavailable" % injuries.size()
	var health_detail := "%s morale watch" % morale.size() if not intelligence.is_empty() else report_status
	snapshot.add_child(
		_stat_card(
			"LOCKER ROOM",
			health_value,
			health_detail,
			"ROSTER"
		)
	)

	# Draft + league pulse are compact utility rows, not more giant panels.
	var utility := HBoxContainer.new()
	utility.add_theme_constant_override("separation", 10)
	add_child(utility)

	var draft_panel := _surface_panel(Color(DS.PANEL, 0.56), Color(DS.SOFT_BORDER, 0.72), 10)
	draft_panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	utility.add_child(draft_panel)

	var draft_row := HBoxContainer.new()
	draft_row.add_theme_constant_override("separation", 10)
	draft_panel.add_child(draft_row)

	var draft_copy := VBoxContainer.new()
	draft_copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	draft_copy.add_theme_constant_override("separation", 2)
	draft_row.add_child(draft_copy)
	draft_copy.add_child(_label("NEXT CHAPTER", 9, DS.GOLD))
	draft_copy.add_child(
		_label(
			"%s Draft • %s" % [
				str(draft.get("draft_year", "Upcoming")),
				str(draft.get("phase", "scouting")).replace("_", " ").capitalize(),
			],
			13,
			DS.TEXT
		)
	)
	draft_row.add_child(_action("SCOUTING", "SCOUTING"))

	var league_panel := _surface_panel(Color(DS.PANEL, 0.56), Color(DS.SOFT_BORDER, 0.72), 10)
	league_panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	utility.add_child(league_panel)

	var league_row := HBoxContainer.new()
	league_row.add_theme_constant_override("separation", 10)
	league_panel.add_child(league_row)

	var league_copy := VBoxContainer.new()
	league_copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	league_copy.add_theme_constant_override("separation", 2)
	league_row.add_child(league_copy)
	league_copy.add_child(_label("AROUND THE LEAGUE", 9, DS.GOLD))

	var recent: Array = intelligence.get("league", {}).get("recent_results", [])
	var news := report_status if intelligence.is_empty() else "No completed games in the current league report."
	if not recent.is_empty():
		var bits := PackedStringArray()
		for item in recent.slice(0, 2):
			bits.append(
				"%s %s–%s %s" % [
					str(item.get("away_team", "AWY")),
					str(item.get("away_score", "?")),
					str(item.get("home_score", "?")),
					str(item.get("home_team", "HME")),
				]
			)
		news = "   •   ".join(bits)
	league_copy.add_child(_label(news, 10, DS.MUTED))
	league_row.add_child(_action("LEAGUE", "LEAGUE"))

	# Keep the existing momentum feature below the compact command deck.
	var momentum = preload("res://scripts/season_momentum_v3.gd").new()
	momentum.name = "SeasonMomentum"
	momentum.navigate.connect(func(page): navigate.emit(page))
	add_child(momentum)
	momentum.configure(intelligence.get("momentum", {}), accent, report_status)
