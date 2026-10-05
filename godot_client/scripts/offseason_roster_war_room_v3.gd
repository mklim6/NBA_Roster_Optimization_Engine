extends VBoxContainer

const DS = preload("res://scripts/design_system_v3.gd")
const Portrait = preload("res://scripts/player_portrait_v3.gd")

signal destination_requested(page_name: String)

var brand_color = DS.TEAM_PRIMARY
var metrics_grid: GridContainer
var coverage_row: HBoxContainer
var young_grid: GridContainer
var battle_rows: VBoxContainer
var grade_label: Label
var grade_detail: Label


func _ready() -> void:
	_ensure_ui()


func configure(
	roster: Dictionary,
	camp: Dictionary,
	young_core: Array,
	roster_battles: Array,
	primary: Color
) -> void:
	brand_color = primary
	_ensure_ui()
	_render_metrics(roster, camp)
	_render_coverage(camp)
	_render_young_core(young_core)
	_render_battles(roster_battles)
	_render_grade(camp)


func apply_team_brand(primary: Color) -> void:
	brand_color = primary


func _ensure_ui() -> void:
	if metrics_grid != null:
		return

	name = "OffseasonRosterWarRoom"
	size_flags_horizontal = Control.SIZE_EXPAND_FILL
	add_theme_constant_override("separation", 12)

	var header = HBoxContainer.new()
	header.add_theme_constant_override("separation", 10)
	add_child(header)

	var titles = VBoxContainer.new()
	titles.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	header.add_child(titles)
	titles.add_child(_label("ROSTER CONSTRUCTION • CAMP PLANNING", 9, DS.ACCENT))
	titles.add_child(_label("OPENING-NIGHT WAR ROOM", 20, DS.TEXT))
	titles.add_child(_label(
		"Build the 14–15 player standard roster, use two-way capacity, protect position depth, and identify camp competition.",
		9,
		DS.MUTED
	))

	var roster_button = _action_button("OPEN ROSTER")
	roster_button.pressed.connect(_emit_destination.bind("ROSTER"))
	header.add_child(roster_button)

	metrics_grid = GridContainer.new()
	metrics_grid.columns = 5
	metrics_grid.add_theme_constant_override("h_separation", 8)
	metrics_grid.add_theme_constant_override("v_separation", 8)
	add_child(metrics_grid)

	var coverage_card = _card(Color("101821"), Color(DS.BORDER, 0.78), 13)
	var coverage_body = _body(coverage_card, 13)
	coverage_body.add_child(_label("POSITION COVERAGE", 9, DS.ACCENT))
	coverage_row = HBoxContainer.new()
	coverage_row.add_theme_constant_override("separation", 8)
	coverage_body.add_child(coverage_row)
	add_child(coverage_card)

	var grade_card = _card(Color("101821"), Color(DS.GOLD, 0.28), 13)
	var grade_body = _body(grade_card, 13)
	var grade_header = HBoxContainer.new()
	grade_body.add_child(grade_header)

	var grade_copy = VBoxContainer.new()
	grade_copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	grade_header.add_child(grade_copy)
	grade_copy.add_child(_label("TRAINING CAMP READINESS MODEL", 9, DS.GOLD))
	grade_label = _label("LOADING...", 18, DS.TEXT)
	grade_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	grade_copy.add_child(grade_label)
	grade_detail = _label("", 9, DS.MUTED)
	grade_detail.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	grade_copy.add_child(grade_detail)
	add_child(grade_card)

	var young_card = _card(DS.PANEL, Color(brand_color, 0.30), 14)
	var young_body = _body(young_card, 14)
	young_body.add_child(_label("SUMMER DEVELOPMENT BOARD", 17, DS.TEXT))
	young_body.add_child(_label(
		"Young-core priorities are derived from age, current rating, potential, future outlook, and growth runway. This is a planning board, not a ratings-change event.",
		9,
		DS.MUTED
	))
	young_grid = GridContainer.new()
	young_grid.columns = 3
	young_grid.add_theme_constant_override("h_separation", 8)
	young_grid.add_theme_constant_override("v_separation", 8)
	young_body.add_child(young_grid)
	add_child(young_card)

	var battle_card = _card(DS.PANEL, Color(DS.BAD, 0.22), 14)
	var battle_body = _body(battle_card, 14)
	battle_body.add_child(_label("TRAINING CAMP • ROSTER BATTLES", 17, DS.TEXT))
	battle_body.add_child(_label(
		"Players nearest the roster bubble are surfaced from current rating, contract term, and guarantee information. No cut is executed from this screen.",
		9,
		DS.MUTED
	))
	battle_rows = VBoxContainer.new()
	battle_rows.add_theme_constant_override("separation", 7)
	battle_body.add_child(battle_rows)
	add_child(battle_card)


func _render_metrics(roster: Dictionary, camp: Dictionary) -> void:
	_clear(metrics_grid)
	_metric(
		metrics_grid,
		"STANDARD ROSTER",
		"%s / %s" % [
			str(roster.get("standard_count", 0)),
			str(roster.get("standard_target", 15))
		],
		DS.TEXT
	)
	_metric(
		metrics_grid,
		"TWO-WAY",
		"%s / %s" % [
			str(roster.get("two_way_count", 0)),
			str(roster.get("two_way_target", 3))
		],
		DS.ACCENT
	)
	_metric(
		metrics_grid,
		"ROTATION",
		"%s PLAYERS" % str(roster.get("rotation_count", 0)),
		brand_color.lightened(0.38)
	)
	_metric(
		metrics_grid,
		"STARTERS",
		"%s / 5" % str(roster.get("starter_count", 0)),
		DS.GOOD
	)
	_metric(
		metrics_grid,
		"READINESS",
		"%s • %s" % [
			str(camp.get("grade", "—")),
			str(camp.get("score", 0))
		],
		DS.GOLD
	)


func _render_coverage(camp: Dictionary) -> void:
	_clear(coverage_row)
	var counts = _dict(camp.get("position_counts"))
	for position in ["PG", "SG", "SF", "PF", "C"]:
		var count = int(counts.get(position, 0))
		var tone = DS.GOOD if count >= 2 else (DS.GOLD if count == 1 else DS.BAD)
		var tile = _card(Color(tone, 0.06), Color(tone, 0.28), 9)
		tile.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		var body = _body(tile, 9)
		body.add_child(_label(position, 8, tone))
		body.add_child(_label(str(count), 18, DS.TEXT))
		body.add_child(_label(
			"DEPTH READY" if count >= 2 else ("ONE DEEP" if count == 1 else "OPEN NEED"),
			8,
			DS.MUTED
		))
		coverage_row.add_child(tile)


func _render_young_core(rows: Array) -> void:
	_clear(young_grid)
	if rows.is_empty():
		young_grid.add_child(_empty("No age-24-or-younger player is available in the current roster snapshot."))
		return

	for raw in rows.slice(0, 8):
		if typeof(raw) != TYPE_DICTIONARY:
			continue
		var row: Dictionary = raw
		var card = _card(Color("0f1820"), Color(brand_color, 0.25), 11)
		card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		card.custom_minimum_size = Vector2(0, 168)
		var body = _body(card, 10)

		var top = HBoxContainer.new()
		top.add_theme_constant_override("separation", 8)
		body.add_child(top)

		var portrait = Portrait.new()
		portrait.custom_minimum_size = Vector2(70, 68)
		portrait.configure({
			"player_id": row.get("player_id", ""),
			"name": row.get("name", "")
		})
		top.add_child(portrait)

		var copy = VBoxContainer.new()
		copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		top.add_child(copy)
		copy.add_child(_label(str(row.get("name", "")), 12, DS.TEXT))
		copy.add_child(_label(
			"%s • AGE %s" % [
				str(row.get("position", "")),
				str(row.get("age", "—"))
			],
			8,
			DS.MUTED
		))
		copy.add_child(_label(
			"PRIORITY %.1f" % float(row.get("development_priority_score", 0.0)),
			8,
			brand_color.lightened(0.42)
		))

		body.add_child(_label(
			"OVR %s • POT %s • FUT %s" % [
				_display(row.get("overall")),
				_display(row.get("potential")),
				_display(row.get("future_outlook"))
			],
			9,
			DS.TEXT
		))
		var development_note = _label(
			"GROWTH RUNWAY +%s • %s" % [
				str(row.get("growth_gap", 0)),
				str(row.get("development_direction", "Stable")).to_upper()
			],
			8,
			DS.MUTED
		)
		development_note.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		development_note.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
		body.add_child(development_note)
		young_grid.add_child(card)


func _render_battles(rows: Array) -> void:
	_clear(battle_rows)
	if rows.is_empty():
		battle_rows.add_child(_empty("No standard-roster camp competition could be derived."))
		return

	for raw in rows.slice(0, 8):
		if typeof(raw) != TYPE_DICTIONARY:
			continue
		var row: Dictionary = raw
		var tier = str(row.get("competition_tier", "CORE"))
		var tone = _battle_color(tier)

		var line = PanelContainer.new()
		line.add_theme_stylebox_override(
			"panel",
			_box(Color(tone, 0.04), 9, Color(tone, 0.18))
		)
		var margin = MarginContainer.new()
		_set_margins(margin, 10, 8, 10, 8)
		line.add_child(margin)

		var hbox = HBoxContainer.new()
		hbox.add_theme_constant_override("separation", 10)
		margin.add_child(hbox)

		var name = _label(str(row.get("name", "")), 10, DS.TEXT)
		name.custom_minimum_size = Vector2(190, 0)
		name.size_flags_horizontal = Control.SIZE_SHRINK_BEGIN
		hbox.add_child(name)

		var profile = _label(
			"%s • AGE %s • OVR %s" % [
				str(row.get("position", "")),
				str(row.get("age", "—")),
				_display(row.get("overall"))
			],
			8,
			DS.MUTED
		)
		profile.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		hbox.add_child(profile)

		hbox.add_child(_pill(tier, tone))

		var reason = _label(str(row.get("reason", "")), 8, DS.MUTED)
		reason.custom_minimum_size = Vector2(230, 0)
		reason.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
		hbox.add_child(reason)

		battle_rows.add_child(line)


func _render_grade(camp: Dictionary) -> void:
	var grade = str(camp.get("grade", "—"))
	var score = int(camp.get("score", 0))
	var label = str(camp.get("label", "READINESS UNKNOWN"))
	grade_label.text = "%s • %s/100 • %s" % [grade, str(score), label]
	grade_detail.text = str(camp.get("model_note", ""))
	var tone = (
		DS.GOOD
		if score >= 80
		else (DS.GOLD if score >= 65 else DS.BAD)
	)
	grade_label.add_theme_color_override("font_color", tone)


func _battle_color(tier: String) -> Color:
	match tier:
		"CUT WATCH":
			return DS.BAD
		"NON-GUARANTEED":
			return DS.GOLD
		"BUBBLE":
			return Color("d7a759")
		_:
			return DS.GOOD


func _metric(parent: GridContainer, title_text: String, value_text: String, tone: Color) -> void:
	var card = _card(Color(tone, 0.05), Color(tone, 0.24), 10)
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var body = _body(card, 9)
	body.add_child(_label(title_text, 8, tone))
	body.add_child(_label(value_text, 15, DS.TEXT))
	parent.add_child(card)


func _action_button(text_value: String) -> Button:
	var button = Button.new()
	button.text = text_value
	button.custom_minimum_size = Vector2(132, 38)
	button.add_theme_font_size_override("font_size", 9)
	button.add_theme_color_override("font_color", DS.TEXT)
	button.add_theme_stylebox_override(
		"normal",
		_box(Color("121a24"), 8, Color(DS.BORDER, 0.82))
	)
	button.add_theme_stylebox_override(
		"hover",
		_box(Color(brand_color, 0.10), 8, Color(brand_color, 0.62))
	)
	return button


func _emit_destination(page_name: String) -> void:
	destination_requested.emit(page_name)


func _empty(text_value: String) -> Control:
	var panel = _card(Color("101821"), Color(DS.BORDER, 0.70), 9)
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var body = _body(panel, 10)
	var label = _label(text_value, 9, DS.MUTED)
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	body.add_child(label)
	return panel


func _pill(text_value: String, tone: Color) -> Label:
	var label = _label("  %s  " % text_value, 8, tone)
	label.autowrap_mode = TextServer.AUTOWRAP_OFF
	label.size_flags_horizontal = Control.SIZE_SHRINK_BEGIN
	label.add_theme_stylebox_override(
		"normal",
		_box(Color(tone, 0.07), 7, Color(tone, 0.28))
	)
	return label


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


func _label(text_value: String, font_size: int, color: Color) -> Label:
	var label = Label.new()
	label.text = text_value
	label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	label.add_theme_font_size_override("font_size", font_size)
	label.add_theme_color_override("font_color", color)
	return label


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


func _set_margins(container: MarginContainer, left: int, top: int, right: int, bottom: int) -> void:
	container.add_theme_constant_override("margin_left", left)
	container.add_theme_constant_override("margin_top", top)
	container.add_theme_constant_override("margin_right", right)
	container.add_theme_constant_override("margin_bottom", bottom)


func _dict(value) -> Dictionary:
	return value if typeof(value) == TYPE_DICTIONARY else {}


func _display(value) -> String:
	return "—" if value == null or str(value).strip_edges() == "" else str(value)


func _clear(node: Node) -> void:
	for child in node.get_children():
		node.remove_child(child)
		child.queue_free()
