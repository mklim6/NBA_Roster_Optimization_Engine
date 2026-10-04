extends Control

const Branding = preload("res://scripts/team_branding_v3.gd")
var franchise := ""
var opponent := ""
var is_home := true
var logos: Array = [null, null]

func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	clip_contents = true
	resized.connect(queue_redraw)

func set_matchup(first: String, second: String, home: bool) -> void:
	franchise = first.strip_edges().to_upper()
	opponent = second.strip_edges().to_upper()
	is_home = home
	logos = [Branding.logo_texture(franchise), Branding.logo_texture(opponent)]
	queue_redraw()

func _draw() -> void:
	if size.x < 1 or size.y < 1:
		return
	var font := get_theme_default_font()
	var middle := size.x * 0.5
	for side in [0, 1]:
		var abbreviation := franchise if side == 0 else opponent
		var palette := Branding.palette(abbreviation)
		var primary: Color = palette["primary"]
		var secondary: Color = palette["secondary"]
		var start := 0.0 if side == 0 else middle
		var finish := middle if side == 0 else size.x
		var panel := StyleBoxFlat.new()
		panel.bg_color = Color("121b27").lerp(primary, 0.40)
		panel.set_corner_radius_all(12)
		draw_style_box(panel, Rect2(start, 0, middle, size.y))
		draw_colored_polygon(PackedVector2Array([Vector2(start + middle * 0.62, 0), Vector2(finish, 0), Vector2(finish - 24, size.y), Vector2(start + middle * 0.32, size.y)]), Color(primary.lightened(0.2), 0.18))
		draw_arc(Vector2(start + middle * 0.78, size.y * 0.5), 43, 0, TAU, 48, Color(secondary, 0.13), 1.5, true)
		draw_line(Vector2(start + 16, 0), Vector2(finish - 16, 0), primary.lightened(0.2), 3, true)
		var center := start + middle * 0.5
		var venue := "HOME COURT" if (is_home and side == 0) or (not is_home and side == 1) else "ON THE ROAD"
		var logo: Texture2D = logos[side]
		if logo != null:
			var extent := 64.0 if middle >= 210 else 46.0
			var source := logo.get_size()
			var scaled := source * minf(extent / source.x, extent / source.y)
			var origin := Vector2(start + 50, 46) if middle >= 210 else Vector2(center, 31)
			draw_texture_rect(logo, Rect2(origin - scaled * 0.5, scaled), false)
			var text_x := start + 92 if middle >= 210 else start + 16
			var text_width := middle - 108 if middle >= 210 else middle - 32
			draw_string(font, Vector2(text_x, 53 if middle >= 210 else 76), abbreviation, HORIZONTAL_ALIGNMENT_CENTER, text_width, 28 if middle >= 210 else 20, Color("f2f5fa"))
			draw_string(font, Vector2(text_x, 76 if middle >= 210 else 94), venue, HORIZONTAL_ALIGNMENT_CENTER, text_width, 9, Color("c3cedb"))
		else:
			draw_string(font, Vector2(center - 64, 57), abbreviation, HORIZONTAL_ALIGNMENT_CENTER, 128, 38, Color("f2f5fa"))
			draw_string(font, Vector2(center - 70, 81), venue, HORIZONTAL_ALIGNMENT_CENTER, 140, 10, Color("c3cedb"))
	# Center plate separates the two team palettes like a televised matchup graphic.
	draw_circle(Vector2(middle, size.y * 0.5), 23, Color("0b111b"))
	draw_arc(Vector2(middle, size.y * 0.5), 23, 0, TAU, 48, Color("3b485d"), 1, true)
	draw_string(font, Vector2(middle - 19, size.y * 0.5 + 5), "VS", HORIZONTAL_ALIGNMENT_CENTER, 38, 13, Color("e5ba6b"))
