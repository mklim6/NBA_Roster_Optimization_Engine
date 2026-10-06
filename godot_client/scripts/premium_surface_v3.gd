extends PanelContainer

# Shared presentation primitive: dark surface, restrained category glow and rim.
# Drawn at the final control size; no image decode or per-card gradient texture.
const DS = preload("res://scripts/design_system_v3.gd")
var tone := DS.ACCENT
var corner_radius := 16

func configure(next_tone: Color, radius: int = 16) -> void:
	tone = Color(next_tone.r, next_tone.g, next_tone.b)
	corner_radius = radius
	add_theme_stylebox_override("panel", DS.style_box(Color("0c121d"), radius, Color(tone, 0.38), 1, 0.0))
	queue_redraw()

func _ready() -> void:
	clip_contents = true
	resized.connect(queue_redraw)

func _draw() -> void:
	var center = Vector2(size.x * 0.83, size.y * 0.10)
	var reach = minf(size.x, size.y) * 0.75
	for i in range(12, 0, -1):
		draw_circle(center, reach * i / 12.0, Color(tone, 0.006))
	draw_line(Vector2(16, 1), Vector2(minf(size.x - 16, 100), 1), Color(tone, 0.85), 2, true)
