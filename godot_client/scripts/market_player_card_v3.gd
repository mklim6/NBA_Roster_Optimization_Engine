extends Button

const DesignSystemV3 = preload("res://scripts/design_system_v3.gd")
const PlayerPortraitV3 = preload("res://scripts/player_portrait_v3.gd")


func configure(player: Dictionary, selected: bool, primary: Color) -> void:
	name = "MarketPlayer_" + str(player.get("player_id", "unknown"))
	set_meta("player_id", str(player.get("player_id", "")))
	custom_minimum_size = Vector2(0, 112)
	mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	tooltip_text = "%s • Select to build an offer" % _display(player.get("name"))
	add_theme_stylebox_override("normal", _style(DesignSystemV3.PANEL_ALT, primary if selected else DesignSystemV3.BORDER))
	add_theme_stylebox_override("hover", _style(DesignSystemV3.PANEL_HOVER, DesignSystemV3.ACCENT))
	add_theme_stylebox_override("focus", _style(Color.TRANSPARENT, DesignSystemV3.ACCENT))
	add_theme_stylebox_override("pressed", _style(DesignSystemV3.PANEL_HOVER, primary))

	var margin = MarginContainer.new()
	margin.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(margin)
	margin.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	for edge in ["left", "right", "top", "bottom"]:
		margin.add_theme_constant_override("margin_" + edge, 10)
	var row = HBoxContainer.new()
	row.mouse_filter = Control.MOUSE_FILTER_IGNORE
	row.add_theme_constant_override("separation", 10)
	margin.add_child(row)
	var portrait = PlayerPortraitV3.new()
	portrait.name = "MarketPortrait"
	portrait.custom_minimum_size = Vector2(102, 76)
	row.add_child(portrait)
	portrait.configure(player)

	var copy = VBoxContainer.new()
	copy.mouse_filter = Control.MOUSE_FILTER_IGNORE
	copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	copy.alignment = BoxContainer.ALIGNMENT_CENTER
	copy.add_theme_constant_override("separation", 5)
	row.add_child(copy)
	var player_name = _label(_display(player.get("name")), 16, DesignSystemV3.TEXT)
	player_name.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	copy.add_child(player_name)
	copy.add_child(_label("%s • AGE %s • POT %s" % [_display(player.get("position")), _display(player.get("age")), _display(player.get("potential"))], 10, DesignSystemV3.MUTED))
	copy.add_child(_label("Reference salary %s" % _money(player.get("salary")), 11, DesignSystemV3.ACCENT))

	var rating = VBoxContainer.new()
	rating.mouse_filter = Control.MOUSE_FILTER_IGNORE
	rating.custom_minimum_size = Vector2(50, 0)
	rating.alignment = BoxContainer.ALIGNMENT_CENTER
	row.add_child(rating)
	var tone = DesignSystemV3.GOLD if _number(player.get("overall"), -1) >= 85 else DesignSystemV3.ACCENT
	var overall = _label(_rating(player.get("overall")), 24, tone)
	overall.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	rating.add_child(overall)
	var caption = _label("OVR", 9, DesignSystemV3.MUTED)
	caption.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	rating.add_child(caption)


func _label(value: String, font_size: int, color: Color) -> Label:
	var label = Label.new()
	label.text = value
	label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	label.add_theme_font_size_override("font_size", font_size)
	label.add_theme_color_override("font_color", color)
	return label


func _style(fill: Color, border: Color) -> StyleBoxFlat:
	var style = StyleBoxFlat.new()
	style.bg_color = fill
	style.border_color = border
	style.set_border_width_all(1)
	style.set_corner_radius_all(12)
	return style


func _display(value) -> String:
	return "N/A" if value == null or str(value).strip_edges() == "" else str(value)


func _number(value, fallback: float) -> float:
	return float(value) if typeof(value) in [TYPE_INT, TYPE_FLOAT] else fallback


func _rating(value) -> String:
	return "--" if typeof(value) not in [TYPE_INT, TYPE_FLOAT] else "%.0f" % float(value)


func _money(value) -> String:
	if typeof(value) not in [TYPE_INT, TYPE_FLOAT]:
		return "N/A"
	if abs(float(value)) >= 1000000:
		return "$%.1fM" % (float(value) / 1000000)
	return "$%.0fK" % (float(value) / 1000)
