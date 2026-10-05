extends Control
const DS = preload("res://scripts/design_system_v3.gd")
const Portrait = preload("res://scripts/player_portrait_v3.gd")
const Logo = preload("res://scripts/team_logo_v3.gd")
signal navigate_requested(page: String)
var content: VBoxContainer
var status: Label
var request: HTTPRequest
var primary = DS.TEAM_PRIMARY
var filter_name = "ALL"
var payload: Dictionary = {}
var stories_box: VBoxContainer
var sound_enabled = false
var audio_player: AudioStreamPlayer

func _ready() -> void:
	name = "FranchisePulse"
	var background = ColorRect.new()
	background.color = DS.BG
	background.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(background)
	var scroll = ScrollContainer.new()
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
	content.add_theme_constant_override("separation",18)
	margin.add_child(content)
	status = _label("Connecting to Franchise Pulse…",13,DS.MUTED)
	content.add_child(status)
	audio_player = AudioStreamPlayer.new()
	audio_player.volume_db = -24
	add_child(audio_player)
	request = HTTPRequest.new()
	request.timeout = 45
	add_child(request)
	request.request_completed.connect(_completed)

func apply_team_brand(_team: String, color: Color, _secondary: Color) -> void:
	primary = color

func refresh() -> void:
	if request == null:
		return
	request.cancel_request()
	_clear_content()
	payload.clear()
	status.text = "Gathering your franchise briefing…"
	if request.request("http://127.0.0.1:8765/v3/franchise-pulse") != OK:
		_error("Could not start briefing request.")

func _completed(result: int, code: int, _headers: PackedStringArray, bytes: PackedByteArray) -> void:
	var data = JSON.parse_string(bytes.get_string_from_utf8())
	if result != HTTPRequest.RESULT_SUCCESS or code != 200 or typeof(data) != TYPE_DICTIONARY:
		_error("Briefing unavailable. Retry to load the current save.")
		return
	configure(data)
	if sound_enabled:
		_play_sting()

func _error(message: String) -> void:
	status.text = message
	var retry = Button.new()
	retry.text = "RETRY BRIEFING"
	retry.custom_minimum_size.y = 42
	retry.pressed.connect(refresh)
	content.add_child(retry)

func configure(data: Dictionary) -> void:
	payload = data.duplicate(true)
	_clear_content()
	status.text = "%s • LEAGUE DAYS %s–%s • %s" % [str(data.get("season","")),str(data.get("window_start",0)),str(data.get("day",0)),str(data.get("phase","")).replace("_"," ").to_upper()]
	var hero = _card(content,primary)
	var logo = Logo.new()
	logo.custom_minimum_size = Vector2(66,66)
	hero.add_child(logo)
	logo.configure(str(data.get("team","")))
	hero.add_child(_label("FRANCHISE PULSE",34,DS.GOLD))
	hero.add_child(_label(str(data.get("team_name",""))+" • THE WEEKLY BRIEFING",13,DS.MUTED))
	var record = data.get("season_record")
	if typeof(record) == TYPE_DICTIONARY:
		hero.add_child(_label("SEASON RECORD • %s–%s" % [str(record.get("wins",0)),str(record.get("losses",0))],16,DS.MUTED))
	hero.add_child(_label(str(data.get("headline","Your franchise, in focus")),25))
	hero.add_child(_label(str(data.get("subtitle","")),13,DS.MUTED))
	var refresh_button = Button.new()
	refresh_button.text = "REFRESH BRIEFING"
	refresh_button.custom_minimum_size.y = 40
	refresh_button.pressed.connect(refresh)
	hero.add_child(refresh_button)
	var sound = CheckButton.new()
	sound.text = "Briefing arrival sound"
	sound.button_pressed = sound_enabled
	sound.toggled.connect(func(enabled: bool): sound_enabled = enabled)
	hero.add_child(sound)
	var recap = _card(content,DS.GOLD)
	recap.add_child(_label("THE WEEK ON COURT",19,DS.GOLD))
	var results = data.get("results",[])
	if results.is_empty():
		recap.add_child(_label("No recorded games in this seven-day window.",15,DS.MUTED))
	else:
		recap.add_child(_label("W %s  /  L %s" % [str(data.get("wins",0)),str(data.get("losses",0))],24))
		for game in results:
			var color = Color("67d9a2") if str(game.get("outcome","")) == "W" else Color("ffa08a")
			_result_card(recap,game,color)
	var filters = HBoxContainer.new()
	var group = ButtonGroup.new()
	filters.add_theme_constant_override("separation",10)
	content.add_child(filters)
	for category in ["ALL","DECISIONS","DEVELOPMENT","STORIES"]:
		var button = Button.new()
		button.text = category
		button.toggle_mode = true
		button.button_group = group
		button.button_pressed = category == filter_name
		button.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		button.custom_minimum_size.y = 40
		button.pressed.connect(_set_filter.bind(category))
		filters.add_child(button)
	stories_box = VBoxContainer.new()
	stories_box.add_theme_constant_override("separation",16)
	content.add_child(stories_box)
	_render_stories()
	# A short entrance makes refreshes legible without delaying decisions.
	hero.modulate.a = 0.0
	create_tween().tween_property(hero,"modulate:a",1.0,0.25)

func _set_filter(category: String) -> void:
	filter_name = category
	_render_stories()

func _render_stories() -> void:
	for child in stories_box.get_children():
		stories_box.remove_child(child)
		child.queue_free()
	var count = 0
	for story in payload.get("stories",[]):
		var destination = str(story.get("destination",""))
		var development = destination == "DEVELOPMENT"
		var storyline = destination == "STORIES"
		if filter_name == "DEVELOPMENT" and not development:
			continue
		if filter_name == "STORIES" and not storyline:
			continue
		if filter_name == "DECISIONS" and (development or storyline or str(story.get("category","")) == "ON THE COURT"):
			continue
		count += 1
		var card = _card(stories_box,DS.GOLD if int(story.get("priority",2)) == 0 else primary)
		card.add_child(_label(str(story.get("category","")).to_upper()+" • "+("ACT NOW" if int(story.get("priority",2)) == 0 else "IN FOCUS"),12,DS.GOLD))
		if not str(story.get("player_id","")).is_empty():
			var portrait = Portrait.new()
			portrait.custom_minimum_size = Vector2(0,92)
			card.add_child(portrait)
			portrait.configure({"player_id":str(story.player_id),"name":str(story.get("name",story.title))})
		card.add_child(_label(str(story.get("title","")),22))
		card.add_child(_label(str(story.get("detail","")),15))
		card.add_child(_label("SOURCE • "+str(story.get("evidence","Saved franchise snapshot")),12,DS.MUTED))
		var action = Button.new()
		action.text = "OPEN "+str(story.get("destination","ROSTER"))
		action.custom_minimum_size.y = 42
		action.pressed.connect(_navigate.bind(str(story.get("destination","ROSTER"))))
		card.add_child(action)
	if count == 0:
		stories_box.add_child(_label("No stories in this category for the current snapshot.",15,DS.MUTED))

func _navigate(page: String) -> void:
	navigate_requested.emit(page)

func _clear_content() -> void:
	for child in content.get_children():
		if child != status:
			content.remove_child(child)
			child.queue_free()

func _card(parent: Node, border: Color) -> VBoxContainer:
	var panel = PanelContainer.new()
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var style = StyleBoxFlat.new()
	style.bg_color = DS.PANEL_ALT
	style.border_color = Color(border,.55)
	style.set_border_width_all(1)
	style.set_corner_radius_all(16)
	for side in ["left","right","top","bottom"]:
		style.set("content_margin_"+side,18)
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
	bytes.resize(13230 * 2)
	for i in range(13230):
		var t = float(i) / 22050.0
		var envelope = sin(PI * float(i) / 13230.0)
		var chord = sin(TAU * 392.0 * t) + 0.6 * sin(TAU * 493.88 * t) + 0.4 * sin(TAU * 587.33 * t)
		bytes.encode_s16(i * 2,int(3000 * envelope * chord))
	wave.data = bytes
	audio_player.stream = wave
	audio_player.play()

func _result_card(parent: Node, game: Dictionary, color: Color) -> void:
	var body = _card(parent,color)
	var row = HBoxContainer.new()
	body.add_child(row)
	var logo = Logo.new()
	logo.custom_minimum_size = Vector2(54,54)
	row.add_child(logo)
	logo.configure(str(game.opponent))
	var score = _label("%s  •  %s–%s vs %s  •  DAY %s" % [str(game.outcome),str(game.score),str(game.against),str(game.opponent),str(game.day)],19,color)
	score.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row.add_child(score)
	var comparison = HBoxContainer.new()
	comparison.add_theme_constant_override("separation",3)
	body.add_child(comparison)
	for entry in [[int(game.score),primary],[int(game.against),Color("7c879c")]]:
		var bar = ColorRect.new()
		bar.color = entry[1]
		bar.custom_minimum_size.y = 8
		bar.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		bar.size_flags_stretch_ratio = max(1.0,float(entry[0]))
		comparison.add_child(bar)
	body.add_child(_label("TEAM POINTS / OPPONENT POINTS",10,DS.MUTED))
