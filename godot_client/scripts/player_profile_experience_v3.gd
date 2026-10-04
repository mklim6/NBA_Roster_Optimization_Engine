extends PanelContainer

signal close_requested

const DesignSystemV3 = preload("res://scripts/design_system_v3.gd")
const TeamLogoV3 = preload("res://scripts/team_logo_v3.gd")
const PlayerPortraitV3 = preload("res://scripts/player_portrait_v3.gd")

const PANEL = DesignSystemV3.PANEL
const PANEL_ALT = DesignSystemV3.PANEL_ALT
const TEXT = DesignSystemV3.TEXT
const MUTED = DesignSystemV3.MUTED
const ACCENT = DesignSystemV3.ACCENT
const GOOD = DesignSystemV3.GOOD
const BAD = DesignSystemV3.BAD
const GOLD = DesignSystemV3.GOLD
const BORDER = DesignSystemV3.BORDER

var player: Dictionary = {}
var active_team = ""
var primary = DesignSystemV3.TEAM_PRIMARY
var secondary = DesignSystemV3.GOLD


func _ready() -> void:
	name = "PlayerProfileExperience"
	custom_minimum_size = Vector2(1120, 760)
	size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	size_flags_vertical = Control.SIZE_SHRINK_CENTER


func configure(
	player_data: Dictionary,
	team_abbreviation: String,
	primary_color: Color,
	secondary_color: Color
) -> void:
	player = player_data
	active_team = team_abbreviation.strip_edges().to_upper()
	primary = primary_color
	secondary = secondary_color
	_clear_children(self)

	add_theme_stylebox_override("panel", _box(PANEL, Color(primary, 0.70), 20))

	var margin = MarginContainer.new()
	_set_margins(margin, 18, 16, 18, 16)
	add_child(margin)

	var body = VBoxContainer.new()
	body.add_theme_constant_override("separation", 12)
	margin.add_child(body)

	_build_top_bar(body)
	_build_hero(body)
	_build_detail_grid(body)


func _build_top_bar(body: VBoxContainer) -> void:
	var row = HBoxContainer.new()
	row.add_theme_constant_override("separation", 10)
	body.add_child(row)

	var label_box = VBoxContainer.new()
	label_box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row.add_child(label_box)
	label_box.add_child(_label("FRANCHISE PLAYER PROFILE", 10, _hover(primary)))
	label_box.add_child(_label("ACTIVE V3 ROSTER • PERFORMANCE • CONTRACT • DEVELOPMENT", 8, MUTED))

	var close = Button.new()
	close.text = "CLOSE"
	close.custom_minimum_size = Vector2(92, 36)
	close.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	close.add_theme_font_size_override("font_size", 10)
	close.add_theme_color_override("font_color", TEXT)
	close.add_theme_stylebox_override("normal", _box(PANEL_ALT, BORDER, 10))
	close.add_theme_stylebox_override("hover", _box(Color(primary, 0.20), Color(primary, 0.55), 10))
	close.pressed.connect(_on_close_pressed)
	row.add_child(close)


func _build_hero(body: VBoxContainer) -> void:
	var hero = PanelContainer.new()
	hero.name = "PlayerProfileHero"
	hero.custom_minimum_size = Vector2(0, 238)
	hero.add_theme_stylebox_override("panel", _box(Color(primary, 0.13), Color(_hover(primary), 0.62), 18))
	body.add_child(hero)

	var margin = MarginContainer.new()
	_set_margins(margin, 16, 12, 16, 12)
	hero.add_child(margin)

	var row = HBoxContainer.new()
	row.add_theme_constant_override("separation", 16)
	margin.add_child(row)

	var hero_portrait = PlayerPortraitV3.new()
	hero_portrait.name = "ProfileHeroPortrait"
	hero_portrait.custom_minimum_size = Vector2(286, 212)
	row.add_child(hero_portrait)
	hero_portrait.configure(player)

	var identity = VBoxContainer.new()
	identity.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	identity.alignment = BoxContainer.ALIGNMENT_CENTER
	identity.add_theme_constant_override("separation", 6)
	row.add_child(identity)

	var team_row = HBoxContainer.new()
	team_row.add_theme_constant_override("separation", 8)
	identity.add_child(team_row)

	var team_logo = TeamLogoV3.new()
	team_logo.custom_minimum_size = Vector2(56, 50)
	team_logo.configure(_player_team())
	team_row.add_child(team_logo)

	var team_copy = VBoxContainer.new()
	team_copy.alignment = BoxContainer.ALIGNMENT_CENTER
	team_row.add_child(team_copy)
	team_copy.add_child(_label(_player_team(), 12, _hover(primary)))
	team_copy.add_child(_label(_display(player.get("position", null), "POSITION N/A"), 10, MUTED))

	var name = _label(_display(player.get("name", null), "Unknown Player"), 34, TEXT)
	name.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	identity.add_child(name)

	var meta = _label(
		"Age %s  •  %s  •  %s" % [
			_number(player.get("age", null), 1),
			_display(player.get("role", null), "Role not assigned"),
			_pretty(_display(player.get("development_direction", null), "Development unknown")),
		],
		12,
		MUTED
	)
	meta.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	identity.add_child(meta)

	var tags = HBoxContainer.new()
	tags.add_theme_constant_override("separation", 7)
	identity.add_child(tags)
	if bool(player.get("is_starter", false)):
		tags.add_child(_pill("STARTER", GOLD))
	elif bool(player.get("in_rotation", false)):
		tags.add_child(_pill("ROTATION", GOOD))
	else:
		tags.add_child(_pill("RESERVE", MUTED))

	var health = _dict(player.get("health"))
	var health_status = _display(health.get("display", null), "Health unknown")
	var health_code = _display(health.get("status", null), "unknown").to_lower()
	tags.add_child(_pill(health_status, GOOD if health_code == "healthy" else BAD if health_code != "unknown" else MUTED))

	var morale = _dict(player.get("morale"))
	var morale_status = _display(morale.get("status", null), "Not evaluated")
	tags.add_child(_pill(morale_status, _morale_tone(morale_status)))

	var projection = _label(
		"Future outlook %s  •  Target %s min  •  %s" % [
			_number(player.get("future_outlook", null), 1),
			_number(player.get("target_minutes", null), 0),
			"Generated prospect" if bool(player.get("generated_prospect", false)) else "NBA player",
		],
		10,
		MUTED
	)
	identity.add_child(projection)

	var ratings = VBoxContainer.new()
	ratings.custom_minimum_size = Vector2(220, 0)
	ratings.alignment = BoxContainer.ALIGNMENT_CENTER
	ratings.add_theme_constant_override("separation", 8)
	row.add_child(ratings)

	var ratings_row = HBoxContainer.new()
	ratings_row.add_theme_constant_override("separation", 8)
	ratings.add_child(ratings_row)
	ratings_row.add_child(_hero_rating("OVR", player.get("overall", null), true))
	ratings_row.add_child(_hero_rating("POT", player.get("potential", null), false))
	ratings.add_child(_hero_future_tile(player.get("future_outlook", null)))


func _build_detail_grid(body: VBoxContainer) -> void:
	var scroll = ScrollContainer.new()
	scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	body.add_child(scroll)

	var content = VBoxContainer.new()
	content.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	content.add_theme_constant_override("separation", 12)
	scroll.add_child(content)

	var grid = GridContainer.new()
	grid.columns = 3
	grid.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	grid.add_theme_constant_override("h_separation", 10)
	grid.add_theme_constant_override("v_separation", 10)
	content.add_child(grid)

	grid.add_child(_season_card())
	grid.add_child(_skills_card())
	grid.add_child(_contract_card())
	grid.add_child(_health_card())
	grid.add_child(_morale_card())
	grid.add_child(_development_card())

	var footer = _label(
		"ACTIVE V3 PLAYER PROFILE • Read-only presentation of the isolated working franchise • Protected V2 remains unchanged.",
		9,
		MUTED
	)
	content.add_child(footer)


func _season_card() -> Control:
	var stats = _dict(player.get("season_stats"))
	var card = _detail_card_shell("SEASON PRODUCTION", ACCENT)
	var body = card.get_meta("body") as VBoxContainer

	var metrics = HBoxContainer.new()
	metrics.add_theme_constant_override("separation", 6)
	body.add_child(metrics)
	metrics.add_child(_stat_tile("PPG", stats.get("ppg", null)))
	metrics.add_child(_stat_tile("RPG", stats.get("rpg", null)))
	metrics.add_child(_stat_tile("APG", stats.get("apg", null)))

	body.add_child(_value_line("Games / starts", "%s / %s" % [
		_display(stats.get("games_played", null)),
		_display(stats.get("games_started", null)),
	]))
	body.add_child(_value_line("Minutes per game", _number(stats.get("mpg", null), 1)))
	body.add_child(_value_line("Steals / blocks", "%s / %s" % [
		_number(stats.get("spg", null), 1),
		_number(stats.get("bpg", null), 1),
	]))
	body.add_child(_value_line("FG / 3PT / FT", "%s / %s / %s" % [
		_pct(stats.get("fg_pct", null)),
		_pct(stats.get("three_pct", null)),
		_pct(stats.get("ft_pct", null)),
	]))
	return card


func _skills_card() -> Control:
	var skills = _dict(player.get("skills"))
	var card = _detail_card_shell("SKILL PROFILE", GOLD)
	var body = card.get_meta("body") as VBoxContainer

	var entries = [
		["Scoring", "scoring_rating"],
		["Shooting", "shooting_rating"],
		["Playmaking", "playmaking_rating"],
		["Rebounding", "rebounding_rating"],
		["Defense", "defense_rating"],
		["Efficiency", "efficiency_rating"],
		["Availability", "availability_rating"],
	]
	var any_rating = false
	for entry in entries:
		var rating = skills.get(entry[1], null)
		if rating == null:
			continue
		any_rating = true
		body.add_child(_skill_bar(str(entry[0]), rating))
	if not any_rating:
		body.add_child(_label("Skill ratings are not available for this player.", 10, MUTED))
	return card


func _contract_card() -> Control:
	var contract = _dict(player.get("contract"))
	var card = _detail_card_shell("ROLE + CONTRACT", GOOD)
	var body = card.get_meta("body") as VBoxContainer
	body.add_child(_value_line("Role", _display(player.get("role", null))))
	body.add_child(_value_line("Target minutes", _number(player.get("target_minutes", null), 0)))
	body.add_child(_value_line("Salary", _display(contract.get("salary_display", null))))
	body.add_child(_value_line("Years remaining", _display(contract.get("years_remaining", null))))
	body.add_child(_value_line("Contract status", _pretty(_display(contract.get("status", null)))))
	body.add_child(_value_line("Option", _pretty(_display(contract.get("option_type", null), "None"))))
	body.add_child(_value_line("Rotation order", _pretty(_display(player.get("rotation_order", null), "None"))))
	return card


func _health_card() -> Control:
	var health = _dict(player.get("health"))
	var health_code = _display(health.get("status", null), "unknown").to_lower()
	var tone = GOOD if health_code == "healthy" else BAD if health_code != "unknown" else MUTED
	var card = _detail_card_shell("HEALTH + WORKLOAD", tone)
	var body = card.get_meta("body") as VBoxContainer

	body.add_child(_value_line("Status", _display(health.get("display", null), "Unknown")))
	body.add_child(_value_line("Fatigue", _number(health.get("fatigue", null), 1)))
	body.add_child(_value_line("Durability", _ratio_pct(health.get("durability", null))))
	body.add_child(_value_line("Risk tier", _pretty(_display(health.get("risk_tier", null), "Unknown"))))
	body.add_child(_value_line("Games missed", _display(health.get("season_games_missed", null), "0")))
	body.add_child(_value_line("Injuries suffered", _display(health.get("injuries_suffered", null), "0")))

	var fatigue = health.get("fatigue", null)
	if fatigue != null:
		body.add_child(_progress("WORKLOAD", float(fatigue), 100.0, BAD if float(fatigue) >= 70.0 else GOLD))

	var notes = _display(health.get("risk_explanation", null), "")
	if notes != "":
		var note = _label(notes, 9, MUTED)
		note.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		body.add_child(note)
	return card


func _morale_card() -> Control:
	var morale = _dict(player.get("morale"))
	var status = _display(morale.get("status", null), "Not evaluated")
	var card = _detail_card_shell("MORALE + ROLE HEALTH", _morale_tone(status))
	var body = card.get_meta("body") as VBoxContainer

	body.add_child(_value_line("Status", status))
	body.add_child(_value_line("Score", _number(morale.get("score", null), 1)))
	body.add_child(_value_line("Role satisfaction", _number(morale.get("role_satisfaction", null), 1)))
	body.add_child(_value_line("Expected role", _pretty(_display(morale.get("expected_role", null), "Unknown"))))
	body.add_child(_value_line("Recent minutes", _number(morale.get("recent_minutes", null), 1)))
	body.add_child(_value_line("Trade request risk", _pct(morale.get("trade_request_risk", null))))

	var reasons = _array(morale.get("reasons"))
	if reasons.is_empty():
		var message = "Morale has not been evaluated for this player." if status == "Not evaluated" else "No active morale concerns."
		body.add_child(_label(message, 9, MUTED))
	else:
		for reason in reasons.slice(0, 3):
			var reason_label = _label("• " + str(reason), 9, MUTED)
			reason_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
			body.add_child(reason_label)
	return card


func _development_card() -> Control:
	var card = _detail_card_shell("DEVELOPMENT + TRAJECTORY", ACCENT)
	var body = card.get_meta("body") as VBoxContainer

	body.add_child(_value_line("Overall", _number(player.get("overall", null), 1)))
	body.add_child(_value_line("Potential", _number(player.get("potential", null), 1)))
	body.add_child(_value_line("Future outlook", _number(player.get("future_outlook", null), 1)))
	body.add_child(_value_line("Direction", _pretty(_display(player.get("development_direction", null), "Unknown"))))
	body.add_child(_value_line("Age", _number(player.get("age", null), 1)))

	var overall = player.get("overall", null)
	var potential = player.get("potential", null)
	if overall != null and potential != null:
		var runway = maxf(0.0, float(potential) - float(overall))
		body.add_child(_progress("DEVELOPMENT RUNWAY", runway, 20.0, GOOD if runway >= 5.0 else ACCENT))
	return card


func _stat_tile(label_text: String, value) -> Control:
	var tile = PanelContainer.new()
	tile.name = "ProfileStat" + label_text
	tile.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	tile.add_theme_stylebox_override("panel", _box(Color(PANEL, 0.92), Color(BORDER, 0.80), 9))

	var margin = MarginContainer.new()
	_set_margins(margin, 8, 7, 8, 7)
	tile.add_child(margin)

	var column = VBoxContainer.new()
	column.add_theme_constant_override("separation", 2)
	margin.add_child(column)
	column.add_child(_label(label_text, 8, MUTED))
	column.add_child(_label(_number(value, 1), 22, TEXT))
	return tile


func _skill_bar(label_text: String, value) -> Control:
	var column = VBoxContainer.new()
	column.add_theme_constant_override("separation", 2)

	var row = HBoxContainer.new()
	column.add_child(row)
	var label = _label(label_text, 9, MUTED)
	label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row.add_child(label)
	row.add_child(_label(_number(value, 1), 10, _rating_tone(value)))

	var bar = ProgressBar.new()
	bar.name = "ProfileSkill" + label_text
	bar.custom_minimum_size = Vector2(0, 7)
	bar.min_value = 0
	bar.max_value = 100
	bar.value = clampf(float(value), 0.0, 100.0)
	bar.show_percentage = false
	bar.add_theme_stylebox_override("background", _box(Color(PANEL, 0.95), PANEL, 4))
	bar.add_theme_stylebox_override("fill", _box(_rating_tone(value), _rating_tone(value), 4))
	column.add_child(bar)
	return column


func _hero_rating(label_text: String, value, emphasized: bool) -> Control:
	var tone = _rating_tone(value)
	var card = PanelContainer.new()
	card.name = "ProfileOverallHero" if label_text == "OVR" else "ProfilePotentialHero"
	card.custom_minimum_size = Vector2(102, 118 if emphasized else 102)
	card.add_theme_stylebox_override("panel", _box(Color(tone, 0.13), Color(tone, 0.62), 14))

	var margin = MarginContainer.new()
	_set_margins(margin, 10, 10, 10, 10)
	card.add_child(margin)

	var column = VBoxContainer.new()
	column.alignment = BoxContainer.ALIGNMENT_CENTER
	margin.add_child(column)
	var heading = _label(label_text, 9, MUTED)
	heading.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	column.add_child(heading)
	var number = _label(_number(value, 1), 42 if emphasized else 34, tone)
	number.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	column.add_child(number)
	return card


func _hero_future_tile(value) -> Control:
	var card = PanelContainer.new()
	card.add_theme_stylebox_override("panel", _box(Color(PANEL_ALT, 0.82), Color(ACCENT, 0.36), 10))
	var margin = MarginContainer.new()
	_set_margins(margin, 10, 7, 10, 7)
	card.add_child(margin)
	var row = HBoxContainer.new()
	margin.add_child(row)
	var label = _label("FUTURE OUTLOOK", 8, MUTED)
	label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row.add_child(label)
	row.add_child(_label(_number(value, 1), 14, ACCENT))
	return card


func _detail_card_shell(title_text: String, tone: Color) -> PanelContainer:
	var card = PanelContainer.new()
	card.custom_minimum_size = Vector2(0, 220)
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	card.add_theme_stylebox_override("panel", _box(PANEL_ALT, Color(tone, 0.34), 13))

	var margin = MarginContainer.new()
	_set_margins(margin, 12, 10, 12, 10)
	card.add_child(margin)

	var body = VBoxContainer.new()
	body.add_theme_constant_override("separation", 6)
	margin.add_child(body)

	var bar = ColorRect.new()
	bar.custom_minimum_size = Vector2(0, 3)
	bar.color = tone
	bar.mouse_filter = Control.MOUSE_FILTER_IGNORE
	body.add_child(bar)
	body.add_child(_label(title_text, 9, tone))
	card.set_meta("body", body)
	return card


func _value_line(label_text: String, value_text: String) -> Label:
	var label = _label("%s   %s" % [label_text, value_text], 10, TEXT)
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	return label


func _progress(label_text: String, value: float, maximum: float, tone: Color) -> Control:
	var column = VBoxContainer.new()
	column.add_theme_constant_override("separation", 2)
	column.add_child(_label(label_text, 8, MUTED))

	var bar = ProgressBar.new()
	bar.custom_minimum_size = Vector2(0, 7)
	bar.min_value = 0.0
	bar.max_value = maximum
	bar.value = clampf(value, 0.0, maximum)
	bar.show_percentage = false
	bar.add_theme_stylebox_override("background", _box(PANEL, PANEL, 4))
	bar.add_theme_stylebox_override("fill", _box(tone, tone, 4))
	column.add_child(bar)
	return column


func _pill(text_value: String, tone: Color) -> Control:
	var panel = PanelContainer.new()
	panel.add_theme_stylebox_override("panel", _box(Color(tone, 0.13), Color(tone, 0.45), 9))
	var label = _label(text_value.to_upper(), 8, tone)
	label.custom_minimum_size = Vector2(0, 24)
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	panel.add_child(label)
	return panel


func _player_team() -> String:
	var team = _display(player.get("team", null), active_team).to_upper()
	return active_team if team == "" else team


func _rating_tone(value) -> Color:
	if value == null:
		return MUTED
	var rating = float(value)
	if rating >= 90.0:
		return GOLD
	if rating >= 85.0:
		return GOOD
	if rating >= 80.0:
		return ACCENT
	if rating >= 75.0:
		return _hover(primary)
	return MUTED


func _morale_tone(status: String) -> Color:
	if status in ["Happy", "Thriving", "Content"]:
		return GOOD
	if status in ["Frustrated", "Angry", "Demanding Trade"]:
		return BAD
	return MUTED


func _display(value, fallback: String = "N/A") -> String:
	if value == null:
		return fallback
	var text = str(value).strip_edges()
	if text == "" or text == "<null>" or text == "null":
		return fallback
	return text


func _number(value, decimals: int) -> String:
	if value == null:
		return "N/A"
	if decimals <= 0:
		return str(int(round(float(value))))
	return "%.1f" % float(value)


func _pct(value) -> String:
	if value == null:
		return "N/A"
	return "%.1f%%" % float(value)


func _ratio_pct(value) -> String:
	if value == null:
		return "N/A"
	return "%.1f%%" % (float(value) * 100.0)


func _pretty(value: String) -> String:
	if value == "" or value == "N/A":
		return value
	return value.replace("_", " ").capitalize()


func _hover(color: Color) -> Color:
	return color.lightened(0.20)


func _label(text_value: String, size: int, color: Color) -> Label:
	var label = Label.new()
	label.text = text_value
	label.add_theme_font_size_override("font_size", size)
	label.add_theme_color_override("font_color", color)
	return label


func _box(fill: Color, border: Color, radius: int) -> StyleBoxFlat:
	var style = StyleBoxFlat.new()
	style.bg_color = fill
	style.border_color = border
	style.set_border_width_all(1)
	style.corner_radius_top_left = radius
	style.corner_radius_top_right = radius
	style.corner_radius_bottom_left = radius
	style.corner_radius_bottom_right = radius
	return style


func _set_margins(container: MarginContainer, left: int, top: int, right: int, bottom: int) -> void:
	container.add_theme_constant_override("margin_left", left)
	container.add_theme_constant_override("margin_top", top)
	container.add_theme_constant_override("margin_right", right)
	container.add_theme_constant_override("margin_bottom", bottom)


func _dict(value) -> Dictionary:
	return value if typeof(value) == TYPE_DICTIONARY else {}


func _array(value) -> Array:
	return value if typeof(value) == TYPE_ARRAY else []


func _clear_children(node: Node) -> void:
	for child in node.get_children():
		node.remove_child(child)
		child.queue_free()


func _on_close_pressed() -> void:
	close_requested.emit()
