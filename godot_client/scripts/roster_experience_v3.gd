extends VBoxContainer

signal player_selected(player: Dictionary)
signal edit_rotation_requested

const DesignSystemV3 = preload("res://scripts/design_system_v3.gd")
const TeamLogoV3 = preload("res://scripts/team_logo_v3.gd")
const PlayerPortraitV3 = preload("res://scripts/player_portrait_v3.gd")
const RotationCourtV3 = preload("res://scripts/rotation_court_v3.gd")

const PANEL = DesignSystemV3.PANEL
const PANEL_ALT = DesignSystemV3.PANEL_ALT
const TEXT = DesignSystemV3.TEXT
const MUTED = DesignSystemV3.MUTED
const ACCENT = DesignSystemV3.ACCENT
const GOOD = DesignSystemV3.GOOD
const GOLD = DesignSystemV3.GOLD
const BORDER = DesignSystemV3.BORDER

const POSITION_ORDER = ["PG", "SG", "SF", "PF", "C"]

var active_team = ""
var primary = DesignSystemV3.TEAM_PRIMARY
var secondary = DesignSystemV3.GOLD
var court = null


func _ready() -> void:
	name = "RosterExperienceShowcase"
	custom_minimum_size = Vector2(0, 430)
	size_flags_horizontal = Control.SIZE_EXPAND_FILL
	add_theme_constant_override("separation", 8)

	var placeholder = _card(PANEL, BORDER, 16)
	placeholder.custom_minimum_size = Vector2(0, 410)
	add_child(placeholder)
	var body = _body(placeholder, 18)
	body.add_child(_label("ROTATION MAP", 11, ACCENT))
	body.add_child(_label("Loading the active roster and starting five...", 15, MUTED))


func configure(
	payload: Dictionary,
	team_abbreviation: String,
	primary_color: Color,
	secondary_color: Color
) -> void:
	active_team = team_abbreviation.strip_edges().to_upper()
	primary = primary_color
	secondary = secondary_color
	_clear_children(self)

	var players = _array(payload.get("players"))
	var team = _dict(payload.get("team"))

	_build_header(team, players)

	var main_row = HBoxContainer.new()
	main_row.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	main_row.add_theme_constant_override("separation", 12)
	add_child(main_row)

	var court_card = _card(Color(primary, 0.08), Color(primary, 0.52), 16)
	court_card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	court_card.custom_minimum_size = Vector2(0, 560)
	main_row.add_child(court_card)

	var court_margin = MarginContainer.new()
	_set_margins(court_margin, 10, 10, 10, 10)
	court_card.add_child(court_margin)

	court = RotationCourtV3.new()
	court.custom_minimum_size = Vector2(640, 540)
	court_margin.add_child(court)
	court.player_selected.connect(_on_player_selected)
	court.configure(players, primary, secondary)

	var depth = _build_depth_chart(players)
	depth.custom_minimum_size = Vector2(320, 350)
	main_row.add_child(depth)


func _build_header(team: Dictionary, players: Array) -> void:
	var card = _card(Color(primary, 0.10), Color(primary, 0.58), 15)
	card.custom_minimum_size = Vector2(0, 68)
	add_child(card)

	var margin = MarginContainer.new()
	_set_margins(margin, 12, 8, 12, 8)
	card.add_child(margin)

	var row = HBoxContainer.new()
	row.add_theme_constant_override("separation", 10)
	margin.add_child(row)

	var logo = TeamLogoV3.new()
	logo.custom_minimum_size = Vector2(60, 52)
	logo.configure(active_team)
	row.add_child(logo)

	var copy = VBoxContainer.new()
	copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	copy.alignment = BoxContainer.ALIGNMENT_CENTER
	copy.add_theme_constant_override("separation", 1)
	row.add_child(copy)
	copy.add_child(_label("ROTATION MAP", 9, _hover(primary)))

	var title = _label(
		"%s STARTING FIVE" % str(team.get("name", active_team)).to_upper(),
		16,
		TEXT
	)
	title.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	copy.add_child(title)

	var minutes = 0.0
	var rotation_count = 0
	for raw in players:
		if typeof(raw) != TYPE_DICTIONARY:
			continue
		var player: Dictionary = raw
		if bool(player.get("in_rotation", false)):
			rotation_count += 1
			minutes += float(player.get("target_minutes", 0.0))

	var context = _label(
		"%s STARTERS • %s ROTATION • %.0f TARGET MINUTES" % [
			str(team.get("starters", 0)),
			str(rotation_count),
			minutes,
		],
		9,
		MUTED
	)
	copy.add_child(context)

	var edit = Button.new()
	edit.text = "EDIT ROTATION"
	edit.custom_minimum_size = Vector2(138, 38)
	edit.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	edit.add_theme_font_size_override("font_size", 10)
	edit.add_theme_color_override("font_color", _foreground(primary))
	edit.add_theme_stylebox_override("normal", _box(primary, _hover(primary), 10))
	edit.add_theme_stylebox_override("hover", _box(_hover(primary), _hover(primary), 10))
	edit.pressed.connect(_on_edit_rotation)
	row.add_child(edit)


func _build_depth_chart(players: Array) -> Control:
	var card = _card(PANEL, Color(ACCENT, 0.38), 16)
	var body = _body(card, 12)
	body.add_child(_label("DEPTH CHART", 11, ACCENT))
	body.add_child(_label("Starter / next option by listed primary position", 8, MUTED))

	for position in POSITION_ORDER:
		body.add_child(_depth_row(position, _players_at_position(players, position)))
	return card


func _depth_row(position: String, players: Array) -> Control:
	var row = PanelContainer.new()
	row.custom_minimum_size = Vector2(0, 76)
	row.add_theme_stylebox_override("panel", _box(Color(PANEL_ALT, 0.82), Color(BORDER, 0.75), 9))

	var margin = MarginContainer.new()
	_set_margins(margin, 7, 4, 7, 4)
	row.add_child(margin)

	var line = HBoxContainer.new()
	line.add_theme_constant_override("separation", 6)
	margin.add_child(line)

	var pos = Label.new()
	pos.text = position
	pos.custom_minimum_size = Vector2(28, 0)
	pos.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	pos.add_theme_color_override("font_color", GOLD)
	pos.add_theme_font_size_override("font_size", 10)
	line.add_child(pos)

	if players.is_empty():
		var empty = _label("No listed option", 9, MUTED)
		empty.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		line.add_child(empty)
		return row

	var starter: Dictionary = players[0]
	var portrait = PlayerPortraitV3.new()
	portrait.name = "DepthPortrait_" + position
	portrait.custom_minimum_size = Vector2(80, 64)
	line.add_child(portrait)
	portrait.configure(starter)

	var names = VBoxContainer.new()
	names.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	names.alignment = BoxContainer.ALIGNMENT_CENTER
	line.add_child(names)

	var first = _label(str(starter.get("name", "Unknown")), 11, TEXT)
	first.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	names.add_child(first)

	var backup_text = "No backup listed"
	if players.size() > 1:
		var backup: Dictionary = players[1]
		backup_text = "Next: %s" % str(backup.get("name", "Unknown"))
	var backup_label = _label(backup_text, 10, MUTED)
	backup_label.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	names.add_child(backup_label)

	var rating = _label(
		"OVR %s" % _rating_text(starter.get("overall", null)),
		9,
		_rating_tone(starter.get("overall", null))
	)
	rating.custom_minimum_size = Vector2(52, 0)
	rating.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	rating.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	line.add_child(rating)
	return row


func _players_at_position(players: Array, position: String) -> Array:
	var result: Array = []

	for starter_pass in [true, false]:
		for raw in players:
			if typeof(raw) != TYPE_DICTIONARY:
				continue
			var player: Dictionary = raw
			if bool(player.get("is_starter", false)) != starter_pass:
				continue
			if _primary_position(player) == position:
				result.append(player)

	for starter_pass in [true, false]:
		for raw in players:
			if typeof(raw) != TYPE_DICTIONARY:
				continue
			var player: Dictionary = raw
			if bool(player.get("is_starter", false)) != starter_pass:
				continue
			if not _position_includes(player, position):
				continue
			if _contains_player(result, str(player.get("player_id", ""))):
				continue
			result.append(player)

	return result


func _contains_player(rows: Array, player_id: String) -> bool:
	for row in rows:
		if typeof(row) == TYPE_DICTIONARY and str(row.get("player_id", "")) == player_id:
			return true
	return false


func _primary_position(player: Dictionary) -> String:
	var raw = str(player.get("position", "")).strip_edges().to_upper()
	if raw == "":
		return ""
	return str(raw.split("/", false)[0]).strip_edges()


func _position_includes(player: Dictionary, position: String) -> bool:
	for piece in str(player.get("position", "")).to_upper().split("/", false):
		if str(piece).strip_edges() == position:
			return true
	return false


func _on_player_selected(player: Dictionary) -> void:
	player_selected.emit(player)


func _on_edit_rotation() -> void:
	edit_rotation_requested.emit()


func _rating_text(value) -> String:
	if value == null:
		return "--"
	return "%.0f" % float(value)


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
	return MUTED


func _foreground(color: Color) -> Color:
	var luma = color.r * 0.299 + color.g * 0.587 + color.b * 0.114
	return Color("071018") if luma > 0.58 else TEXT


func _hover(color: Color) -> Color:
	return color.lightened(0.18) if _foreground(color) == TEXT else color.darkened(0.14)


func _card(fill: Color, border: Color, radius: int) -> PanelContainer:
	var card = PanelContainer.new()
	card.add_theme_stylebox_override("panel", _box(fill, border, radius))
	return card


func _body(card: PanelContainer, margin_size: int) -> VBoxContainer:
	var margin = MarginContainer.new()
	_set_margins(margin, margin_size, margin_size, margin_size, margin_size)
	card.add_child(margin)
	var body = VBoxContainer.new()
	body.add_theme_constant_override("separation", 5)
	margin.add_child(body)
	return body


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
