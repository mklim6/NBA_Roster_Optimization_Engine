extends CheckBox

const Design = preload("res://scripts/design_system_v3.gd")
const Portrait = preload("res://scripts/player_portrait_v3.gd")
var accent = Design.ACCENT

func configure(player: Dictionary, selected: bool, color: Color) -> void:
	accent = color
	name = "TradePlayer_" + str(player.get("player_id", ""))
	set_meta("asset_id", str(player.get("player_id", "")))
	flat = false
	custom_minimum_size = Vector2(0, 100)
	mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	tooltip_text = "%s • %s • OVR %s • %s" % [_text(player.get("name")), _text(player.get("position")), _text(player.get("overall")), _money(player.get("salary"))]
	button_pressed = selected
	_update_border(selected)
	add_theme_stylebox_override("hover", _box(Design.PANEL_HOVER, color))
	add_theme_stylebox_override("focus", _box(Color.TRANSPARENT, Design.ACCENT))
	toggled.connect(_update_border)
	var margin = MarginContainer.new()
	margin.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(margin)
	margin.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	margin.add_theme_constant_override("margin_left", 30)
	margin.add_theme_constant_override("margin_right", 8)
	margin.add_theme_constant_override("margin_top", 8)
	margin.add_theme_constant_override("margin_bottom", 8)
	var row = HBoxContainer.new()
	row.mouse_filter = Control.MOUSE_FILTER_IGNORE
	row.add_theme_constant_override("separation", 8)
	margin.add_child(row)
	var portrait = Portrait.new()
	portrait.name = "TradeAssetPortrait"
	portrait.custom_minimum_size = Vector2(72, 64)
	row.add_child(portrait)
	portrait.configure(player)
	var copy = VBoxContainer.new()
	copy.mouse_filter = Control.MOUSE_FILTER_IGNORE
	copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	copy.alignment = BoxContainer.ALIGNMENT_CENTER
	row.add_child(copy)
	var player_name = _label(_text(player.get("name")), 13, Design.TEXT)
	player_name.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	copy.add_child(player_name)
	copy.add_child(_label("%s • AGE %s" % [_text(player.get("position")), _text(player.get("age"))], 9, Design.MUTED))
	copy.add_child(_label(_money(player.get("salary")), 11, Design.ACCENT))
	var overall = _label("--" if typeof(player.get("overall")) not in [TYPE_INT, TYPE_FLOAT] else "%.0f" % float(player.get("overall")), 20, Design.GOLD)
	overall.custom_minimum_size = Vector2(35, 0)
	overall.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	overall.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	row.add_child(overall)

func _update_border(selected: bool) -> void:
	add_theme_stylebox_override("normal", _box(Color(accent, 0.10) if selected else Design.PANEL_ALT, accent if selected else Design.BORDER))
	add_theme_stylebox_override("pressed", _box(Color(accent, 0.15), accent))

func _box(fill: Color, border: Color) -> StyleBoxFlat:
	var style = StyleBoxFlat.new()
	style.bg_color = fill
	style.border_color = border
	style.set_border_width_all(1)
	style.set_corner_radius_all(10)
	return style

func _label(value: String, font_size: int, color: Color) -> Label:
	var label = Label.new()
	label.text = value
	label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	label.add_theme_font_size_override("font_size", font_size)
	label.add_theme_color_override("font_color", color)
	return label

func _text(value) -> String:
	return "N/A" if value == null or str(value) == "" else str(value)

func _money(value) -> String:
	return "$%.1fM" % (float(value) / 1000000) if typeof(value) in [TYPE_INT, TYPE_FLOAT] else "Salary N/A"
