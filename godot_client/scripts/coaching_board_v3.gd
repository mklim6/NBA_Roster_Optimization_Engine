extends VBoxContainer

signal edit_rotation

const DS = preload("res://scripts/design_system_v3.gd")
const Portrait = preload("res://scripts/player_portrait_v3.gd")
const TeamLogoV3 = preload("res://scripts/team_logo_v3.gd")
const TeamBrandingV3 = preload("res://scripts/team_branding_v3.gd")

var payload: Dictionary = {}
var postgame_game: Dictionary = {}
var postgame_team = ""


class TacticalCourt extends Control:
	var scheme = "balanced"
	var creation = 0.0
	var spacing = 0.0
	var rim_pressure = 0.0
	var glass_size = 0.0

	func _ready() -> void:
		custom_minimum_size = Vector2(520, 300)
		mouse_filter = Control.MOUSE_FILTER_IGNORE

	func _draw() -> void:
		var bounds = Rect2(Vector2(10, 10), size - Vector2(20, 20))
		draw_style_box(DS.style_box(Color("0b1720"), 16, DS.BORDER, 1, 0.0), bounds)

		var left = bounds.position.x + 18.0
		var top = bounds.position.y + 18.0
		var width = bounds.size.x - 36.0
		var height = bounds.size.y - 36.0
		var hoop = Vector2(left + width * 0.5, top + 34.0)

		draw_rect(Rect2(Vector2(left, top), Vector2(width, height)), Color("13252f"), true)
		draw_rect(Rect2(Vector2(left, top), Vector2(width, height)), Color("5d7482"), false, 1.3)
		draw_line(Vector2(left, top + height * 0.62), Vector2(left + width, top + height * 0.62), Color("536876"), 1.1)

		var lane_width = width * 0.30
		draw_rect(
			Rect2(
				Vector2(hoop.x - lane_width * 0.5, top),
				Vector2(lane_width, height * 0.35)
			),
			Color("7b8c96"),
			false,
			1.5
		)
		draw_arc(hoop, 12.0, 0.0, TAU, 40, DS.GOLD, 2.0)
		draw_arc(hoop, width * 0.34, 0.0, PI, 64, Color("71858f"), 1.6)

		var spots = [
			Vector2(0.20, 0.72),
			Vector2(0.40, 0.79),
			Vector2(0.80, 0.72),
			Vector2(0.64, 0.45),
			Vector2(0.39, 0.33)
		]

		if scheme == "pack_paint":
			spots = [
				Vector2(0.38, 0.49),
				Vector2(0.50, 0.60),
				Vector2(0.62, 0.49),
				Vector2(0.58, 0.31),
				Vector2(0.42, 0.31)
			]
		elif scheme == "match_size_and_glass":
			spots = [
				Vector2(0.31, 0.51),
				Vector2(0.47, 0.59),
				Vector2(0.69, 0.51),
				Vector2(0.60, 0.30),
				Vector2(0.40, 0.30)
			]
		elif scheme == "load_primary_creator":
			spots = [
				Vector2(0.31, 0.76),
				Vector2(0.44, 0.69),
				Vector2(0.80, 0.67),
				Vector2(0.63, 0.43),
				Vector2(0.40, 0.32)
			]

		for index in range(spots.size()):
			var pos = Vector2(
				left + spots[index].x * width,
				top + spots[index].y * height
			)
			draw_line(pos, hoop, Color(0.28, 0.82, 0.72, 0.18), 2.0)
			draw_circle(pos, 15.0, DS.GOOD)
			draw_string(
				ThemeDB.fallback_font,
				pos + Vector2(-5, 5),
				str(index + 1),
				HORIZONTAL_ALIGNMENT_LEFT,
				-1,
				14,
				Color("071014")
			)

		var threat_center = Vector2(left + width * 0.5, top + height * 0.78)
		var threat_strength = clamp(max(creation, rim_pressure) / 100.0, 0.0, 1.0)
		var threat_radius = 24.0 + 24.0 * threat_strength
		draw_arc(threat_center, threat_radius, 0.0, TAU, 48, Color(DS.GOLD, 0.65), 2.5)
		draw_string(
			ThemeDB.fallback_font,
			threat_center + Vector2(-31, 4),
			"THREAT",
			HORIZONTAL_ALIGNMENT_LEFT,
			-1,
			12,
			DS.GOLD
		)

		var cue = "BALANCED"
		if scheme == "pack_paint":
			cue = "PACK PAINT"
		elif scheme == "match_size_and_glass":
			cue = "SIZE + GLASS"
		elif scheme == "load_primary_creator":
			cue = "LOAD CREATOR"

		draw_string(
			ThemeDB.fallback_font,
			Vector2(left + 8.0, top + 20.0),
			cue,
			HORIZONTAL_ALIGNMENT_LEFT,
			-1,
			13,
			DS.MUTED
		)


func _ready() -> void:
	name = "CoachingTacticalCommand"
	size_flags_horizontal = Control.SIZE_EXPAND_FILL
	add_theme_constant_override("separation", 12)
	if get_child_count() == 0:
		clear_board("Refresh to load coaching intelligence.")


func clear_board(message: String) -> void:
	payload.clear()
	_rebuild_empty(message)


func configure(data: Dictionary) -> void:
	payload = data.duplicate(true)
	_rebuild()


func configure_postgame(game: Dictionary, controlled_team: String) -> void:
	postgame_game = game.duplicate(true)
	postgame_team = controlled_team.strip_edges().to_upper()
	if not payload.is_empty():
		_rebuild()


func clear_postgame() -> void:
	postgame_game.clear()
	postgame_team = ""
	if not payload.is_empty():
		_rebuild()


func _rebuild_empty(message: String) -> void:
	_clear_children(self)
	add_theme_constant_override("separation", 12)

	var hero = _card(Color("0d151f"), Color(DS.BORDER, 0.9), 16)
	hero.custom_minimum_size = Vector2(0, 110)
	var body = _body(hero, 16)
	body.add_child(_label("TACTICAL COMMAND CENTER", 20, DS.GOLD))
	body.add_child(_label(message, 12, DS.MUTED))
	add_child(hero)


func _rebuild() -> void:
	_clear_children(self)
	add_theme_constant_override("separation", 12)

	if not bool(payload.get("available", false)):
		_rebuild_empty(str(payload.get("detail", "No matchup available.")))
		return

	var decision = _dict(payload.get("decision"))
	var staff = _dict(payload.get("staff"))
	var threats = _dict(payload.get("threats"))

	_build_header(decision, staff)
	_build_identity_row(decision, staff, threats)
	_build_strategy_row(decision, threats)
	_build_plan_explanation(decision, staff, threats)

	if not postgame_game.is_empty() and postgame_team != "":
		_build_postgame_debrief(decision)

	var button = Button.new()
	button.name = "CoachingEditRotationButton"
	button.text = "EDIT ROTATION • PREVIEW YOUR CHANGES"
	button.custom_minimum_size = Vector2(0, 44)
	button.pressed.connect(func(): edit_rotation.emit())
	add_child(button)


func _build_header(decision: Dictionary, staff: Dictionary) -> void:
	var card = _card(Color("0a141b"), Color(DS.GOLD, 0.42), 18)
	card.name = "CoachingCommandHero"
	var body = _body(card, 16)

	var row = HBoxContainer.new()
	row.add_theme_constant_override("separation", 12)
	body.add_child(row)

	var copy = VBoxContainer.new()
	copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	copy.add_theme_constant_override("separation", 3)
	row.add_child(copy)

	copy.add_child(_label("GAME PLAN • COACHING IDENTITY", 9, DS.GOOD))
	copy.add_child(_label("TACTICAL COMMAND CENTER", 27, DS.TEXT))
	copy.add_child(_label(
		"Production matchup intelligence, staff identity, opponent pressure, and postgame outcome signals.",
		10,
		DS.MUTED
	))

	var scheme_panel = _card(Color(DS.GOLD, 0.08), Color(DS.GOLD, 0.42), 12)
	scheme_panel.custom_minimum_size = Vector2(240, 86)
	var scheme_body = _body(scheme_panel, 10)
	scheme_body.add_child(_label("MODEL SCHEME", 8, DS.GOLD))
	scheme_body.add_child(_label(
		str(decision.get("scheme_label", "Balanced")).to_upper(),
		18,
		DS.TEXT
	))
	row.add_child(scheme_panel)

	add_child(card)


func _build_identity_row(
	decision: Dictionary,
	staff: Dictionary,
	threats: Dictionary
) -> void:
	var row = GridContainer.new()
	row.columns = 3
	row.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row.add_theme_constant_override("h_separation", 12)
	add_child(row)

	var staff_card = _card(DS.PANEL, Color(DS.GOOD, 0.30), 15)
	staff_card.custom_minimum_size = Vector2(0, 190)
	staff_card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var staff_body = _body(staff_card, 14)
	staff_body.add_child(_label("COACHING IDENTITY", 9, DS.GOOD))
	staff_body.add_child(_label(
		str(staff.get("head_coach_name", "Head Coach")),
		20,
		DS.TEXT
	))

	var head_traits = _array(staff.get("head_traits"))
	var assistant_traits = _array(staff.get("assistant_traits"))
	staff_body.add_child(_label("HEAD COACH TRAITS", 8, DS.MUTED))
	staff_body.add_child(_trait_line(head_traits))
	staff_body.add_child(_label("ASSISTANT TRAITS", 8, DS.MUTED))
	staff_body.add_child(_trait_line(assistant_traits))
	row.add_child(staff_card)

	var scheme_card = _card(DS.PANEL, Color(DS.ACCENT, 0.30), 15)
	scheme_card.custom_minimum_size = Vector2(0, 190)
	scheme_card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var scheme_body = _body(scheme_card, 14)
	scheme_body.add_child(_label("TACTICAL IDENTITY", 9, DS.ACCENT))
	scheme_body.add_child(_label(
		str(decision.get("scheme_label", "Balanced")),
		20,
		DS.TEXT
	))
	scheme_body.add_child(_label(
		"MODELED OPPONENT SUPPRESSION",
		8,
		DS.MUTED
	))
	scheme_body.add_child(_label(
		"%.2f PTS" % _f(decision.get("suppression_points"), 0.0),
		24,
		DS.GOOD
	))
	scheme_body.add_child(_label(
		"Production model output • not a guaranteed score change.",
		9,
		DS.MUTED
	))
	row.add_child(scheme_card)

	var threat_card = _card(DS.PANEL, Color(DS.GOLD, 0.34), 15)
	threat_card.custom_minimum_size = Vector2(0, 190)
	threat_card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var threat_body = _body(threat_card, 14)
	threat_body.add_child(_label("PRIMARY THREAT", 9, DS.GOLD))

	var threat_row = HBoxContainer.new()
	threat_row.add_theme_constant_override("separation", 10)
	threat_body.add_child(threat_row)

	var portrait = Portrait.new()
	portrait.name = "CoachingThreatPortrait"
	portrait.custom_minimum_size = Vector2(112, 100)
	portrait.configure({
		"player_id": threats.get("primary_threat_player_id", ""),
		"name": threats.get("primary_threat_player_name", "Unknown")
	})
	threat_row.add_child(portrait)

	var threat_copy = VBoxContainer.new()
	threat_copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	threat_copy.alignment = BoxContainer.ALIGNMENT_CENTER
	threat_row.add_child(threat_copy)
	threat_copy.add_child(_label(
		str(threats.get("primary_threat_player_name", "Unknown")),
		18,
		DS.TEXT
	))
	threat_copy.add_child(_label(
		str(payload.get("opponent", "")).to_upper() + " • MATCHUP PRIORITY",
		9,
		DS.MUTED
	))
	row.add_child(threat_card)


func _build_strategy_row(decision: Dictionary, threats: Dictionary) -> void:
	var row = HBoxContainer.new()
	row.name = "TacticalStrategyRow"
	row.add_theme_constant_override("separation", 12)
	add_child(row)

	var court_card = _card(DS.PANEL, Color(DS.GOOD, 0.30), 16)
	court_card.custom_minimum_size = Vector2(560, 350)
	var court_body = _body(court_card, 14)
	court_body.add_child(_label("SCHEMATIC COVERAGE", 9, DS.GOOD))
	court_body.add_child(_label(
		str(decision.get("scheme_label", "Balanced")).to_upper(),
		20,
		DS.TEXT
	))

	var court = TacticalCourt.new()
	court.name = "PremiumTacticalCourt"
	court.scheme = str(decision.get("scheme", "balanced"))
	court.creation = _f(threats.get("creation"), 0.0)
	court.spacing = _f(threats.get("spacing"), 0.0)
	court.rim_pressure = _f(threats.get("rim_pressure"), 0.0)
	court.glass_size = _f(threats.get("glass_size"), 0.0)
	court_body.add_child(court)

	court_body.add_child(_label(
		"Schematic coverage only • player dots are tactical positions, not tracked coordinates.",
		9,
		DS.MUTED
	))
	row.add_child(court_card)

	var pressure_card = _card(DS.PANEL, Color(DS.GOLD, 0.32), 16)
	pressure_card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	pressure_card.custom_minimum_size = Vector2(0, 350)
	var pressure_body = _body(pressure_card, 14)
	pressure_body.add_child(_label("OPPONENT PRESSURE PROFILE", 9, DS.GOLD))
	pressure_body.add_child(_label(
		str(threats.get("primary_threat_player_name", "Unknown")),
		20,
		DS.TEXT
	))

	for metric in [
		["creation", "CREATION"],
		["spacing", "SPACING"],
		["rim_pressure", "RIM PRESSURE"],
		["glass_size", "SIZE / GLASS"],
		["interior_hub", "INTERIOR HUB"]
	]:
		_add_metric_bar(
			pressure_body,
			metric[1],
			threats.get(metric[0], null)
		)

	pressure_body.add_child(_divider())
	pressure_body.add_child(_label("MODEL EMPHASIS", 9, DS.GOOD))
	for cue in _model_cues(threats):
		pressure_body.add_child(_cue_row(cue))
	row.add_child(pressure_card)


func _build_plan_explanation(
	decision: Dictionary,
	staff: Dictionary,
	threats: Dictionary
) -> void:
	var card = _card(Color("101922"), Color(DS.ACCENT, 0.30), 15)
	card.name = "WhyThisPlanCard"
	var body = _body(card, 14)

	body.add_child(_label("WHY THIS PLAN", 10, DS.ACCENT))
	var explanation = _label(
		str(decision.get("explanation", "No model explanation was returned.")),
		12,
		DS.TEXT
	)
	explanation.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	body.add_child(explanation)

	var opponent = str(payload.get("opponent", "Opponent")).to_upper()
	body.add_child(_label(
		"%s • %s • %.2f modeled suppression pts" % [
			str(staff.get("head_coach_name", "Staff")),
			opponent,
			_f(decision.get("suppression_points"), 0.0)
		],
		11,
		DS.GOOD
	))

	body.add_child(_label(
		"Pregame model intelligence. It does not preview a score, alter player ratings, or guarantee the listed outcome.",
		9,
		DS.MUTED
	))
	add_child(card)


func _build_postgame_debrief(decision: Dictionary) -> void:
	var game = postgame_game
	var home_team = _s(game.get("home_team"), "").to_upper()
	var away_team = _s(game.get("away_team"), "").to_upper()
	if home_team == "" or away_team == "":
		return

	var controlled = postgame_team
	var opponent = away_team if controlled == home_team else home_team

	var team_rows = _team_rows(game, controlled)
	var opp_rows = _team_rows(game, opponent)

	var team_score = _team_score(game, controlled)
	var opp_score = _team_score(game, opponent)
	var score_margin = team_score - opp_score

	var team_reb = _sum(team_rows, "rebounds")
	var opp_reb = _sum(opp_rows, "rebounds")
	var team_ast = _sum(team_rows, "assists")
	var opp_ast = _sum(opp_rows, "assists")
	var team_to = _sum(team_rows, "turnovers")
	var opp_to = _sum(opp_rows, "turnovers")
	var opp_3m = _sum(opp_rows, "three_pointers_made")
	var opp_3a = _sum(opp_rows, "three_pointers_attempted")

	var card = _card(Color("0f1820"), Color(DS.GOOD, 0.36), 16)
	card.name = "PostgameTacticalDebrief"
	var body = _body(card, 14)

	var header = HBoxContainer.new()
	header.add_theme_constant_override("separation", 10)
	body.add_child(header)

	var copy = VBoxContainer.new()
	copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	header.add_child(copy)
	copy.add_child(_label("POSTGAME TACTICAL DEBRIEF", 10, DS.GOOD))
	copy.add_child(_label(
		"%s vs %s • OUTCOME SIGNALS" % [controlled, opponent],
		20,
		DS.TEXT
	))

	var scheme_badge = _card(Color(DS.GOLD, 0.08), Color(DS.GOLD, 0.34), 10)
	scheme_badge.custom_minimum_size = Vector2(210, 58)
	var badge_body = _body(scheme_badge, 8)
	badge_body.add_child(_label("PREGAME SCHEME", 8, DS.MUTED))
	badge_body.add_child(_label(
		str(decision.get("scheme_label", "Balanced")).to_upper(),
		13,
		DS.GOLD
	))
	header.add_child(scheme_badge)

	var metrics = GridContainer.new()
	metrics.columns = 4
	metrics.add_theme_constant_override("h_separation", 9)
	body.add_child(metrics)

	_metric_card(
		metrics,
		"SCORE MARGIN",
		("%+d" % score_margin) if score_margin != 0 else "EVEN",
		DS.GOOD if score_margin > 0 else (DS.BAD if score_margin < 0 else DS.MUTED)
	)
	_metric_card(
		metrics,
		"REBOUND MARGIN",
		"%+d" % (team_reb - opp_reb),
		DS.GOOD if team_reb >= opp_reb else DS.GOLD
	)
	_metric_card(
		metrics,
		"AST / TO EDGE",
		"%+d" % ((team_ast - team_to) - (opp_ast - opp_to)),
		DS.ACCENT
	)
	_metric_card(
		metrics,
		"OPP 3PT",
		"%d / %d" % [opp_3m, opp_3a],
		DS.GOLD
	)

	var note = _label(_debrief_note(
		str(decision.get("scheme", "balanced")),
		team_reb - opp_reb,
		opp_to,
		opp_3m,
		opp_3a
	), 11, DS.TEXT)
	note.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	body.add_child(note)

	body.add_child(_label(
		"These are descriptive box-score signals. They do not prove the coaching plan caused the result.",
		9,
		DS.MUTED
	))
	add_child(card)


func _debrief_note(
	scheme: String,
	rebound_margin: int,
	opponent_turnovers: int,
	opponent_three_made: int,
	opponent_three_attempted: int
) -> String:
	if scheme == "pack_paint":
		return "PACK PAINT REVIEW • Rebound margin %+d. Opponent perimeter result: %d/%d from three." % [
			rebound_margin,
			opponent_three_made,
			opponent_three_attempted
		]
	if scheme == "match_size_and_glass":
		return "SIZE + GLASS REVIEW • Rebound margin %+d. Use this alongside the full box score when judging the matchup." % rebound_margin
	if scheme == "load_primary_creator":
		return "LOAD CREATOR REVIEW • Opponent committed %d turnovers. Compare that outcome with the primary-threat usage shown above." % opponent_turnovers
	return "BALANCED REVIEW • Use score margin, rebounding, ball security, and opponent shooting together rather than treating one stat as proof of plan quality."


func _model_cues(threats: Dictionary) -> Array[String]:
	var cues: Array[String] = []
	if _f(threats.get("creation"), 0.0) >= 70.0:
		cues.append("CREATOR PRESSURE • The model sees elevated on-ball creation.")
	if _f(threats.get("spacing"), 0.0) >= 70.0:
		cues.append("SPACING ALERT • Weak-side shooters carry elevated pressure.")
	if _f(threats.get("rim_pressure"), 0.0) >= 70.0:
		cues.append("RIM PRESSURE • Interior help and size matter more in this matchup.")
	if _f(threats.get("glass_size"), 0.0) >= 70.0:
		cues.append("GLASS / SIZE • Finish possessions with strong rebounding coverage.")
	if _f(threats.get("interior_hub"), 0.0) >= 70.0:
		cues.append("INTERIOR HUB • Expect offense to flow through frontcourt touches.")
	if cues.is_empty():
		cues.append("BALANCED THREAT PROFILE • No single pressure category dominates the model.")
	return cues


func _cue_row(text_value: String) -> Control:
	var panel = PanelContainer.new()
	panel.add_theme_stylebox_override("panel", _box(Color("0d151d"), 9, Color(DS.BORDER, 0.78)))
	var margin = MarginContainer.new()
	_set_margins(margin, 9, 7, 9, 7)
	panel.add_child(margin)

	var row = HBoxContainer.new()
	row.add_theme_constant_override("separation", 7)
	margin.add_child(row)

	var dot = _label("•", 13, DS.GOOD)
	dot.size_flags_horizontal = Control.SIZE_SHRINK_BEGIN
	dot.custom_minimum_size = Vector2(14, 0)
	row.add_child(dot)
	var text = _label(text_value, 10, DS.MUTED)
	text.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	text.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row.add_child(text)
	return panel


func _add_metric_bar(parent: VBoxContainer, title: String, value) -> void:
	var header = HBoxContainer.new()
	header.add_theme_constant_override("separation", 8)
	parent.add_child(header)

	var title_label = _label(title, 9, DS.MUTED)
	title_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	header.add_child(title_label)

	var value_label = _label(
		"—" if value == null else "%.0f / 100" % _f(value, 0.0),
		9,
		DS.TEXT
	)
	header.add_child(value_label)

	var bar = ProgressBar.new()
	bar.custom_minimum_size = Vector2(0, 8)
	bar.show_percentage = false
	bar.min_value = 0.0
	bar.max_value = 100.0
	bar.value = 0.0 if value == null else _f(value, 0.0)
	parent.add_child(bar)


func _trait_line(values: Array) -> Label:
	var text = "No trait metadata"
	if not values.is_empty():
		var pieces: Array[String] = []
		for value in values:
			pieces.append(str(value).replace("_", " ").capitalize())
		text = " • ".join(pieces)
	var label = _label(text, 10, DS.TEXT)
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	return label


func _metric_card(parent: GridContainer, title: String, value: String, tone: Color) -> void:
	var card = _card(Color(tone, 0.06), Color(tone, 0.28), 10)
	card.custom_minimum_size = Vector2(0, 70)
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var body = _body(card, 8)
	body.add_child(_label(title, 8, tone))
	body.add_child(_label(value, 16, DS.TEXT))
	parent.add_child(card)


func _team_rows(game: Dictionary, team: String) -> Array:
	var rows: Array = []
	for raw in _array(game.get("player_box_scores")):
		var line = _dict(raw)
		if _s(line.get("team"), "").to_upper() == team:
			rows.append(line)
	return rows


func _team_score(game: Dictionary, team: String) -> int:
	var home = _s(game.get("home_team"), "").to_upper()
	var away = _s(game.get("away_team"), "").to_upper()
	if team == home:
		return _i(game.get("home_score"), 0)
	if team == away:
		return _i(game.get("away_score"), 0)
	return _sum(_team_rows(game, team), "points")


func _sum(rows: Array, key: String) -> int:
	var total = 0
	for raw in rows:
		var row = _dict(raw)
		total += _i(row.get(key), 0)
	return total


func _card(fill: Color, border: Color, radius: int) -> PanelContainer:
	var card = PanelContainer.new()
	card.add_theme_stylebox_override("panel", _box(fill, radius, border))
	return card


func _body(card: PanelContainer, padding: int) -> VBoxContainer:
	var margin = MarginContainer.new()
	_set_margins(margin, padding, padding, padding, padding)
	card.add_child(margin)

	var body = VBoxContainer.new()
	body.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	body.add_theme_constant_override("separation", 7)
	margin.add_child(body)
	return body


func _divider() -> HSeparator:
	var line = HSeparator.new()
	line.modulate = Color(1, 1, 1, 0.10)
	return line


func _box(fill: Color, radius: int, border: Color) -> StyleBoxFlat:
	var box = StyleBoxFlat.new()
	box.bg_color = fill
	box.border_color = border
	box.border_width_left = 1
	box.border_width_top = 1
	box.border_width_right = 1
	box.border_width_bottom = 1
	box.corner_radius_top_left = radius
	box.corner_radius_top_right = radius
	box.corner_radius_bottom_left = radius
	box.corner_radius_bottom_right = radius
	return box


func _label(text_value: String, font_size: int, color: Color = DS.TEXT) -> Label:
	var result = Label.new()
	result.text = text_value
	result.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	result.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	result.add_theme_font_size_override("font_size", font_size)
	result.add_theme_color_override("font_color", color)
	return result


func _set_margins(container: MarginContainer, left: int, top: int, right: int, bottom: int) -> void:
	container.add_theme_constant_override("margin_left", left)
	container.add_theme_constant_override("margin_top", top)
	container.add_theme_constant_override("margin_right", right)
	container.add_theme_constant_override("margin_bottom", bottom)


func _clear_children(node: Node) -> void:
	for child in node.get_children():
		node.remove_child(child)
		child.queue_free()


func _dict(value) -> Dictionary:
	return value if typeof(value) == TYPE_DICTIONARY else {}


func _array(value) -> Array:
	return value if typeof(value) == TYPE_ARRAY else []


func _s(value, fallback: String = "") -> String:
	if value == null:
		return fallback
	var text = str(value)
	return text if text.strip_edges() != "" else fallback


func _i(value, fallback: int = 0) -> int:
	if typeof(value) in [TYPE_INT, TYPE_FLOAT]:
		return int(value)
	return fallback


func _f(value, fallback: float = 0.0) -> float:
	if typeof(value) in [TYPE_INT, TYPE_FLOAT]:
		return float(value)
	return fallback
