extends Control
const DS = preload("res://scripts/design_system_v3.gd")
const Portrait = preload("res://scripts/player_portrait_v3.gd")
var game: Dictionary = {}
var highlight = ""
var tokens: Array = []
var home_color = Color("008348")
var away_color = Color("506b92")

func _ready() -> void:
	custom_minimum_size = Vector2(0,390)
	resized.connect(_place)

func configure(data: Dictionary, player_id: String = "") -> void:
	game = data
	home_color = DS.team_palette(str(data.get("home_team",""))).get("primary",home_color)
	away_color = DS.team_palette(str(data.get("away_team",""))).get("primary",away_color)
	highlight = player_id
	for child in get_children():
		remove_child(child)
		child.queue_free()
	tokens.clear()
	var spots = [Vector2(.13,.35),Vector2(.29,.29),Vector2(.39,.49),Vector2(.29,.68),Vector2(.14,.65)]
	for side in ["home_team","away_team"]:
		var index = 0
		for player in game.get("players",[]):
			if str(player.get("team","")) != str(game.get(side,"")) or not bool(player.get("starter",false)) or index >= 5:
				continue
			var token = VBoxContainer.new()
			token.mouse_filter = Control.MOUSE_FILTER_IGNORE
			token.add_theme_constant_override("separation",0)
			var portrait = Portrait.new()
			portrait.custom_minimum_size = Vector2(64,43)
			token.add_child(portrait)
			add_child(token)
			portrait.configure(player)
			var label = Label.new()
			label.text = str(player.get("name","Player")).get_slice(" ",str(player.get("name","Player")).get_slice_count(" ")-1)
			label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
			label.add_theme_font_size_override("font_size",10)
			label.add_theme_color_override("font_color",Color("f6f1df"))
			token.add_child(label)
			var spot: Vector2 = spots[index]
			if side == "away_team":
				spot.x = 1.0-spot.x
			tokens.append({"node":token,"spot":spot,"id":str(player.player_id)})
			index += 1
	_place()

func _place() -> void:
	for token in tokens:
		token.node.position = Vector2(size.x*token.spot.x-32,size.y*token.spot.y-28)
		token.node.size = Vector2(64,60)
	queue_redraw()

func _draw() -> void:
	var w = size.x
	var h = size.y
	if w < 10 or h < 10:
		return
	draw_rect(Rect2(Vector2.ZERO,size),Color("080f18"))
	# Decorative crowd and lighting; no simulated spectators or shot positions.
	for row in range(3):
		for i in range(42):
			var shade = .18 + float((i*7+row*3)%8)*.025
			draw_circle(Vector2((float(i)+.5)*w/42.0,12+row*10),2.5,Color(shade,shade+.03,shade+.04))
	var floor = Rect2(w*.04,h*.18,w*.92,h*.64)
	draw_rect(floor,Color("ac8754"))
	for strip in range(22):
		draw_rect(Rect2(floor.position.x+strip*floor.size.x/22.0,floor.position.y,floor.size.x/22.0,floor.size.y),Color("c19a64") if strip%2==0 else Color("b48d59"))
	var lines = Color("f5e4bd")
	draw_rect(floor,lines,false,2)
	draw_line(Vector2(w*.5,h*.18),Vector2(w*.5,h*.82),lines,2)
	draw_arc(Vector2(w*.5,h*.5),h*.1,0,TAU,64,lines,2,true)
	for left in [true,false]:
		var x = w*.08 if left else w*.92
		var key_x = w*.04 if left else w*.79
		draw_rect(Rect2(key_x,h*.38,w*.17,h*.24),Color(home_color,.6) if left else Color(away_color,.6))
		draw_rect(Rect2(key_x,h*.38,w*.17,h*.24),lines,false,2)
		draw_arc(Vector2(x,h*.5),h*.27,-PI/2 if left else PI/2,PI/2 if left else 3*PI/2,64,lines,2,true)
		draw_arc(Vector2(x,h*.5),5,0,TAU,32,Color("e36232"),2,true)
		draw_line(Vector2(x-5,h*.465),Vector2(x+5,h*.465),lines,2)
	for token in tokens:
		if token.id == highlight:
			draw_arc(Vector2(w*token.spot.x,h*token.spot.y),43,0,TAU,64,Color("f4c96a"),3,true)
	draw_rect(Rect2(0,h*.88,w,h*.12),Color("111c2c"))
