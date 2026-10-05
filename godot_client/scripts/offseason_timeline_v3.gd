extends VBoxContainer

const DS = preload("res://scripts/design_system_v3.gd")
const TeamBrandingV3 = preload("res://scripts/team_branding_v3.gd")

signal destination_requested(page_name: String)

var brand_color = DS.TEAM_PRIMARY
var stage_rows: VBoxContainer
var summary_label: Label
var current_label: Label


func _ready() -> void:
	_ensure_ui()


func configure(stages: Array, primary: Color) -> void:
	brand_color = primary
	_ensure_ui()
	_clear(stage_rows)

	var complete_count = 0
	var current_title = "OFFSEASON PLAN"
	for raw in stages:
		if typeof(raw) != TYPE_DICTIONARY:
			continue
		var stage: Dictionary = raw
		if str(stage.get("status", "")).to_lower() == "complete":
			complete_count += 1
		if bool(stage.get("current_focus", false)):
			current_title = str(stage.get("label", current_title))
		stage_rows.add_child(_stage_card(stage))

	summary_label.text = "%s OF %s MILESTONES COMPLETE" % [
		str(complete_count),
		str(stages.size())
	]
	current_label.text = "CURRENT FOCUS • %s" % current_title


func apply_team_brand(primary: Color) -> void:
	brand_color = primary


func _ensure_ui() -> void:
	if stage_rows != null:
		return

	name = "OffseasonRoadmap"
	size_flags_horizontal = Control.SIZE_EXPAND_FILL
	add_theme_constant_override("separation", 10)

	var header = HBoxContainer.new()
	header.add_theme_constant_override("separation", 10)
	add_child(header)

	var titles = VBoxContainer.new()
	titles.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	header.add_child(titles)

	var eyebrow = _label("COMPLETE NBA OFFSEASON", 9, DS.ACCENT)
	titles.add_child(eyebrow)

	var title = _label("OFFSEASON ROADMAP", 19, DS.TEXT)
	titles.add_child(title)

	current_label = _label("CURRENT FOCUS • LOADING", 10, DS.GOLD)
	titles.add_child(current_label)

	summary_label = _label("LOADING MILESTONES...", 9, DS.MUTED)
	summary_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	header.add_child(summary_label)

	stage_rows = VBoxContainer.new()
	stage_rows.name = "OffseasonRoadmapRows"
	stage_rows.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	stage_rows.add_theme_constant_override("separation", 7)
	add_child(stage_rows)


func _stage_card(stage: Dictionary) -> Control:
	var status = str(stage.get("status", "locked")).to_lower()
	var destination = str(stage.get("destination", ""))
	var focus = bool(stage.get("current_focus", false))

	var tone = _status_color(status)
	var panel = PanelContainer.new()
	panel.name = "OffseasonStage_%s" % str(stage.get("key", "stage"))
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	panel.add_theme_stylebox_override(
		"panel",
		_box(
			Color(tone, 0.085 if focus else 0.035),
			11,
			Color(tone, 0.62 if focus else 0.22)
		)
	)

	var margin = MarginContainer.new()
	_set_margins(margin, 13, 10, 13, 10)
	panel.add_child(margin)

	var row = HBoxContainer.new()
	row.add_theme_constant_override("separation", 11)
	margin.add_child(row)

	var index_badge = PanelContainer.new()
	index_badge.custom_minimum_size = Vector2(42, 42)
	index_badge.add_theme_stylebox_override(
		"panel",
		_box(Color(tone, 0.11), 10, Color(tone, 0.42))
	)
	row.add_child(index_badge)

	var index_label = _label("%02d" % (int(stage.get("index", 0)) + 1), 12, tone)
	index_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	index_label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	index_badge.add_child(index_label)

	var copy = VBoxContainer.new()
	copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	copy.add_theme_constant_override("separation", 2)
	row.add_child(copy)

	var kicker = _label(str(stage.get("kicker", "")).to_upper(), 8, tone)
	copy.add_child(kicker)

	var title = _label(str(stage.get("label", "")).to_upper(), 13, DS.TEXT)
	copy.add_child(title)

	var detail = _label(str(stage.get("detail", "")), 9, DS.MUTED)
	detail.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	copy.add_child(detail)

	var status_box = VBoxContainer.new()
	status_box.custom_minimum_size = Vector2(122, 0)
	status_box.alignment = BoxContainer.ALIGNMENT_CENTER
	row.add_child(status_box)

	var pill = _pill(_status_text(status), tone)
	pill.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	status_box.add_child(pill)

	if destination != "":
		var button = Button.new()
		button.text = "OPEN %s" % destination
		button.custom_minimum_size = Vector2(122, 30)
		button.add_theme_font_size_override("font_size", 8)
		button.add_theme_color_override("font_color", DS.TEXT)
		button.add_theme_color_override("font_hover_color", DS.TEXT)
		button.add_theme_stylebox_override(
			"normal",
			_box(Color("121a24"), 7, Color(DS.BORDER, 0.82))
		)
		button.add_theme_stylebox_override(
			"hover",
			_box(Color(tone, 0.10), 7, Color(tone, 0.65))
		)
		button.pressed.connect(_emit_destination.bind(destination))
		status_box.add_child(button)

	return panel


func _emit_destination(page_name: String) -> void:
	destination_requested.emit(page_name)


func _status_text(status: String) -> String:
	match status:
		"complete":
			return "COMPLETE"
		"current":
			return "CURRENT"
		"ready":
			return "READY"
		"available":
			return "AVAILABLE"
		"planning":
			return "PLANNING"
		"blocked":
			return "BLOCKED"
		_:
			return "LOCKED"


func _status_color(status: String) -> Color:
	match status:
		"complete":
			return DS.GOOD
		"current":
			return brand_color.lightened(0.38)
		"ready":
			return DS.GOLD
		"available":
			return DS.ACCENT
		"planning":
			return Color("8fa6c8")
		"blocked":
			return DS.BAD
		_:
			return DS.MUTED


func _pill(text_value: String, tone: Color) -> Label:
	var label = _label("  %s  " % text_value, 8, tone)
	label.autowrap_mode = TextServer.AUTOWRAP_OFF
	label.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	label.add_theme_stylebox_override(
		"normal",
		_box(Color(tone, 0.08), 7, Color(tone, 0.32))
	)
	return label


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


func _clear(node: Node) -> void:
	for child in node.get_children():
		node.remove_child(child)
		child.queue_free()
