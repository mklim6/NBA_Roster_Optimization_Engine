extends Control

const VERSION := "v3-visual-overhaul-50a4-franchise-core-stage-v1.0.0-2026-10-05"
const HeroPlayerPortraitV50A = preload("res://scripts/hero_player_portrait_v50a.gd")

var accent := Color("007a33")
var secondary := Color("ba9653")
var source_players: Array = []
var portrait_nodes: Array = []


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	clip_contents = false
	resized.connect(_layout_stage)
	queue_redraw()


func apply_team_brand(next_accent: Color, next_secondary: Color = Color("ba9653")) -> void:
	accent = next_accent
	secondary = next_secondary
	for node in portrait_nodes:
		if is_instance_valid(node) and node.has_method("apply_team_brand"):
			node.call("apply_team_brand", accent)
	queue_redraw()


func configure(players: Array, next_accent: Color, next_secondary: Color = Color("ba9653")) -> void:
	accent = next_accent
	secondary = next_secondary
	source_players = players.duplicate(true)
	_rebuild()


func _rebuild() -> void:
	for child in get_children():
		remove_child(child)
		child.queue_free()
	portrait_nodes.clear()

	var ranked: Array = []
	for raw_player in source_players:
		if typeof(raw_player) != TYPE_DICTIONARY:
			continue
		var player: Dictionary = raw_player
		var score := float(player.get("overall", 0.0))
		if bool(player.get("is_starter", false)):
			score += 4.0
		elif bool(player.get("in_rotation", false)):
			score += 1.5
		var candidate := {"score": score, "player": player}
		var insert_at := ranked.size()
		for index in range(ranked.size()):
			var existing: Dictionary = ranked[index]
			if score > float(existing.get("score", 0.0)):
				insert_at = index
				break
		ranked.insert(insert_at, candidate)
		if ranked.size() > 3:
			ranked.pop_back()

	var ordered: Array = []
	if ranked.size() >= 2:
		ordered.append(ranked[1].get("player", {}))
	if ranked.size() >= 1:
		ordered.append(ranked[0].get("player", {}))
	if ranked.size() >= 3:
		ordered.append(ranked[2].get("player", {}))

	while ordered.size() < 3:
		ordered.append({})

	for index in range(3):
		var portrait := HeroPlayerPortraitV50A.new()
		portrait.name = "HeroPlayer%s" % (index + 1)
		portrait.z_index = 3 if index == 1 else 1
		add_child(portrait)
		portrait_nodes.append(portrait)
		var player: Dictionary = ordered[index]
		if player.is_empty():
			portrait.visible = false
		else:
			portrait.configure(player, accent, index == 1)

	call_deferred("_layout_stage")
	queue_redraw()


func _layout_stage() -> void:
	if portrait_nodes.size() != 3 or size.x <= 1.0 or size.y <= 1.0:
		return
	var w := size.x
	var h := size.y
	var side_w := w * 0.355
	var center_w := w * 0.405
	var side_h := h * 0.88
	var center_h := h

	var positions := [
		Rect2(Vector2(w * 0.005, h * 0.11), Vector2(side_w, side_h)),
		Rect2(Vector2(w * 0.292, 0), Vector2(center_w, center_h)),
		Rect2(Vector2(w * 0.650, h * 0.11), Vector2(side_w, side_h)),
	]

	for index in range(3):
		var node: Control = portrait_nodes[index]
		node.position = positions[index].position
		node.size = positions[index].size


func _draw() -> void:
	if size.x <= 1.0 or size.y <= 1.0:
		return
	var star_center := Vector2(size.x * 0.50, size.y * 0.52)
	for radius_scale in [0.46, 0.34, 0.23]:
		draw_arc(
			star_center,
			size.y * float(radius_scale),
			0,
			TAU,
			72,
			Color(secondary, 0.045),
			1.0,
			true
		)
	draw_circle(star_center, size.y * 0.32, Color(accent, 0.030))
