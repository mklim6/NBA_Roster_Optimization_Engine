class_name UiComponentsV3
extends RefCounted

const DesignSystemV3 = preload("res://scripts/design_system_v3.gd")
const TeamBrandingV3 = preload("res://scripts/team_branding_v3.gd")
const VERSION := "v3-ui-components-batch-19b-v1.0.0-2026-10-03"


static func _surface(
	fill: Color,
	radius: int,
	border: Color,
	border_width: int = 1,
	shadow: float = 0.0
) -> StyleBoxFlat:
	return DesignSystemV3.style_box(fill, radius, border, border_width, shadow)


static func card(minimum: Vector2, elevated: bool = false) -> PanelContainer:
	var panel := PanelContainer.new()
	panel.custom_minimum_size = minimum
	var fill := DesignSystemV3.PANEL_ALT if elevated else DesignSystemV3.PANEL
	var border := DesignSystemV3.BORDER if elevated else DesignSystemV3.SOFT_BORDER
	panel.add_theme_stylebox_override(
		"panel",
		_surface(fill, DesignSystemV3.RADIUS_LG, border, 1, 0.18 if elevated else 0.12)
	)
	return panel


static func card_body(card: PanelContainer, margin_size: int = 18) -> VBoxContainer:
	var margin := MarginContainer.new()
	margin.add_theme_constant_override("margin_left", margin_size)
	margin.add_theme_constant_override("margin_top", margin_size)
	margin.add_theme_constant_override("margin_right", margin_size)
	margin.add_theme_constant_override("margin_bottom", margin_size)
	card.add_child(margin)

	var body := VBoxContainer.new()
	body.add_theme_constant_override("separation", DesignSystemV3.SPACE_SM)
	margin.add_child(body)
	return body


static func action_button(text_value: String, primary: bool = false) -> Button:
	var button := Button.new()
	button.custom_minimum_size = Vector2(124, 40)
	button.text = text_value
	button.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	button.add_theme_font_size_override("font_size", DesignSystemV3.FONT_SMALL)
	button.add_theme_color_override("font_color", DesignSystemV3.TEXT)
	button.add_theme_color_override("font_hover_color", DesignSystemV3.TEXT_STRONG)
	button.add_theme_color_override("font_pressed_color", DesignSystemV3.TEXT_STRONG)
	button.add_theme_color_override("font_disabled_color", DesignSystemV3.MUTED_DARK)

	var normal_fill := DesignSystemV3.TEAM_PRIMARY if primary else DesignSystemV3.PANEL_ALT
	var normal_border := DesignSystemV3.TEAM_PRIMARY if primary else DesignSystemV3.BORDER
	var hover_fill := DesignSystemV3.TEAM_PRIMARY_HOVER if primary else DesignSystemV3.PANEL_HOVER
	var hover_border := DesignSystemV3.TEAM_PRIMARY_HOVER if primary else DesignSystemV3.ACCENT

	button.add_theme_stylebox_override(
		"normal",
		_surface(normal_fill, DesignSystemV3.RADIUS_MD, normal_border, 1, 0.16)
	)
	button.add_theme_stylebox_override(
		"hover",
		_surface(hover_fill, DesignSystemV3.RADIUS_MD, hover_border, 1, 0.22)
	)
	button.add_theme_stylebox_override(
		"pressed",
		_surface(Color(hover_fill, 0.86), DesignSystemV3.RADIUS_MD, hover_border, 1, 0.08)
	)
	button.add_theme_stylebox_override(
		"focus",
		_surface(normal_fill, DesignSystemV3.RADIUS_MD, DesignSystemV3.ACCENT, 2, 0.16)
	)
	button.add_theme_stylebox_override(
		"disabled",
		_surface(
			Color(DesignSystemV3.PANEL_ALT, 0.46),
			DesignSystemV3.RADIUS_MD,
			Color(DesignSystemV3.SOFT_BORDER, 0.70),
			1,
			0.0
		)
	)
	return button


static func wide_action(title_text: String, subtitle_text: String) -> Button:
	var button := Button.new()
	button.custom_minimum_size = Vector2(0, 66)
	button.text = "%s\n%s" % [title_text, subtitle_text]
	button.alignment = HORIZONTAL_ALIGNMENT_LEFT
	button.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	button.tooltip_text = subtitle_text
	button.add_theme_font_size_override("font_size", DesignSystemV3.FONT_SMALL)
	button.add_theme_color_override("font_color", DesignSystemV3.TEXT)
	button.add_theme_color_override("font_hover_color", DesignSystemV3.TEXT_STRONG)
	button.add_theme_stylebox_override(
		"normal",
		_surface(DesignSystemV3.PANEL_ALT, DesignSystemV3.RADIUS_MD, DesignSystemV3.BORDER, 1, 0.08)
	)
	button.add_theme_stylebox_override(
		"hover",
		_surface(DesignSystemV3.PANEL_HOVER, DesignSystemV3.RADIUS_MD, DesignSystemV3.ACCENT, 1, 0.18)
	)
	button.add_theme_stylebox_override(
		"pressed",
		_surface(DesignSystemV3.PANEL_PRESSED, DesignSystemV3.RADIUS_MD, DesignSystemV3.ACCENT, 1, 0.06)
	)
	return button


static func _nav_box(fill: Color, border: Color, active: bool, focus: bool = false) -> StyleBoxFlat:
	var box := _surface(
		fill,
		DesignSystemV3.RADIUS_MD,
		DesignSystemV3.ACCENT if focus else border,
		1,
		0.10 if active else 0.0
	)
	box.border_width_left = 3 if active else 1
	box.border_color = DesignSystemV3.TEAM_PRIMARY_HOVER if active and not focus else (
		DesignSystemV3.ACCENT if focus else border
	)
	box.content_margin_left = 14.0
	box.content_margin_right = 12.0
	box.content_margin_top = 9.0
	box.content_margin_bottom = 9.0
	return box


static func nav_button(
	text_value: String,
	active: bool = false,
	brand_color: Color = DesignSystemV3.TEAM_PRIMARY_HOVER
) -> Button:
	var button := Button.new()
	button.custom_minimum_size = Vector2(0, 39)
	button.text = text_value
	button.alignment = HORIZONTAL_ALIGNMENT_LEFT
	button.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	button.add_theme_font_size_override("font_size", DesignSystemV3.FONT_SMALL)
	button.add_theme_color_override("font_hover_color", DesignSystemV3.TEXT_STRONG)
	button.add_theme_color_override("font_pressed_color", DesignSystemV3.TEXT_STRONG)
	button.add_theme_color_override("font_disabled_color", DesignSystemV3.MUTED_DARK)
	button.add_theme_stylebox_override(
		"hover",
		_nav_box(DesignSystemV3.PANEL_HOVER, DesignSystemV3.BORDER, false)
	)
	button.add_theme_stylebox_override(
		"pressed",
		_nav_box(DesignSystemV3.PANEL_PRESSED, DesignSystemV3.ACCENT, false)
	)
	button.add_theme_stylebox_override(
		"focus",
		_nav_box(DesignSystemV3.SIDEBAR, DesignSystemV3.ACCENT, false, true)
	)
	button.add_theme_stylebox_override(
		"disabled",
		_nav_box(DesignSystemV3.SIDEBAR, DesignSystemV3.SIDEBAR, false)
	)
	apply_nav_state(button, active, brand_color)
	return button


static func apply_nav_state(
	button: Button,
	active: bool,
	brand_color: Color = DesignSystemV3.TEAM_PRIMARY_HOVER
) -> void:
	TeamBrandingV3.apply_nav_state(button, active, brand_color)


static func pill(text_value: String, color: Color) -> Label:
	var label := Label.new()
	label.text = "  %s  " % text_value
	label.add_theme_color_override("font_color", color)
	label.add_theme_font_size_override("font_size", DesignSystemV3.FONT_CAPTION)
	label.add_theme_stylebox_override(
		"normal",
		_surface(Color(color, 0.10), DesignSystemV3.RADIUS_SM, Color(color, 0.34), 1, 0.0)
	)
	return label


static func section_title(text_value: String) -> Label:
	var label := Label.new()
	label.text = text_value
	label.add_theme_color_override("font_color", DesignSystemV3.TEXT_STRONG)
	label.add_theme_font_size_override("font_size", DesignSystemV3.FONT_SECTION)
	return label


static func small_label(text_value: String, color: Color) -> Label:
	var label := Label.new()
	label.text = text_value
	label.add_theme_color_override("font_color", color)
	label.add_theme_font_size_override("font_size", DesignSystemV3.FONT_SMALL)
	return label


static func sidebar_group_label(text_value: String) -> Label:
	var label := Label.new()
	label.text = text_value
	label.add_theme_color_override("font_color", DesignSystemV3.MUTED_DARK)
	label.add_theme_font_size_override("font_size", DesignSystemV3.FONT_MICRO)
	return label


static func divider() -> HSeparator:
	var line := HSeparator.new()
	line.add_theme_constant_override("separation", DesignSystemV3.SPACE_MD)
	line.modulate = Color(1, 1, 1, 0.10)
	return line


static func page_header(
	eyebrow_text: String,
	title_text: String,
	subtitle_text: String
) -> Dictionary:
	var root := VBoxContainer.new()
	root.add_theme_constant_override("separation", DesignSystemV3.SPACE_XS)

	var eyebrow := small_label(eyebrow_text, DesignSystemV3.ACCENT)
	eyebrow.add_theme_font_size_override("font_size", DesignSystemV3.FONT_CAPTION)
	root.add_child(eyebrow)

	var title := Label.new()
	title.text = title_text
	title.add_theme_color_override("font_color", DesignSystemV3.TEXT_STRONG)
	title.add_theme_font_size_override("font_size", DesignSystemV3.FONT_TITLE)
	root.add_child(title)

	var subtitle := Label.new()
	subtitle.text = subtitle_text
	subtitle.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	subtitle.add_theme_color_override("font_color", DesignSystemV3.MUTED)
	subtitle.add_theme_font_size_override("font_size", DesignSystemV3.FONT_BODY)
	root.add_child(subtitle)

	return {"root": root, "eyebrow": eyebrow, "title": title, "subtitle": subtitle}
