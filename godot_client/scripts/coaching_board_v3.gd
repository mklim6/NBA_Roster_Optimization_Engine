extends VBoxContainer
signal edit_rotation
const DS = preload("res://scripts/design_system_v3.gd")
const Portrait = preload("res://scripts/player_portrait_v3.gd")
var payload: Dictionary = {}

class CoverageCourt extends Control:
	var scheme := "balanced"
	func _draw():
		var bounds = Rect2(Vector2(12, 12), size - Vector2(24, 24))
		draw_style_box(DS.style_box(Color("101e2a"), 12, DS.BORDER, 1, 0.0), bounds)
		var origin = Vector2(size.x * 0.5, 40)
		draw_rect(Rect2(Vector2(size.x * 0.32, 24), Vector2(size.x * 0.36, 95)), Color("8a9eaf"), false, 1.5)
		draw_arc(origin, 12, 0, TAU, 40, DS.GOLD, 2)
		draw_arc(origin, size.x * 0.34, 0, PI, 60, Color("506477"), 1.5)
		var spots = [Vector2(.2,.65),Vector2(.4,.78),Vector2(.8,.65),Vector2(.62,.44),Vector2(.38,.32)]
		if scheme == "pack_paint" or scheme == "match_size_and_glass":
			spots = [Vector2(.36,.4),Vector2(.5,.55),Vector2(.64,.4),Vector2(.6,.25),Vector2(.4,.25)]
		elif scheme == "load_primary_creator":
			spots = [Vector2(.35,.73),Vector2(.48,.68),Vector2(.8,.65),Vector2(.62,.4),Vector2(.4,.3)]
		for i in range(spots.size()):
			var pos = Vector2(spots[i].x * size.x, spots[i].y * size.y)
			draw_line(pos, origin, Color(0.3,0.8,0.7,0.2), 2)
			draw_circle(pos, 13, DS.GOOD)
			draw_string(ThemeDB.fallback_font, pos + Vector2(-4,5), str(i+1), HORIZONTAL_ALIGNMENT_LEFT, -1, 14, Color("071014"))

func _ready() -> void:
	if get_child_count() == 0:
		clear_board("Refresh to load coaching intelligence.")

func clear_board(message: String) -> void:
	payload.clear()
	for child in get_children():
		remove_child(child)
		child.queue_free()
	add_theme_constant_override("separation", 12)
	add_child(label("COACHING BOARD", 20, DS.GOLD))
	add_child(label(message, 14, DS.MUTED))

func configure(data: Dictionary) -> void:
	clear_board("Automatic tactical selection • current saved rotation")
	if not data.get("available", false):
		get_child(1).text = str(data.get("detail", "No matchup available."))
		return
	payload = data.duplicate(true)
	var decision: Dictionary = data.get("decision", {})
	var staff: Dictionary = data.get("staff", {})
	var threats: Dictionary = data.get("threats", {})
	var layout = HBoxContainer.new()
	layout.add_theme_constant_override("separation", 18)
	add_child(layout)
	var court_column = VBoxContainer.new()
	court_column.custom_minimum_size.x = 320
	layout.add_child(court_column)
	court_column.add_child(label(str(decision.get("scheme_label", "Balanced")), 20))
	var court = CoverageCourt.new()
	court.scheme = str(decision.get("scheme", "balanced"))
	court.custom_minimum_size = Vector2(320,220)
	court_column.add_child(court)
	court_column.add_child(label("Schematic coverage • not tracked player positions", 12, DS.MUTED))
	var info = VBoxContainer.new()
	info.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	info.add_theme_constant_override("separation", 8)
	layout.add_child(info)
	info.add_child(label(str(data.get("opponent", "")) + " • OPPONENT PRESSURE", 14, DS.GOLD))
	var player_row = HBoxContainer.new()
	info.add_child(player_row)
	var portrait = Portrait.new()
	portrait.custom_minimum_size = Vector2(88,80)
	portrait.configure({"player_id": threats.get("primary_threat_player_id", ""), "name": threats.get("primary_threat_player_name", "Unknown")})
	player_row.add_child(portrait)
	var threat_copy = VBoxContainer.new()
	threat_copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	player_row.add_child(threat_copy)
	threat_copy.add_child(label("PRIMARY THREAT", 12, DS.MUTED))
	threat_copy.add_child(label(str(threats.get("primary_threat_player_name", "Unknown")), 19))
	for metric in [["creation","CREATION"],["spacing","SPACING"],["rim_pressure","RIM PRESSURE"],["glass_size","SIZE / GLASS"],["interior_hub","INTERIOR HUB"]]:
		var value = threats.get(metric[0], null)
		info.add_child(label(metric[1] + "   " + ("—" if value == null else "%.0f / 100" % float(value)), 12, DS.MUTED))
		if value != null:
			var bar = ProgressBar.new()
			bar.custom_minimum_size.y = 7
			bar.show_percentage = false
			bar.value = float(value)
			info.add_child(bar)
	add_child(label(str(decision.get("explanation", "")), 14, DS.MUTED))
	add_child(label("%s • modeled opponent suppression %.2f pts" % [staff.get("head_coach_name", "Staff"), decision.get("suppression_points", 0.0)], 16, DS.GOOD))
	add_child(label("Simulated staff traits: " + ", ".join(staff.get("head_traits", [])) + " • Assistant: " + ", ".join(staff.get("assistant_traits", [])), 13, DS.MUTED))
	add_child(label("Pregame model intelligence. This does not preview a score or change player ratings.", 12, DS.MUTED))
	var button = Button.new()
	button.text = "EDIT ROTATION • PREVIEW YOUR CHANGES"
	button.custom_minimum_size.y = 40
	button.pressed.connect(func(): edit_rotation.emit())
	add_child(button)

func label(text: String, font_size: int, color: Color = DS.TEXT) -> Label:
	var result = Label.new()
	result.text = text
	result.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	result.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	result.add_theme_font_size_override("font_size", font_size)
	result.add_theme_color_override("font_color", color)
	return result
