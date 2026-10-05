extends Control

# Visual Overhaul 50A.4: smooth broadcast hero field for the desktop client.
const VERSION := "v3-visual-overhaul-50a4-home-art-v1.0.0-2026-10-05"

var primary := Color("007a33")
var secondary := Color("ba9653")
var team := "BOS"


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	clip_contents = true
	resized.connect(queue_redraw)


func apply_team_brand(abbreviation: String, first: Color, second: Color) -> void:
	team = abbreviation.strip_edges().to_upper()
	primary = first
	secondary = second
	queue_redraw()


func _smooth(value: float) -> float:
	var t := clampf(value, 0.0, 1.0)
	return t * t * (3.0 - 2.0 * t)


func _draw() -> void:
	if size.x < 1.0 or size.y < 1.0:
		return

	# 50A.4 removes the visible vertical banding from 50A.3. The hero now behaves
	# like one broadcast backdrop: rich team color on the identity side, gradually
	# dissolving into a near-black player stage.
	var bands := 256
	var band_width := size.x / float(bands)
	var left_color := primary.darkened(0.10)
	var middle_color := primary.darkened(0.50)
	var right_color := Color("070a10")

	for index in range(bands):
		var t := float(index) / float(maxi(bands - 1, 1))
		var color_value: Color
		if t < 0.56:
			color_value = left_color.lerp(middle_color, _smooth(t / 0.56))
		else:
			color_value = middle_color.lerp(right_color, _smooth((t - 0.56) / 0.44))
		draw_rect(
			Rect2(Vector2(float(index) * band_width, 0), Vector2(band_width + 1.2, size.y)),
			color_value
		)

	# Broadcast-style depth behind the core rotation, without boxing the players.
	draw_circle(
		Vector2(size.x * 0.77, size.y * 0.50),
		size.y * 0.62,
		Color(primary.lightened(0.12), 0.035)
	)
	for x_ratio in [0.70, 0.82, 0.94]:
		draw_arc(
			Vector2(size.x * x_ratio, size.y * 0.53),
			size.y * 0.44,
			0,
			TAU,
			72,
			Color(secondary, 0.050),
			1.0,
			true
		)

	# A single low-contrast diagonal adds motion without the engineering-grid look.
	draw_colored_polygon(
		PackedVector2Array([
			Vector2(size.x * 0.44, 0),
			Vector2(size.x * 0.54, 0),
			Vector2(size.x * 0.43, size.y),
			Vector2(size.x * 0.34, size.y),
		]),
		Color(secondary, 0.032)
	)

	# Oversized city/team monogram, barely visible behind the player stage.
	draw_string(
		get_theme_default_font(),
		Vector2(size.x * 0.71, size.y * 0.88),
		team,
		HORIZONTAL_ALIGNMENT_LEFT,
		size.x * 0.22,
		96,
		Color(primary.lightened(0.44), 0.050)
	)

	# Crisp top accent, matching the team rather than a generic desktop chrome line.
	draw_rect(Rect2(Vector2(0, 0), Vector2(size.x, 3)), Color(primary, 0.96))
