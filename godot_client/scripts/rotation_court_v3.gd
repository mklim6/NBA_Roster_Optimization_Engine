extends Control

signal player_selected(player: Dictionary)

const DesignSystemV3 = preload("res://scripts/design_system_v3.gd")
const PlayerPortraitV3 = preload("res://scripts/player_portrait_v3.gd")

const PANEL_ALT = DesignSystemV3.PANEL_ALT
const TEXT = DesignSystemV3.TEXT
const MUTED = DesignSystemV3.MUTED
const ACCENT = DesignSystemV3.ACCENT
const GOOD = DesignSystemV3.GOOD
const GOLD = DesignSystemV3.GOLD
const BORDER = DesignSystemV3.BORDER

const SLOT_ORDER = ["PG", "SG", "SF", "PF", "C"]
const SLOT_POINTS = {
	"PG": Vector2(0.50, 0.82),
	"SG": Vector2(0.16, 0.58),
	"SF": Vector2(0.84, 0.58),
	"PF": Vector2(0.34, 0.23),
	"C": Vector2(0.66, 0.23),
}

var primary = DesignSystemV3.TEAM_PRIMARY
var secondary = DesignSystemV3.GOLD
var player_cards: Array = []
var current_players: Array = []


func _ready() -> void:
	if name == "":
		name = "RotationCourtV3"
	custom_minimum_size = Vector2(700, 540)
	size_flags_horizontal = Control.SIZE_EXPAND_FILL
	mouse_filter = Control.MOUSE_FILTER_PASS
	clip_contents = true
	resized.connect(_layout_player_cards)
	queue_redraw()


func configure(players: Array, primary_color: Color, secondary_color: Color) -> void:
	current_players = players
	primary = primary_color
	secondary = secondary_color
	_clear_player_cards()

	var starters = _starting_five(players)
	for slot in SLOT_ORDER:
		var player: Dictionary = starters.get(slot, {})
		if player.is_empty():
			continue
		_create_player_card(slot, player)

	queue_redraw()
	call_deferred("_layout_player_cards")


func _draw() -> void:
	var width = size.x
	var height = size.y
	if width <= 10.0 or height <= 10.0:
		return

	var court_fill = Color(primary, 0.065)
	var line = Color(1, 1, 1, 0.18)
	var bright = Color(secondary, 0.32)
	var edge = Color(primary, 0.48)

	draw_rect(Rect2(Vector2.ZERO, size), Color("0b1118"), true)
	draw_rect(Rect2(12, 12, width - 24, height - 24), court_fill, true)
	draw_rect(Rect2(12, 12, width - 24, height - 24), edge, false, 2.0)

	var hoop = Vector2(width * 0.5, 40.0)
	draw_line(Vector2(width * 0.44, 27), Vector2(width * 0.56, 27), line, 3.0)
	draw_arc(hoop, 7.0, 0.0, TAU, 32, bright, 2.0, true)

	var lane_width = min(width * 0.30, 230.0)
	var lane = Rect2(
		Vector2(width * 0.5 - lane_width * 0.5, 12),
		Vector2(lane_width, height * 0.34)
	)
	draw_rect(lane, line, false, 2.0)

	var ft_center = Vector2(width * 0.5, lane.position.y + lane.size.y)
	draw_arc(ft_center, lane_width * 0.25, 0.0, TAU, 48, line, 2.0, true)

	var arc_radius = min(width * 0.39, 255.0)
	draw_arc(hoop, arc_radius, 0.18, PI - 0.18, 64, line, 2.0, true)
	draw_line(Vector2(12, height * 0.50), Vector2(width - 12, height * 0.50), Color(line, 0.55), 1.0)

	var center = Vector2(width * 0.5, height - 12)
	draw_arc(center, min(width * 0.12, 78.0), PI, TAU, 40, Color(line, 0.65), 1.5, true)


func _starting_five(players: Array) -> Dictionary:
	var candidates: Array = []
	for raw in players:
		if typeof(raw) != TYPE_DICTIONARY:
			continue
		var player: Dictionary = raw
		if bool(player.get("is_starter", false)):
			candidates.append(player)

	if candidates.size() < 5:
		for raw in players:
			if candidates.size() >= 5:
				break
			if typeof(raw) != TYPE_DICTIONARY:
				continue
			var player: Dictionary = raw
			if not bool(player.get("in_rotation", false)):
				continue
			if _contains_player(candidates, str(player.get("player_id", ""))):
				continue
			candidates.append(player)

	var assigned = {}
	var used = {}

	for slot in SLOT_ORDER:
		for player in candidates:
			var player_id = str(player.get("player_id", ""))
			if used.has(player_id):
				continue
			if _primary_position(player) == slot:
				assigned[slot] = player
				used[player_id] = true
				break

	for slot in SLOT_ORDER:
		if assigned.has(slot):
			continue
		for player in candidates:
			var player_id = str(player.get("player_id", ""))
			if used.has(player_id):
				continue
			if _position_includes(player, slot):
				assigned[slot] = player
				used[player_id] = true
				break

	for slot in SLOT_ORDER:
		if assigned.has(slot):
			continue
		for player in candidates:
			var player_id = str(player.get("player_id", ""))
			if used.has(player_id):
				continue
			assigned[slot] = player
			used[player_id] = true
			break

	return assigned


func _create_player_card(slot: String, player: Dictionary) -> void:
	var card = PanelContainer.new()
	card.name = "CourtPlayer_" + slot
	card.custom_minimum_size = Vector2(184, 174)
	card.size = Vector2(184, 174)
	card.mouse_filter = Control.MOUSE_FILTER_STOP
	card.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	card.tooltip_text = "Open %s" % str(player.get("name", "player"))
	var tone = GOLD if bool(player.get("is_starter", false)) else ACCENT
	card.add_theme_stylebox_override("panel", _box(Color(PANEL_ALT, 0.98), Color(tone, 0.70), 12))
	card.gui_input.connect(_on_player_card_input.bind(player))
	add_child(card)

	var margin = MarginContainer.new()
	margin.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_set_margins(margin, 7, 7, 7, 7)
	card.add_child(margin)

	var row = VBoxContainer.new()
	row.mouse_filter = Control.MOUSE_FILTER_IGNORE
	row.add_theme_constant_override("separation", 6)
	margin.add_child(row)

	var portrait = PlayerPortraitV3.new()
	portrait.name = "CourtPortrait_" + slot
	portrait.custom_minimum_size = Vector2(160, 102)
	row.add_child(portrait)
	portrait.configure(player)

	var copy = VBoxContainer.new()
	copy.mouse_filter = Control.MOUSE_FILTER_IGNORE
	copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	copy.alignment = BoxContainer.ALIGNMENT_CENTER
	copy.add_theme_constant_override("separation", 1)
	row.add_child(copy)

	var slot_label = Label.new()
	slot_label.text = slot
	slot_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	slot_label.add_theme_color_override("font_color", tone)
	slot_label.add_theme_font_size_override("font_size", 10)
	copy.add_child(slot_label)

	var name_label = Label.new()
	name_label.text = str(player.get("name", "Unknown"))
	name_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	name_label.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	name_label.add_theme_color_override("font_color", TEXT)
	name_label.add_theme_font_size_override("font_size", 13)
	copy.add_child(name_label)

	var meta = Label.new()
	meta.text = "OVR %s • %s MIN" % [
		_rating_text(player.get("overall", null)),
		_number_text(player.get("target_minutes", 0), 0),
	]
	meta.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	meta.add_theme_color_override("font_color", MUTED)
	meta.add_theme_font_size_override("font_size", 10)
	copy.add_child(meta)

	player_cards.append({"node": card, "slot": slot, "player": player})


func _layout_player_cards() -> void:
	if player_cards.is_empty():
		return
	for entry in player_cards:
		var card = entry.get("node")
		if card == null or not is_instance_valid(card):
			continue
		var slot = str(entry.get("slot", "PG"))
		var normalized: Vector2 = SLOT_POINTS.get(slot, Vector2(0.5, 0.5))
		var target = Vector2(size.x * normalized.x, size.y * normalized.y)
		card.position = target - card.size * 0.5


func _on_player_card_input(event: InputEvent, player: Dictionary) -> void:
	if event is InputEventMouseButton:
		var mouse_event = event as InputEventMouseButton
		if mouse_event.button_index == MOUSE_BUTTON_LEFT and mouse_event.pressed:
			player_selected.emit(player)


func _clear_player_cards() -> void:
	for entry in player_cards:
		var card = entry.get("node")
		if card != null and is_instance_valid(card):
			card.queue_free()
	player_cards.clear()


func _primary_position(player: Dictionary) -> String:
	var raw = str(player.get("position", "")).strip_edges().to_upper()
	if raw == "":
		return ""
	var pieces = raw.split("/", false)
	return str(pieces[0]).strip_edges()


func _position_includes(player: Dictionary, slot: String) -> bool:
	var raw = str(player.get("position", "")).strip_edges().to_upper()
	for piece in raw.split("/", false):
		if str(piece).strip_edges() == slot:
			return true
	return false


func _contains_player(rows: Array, player_id: String) -> bool:
	for row in rows:
		if typeof(row) == TYPE_DICTIONARY and str(row.get("player_id", "")) == player_id:
			return true
	return false


func _rating_text(value) -> String:
	if value == null:
		return "--"
	return "%.0f" % float(value)


func _number_text(value, decimals: int) -> String:
	if value == null:
		return "--"
	if decimals <= 0:
		return str(int(round(float(value))))
	return "%.1f" % float(value)


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
