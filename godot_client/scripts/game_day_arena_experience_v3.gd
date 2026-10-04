extends VBoxContainer

# Batch 36 Game Day arena + starting-five visual overhaul.
# Read-only presentation component. It consumes the existing Game Day + roster payloads.

const DesignSystemV3 = preload("res://scripts/design_system_v3.gd")
const TeamBrandingV3 = preload("res://scripts/team_branding_v3.gd")
const TeamLogoV3 = preload("res://scripts/team_logo_v3.gd")
const PlayerPortraitV3 = preload("res://scripts/player_portrait_v3.gd")

const PANEL = DesignSystemV3.PANEL
const PANEL_ALT = DesignSystemV3.PANEL_ALT
const TEXT = DesignSystemV3.TEXT
const MUTED = DesignSystemV3.MUTED
const ACCENT = DesignSystemV3.ACCENT
const GOOD = DesignSystemV3.GOOD
const GOLD = DesignSystemV3.GOLD
const BAD = DesignSystemV3.BAD
const BORDER = DesignSystemV3.BORDER

var active_team = ""
var active_opponent = ""
var primary = DesignSystemV3.TEAM_PRIMARY
var secondary = DesignSystemV3.GOLD


func _ready() -> void:
	name = "GameDayArenaExperience"
	size_flags_horizontal = Control.SIZE_EXPAND_FILL
	add_theme_constant_override("separation", 12)


func configure(
	game_payload: Dictionary,
	roster_payload: Dictionary,
	team_abbreviation: String,
	opponent_abbreviation: String
) -> void:
	active_team = team_abbreviation.strip_edges().to_upper()
	active_opponent = opponent_abbreviation.strip_edges().to_upper()

	var palette = DesignSystemV3.team_palette(active_team)
	primary = palette.get("primary", DesignSystemV3.TEAM_PRIMARY)
	secondary = palette.get("secondary", DesignSystemV3.GOLD)

	_clear_children(self)
	_build_game_night_strip(game_payload)
	_build_starting_five(roster_payload)
	_build_rotation_pulse(roster_payload)


func _build_game_night_strip(game_payload: Dictionary) -> void:
	var card = _card(Color("0b1118"), Color(primary, 0.50), 16)
	card.name = "ArenaGameNightStrip"
	card.custom_minimum_size = Vector2(0, 112)
	add_child(card)

	var margin = MarginContainer.new()
	_set_margins(margin, 16, 12, 16, 12)
	card.add_child(margin)

	var row = HBoxContainer.new()
	row.add_theme_constant_override("separation", 14)
	margin.add_child(row)

	var copy = VBoxContainer.new()
	copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	copy.alignment = BoxContainer.ALIGNMENT_CENTER
	copy.add_theme_constant_override("separation", 3)
	row.add_child(copy)
	copy.add_child(_label("FRANCHISE NETWORK • GAME NIGHT", 9, TeamBrandingV3.hover_color(primary)))
	copy.add_child(_label("STARTING FIVE + ROTATION CHECK", 21, TEXT))
	copy.add_child(_label("Broadcast matchup above • lineup intelligence below", 9, MUTED))

	var next_game = _dict(game_payload.get("next_game"))
	var display_day = _i(game_payload.get("day_index"), 0)
	var venue = "GAME DAY"
	var matchup = "%s VS %s" % [
		active_team if active_team != "" else "TEAM",
		active_opponent if active_opponent != "" else "TBD",
	]
	if not next_game.is_empty():
		display_day = _i(next_game.get("day_index"), display_day)
		var is_home = bool(next_game.get("is_home", false))
		venue = "HOME" if is_home else "ROAD"
		matchup = "%s %s %s" % [
			active_team if active_team != "" else "TEAM",
			"VS" if is_home else "AT",
			active_opponent if active_opponent != "" else "TBD",
		]

	var matchup_panel = _card(Color(primary, 0.06), Color(primary, 0.34), 12)
	matchup_panel.name = "ArenaCompactMatchup"
	matchup_panel.custom_minimum_size = Vector2(300, 82)
	var matchup_body = _body(matchup_panel, 9)
	var matchup_title = _label(matchup, 18, TEXT)
	matchup_title.name = "ArenaCompactMatchupTitle"
	matchup_title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	matchup_body.add_child(matchup_title)
	var context = _label("%s • DAY %d" % [venue, display_day], 9, GOLD)
	context.name = "ArenaCompactGameContext"
	context.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	matchup_body.add_child(context)
	row.add_child(matchup_panel)


func _build_starting_five(roster_payload: Dictionary) -> void:
	var section = VBoxContainer.new()
	section.name = "ArenaStartingFiveSection"
	section.add_theme_constant_override("separation", 8)
	add_child(section)

	var header = HBoxContainer.new()
	header.add_theme_constant_override("separation", 10)
	section.add_child(header)

	var header_copy = VBoxContainer.new()
	header_copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	header_copy.add_theme_constant_override("separation", 2)
	header.add_child(header_copy)
	header_copy.add_child(_label("YOUR STARTING FIVE", 18, TEXT))
	header_copy.add_child(_label("Faces, roles, ratings, and planned minutes before tip-off.", 10, MUTED))

	var starters = _starting_five(_array(roster_payload.get("players")))
	var availability = 0
	for player in starters:
		if _health_available(_dict(player)):
			availability += 1

	var availability_badge = _badge(
		"%d / 5 AVAILABLE" % availability if starters.size() >= 5 else "LINEUP LOADING",
		GOOD if availability >= 5 else GOLD
	)
	header.add_child(availability_badge)

	var grid = GridContainer.new()
	grid.name = "ArenaStartingFiveGrid"
	grid.columns = 5
	grid.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	grid.add_theme_constant_override("h_separation", 10)
	grid.add_theme_constant_override("v_separation", 10)
	section.add_child(grid)

	if starters.is_empty():
		for index in range(5):
			grid.add_child(_starter_placeholder(index))
		return

	for index in range(5):
		if index < starters.size():
			grid.add_child(_starter_card(_dict(starters[index]), index))
		else:
			grid.add_child(_starter_placeholder(index))


func _build_rotation_pulse(roster_payload: Dictionary) -> void:
	var players = _array(roster_payload.get("players"))
	var starters = _starting_five(players)

	var starter_ovr_total = 0.0
	var starter_ovr_count = 0
	var starter_minutes = 0
	for raw in starters:
		var player = _dict(raw)
		if typeof(player.get("overall")) in [TYPE_INT, TYPE_FLOAT]:
			starter_ovr_total += float(player.get("overall"))
			starter_ovr_count += 1
		starter_minutes += _i(player.get("target_minutes"), 0)

	var rotation_count = 0
	var healthy_rotation = 0
	for raw in players:
		var player = _dict(raw)
		if bool(player.get("in_rotation", false)):
			rotation_count += 1
			if _health_available(player):
				healthy_rotation += 1

	var row = GridContainer.new()
	row.name = "ArenaRotationPulse"
	row.columns = 4
	row.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row.add_theme_constant_override("h_separation", 10)
	add_child(row)

	_metric(row, "STARTER AVG OVR", "%.1f" % (starter_ovr_total / starter_ovr_count) if starter_ovr_count > 0 else "N/A", GOLD)
	_metric(row, "STARTER MINUTES", str(starter_minutes) if starter_minutes > 0 else "N/A", ACCENT)
	_metric(row, "ROTATION", "%d PLAYERS" % rotation_count if rotation_count > 0 else "N/A", GOOD)
	_metric(row, "AVAILABLE", "%d / %d" % [healthy_rotation, rotation_count] if rotation_count > 0 else "N/A", GOOD if healthy_rotation == rotation_count and rotation_count > 0 else GOLD)


func _starter_card(player: Dictionary, index: int) -> Control:
	var tone = _position_tone(_s(player.get("position"), ""))
	var card = _card(PANEL, Color(tone, 0.52), 14)
	card.name = "ArenaStarterCard_%d" % index
	card.custom_minimum_size = Vector2(0, 178)
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL

	var body = _body(card, 10)
	body.add_theme_constant_override("separation", 5)

	var top = HBoxContainer.new()
	top.add_theme_constant_override("separation", 8)
	body.add_child(top)

	var portrait = PlayerPortraitV3.new()
	portrait.name = "ArenaStarterPortrait_%d" % index
	portrait.custom_minimum_size = Vector2(104, 92)
	portrait.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	top.add_child(portrait)
	portrait.configure(player)

	var rating = VBoxContainer.new()
	rating.custom_minimum_size = Vector2(48, 0)
	rating.alignment = BoxContainer.ALIGNMENT_CENTER
	top.add_child(rating)
	var ovr = _label("%.0f" % _f(player.get("overall"), 0.0), 22, tone)
	ovr.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	rating.add_child(ovr)
	var ovr_label = _label("OVR", 8, MUTED)
	ovr_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	rating.add_child(ovr_label)

	var name = _label(_s(player.get("name"), "Unknown"), 13, TEXT)
	name.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	body.add_child(name)

	var meta = _label("%s • %d MIN" % [
		_s(player.get("position"), "--").to_upper(),
		_i(player.get("target_minutes"), 0),
	], 9, MUTED)
	body.add_child(meta)

	var health = _health_display(player)
	var health_label = _label(
		health,
		9,
		GOOD if _health_available(player) else BAD
	)
	body.add_child(health_label)

	return card


func _starter_placeholder(index: int) -> Control:
	var card = _card(PANEL_ALT, Color(BORDER, 0.80), 14)
	card.name = "ArenaStarterCard_%d" % index
	card.custom_minimum_size = Vector2(0, 178)
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL

	var body = _body(card, 12)
	var label = _label("STARTER %d" % (index + 1), 12, MUTED)
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	body.add_child(label)

	var detail = _label("ROSTER DATA PENDING", 9, MUTED)
	detail.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	body.add_child(detail)
	return card


func _starting_five(players: Array) -> Array:
	var starters: Array = []
	for raw in players:
		var player = _dict(raw)
		if bool(player.get("is_starter", false)):
			starters.append(player)

	starters.sort_custom(func(a, b):
		return _position_rank(_s(_dict(a).get("position"), "")) < _position_rank(_s(_dict(b).get("position"), ""))
	)
	return starters.slice(0, 5)


func _position_rank(position: String) -> int:
	var value = position.to_upper()
	if value.begins_with("PG"):
		return 0
	if value.begins_with("SG"):
		return 1
	if value.begins_with("SF"):
		return 2
	if value.begins_with("PF"):
		return 3
	if value.begins_with("C"):
		return 4
	return 5


func _position_tone(position: String) -> Color:
	var value = position.to_upper()
	if value.begins_with("PG"):
		return ACCENT
	if value.begins_with("SG"):
		return Color("53d7a6")
	if value.begins_with("SF"):
		return GOLD
	if value.begins_with("PF"):
		return Color("e29f5b")
	if value.begins_with("C"):
		return Color("c89ef5")
	return TeamBrandingV3.hover_color(primary)


func _health_available(player: Dictionary) -> bool:
	var health = _dict(player.get("health"))
	var status = _s(health.get("status"), _s(player.get("health_status"), "healthy")).to_lower()
	return status not in ["out", "injured", "inactive", "unavailable"]


func _health_display(player: Dictionary) -> String:
	var health = _dict(player.get("health"))
	var display = _s(health.get("display"), "")
	if display != "":
		return display.to_upper()
	var status = _s(health.get("status"), _s(player.get("health_status"), "healthy"))
	return status.replace("_", " ").to_upper()


func _metric(parent: GridContainer, title: String, value: String, tone: Color) -> void:
	var card = _card(PANEL_ALT, Color(tone, 0.28), 12)
	card.custom_minimum_size = Vector2(0, 74)
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var body = _body(card, 9)
	body.add_child(_label(title, 8, tone))
	body.add_child(_label(value, 16, TEXT))
	parent.add_child(card)


func _badge(text_value: String, tone: Color) -> Control:
	var panel = _card(Color(tone, 0.09), Color(tone, 0.48), 10)
	panel.custom_minimum_size = Vector2(150, 48)
	var body = _body(panel, 8)
	var label = _label(text_value, 9, tone)
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	body.add_child(label)
	return panel


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
	body.add_theme_constant_override("separation", 6)
	margin.add_child(body)
	return body


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


func _label(text_value: String, size: int, color: Color) -> Label:
	var label = Label.new()
	label.text = text_value
	label.add_theme_color_override("font_color", color)
	label.add_theme_font_size_override("font_size", size)
	return label


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
	return str(value) if value != null and str(value) != "" else fallback


func _i(value, fallback: int = 0) -> int:
	if typeof(value) in [TYPE_INT, TYPE_FLOAT]:
		return int(value)
	return fallback


func _f(value, fallback: float = 0.0) -> float:
	if typeof(value) in [TYPE_INT, TYPE_FLOAT]:
		return float(value)
	return fallback
