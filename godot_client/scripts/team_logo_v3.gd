extends Control

const Branding = preload("res://scripts/team_branding_v3.gd")
var team := ""
var texture: Texture2D

func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	resized.connect(queue_redraw)

func configure(abbreviation: String) -> void:
	team = abbreviation.strip_edges().to_upper()
	texture = Branding.logo_texture(team)
	tooltip_text = team
	queue_redraw()

func _draw() -> void:
	if texture != null:
		var available := size - Vector2(16, 16)
		if available.x <= 0 or available.y <= 0:
			return
		var source := texture.get_size()
		var scaled := source * minf(available.x / source.x, available.y / source.y)
		draw_texture_rect(texture, Rect2((size - scaled) * 0.5, scaled), false)
	else:
		draw_string(get_theme_default_font(), Vector2(0, size.y * 0.5 + 7), team if team != "" else "--", HORIZONTAL_ALIGNMENT_CENTER, size.x, 20, Color("e9eef5"))
