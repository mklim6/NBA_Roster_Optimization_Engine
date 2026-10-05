extends Control
const DS = preload("res://scripts/design_system_v3.gd")
const Portrait = preload("res://scripts/player_portrait_v3.gd")
const Logo = preload("res://scripts/team_logo_v3.gd")
signal navigate_requested(page: String)
var content: VBoxContainer
var status: Label
var request: HTTPRequest
var board: Dictionary = {}
var player_picker: OptionButton
var meeting_picker: OptionButton
var role_picker: OptionButton
var review_picker: OptionButton
var meeting_button: Button
var promise_button: Button
var confirm_button: Button
var workspace: VBoxContainer
var review_box: VBoxContainer
var player: Dictionary = {}
var selected_id = ""
var pending_action = ""
var submitted: Dictionary = {}
var preview_ready = false
var primary = DS.TEAM_PRIMARY

func _ready() -> void:
	name = "LockerRoom"
	var bg = ColorRect.new()
	bg.color = DS.BG
	bg.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(bg)
	var scroll = ScrollContainer.new()
	scroll.name = "LockerRoomScroll"
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
	status = _label("Connecting to your locker room…",13,DS.MUTED)
	content.add_child(status)
	request = HTTPRequest.new()
	request.timeout = 45
	request.request_completed.connect(_completed)
	add_child(request)

func apply_team_brand(_team: String, color: Color, _secondary: Color) -> void:
	primary = color

func refresh() -> void:
	if request == null:
		return
	request.cancel_request()
	pending_action = ""
	preview_ready = false
	_clear(content,status)
	board.clear()
	status.text = "Loading saved roles, morale and conversation memory…"
	if request.request("http://127.0.0.1:8765/v3/locker-room") != OK:
		_error("Could not start locker-room request.")

func _completed(result: int, code: int, _headers: PackedStringArray, bytes: PackedByteArray) -> void:
	var data = JSON.parse_string(bytes.get_string_from_utf8())
	if result != HTTPRequest.RESULT_SUCCESS or code != 200 or typeof(data) != TYPE_DICTIONARY:
		var message = str(data.get("detail","Locker room unavailable. Refresh to retry.")) if typeof(data) == TYPE_DICTIONARY else "Locker room unavailable. Refresh to retry."
		_error(message)
		return
	if pending_action == "preview":
		preview_ready = true
		_render_effect(data.effect)
		confirm_button.visible = true
		confirm_button.disabled = false
		_set_busy(false)
		status.text = "PREVIEW • Review the consequences below before saving your response."
	else:
		configure(data)
		if bool(data.get("applied",false)):
			status.text = "CONVERSATION SAVED • Your player’s expectations and memory are updated."
	pending_action = ""

func _error(message: String) -> void:
	pending_action = ""
	preview_ready = false
	_set_busy(false)
	if is_instance_valid(confirm_button):
		confirm_button.visible = false
	status.text = message
	if board.is_empty():
		content.add_child(_button("RETRY LOCKER ROOM",refresh))

func configure(data: Dictionary) -> void:
	board = data.duplicate(true)
	_clear(content,status)
	preview_ready = false
	status.text = "%s • %s • SAVED FRANCHISE CONTEXT" % [str(board.get("season","")),str(board.get("phase","")).replace("_"," ").to_upper()]
	var hero = _card(content,primary)
	var logo = Logo.new()
	logo.custom_minimum_size = Vector2(60,60)
	hero.add_child(logo)
	logo.configure(str(board.get("team","")))
	hero.add_child(_label("INSIDE THE LOCKER ROOM",30,DS.GOLD))
	hero.add_child(_label("Build trust. Set expectations. Follow through.",17))
	hero.add_child(_label("TEAM CHEMISTRY • %.1f / 100" % float(board.get("chemistry",0)),19,DS.GOLD))
	hero.add_child(_label(str(board.get("rules","")),13,DS.MUTED))
	hero.add_child(_button("REFRESH LOCKER ROOM",refresh))
	player_picker = OptionButton.new()
	player_picker.custom_minimum_size.y = 42
	content.add_child(player_picker)
	var selected = 0
	for index in range(board.get("players",[]).size()):
		var row = board.players[index]
		player_picker.add_item(str(row.name)+" • "+str(row.status))
		if str(row.player_id) == selected_id:
			selected = index
	player_picker.item_selected.connect(_select_player)
	workspace = VBoxContainer.new()
	workspace.add_theme_constant_override("separation",16)
	content.add_child(workspace)
	if board.get("players",[]).is_empty():
		workspace.add_child(_label("No roster players are available for this discussion.",15,DS.MUTED))
		return
	player_picker.select(selected)
	_select_player(selected)

func _select_player(index: int) -> void:
	player_picker.select(index)
	preview_ready = false
	status.text = "%s • %s • SAVED FRANCHISE CONTEXT" % [str(board.get("season","")),str(board.get("phase","")).replace("_"," ").to_upper()]
	player = board.players[index].duplicate(true)
	selected_id = str(player.player_id)
	_clear(workspace)
	var profile = _card(workspace,primary)
	var portrait = Portrait.new()
	portrait.custom_minimum_size = Vector2(0,125)
	profile.add_child(portrait)
	portrait.configure(player)
	profile.add_child(_label(str(player.name),28,DS.GOLD))
	profile.add_child(_label("AGE %s • OVERALL %.1f • %s" % [str(player.age),float(player.overall),str(player.status).to_upper()],13,DS.MUTED))
	_meter(profile,"MORALE",float(player.score))
	_meter(profile,"ROLE SATISFACTION",float(player.role_satisfaction))
	profile.add_child(_label("TRADE PRESSURE • %.1f / 100 • %s" % [float(player.trade_request_risk),str(player.trade_request_status)],13,DS.MUTED))
	var perspective = _card(workspace,DS.GOLD)
	perspective.add_child(_label("PLAYER PERSPECTIVE • SIMULATED DIALOGUE",12,DS.GOLD))
	perspective.add_child(_label(str(player.dialogue),21))
	perspective.add_child(_label("Based on saved role expectations and usage context.",12,DS.MUTED))
	perspective.add_child(_label("EXPECTED • %s / %.1f MIN\nUSAGE CONTEXT • %.1f MIN\nROTATION PLAN • %.1f MIN" % [str(player.expected_role),float(player.expected_minutes),float(player.actual_minutes),float(player.planned_minutes)],16))
	perspective.add_child(_label(str(player.usage_basis),12,DS.MUTED))
	for reason in player.get("reasons",[]):
		perspective.add_child(_label("• "+str(reason),13,DS.MUTED))
	var promise = player.promise
	if bool(promise.promise_active):
		var agreement = _card(workspace,primary)
		agreement.add_child(_label("ROLE AGREEMENT • "+str(promise.promise_status).to_upper(),18,DS.GOLD))
		agreement.add_child(_label("%s • %.1f MIN • REVIEW AFTER %s GAMES" % [str(promise.role),float(promise.minutes),str(promise.review_after_games)],15))
		agreement.add_child(_label("%s reviewed • %s met • %s missed" % [str(promise.games_since_set),str(promise.met_games),str(promise.missed_games)],14,DS.MUTED))
		agreement.add_child(_button("REVIEW GAME DAY ROTATION",func(): navigate_requested.emit("GAME DAY")))
	var meeting = _card(workspace,primary)
	meeting.add_child(_label("CHOOSE YOUR RESPONSE",19,DS.GOLD))
	meeting_picker = OptionButton.new()
	meeting_picker.custom_minimum_size.y = 42
	for option in board.meetings:
		meeting_picker.add_item(str(option.action))
	meeting.add_child(meeting_picker)
	var explanation = _label(str(board.meetings[0].detail),14,DS.MUTED)
	meeting.add_child(explanation)
	meeting_picker.item_selected.connect(func(index: int): explanation.text = str(board.meetings[index].detail); _invalidate())
	meeting.add_child(_label("MEETING COOLDOWN • %s GAMES\nSUPPORT • %s GAMES / PATIENCE • %s GAMES" % [str(player.meeting_cooldown_games),str(player.meeting_support_games),str(player.patience_games)],13,DS.MUTED))
	meeting_button = _button("PREVIEW CONVERSATION",func(): _submit("preview","meeting"))
	meeting.add_child(meeting_button)
	var role = _card(workspace,primary)
	role.add_child(_label("MAKE A ROLE AGREEMENT",19,DS.GOLD))
	role.add_child(_label("Commit to a role and minutes, then let game results determine whether you kept your word.",14,DS.MUTED))
	role_picker = OptionButton.new()
	role_picker.custom_minimum_size.y = 42
	for option in board.roles:
		role_picker.add_item("%s • %.0f MIN" % [str(option.role),float(option.minutes)])
	role_picker.item_selected.connect(func(_index: int): _invalidate())
	role.add_child(role_picker)
	review_picker = OptionButton.new()
	review_picker.custom_minimum_size.y = 42
	for games in board.reviews:
		review_picker.add_item("REVIEW AFTER %s GAMES" % str(games))
	review_picker.select(1)
	review_picker.item_selected.connect(func(_index: int): _invalidate())
	role.add_child(review_picker)
	role.add_child(_label("A promise changes expectations. Set the actual lineup and minutes in Game Day. Active agreements stay fixed until review or an honest reset.",13,DS.MUTED))
	promise_button = _button("PREVIEW ROLE AGREEMENT",func(): _submit("preview","promise"))
	role.add_child(promise_button)
	review_box = VBoxContainer.new()
	review_box.add_theme_constant_override("separation",12)
	workspace.add_child(review_box)
	confirm_button = _button("CONFIRM RESPONSE • SAVE CONSEQUENCES",func(): _submit("execute",str(submitted.get("kind",""))))
	confirm_button.visible = false
	workspace.add_child(confirm_button)
	_render_history()
	_set_busy(false)

func _draft(kind: String) -> Dictionary:
	if kind == "meeting":
		return {"kind":kind,"player_id":selected_id,"meeting":str(board.meetings[meeting_picker.selected].action)}
	return {"kind":kind,"player_id":selected_id,"role":str(board.roles[role_picker.selected].role),"review_games":int(board.reviews[review_picker.selected])}

func _submit(action: String, kind: String) -> void:
	if action == "execute" and (not preview_ready or submitted != _draft(kind)):
		_invalidate()
		return
	submitted = _draft(kind)
	pending_action = action
	var body = submitted.duplicate(true)
	body.action = action
	body.expected_working_save_sha256 = board.get("working_save_sha256","")
	_set_busy(true)
	status.text = "Reviewing your response…"
	if request.request("http://127.0.0.1:8765/v3/locker-room",["Content-Type: application/json"],HTTPClient.METHOD_POST,JSON.stringify(body)) != OK:
		_error("Could not start the conversation. Refresh and retry.")

func _set_busy(busy: bool) -> void:
	for control in [player_picker,meeting_picker,role_picker,review_picker]:
		if is_instance_valid(control):
			control.disabled = busy
	if is_instance_valid(meeting_button):
		meeting_button.disabled = busy or not bool(player.get("can_meet",false))
	if is_instance_valid(promise_button):
		promise_button.disabled = busy or not bool(player.get("can_promise",false))
	if is_instance_valid(confirm_button):
		confirm_button.disabled = busy

func _invalidate() -> void:
	preview_ready = false
	status.text = "Response changed. Preview the updated choice before saving."
	if is_instance_valid(confirm_button):
		confirm_button.visible = false
	if is_instance_valid(review_box):
		_clear(review_box)

func _render_effect(effect: Dictionary) -> void:
	_clear(review_box)
	var card = _card(review_box,DS.GOLD)
	card.add_child(_label("RESPONSE PREVIEW • "+str(effect.name),20,DS.GOLD))
	card.add_child(_label(str(effect.detail),15))
	card.add_child(_label("MORALE • %.1f → %.1f\nTEAM CHEMISTRY • %.1f → %.1f\nROLE • %s / %.1f MIN\nMEETING COOLDOWN • %s GAMES" % [float(effect.before.score),float(effect.after.score),float(effect.chemistry_before),float(effect.chemistry_after),str(effect.after.expected_role),float(effect.after.expected_minutes),str(effect.after.meeting_cooldown_games)],17))
	card.add_child(_label("Preview has not changed the franchise. Confirm to save this response.",12,DS.MUTED))

func _render_history() -> void:
	var history = _card(workspace,primary)
	history.add_child(_label("CONVERSATION MEMORY",19,DS.GOLD))
	if player.get("history",[]).is_empty():
		history.add_child(_label("Your first conversation or agreement will begin this player’s memory here.",14,DS.MUTED))
		return
	for event in player.history:
		var title = str(event.get("type","")).replace("-"," ").to_upper()
		var detail = str(event.get("action",event.get("role",event.get("verdict","Automatic role expectations restored"))))
		history.add_child(_label("%s • %s • DAY %s\n%s" % [title,str(event.get("season","")),str(event.get("day",event.get("set_day",0))),detail],14,DS.MUTED))

func _meter(parent: Node, title: String, value: float) -> void:
	parent.add_child(_label("%s • %.1f / 100" % [title,value],15))
	var bar = ProgressBar.new()
	bar.value = value
	bar.show_percentage = false
	bar.custom_minimum_size.y = 12
	var fill = StyleBoxFlat.new()
	fill.bg_color = Color("70d5a2") if value >= 70 else DS.GOLD if value >= 49 else Color("f28c85")
	bar.add_theme_stylebox_override("fill",fill)
	parent.add_child(bar)

func _clear(parent: Node, keep: Node = null) -> void:
	for child in parent.get_children():
		if child != keep:
			parent.remove_child(child)
			child.queue_free()

func _button(text: String, callback: Callable) -> Button:
	var button = Button.new()
	button.text = text
	button.custom_minimum_size.y = 42
	button.pressed.connect(callback)
	return button

func _card(parent: Node, border: Color) -> VBoxContainer:
	var panel = PanelContainer.new()
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var style = StyleBoxFlat.new()
	style.bg_color = DS.PANEL_ALT
	style.border_color = Color(border,.5)
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
