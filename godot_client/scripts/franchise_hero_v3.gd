extends Control

const DS = preload("res://scripts/design_system_v3.gd")
const Logo = preload("res://scripts/team_logo_v3.gd")
const Portrait = preload("res://scripts/player_portrait_v3.gd")
var accent := Color("007a33")
var portraits: Array = []
# 50A / Expansion 49 compatibility: PlayerPortraitV3.configure accepts the player dictionary.
var copy: VBoxContainer

func configure(team: String, team_name: String, eyebrow: String, detail: String, players: Array = []) -> void:
	accent = DS.team_palette(team).get("primary", DS.TEAM_PRIMARY)
	custom_minimum_size = Vector2(0, 270)
	clip_contents = true
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	var logo = Logo.new()
	logo.position = Vector2(24, 65)
	logo.size = Vector2(92, 92)
	add_child(logo)
	logo.configure(team)
	copy = VBoxContainer.new()
	copy.position = Vector2(132, 32)
	copy.add_theme_constant_override("separation", 12)
	add_child(copy)
	for row in [[eyebrow, 10, accent.lightened(0.55)], [team_name, 36, DS.TEXT], [detail, 13, DS.MUTED], ["YOUR TEAM. YOUR DECISIONS. YOUR NEXT CHAPTER.", 10, DS.TEXT]]:
		var label = Label.new()
		label.text = str(row[0])
		label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		label.add_theme_font_size_override("font_size", int(row[1]))
		label.add_theme_color_override("font_color", row[2])
		copy.add_child(label)
	for i in range(mini(players.size(), 3)):
		var player: Dictionary = players[i]
		var portrait = Portrait.new()
		add_child(portrait)
		portrait.configure(player)
		portrait.add_theme_stylebox_override("panel", StyleBoxEmpty.new())
		portraits.append(portrait)
	resized.connect(_layout)
	_layout()

func _layout() -> void:
	if copy == null: return
	var show_players = size.x >= 760 and not portraits.is_empty()
	copy.size = Vector2(maxf(180, size.x - 160 - (330 if show_players else 24)), 215)
	for i in range(portraits.size()):
		var portrait = portraits[i]
		portrait.visible = show_players
		portrait.size = Vector2(190, 205 if i == 2 else 170)
		portrait.position = Vector2(size.x - 340 + i * 73, 65 if i == 2 else 100)
	queue_redraw()

func _draw() -> void:
	var box = DS.style_box(Color("0a101b"), 18, Color(accent, 0.55), 1)
	draw_style_box(box, Rect2(Vector2.ZERO, size))
	for i in range(64):
		var t = float(i) / 63.0
		draw_rect(Rect2(size.x * t, 1, size.x / 63.0 + 1, size.y - 2), Color(accent, 0.015 + 0.19 * t * t))
	var center = Vector2(size.x * 0.78, size.y * 0.55)
	draw_arc(center, 125, 0, TAU, 80, Color(DS.TEXT, 0.07), 1.0, true)
	draw_arc(center, 55, 0, TAU, 50, Color(DS.TEXT, 0.05), 1.0, true)
	draw_line(Vector2(size.x * 0.78, 1), Vector2(size.x * 0.78, size.y - 1), Color(DS.TEXT, 0.05))
	draw_rect(Rect2(24, size.y - 5, 90, 3), accent)
