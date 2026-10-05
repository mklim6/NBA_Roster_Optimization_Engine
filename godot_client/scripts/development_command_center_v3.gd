extends Control
const DS = preload("res://scripts/design_system_v3.gd")
const Portrait = preload("res://scripts/player_portrait_v3.gd")
const Logo = preload("res://scripts/team_logo_v3.gd")
const URL = "http://127.0.0.1:8765/v3/development-goals"
signal navigate_requested(page: String)
var request: HTTPRequest
var content: VBoxContainer
var status: Label
var board: Dictionary = {}
var forms: Array = []
var review: VBoxContainer
var preview_button: Button
var confirm_button: Button
var submitted: Array = []
var pending_action = ""
var primary = DS.TEAM_PRIMARY

func _ready() -> void:
	name = "DevelopmentCommandCenter"
	var background = ColorRect.new()
	background.color = DS.BG
	background.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(background)
	var scroll = ScrollContainer.new()
	scroll.name = "DevelopmentCommandScroll"
	scroll.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	scroll.vertical_scroll_mode = ScrollContainer.SCROLL_MODE_AUTO
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
	status = _label("Connecting to your development board…",13,DS.MUTED)
	content.add_child(status)
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
	pending_action = ""
	board.clear()
	_clear_content()
	status.text = "Loading the current franchise development board…"
	if request.request(URL) != OK:
		status.text = "Development request could not start. Return to this page to retry."

func _completed(result: int, code: int, _headers: PackedStringArray, bytes: PackedByteArray) -> void:
	var data = JSON.parse_string(bytes.get_string_from_utf8())
	if result != HTTPRequest.RESULT_SUCCESS or typeof(data) != TYPE_DICTIONARY or code != 200:
		_set_form_busy(false)
		status.text = str(data.get("detail","Development staff unavailable. Refresh this page to retry.")) if typeof(data) == TYPE_DICTIONARY else "Development staff unavailable. Refresh this page to retry."
		if confirm_button != null and is_instance_valid(confirm_button):
			confirm_button.visible = false
		if preview_button != null and is_instance_valid(preview_button):
			preview_button.disabled = false
		return
	if pending_action == "preview":
		if JSON.stringify(_selections()) != JSON.stringify(submitted):
			status.text = "Your plan changed during preview. Review the updated plan again."
			preview_button.disabled = false
			pending_action = ""
			return
		_clear(review)
		for goal in data.get("goals",[]):
			_goal_card(review,goal)
		confirm_button.visible = true
		confirm_button.disabled = false
		preview_button.disabled = false
		status.text = "PREVIEW • These targets become fixed commitments for this season when you confirm."
	else:
		configure(data)
	pending_action = ""

func configure(data: Dictionary) -> void:
	board = data.duplicate(true)
	_clear_content()
	status.text = "LIVE DEVELOPMENT BOARD • %s • %s" % [str(board.get("season","")),str(board.get("phase","")).replace("_"," ").to_upper()]
	var hero = _card(content,primary)
	var logo = Logo.new()
	logo.custom_minimum_size = Vector2(70,70)
	hero.add_child(logo)
	logo.configure(str(board.get("team","")))
	hero.add_child(_label("BUILD THE NEXT GENERATION",30,DS.GOLD))
	hero.add_child(_label("Turn roster potential into a season you can measure.",16))
	hero.add_child(_label(str(board.get("rules","")),13,DS.MUTED))
	var buttons = HBoxContainer.new()
	buttons.add_theme_constant_override("separation",10)
	hero.add_child(buttons)
	for destination in [["OPEN TRAINING CAMP","OFFSEASON"],["EXPLORE CAREER HISTORIES","FRONT OFFICE"]]:
		var action = Button.new()
		action.text = destination[0]
		action.custom_minimum_size.y = 42
		action.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		action.pressed.connect(func(): navigate_requested.emit(destination[1]))
		buttons.add_child(action)
	if bool(board.get("committed",false)):
		var goals: Array = board.get("goals",[])
		var met = 0
		for goal in goals:
			if str(goal.status) in ["target_met","achieved"]:
				met += 1
		content.add_child(_label("YOUR SEASON COMMITMENTS • %s / %s TARGETS MET" % [met,goals.size()],22,DS.GOLD))
		for goal in goals:
			_goal_card(content,goal)
		content.add_child(_label("Targets are fixed for this season. Current targets can move back below their threshold; archived outcomes use closing season evidence.",13,DS.MUTED))
	elif bool(board.get("can_commit",false)):
		_build_planner()
	else:
		content.add_child(_label("No commitments for this season. New plans open during regular season or offseason.",16,DS.MUTED))
	_build_archive()

func _build_planner() -> void:
	content.add_child(_label("SET THE SEASON AGENDA",22,DS.GOLD))
	content.add_child(_label("Choose up to three players. One goal each. Preview the targets before committing your season plan.",14,DS.MUTED))
	for i in range(3):
		var card = _card(content,DS.BORDER)
		card.add_child(_label("PRIORITY %s" % (i+1),12,DS.ACCENT))
		var player = OptionButton.new()
		player.name = "GoalPlayer%s" % i
		player.add_item("Leave this priority empty")
		player.custom_minimum_size.y = 44
		player.clip_text = true
		for row in board.get("players",[]):
			player.add_item(str(row.name))
		card.add_child(player)
		var metric = OptionButton.new()
		metric.name = "GoalMetric%s" % i
		for text in ["Shooting growth","Playmaking growth","Defense growth","Rebounding growth","Playing opportunity"]:
			metric.add_item(text)
		metric.custom_minimum_size.y = 42
		card.add_child(metric)
		var target = OptionButton.new()
		target.name = "GoalTarget%s" % i
		target.custom_minimum_size.y = 42
		card.add_child(target)
		var detail = _label("Choose a player to inspect the baseline.",12,DS.MUTED)
		card.add_child(detail)
		forms.append({"player":player,"metric":metric,"target":target,"detail":detail})
		player.item_selected.connect(func(_index): _update_form(i))
		metric.item_selected.connect(func(_index): _update_form(i))
		target.item_selected.connect(func(_index): _invalidate_preview())
		_update_form(i)
	preview_button = Button.new()
	preview_button.text = "REVIEW SEASON PLAN"
	preview_button.custom_minimum_size.y = 48
	preview_button.pressed.connect(func(): _submit("preview"))
	content.add_child(preview_button)
	review = VBoxContainer.new()
	review.add_theme_constant_override("separation",12)
	content.add_child(review)
	confirm_button = Button.new()
	confirm_button.text = "COMMIT SEASON GOALS • SAVE FIXED TARGETS"
	confirm_button.custom_minimum_size.y = 48
	confirm_button.visible = false
	confirm_button.pressed.connect(func(): _submit("execute"))
	content.add_child(confirm_button)

func _update_form(index: int) -> void:
	var form: Dictionary = forms[index]
	form.target.clear()
	var opportunity = form.metric.selected == 4
	for value in ([10,15,20,25,30] if opportunity else [1,2,3]):
		form.target.add_item("%s MPG • at least 10 games" % value if opportunity else "+%s skill points" % value)
	form.metric.disabled = form.player.selected == 0
	form.target.disabled = form.player.selected == 0
	if form.player.selected > 0:
		var row: Dictionary = board.players[form.player.selected-1]
		var metric = ["shooting","playmaking","defense","rebounding","opportunity"][form.metric.selected]
		var value = row.get("minutes_per_game",null) if opportunity else row.get("skills",{}).get(metric,null)
		form.detail.text = "BASELINE %s • %s GAMES PLAYED" % [_number(value),row.get("games",0)]
	else:
		form.detail.text = "Choose a player to inspect the baseline."
	_invalidate_preview()

func _invalidate_preview() -> void:
	if review != null and is_instance_valid(review):
		_clear(review)
	if confirm_button != null and is_instance_valid(confirm_button):
		confirm_button.visible = false

func _selections() -> Array:
	var selections: Array = []
	for form in forms:
		if form.player.selected == 0:
			continue
		var row: Dictionary = board.players[form.player.selected-1]
		var metric = ["shooting","playmaking","defense","rebounding","opportunity"][form.metric.selected]
		var choice = {"player_id":str(row.player_id),"metric":metric}
		if metric == "opportunity":
			choice["target"] = [10,15,20,25,30][form.target.selected]
		else:
			choice["delta"] = form.target.selected+1
		selections.append(choice)
	return selections

func _submit(action: String) -> void:
	submitted = _selections()
	if submitted.is_empty():
		status.text = "Choose at least one player goal."
		return
	pending_action = action
	_set_form_busy(action == "execute")
	preview_button.disabled = true
	confirm_button.disabled = true
	var body = {"action":action,"selections":submitted,"expected_working_save_sha256":board.get("working_save_sha256","")}
	status.text = "Reviewing your season agenda…"
	if request.request(URL,["Content-Type: application/json"],HTTPClient.METHOD_POST,JSON.stringify(body)) != OK:
		status.text = "Development request could not start. Refresh this page."
		confirm_button.visible = false
		preview_button.disabled = false
		_set_form_busy(false)

func _set_form_busy(busy: bool) -> void:
	for form in forms:
		form.player.disabled = busy
		form.metric.disabled = busy or form.player.selected == 0
		form.target.disabled = busy or form.player.selected == 0

func _goal_card(parent: Node, goal: Dictionary) -> void:
	var met = str(goal.get("status","")) in ["target_met","achieved"]
	var card = _card(parent,DS.GOOD if met else DS.BORDER)
	var portrait = Portrait.new()
	portrait.custom_minimum_size = Vector2(96,78)
	card.add_child(portrait)
	portrait.configure({"player_id":str(goal.player_id),"name":str(goal.name)})
	card.add_child(_label(str(goal.name) + " • " + str(goal.metric).to_upper(),21,DS.GOLD))
	card.add_child(_label(str(goal.season) + " • " + str(goal.status).replace("_"," ").to_upper(),12,DS.GOOD if met else DS.MUTED))
	card.add_child(_label("BASELINE %s    NOW %s    TARGET %s" % [_number(goal.baseline),_number(goal.get("current",null)),_number(goal.target)],16))
	if goal.get("current",null) != null:
		var bar = ProgressBar.new()
		bar.name = "GoalProgress_" + str(goal.player_id)
		bar.value = float(goal.get("progress",0))*100
		bar.custom_minimum_size.y = 16
		var fill = StyleBoxFlat.new()
		fill.bg_color = DS.GOOD if met else DS.ACCENT
		fill.set_corner_radius_all(6)
		var track = StyleBoxFlat.new()
		track.bg_color = DS.PANEL
		track.set_corner_radius_all(6)
		bar.add_theme_stylebox_override("fill",fill)
		bar.add_theme_stylebox_override("background",track)
		card.add_child(bar)
	else:
		card.add_child(_label("Progress unavailable until closing evidence is recorded.",13,DS.WARNING))
	card.add_child(_label(str(goal.get("evidence","")),12,DS.MUTED))
	if goal.metric == "opportunity":
		card.add_child(_label("%s / 10 REQUIRED APPEARANCES" % goal.get("games",0),12,DS.ACCENT))
	if bool(goal.get("departed",false)):
		card.add_child(_label("PLAYER HAS LEFT THIS ROSTER • Your original commitment remains in franchise history.",12,DS.WARNING))

func _build_archive() -> void:
	content.add_child(_label("PAST SEASON AGENDAS",20,DS.GOLD))
	var archive: Array = board.get("archive",[])
	if archive.is_empty():
		content.add_child(_label("Your first season agenda will appear here after the franchise advances. Missing closing evidence is marked unverified.",14,DS.MUTED))
		return
	var toggle = CheckButton.new()
	toggle.text = "Show previous commitments • %s recorded" % board.get("archived_count",archive.size())
	content.add_child(toggle)
	var history = VBoxContainer.new()
	history.visible = false
	history.add_theme_constant_override("separation",12)
	content.add_child(history)
	toggle.toggled.connect(func(value): history.visible = value)
	for goal in archive:
		_goal_card(history,goal)
	if int(board.get("archived_count",0)) > archive.size():
		history.add_child(_label("Showing the latest %s archived commitments." % archive.size(),12,DS.MUTED))

func _clear_content() -> void:
	forms.clear()
	review = null
	preview_button = null
	confirm_button = null
	for child in content.get_children():
		if child != status:
			content.remove_child(child)
			child.queue_free()

func _clear(parent: Node) -> void:
	for child in parent.get_children():
		parent.remove_child(child)
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

func _number(value) -> String:
	return "Unavailable" if value == null else "%.1f" % float(value)

func _label(text: String, font_size: int, color: Color = DS.TEXT) -> Label:
	var label = Label.new()
	label.text = text
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.add_theme_font_size_override("font_size",font_size)
	label.add_theme_color_override("font_color",color)
	return label
