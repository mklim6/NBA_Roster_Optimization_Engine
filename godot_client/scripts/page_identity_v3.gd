extends PanelContainer

const TeamLogoV3 = preload("res://scripts/team_logo_v3.gd")
const TeamBrandingV3 = preload("res://scripts/team_branding_v3.gd")

var team := ""
var logo: Control
var accent: ColorRect


func _ready() -> void:
	custom_minimum_size = Vector2(92, 76)
	mouse_filter = Control.MOUSE_FILTER_PASS
	add_theme_stylebox_override("panel", _box(Color("101823"), 15, Color("2a364a")))

	var stack := VBoxContainer.new()
	stack.add_theme_constant_override("separation", 0)
	add_child(stack)

	accent = ColorRect.new()
	accent.custom_minimum_size = Vector2(0, 4)
	accent.color = Color("8ed8ff")
	accent.mouse_filter = Control.MOUSE_FILTER_IGNORE
	stack.add_child(accent)

	var center := CenterContainer.new()
	center.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	center.size_flags_vertical = Control.SIZE_EXPAND_FILL
	stack.add_child(center)

	logo = TeamLogoV3.new()
	logo.custom_minimum_size = Vector2(74, 60)
	center.add_child(logo)


func configure(abbreviation: String, primary: Color, secondary: Color) -> void:
	team = abbreviation.strip_edges().to_upper()
	if logo != null:
		logo.configure(team)

	var edge := TeamBrandingV3.hover_color(primary)
	var accent_color := secondary
	if accent_color.a <= 0.0 or accent_color == Color.BLACK:
		accent_color = edge
	if accent != null:
		accent.color = accent_color

	add_theme_stylebox_override("panel", _box(Color(primary, 0.14), 15, Color(edge, 0.72)))
	tooltip_text = team if team != "" else "Active franchise"


func _box(color: Color, radius: int, border: Color) -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = color
	style.border_color = border
	style.set_border_width_all(1)
	style.corner_radius_top_left = radius
	style.corner_radius_top_right = radius
	style.corner_radius_bottom_left = radius
	style.corner_radius_bottom_right = radius
	return style
