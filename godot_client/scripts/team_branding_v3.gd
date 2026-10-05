class_name TeamBrandingV3
extends RefCounted

const DesignSystemV3 = preload("res://scripts/design_system_v3.gd")
const VERSION := "v3-team-branding-batch-19c-v1.0.0-2026-10-03"


static func logo_texture(abbreviation: String) -> Texture2D:
	var team := abbreviation.strip_edges().to_upper()
	if not DesignSystemV3.TEAM_BRANDS.has(team):
		return null
	var logo_cache: Dictionary = Engine.get_meta("v3_team_logo_cache", {})
	if logo_cache.has(team):
		var cached = logo_cache[team].get_ref()
		if cached != null:
			return cached
	var path := "res://assets/team_logos/%s.svg" % team
	var image := Image.new()
	if FileAccess.file_exists(path + ".import") and ResourceLoader.exists(path):
		var imported = load(path)
		if not imported is Texture2D:
			return null
		image = imported.get_image()
	else:
		# Source bundles can start before the editor creates any .godot imports.
		if not FileAccess.file_exists(path) or image.load(path) != OK:
			return null
	var bounds := image.get_used_rect()
	if bounds.size.x <= 0 or bounds.size.y <= 0:
		return null
	# Fit the actual mark, rather than the CDN's transparent square canvas.
	image = image.get_region(bounds)
	var texture := ImageTexture.create_from_image(image)
	# Weak references share live textures without retaining GPU resources at shutdown.
	logo_cache[team] = weakref(texture)
	Engine.set_meta("v3_team_logo_cache", logo_cache)
	return texture


static func palette(team_abbreviation: String) -> Dictionary:
	return DesignSystemV3.team_palette(team_abbreviation)


static func luminance(color: Color) -> float:
	return (
		(0.2126 * color.r)
		+ (0.7152 * color.g)
		+ (0.0722 * color.b)
	)


static func readable_foreground(background: Color) -> Color:
	return Color("0a0d12") if luminance(background) >= 0.58 else DesignSystemV3.TEXT_STRONG


static func hover_color(primary: Color) -> Color:
	return primary.darkened(0.12) if luminance(primary) >= 0.62 else primary.lightened(0.14)


static func muted_brand(primary: Color, amount: float = 0.10) -> Color:
	return Color(primary, clamp(amount, 0.0, 1.0))


static func active_nav_box(primary: Color) -> StyleBoxFlat:
	var box := DesignSystemV3.style_box(
		Color(DesignSystemV3.PANEL_ALT, 0.94),
		DesignSystemV3.RADIUS_MD,
		Color(primary, 0.62),
		1,
		0.12
	)
	box.border_width_left = 2
	box.border_color = primary
	box.content_margin_left = 10.0
	box.content_margin_right = 9.0
	box.content_margin_top = 6.0
	box.content_margin_bottom = 6.0
	return box


static func apply_nav_state(button: Button, active: bool, primary: Color) -> void:
	if button == null:
		return
	button.add_theme_color_override(
		"font_color",
		DesignSystemV3.TEXT_STRONG if active else DesignSystemV3.MUTED
	)
	if active:
		button.add_theme_stylebox_override("normal", active_nav_box(primary))
	else:
		var box := DesignSystemV3.style_box(
			DesignSystemV3.SIDEBAR,
			DesignSystemV3.RADIUS_MD,
			DesignSystemV3.SIDEBAR,
			1,
			0.0
		)
		box.content_margin_left = 10.0
		box.content_margin_right = 9.0
		box.content_margin_top = 6.0
		box.content_margin_bottom = 6.0
		button.add_theme_stylebox_override("normal", box)


static func apply_primary_button(button: Button, primary: Color) -> void:
	if button == null:
		return
	var hover := hover_color(primary)
	var foreground := readable_foreground(primary)
	var hover_foreground := readable_foreground(hover)

	button.add_theme_color_override("font_color", foreground)
	button.add_theme_color_override("font_hover_color", hover_foreground)
	button.add_theme_color_override("font_pressed_color", hover_foreground)

	button.add_theme_stylebox_override(
		"normal",
		DesignSystemV3.style_box(
			primary,
			DesignSystemV3.RADIUS_MD,
			primary,
			1,
			0.16
		)
	)
	button.add_theme_stylebox_override(
		"hover",
		DesignSystemV3.style_box(
			hover,
			DesignSystemV3.RADIUS_MD,
			hover,
			1,
			0.22
		)
	)
	button.add_theme_stylebox_override(
		"pressed",
		DesignSystemV3.style_box(
			Color(hover, 0.88),
			DesignSystemV3.RADIUS_MD,
			hover,
			1,
			0.08
		)
	)
	button.add_theme_stylebox_override(
		"focus",
		DesignSystemV3.style_box(
			primary,
			DesignSystemV3.RADIUS_MD,
			DesignSystemV3.ACCENT,
			2,
			0.16
		)
	)
