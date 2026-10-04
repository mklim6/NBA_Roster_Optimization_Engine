extends Control

# Batch 20N: lightweight vector court artwork; redraw only on resize or branding.
var primary := Color("007a33")
var secondary := Color("ffffff")
var team := ""

func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	clip_contents = true
	resized.connect(queue_redraw)

func apply_team_brand(abbreviation: String, first: Color, second: Color) -> void:
	team = abbreviation
	primary = first
	secondary = second
	queue_redraw()

func _draw() -> void:
	if size.x < 1 or size.y < 1:
		return
	var glow := primary.lerp(Color.WHITE, 0.35)
	# Layered arena light gives the panel depth without an animated background.
	draw_colored_polygon(PackedVector2Array([
		Vector2(size.x * 0.38, 0), Vector2(size.x, 0),
		Vector2(size.x, size.y), Vector2(size.x * 0.82, size.y)
	]), Color(primary, 0.13))
	draw_colored_polygon(PackedVector2Array([
		Vector2(size.x * 0.70, 0), Vector2(size.x * 0.81, 0),
		Vector2(size.x * 0.42, size.y), Vector2(size.x * 0.30, size.y)
	]), Color(secondary, 0.025))
	var court := Rect2(Vector2(size.x * 0.57, size.y * 0.16), Vector2(size.x * 0.50, size.y * 0.70))
	var ink := Color(glow, 0.25)
	draw_rect(court, ink, false, 1.2)
	var mid := Vector2(court.position.x + court.size.x * 0.5, court.get_center().y)
	draw_line(Vector2(mid.x, court.position.y), Vector2(mid.x, court.end.y), ink, 1.2, true)
	draw_arc(mid, court.size.y * 0.17, 0, TAU, 48, ink, 1.2, true)
	for x in [court.position.x, court.end.x]:
		var sign_value := 1.0 if x == court.position.x else -1.0
		var key := Rect2(Vector2(x if sign_value > 0 else x - court.size.x * 0.22, court.position.y + court.size.y * 0.32), Vector2(court.size.x * 0.22, court.size.y * 0.36))
		draw_rect(key, ink, false, 1.2)
		draw_arc(Vector2(x + sign_value * court.size.x * 0.22, mid.y), court.size.y * 0.18, -PI * 0.5 if sign_value > 0 else PI * 0.5, PI * 0.5 if sign_value > 0 else PI * 1.5, 24, ink, 1.2, true)
	# A restrained team monogram anchors the identity without requiring bitmap assets.
	draw_string(get_theme_default_font(), Vector2(size.x * 0.63, size.y * 0.86), team, HORIZONTAL_ALIGNMENT_LEFT, -1, 56, Color(glow, 0.10))
	draw_line(Vector2(0, 16), Vector2(0, size.y - 16), Color(primary, 0.95), 5.0, true)
