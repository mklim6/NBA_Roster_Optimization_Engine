extends Control
const DS = preload("res://scripts/design_system_v3.gd")
const Logo = preload("res://scripts/team_logo_v3.gd")
const Portrait = preload("res://scripts/player_portrait_v3.gd")
const Court = preload("res://scripts/theater_court_v3.gd")
signal navigate_requested(page: String)
var content: VBoxContainer
var status: Label
var request: HTTPRequest
var picker: OptionButton
var game: Dictionary = {}
var games: Array = []
var chapter_index = 0
var chapter_time = 0.0
var playing = false
var speed = 1.0
var sound_enabled = false
var audio_player: AudioStreamPlayer
var chapter_title: Label
var chapter_detail: Label
var chapter_body: VBoxContainer
var scoreboard: Label
var court: Control
var seek: HSlider
var play_button: Button
var primary = DS.TEAM_PRIMARY

func _ready() -> void:
	name = "GameNightTheater"
	var bg = ColorRect.new()
	bg.color = DS.BG
	bg.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(bg)
	var scroll = ScrollContainer.new()
	scroll.name = "TheaterScroll"
	scroll.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	add_child(scroll)
	var margin = MarginContainer.new()
	margin.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	for side in ["left","right","top"]:
		margin.add_theme_constant_override("margin_"+side,24)
	margin.add_theme_constant_override("margin_bottom",160)
	scroll.add_child(margin)
	content = VBoxContainer.new()
	content.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	content.add_theme_constant_override("separation",16)
	margin.add_child(content)
	status = _label("Connecting to the broadcast archive…",13,DS.MUTED)
	content.add_child(status)
	request = HTTPRequest.new()
	request.timeout = 45
	request.request_completed.connect(_completed)
	add_child(request)
	audio_player = AudioStreamPlayer.new()
	audio_player.volume_db = -24
	add_child(audio_player)

func apply_team_brand(_team: String, color: Color, _secondary: Color) -> void:
	primary = color

func refresh() -> void:
	playing = false
	if request == null:
		return
	request.cancel_request()
	_clear()
	status.text = "Loading recorded game broadcasts…"
	if request.request("http://127.0.0.1:8765/v3/game-night-theater") != OK:
		_error()

func _completed(result: int, code: int, _headers: PackedStringArray, bytes: PackedByteArray) -> void:
	var data = JSON.parse_string(bytes.get_string_from_utf8())
	if result != HTTPRequest.RESULT_SUCCESS or code != 200 or typeof(data) != TYPE_DICTIONARY:
		_error()
		return
	configure(data)

func _error() -> void:
	status.text = "Broadcast archive unavailable. Retry to load your save."
	content.add_child(_button("RETRY",refresh))

func configure(data: Dictionary) -> void:
	_clear()
	games = data.get("games",[]).duplicate(true)
	status.text = "%s • RECORDED POSTGAME BROADCAST • %s AVAILABLE GAMES" % [str(data.get("season","")),str(data.get("available_count",games.size()))]
	var header = _card(content)
	header.add_child(_label("GAME NIGHT THEATER",30,DS.GOLD))
	header.add_child(_label(str(data.get("detail","")),13,DS.MUTED))
	header.add_child(_button("REFRESH BROADCAST ARCHIVE",refresh))
	if games.is_empty():
		header.add_child(_label("Your first broadcast is waiting for a game.",22))
		header.add_child(_label("Complete a game in Game Day, then return for the recorded result, starting cast and player spotlights.",15,DS.MUTED))
		header.add_child(_button("OPEN GAME DAY",func(): navigate_requested.emit("GAME DAY")))
		var waiting = _card(content)
		waiting.add_child(_label("THE STAGE IS SET",18,DS.GOLD))
		var empty_court = Court.new()
		empty_court.home_color = primary
		waiting.add_child(empty_court)
		waiting.add_child(_label("Your recorded starting cast will appear here after the first game.",13,DS.MUTED))
		return
	picker = OptionButton.new()
	picker.custom_minimum_size.y = 42
	for entry in games:
		picker.add_item("%s %s — %s %s • %s" % [str(entry.away_team),str(entry.away_score),str(entry.home_team),str(entry.home_score),str(entry.game_id)])
	picker.item_selected.connect(_select_game)
	header.add_child(picker)
	var arena = _card(content)
	arena.add_child(_label("FRANCHISE NETWORK • FINAL RESULT",12,DS.GOLD))
	var logos = HBoxContainer.new()
	arena.add_child(logos)
	for side in ["away_team","home_team"]:
		var logo = Logo.new()
		logo.name = side
		logo.custom_minimum_size = Vector2(64,64)
		logo.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		logos.add_child(logo)
	scoreboard = _label("",30)
	scoreboard.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	arena.add_child(scoreboard)
	court = Court.new()
	arena.add_child(court)
	arena.add_child(_label("STARTING CAST • LINEUP DIAGRAM • ILLUSTRATIVE PLACEMENT",11,DS.MUTED))
	chapter_title = _label("",24,DS.GOLD)
	content.add_child(chapter_title)
	chapter_detail = _label("",15,DS.MUTED)
	content.add_child(chapter_detail)
	var controls = HBoxContainer.new()
	controls.add_theme_constant_override("separation",8)
	content.add_child(controls)
	controls.add_child(_button("PREVIOUS",func(): _show_chapter(max(0,chapter_index-1))))
	play_button = _button("PLAY RECAP",_toggle_play)
	controls.add_child(play_button)
	controls.add_child(_button("NEXT",func(): _show_chapter(min(game.chapters.size()-1,chapter_index+1))))
	var speeds = OptionButton.new()
	speeds.add_item("1× PACE")
	speeds.add_item("2× PACE")
	speeds.add_item("4× PACE")
	speeds.selected = 0 if speed == 1.0 else 1 if speed == 2.0 else 2
	speeds.item_selected.connect(func(index: int): speed = [1.0,2.0,4.0][index])
	controls.add_child(speeds)
	seek = HSlider.new()
	seek.step = 1
	seek.value_changed.connect(func(value: float): _show_chapter(int(value)))
	content.add_child(seek)
	content.move_child(controls,2)
	content.move_child(seek,3)
	var sound = CheckButton.new()
	sound.text = "Broadcast transition sound"
	sound.button_pressed = sound_enabled
	sound.toggled.connect(func(enabled: bool): sound_enabled = enabled)
	content.add_child(sound)
	chapter_body = VBoxContainer.new()
	chapter_body.add_theme_constant_override("separation",12)
	content.add_child(chapter_body)
	content.add_child(_button("OPEN FRANCHISE PULSE",func(): navigate_requested.emit("PULSE")))
	_select_game(0)

func _select_game(index: int) -> void:
	playing = false
	game = games[index].duplicate(true)
	var row = scoreboard.get_parent().get_child(1)
	row.get_node("away_team").configure(str(game.away_team))
	row.get_node("home_team").configure(str(game.home_team))
	scoreboard.text = "%s  %s    —    %s  %s  •  FINAL%s" % [str(game.away_team),str(game.away_score),str(game.home_team),str(game.home_score)," / %s OT" % str(game.overtime_periods) if int(game.overtime_periods)>0 else ""]
	seek.max_value = game.chapters.size()-1
	_show_chapter(0)

func _toggle_play() -> void:
	if chapter_index == game.chapters.size()-1 and not playing:
		_show_chapter(0)
	playing = not playing
	_update_play()

func _process(delta: float) -> void:
	if not visible or not playing or game.is_empty():
		return
	chapter_time += delta*speed
	if chapter_time >= 6.0:
		if chapter_index >= game.chapters.size()-1:
			playing = false
			_update_play()
		else:
			_show_chapter(chapter_index+1)

func _show_chapter(index: int) -> void:
	chapter_index = index
	chapter_time = 0.0
	var chapter = game.chapters[index]
	chapter_title.text = "%s / %s • %s" % [str(index+1),str(game.chapters.size()),str(chapter.title)]
	chapter_detail.text = str(chapter.detail)
	seek.set_value_no_signal(index)
	for child in chapter_body.get_children():
		chapter_body.remove_child(child)
		child.queue_free()
	court.configure(game,str(chapter.get("player",{}).get("player_id","")))
	if str(chapter.kind) == "spotlight":
		_player_card(chapter_body,chapter.player)
	elif str(chapter.kind) == "comparison":
		_comparison()
	elif str(chapter.kind) == "lineups":
		for side in [str(game.home_team),str(game.away_team)]:
			var card = _card(chapter_body)
			card.add_child(_label(side+" • RECORDED STARTERS",16,DS.GOLD))
			for player in game.players:
				if str(player.team) == side and bool(player.starter):
					card.add_child(_label("%s • %.1f MIN • %s PTS" % [str(player.name),float(player.minutes),str(player.points)],14))
	else:
		var card = _card(chapter_body)
		card.add_child(_label(str(game.away_name)+" at "+str(game.home_name),20))
		card.add_child(_label("SOURCE • "+str(game.evidence),12,DS.MUTED))
		card.add_child(_label("Six-second broadcast chapters. Playback does not advance the franchise.",14,DS.MUTED))
	chapter_body.modulate.a = 0.0
	create_tween().tween_property(chapter_body,"modulate:a",1.0,.2)
	if sound_enabled:
		_play_sting()
	_update_play()

func _update_play() -> void:
	play_button.text = "PAUSE" if playing else "REPLAY RECAP" if chapter_index == game.chapters.size()-1 else "PLAY RECAP"

func _player_card(parent: Node, player: Dictionary) -> void:
	var card = _card(parent)
	var portrait = Portrait.new()
	portrait.custom_minimum_size = Vector2(0,100)
	card.add_child(portrait)
	portrait.configure(player)
	card.add_child(_label(str(player.name),25,DS.GOLD))
	card.add_child(_label("%s PTS  /  %s REB  /  %s AST" % [str(player.points),str(player.rebounds),str(player.assists)],22))
	card.add_child(_label("%.1f MIN • FG %s/%s • 3PT %s/%s • %s STL • %s BLK" % [float(player.minutes),str(player.field_goals_made),str(player.field_goals_attempted),str(player.three_pointers_made),str(player.three_pointers_attempted),str(player.steals),str(player.blocks)],14,DS.MUTED))

func _comparison() -> void:
	if game.totals.is_empty():
		chapter_body.add_child(_label("Complete team totals were not recorded for this game.",15,DS.MUTED))
		return
	for metric in ["points","rebounds","assists","turnovers"]:
		var card = _card(chapter_body)
		var home = int(game.totals[game.home_team][metric])
		var away = int(game.totals[game.away_team][metric])
		card.add_child(_label("%s • %s %s / %s %s" % [metric.to_upper(),str(game.away_team),str(away),str(game.home_team),str(home)],17))
		var bars = HBoxContainer.new()
		card.add_child(bars)
		for value in [away,home]:
			var bar = ColorRect.new()
			bar.custom_minimum_size.y = 10
			bar.color = Color("64748b") if bars.get_child_count() == 0 else primary
			bar.size_flags_horizontal = Control.SIZE_EXPAND_FILL
			bar.size_flags_stretch_ratio = max(1.0,float(value))
			bars.add_child(bar)

func _clear() -> void:
	playing = false
	game.clear()
	for child in content.get_children():
		if child != status:
			content.remove_child(child)
			child.queue_free()

func _button(text: String, callback: Callable) -> Button:
	var button = Button.new()
	button.text = text
	button.custom_minimum_size.y = 40
	button.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	button.pressed.connect(callback)
	return button

func _card(parent: Node) -> VBoxContainer:
	var panel = PanelContainer.new()
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var style = StyleBoxFlat.new()
	style.bg_color = DS.PANEL_ALT
	style.border_color = Color(primary,.5)
	style.set_border_width_all(1)
	style.set_corner_radius_all(16)
	for side in ["left","right","top","bottom"]:
		style.set("content_margin_"+side,16)
	panel.add_theme_stylebox_override("panel",style)
	parent.add_child(panel)
	var body = VBoxContainer.new()
	body.add_theme_constant_override("separation",10)
	panel.add_child(body)
	return body

func _label(text: String, font_size: int, color: Color = DS.TEXT) -> Label:
	var label = Label.new()
	label.text = text
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.add_theme_font_size_override("font_size",font_size)
	label.add_theme_color_override("font_color",color)
	return label

func _play_sting() -> void:
	var wave = AudioStreamWAV.new()
	wave.format = AudioStreamWAV.FORMAT_16_BITS
	wave.mix_rate = 22050
	var bytes = PackedByteArray()
	bytes.resize(6615*2)
	for i in range(6615):
		var t = float(i)/22050.0
		bytes.encode_s16(i*2,int(4000*sin(PI*float(i)/6615.0)*sin(TAU*523.25*t)))
	wave.data = bytes
	audio_player.stream = wave
	audio_player.play()
