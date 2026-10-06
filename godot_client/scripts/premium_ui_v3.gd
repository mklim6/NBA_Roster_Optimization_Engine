extends RefCounted

const DS = preload("res://scripts/design_system_v3.gd")

static func chip(text: String, tone: Color, font_size: int = 9) -> Label:
	var label = Label.new()
	label.text = text
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	label.add_theme_font_size_override("font_size", font_size)
	label.add_theme_color_override("font_color", tone.lightened(0.18))
	var style = DS.style_box(Color(tone, 0.10), 7, Color(tone, 0.28), 1, 0.0)
	style.content_margin_left = 8
	style.content_margin_right = 8
	style.content_margin_top = 5
	style.content_margin_bottom = 5
	label.add_theme_stylebox_override("normal", style)
	return label
