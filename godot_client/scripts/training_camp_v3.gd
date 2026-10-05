extends VBoxContainer
const DS = preload("res://scripts/design_system_v3.gd")
const Portrait = preload("res://scripts/player_portrait_v3.gd")
const URL = "http://127.0.0.1:8765/v3/training-camp"
var request: HTTPRequest
var report: Dictionary = {}
var plans: Dictionary = {}
var status: Label
var grid: GridContainer
var results: VBoxContainer
var preview_button: Button
var confirm_button: Button
var sound_toggle: CheckButton
var audio_player: AudioStreamPlayer
var pending_action = ""
var preview_ready = false
var submitted_plans = ""
var mentors: Dictionary = {}
var mentor_selectors: Dictionary = {}
var mentor_choices: Dictionary = {}

func _ready() -> void:
	name = "TrainingCamp"
	add_theme_constant_override("separation", 14)
	add_child(_label("THE DEVELOPMENT FACILITY", 24, DS.GOLD))
	add_child(_label("Shape the next chapter of your roster. Three focused coaching slots. One camp each offseason.", 14, DS.MUTED))
	add_child(_label("VETERAN PARTNERSHIPS • Age 28+ • One learner age 24 or younger • Eight-point skill edge • Mentors give up focused training this camp.", 12, DS.GOLD))
	status = _label("Connecting to training staff…", 14)
	add_child(status)
	grid = GridContainer.new()
	grid.columns = 2
	grid.add_theme_constant_override("h_separation", 12)
	grid.add_theme_constant_override("v_separation", 12)
	add_child(grid)
	preview_button = Button.new()
	preview_button.text = "PREVIEW CAMP RESULTS"
	preview_button.custom_minimum_size.y = 46
	preview_button.pressed.connect(func(): _submit("preview"))
	add_child(preview_button)
	results = VBoxContainer.new()
	results.add_theme_constant_override("separation", 10)
	add_child(results)
	confirm_button = Button.new()
	confirm_button.text = "CONFIRM CAMP • SAVE THESE OUTCOMES"
	confirm_button.custom_minimum_size.y = 46
	confirm_button.visible = false
	confirm_button.pressed.connect(func(): _submit("execute"))
	add_child(confirm_button)
	sound_toggle = CheckButton.new()
	sound_toggle.text = "Camp result sound"
	sound_toggle.button_pressed = false
	add_child(sound_toggle)
	audio_player = AudioStreamPlayer.new()
	audio_player.volume_db = -20
	add_child(audio_player)
	request = HTTPRequest.new()
	request.timeout = 45
	add_child(request)
	request.request_completed.connect(_completed)
	request.request(URL)
	resized.connect(_resize_cards)

func _resize_cards() -> void:
	if grid != null:
		grid.columns = 1 if size.x < 760 else 2

func _submit(action: String) -> void:
	if action == "execute" and not preview_ready:
		return
	pending_action = action
	submitted_plans = JSON.stringify([plans, mentors])
	preview_button.disabled = true
	confirm_button.disabled = true
	status.text = "Staff is reviewing your plan…"
	var body = {"action": action, "assignments": plans, "mentors": mentors, "expected_working_save_sha256": report.get("working_save_sha256", "")}
	var error = request.request(URL, ["Content-Type: application/json"], HTTPClient.METHOD_POST, JSON.stringify(body))
	if error != OK:
		status.text = "Unable to start camp request. Refresh the Offseason page."
		confirm_button.visible = false

func _completed(result: int, code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	var data = JSON.parse_string(body.get_string_from_utf8())
	if result != HTTPRequest.RESULT_SUCCESS or typeof(data) != TYPE_DICTIONARY:
		status.text = "Training staff unavailable. Refresh the Offseason page to retry."
		confirm_button.visible = false
		return
	if code != 200:
		status.text = str(data.get("detail", "Camp unavailable."))
		preview_ready = false
		confirm_button.visible = false
		preview_button.disabled = false
		return
	if pending_action == "preview":
		if JSON.stringify([plans, mentors]) != submitted_plans:
			status.text = "Plan changed during preview. Preview your updated plan."
			preview_button.disabled = plans.is_empty()
			pending_action = ""
			return
		preview_ready = true
		_render_results(data.get("results", []), true)
		confirm_button.visible = true
		confirm_button.disabled = false
		preview_button.disabled = false
		status.text = "PREVIEW • Exact outcomes for this plan. Confirm to apply to the working save."
	else:
		report = data
		_render_roster()
		_render_results(data.get("results", []), false)
		confirm_button.visible = false
		preview_ready = false
		if bool(data.get("completed", false)):
			status.text = "CAMP COMPLETE • Outcomes saved across the league."
		elif not bool(data.get("available", false)):
			status.text = "CAMP OPENS DURING OFFSEASON • Current phase: %s. Explore your players below; return after the season to run camp." % str(data.get("phase", "unknown")).replace("_", " ").to_upper()
		else:
			status.text = str(data.get("detail", ""))
	pending_action = ""

func _render_roster() -> void:
	_clear(grid)
	mentor_selectors.clear()
	mentor_choices.clear()
	var available = bool(report.get("available", false))
	preview_button.disabled = not available or plans.is_empty()
	for player in report.get("players", []):
		var card = _card(grid)
		var portrait = Portrait.new()
		portrait.custom_minimum_size = Vector2(100, 86)
		card.add_child(portrait)
		portrait.configure(player)
		card.add_child(_label(str(player.get("name", "")), 19))
		card.add_child(_label("AGE %.0f • OVR %.1f • POT %.1f" % [float(player.age), float(player.overall), float(player.potential)], 12, DS.MUTED))
		for focus in report.get("focuses", []):
			var skill = float(player.skills.get(focus, 0))
			card.add_child(_label("%s  %.1f" % [str(focus).to_upper(), skill], 11, DS.MUTED))
			var bar = ProgressBar.new()
			bar.show_percentage = false
			bar.value = skill
			bar.custom_minimum_size.y = 6
			var fill = StyleBoxFlat.new()
			fill.bg_color = DS.GOLD if skill >= 80 else DS.ACCENT
			fill.set_corner_radius_all(3)
			bar.add_theme_stylebox_override("fill", fill)
			card.add_child(bar)
		var choices = OptionButton.new()
		choices.custom_minimum_size.y = 42
		choices.add_item("Standard preparation • no focused slot")
		for focus in report.get("focuses", []):
			choices.add_item("%s • %.1f" % [str(focus).capitalize(), float(player.skills.get(focus, 0))])
		choices.disabled = not available
		card.add_child(choices)
		choices.item_selected.connect(_choose.bind(str(player.player_id), choices))
		if float(player.age) <= 24:
			var partner = OptionButton.new()
			partner.custom_minimum_size.y = 40
			partner.size_flags_horizontal = Control.SIZE_EXPAND_FILL
			partner.clip_text = true
			card.add_child(partner)
			mentor_selectors[str(player.player_id)] = partner
			partner.item_selected.connect(_choose_mentor.bind(str(player.player_id)))
	_refresh_mentors()
	_resize_cards()

func _choose(index: int, id: String, choices: OptionButton) -> void:
	if index == 0:
		plans.erase(id)
		mentors.erase(id)
	elif plans.has(id) or plans.size() < 3:
		plans[id] = report.focuses[index - 1]
	else:
		choices.select(0)
	_refresh_mentors()
	_invalidate_preview()

func _invalidate_preview() -> void:
	preview_ready = false
	confirm_button.visible = false
	_clear(results)
	status.text = "%s / 3 COACHING SLOTS • %s PARTNERSHIPS • Preview to review gains and skill tradeoffs." % [plans.size(), mentors.size()]
	preview_button.disabled = plans.is_empty()

func _refresh_mentors() -> void:
	for learner_id in mentor_selectors:
		var selector: OptionButton = mentor_selectors[learner_id]
		selector.clear()
		var ids: Array = []
		var learner: Dictionary = {}
		for row in report.get("players", []):
			if str(row.player_id) == learner_id:
				learner = row
		if not plans.has(learner_id):
			selector.add_item("Choose focused work to find a mentor")
			selector.disabled = true
			mentors.erase(learner_id)
			mentor_choices[learner_id] = ids
			continue
		selector.add_item("Solo training • no veteran partner")
		var focus = str(plans[learner_id])
		for row in report.get("players", []):
			var id = str(row.player_id)
			if float(row.age) < 28 or plans.has(id):
				continue
			if float(row.skills.get(focus,0)) - float(learner.get("skills",{}).get(focus,0)) < 8:
				continue
			var used = false
			for other in mentors:
				if other != learner_id and str(mentors[other]) == id:
					used = true
			if used:
				continue
			ids.append(id)
			selector.add_item("%s • %s %.1f" % [str(row.name), focus.capitalize(), float(row.skills.get(focus,0))])
		mentor_choices[learner_id] = ids
		selector.disabled = not bool(report.get("available",false)) or ids.is_empty()
		var selected = str(mentors.get(learner_id,""))
		if ids.has(selected):
			selector.select(ids.find(selected)+1)
		else:
			mentors.erase(learner_id)

func _choose_mentor(index: int, id: String) -> void:
	if index == 0:
		mentors.erase(id)
	else:
		mentors[id] = mentor_choices[id][index-1]
	_refresh_mentors()
	_invalidate_preview()

func _render_results(rows: Array, preview: bool) -> void:
	_clear(results)
	for row in rows:
		var card = _card(results)
		card.add_child(_label(str(row.name) + " • " + str(row.focus).to_upper(), 18, DS.GOLD))
		card.add_child(_label("%.2f → %.2f   (+%.2f)" % [float(row.before), float(row.after), float(row.gain)], 24, DS.GOOD))
		card.add_child(_label("%s: %.2f → %.2f • Overall: %.2f → %.2f" % [str(row.tradeoff).capitalize(), float(row.tradeoff_before), float(row.tradeoff_after), float(row.overall_before), float(row.overall_after)], 13, DS.MUTED))
		if str(row.get("mentor_name", "")) != "":
			card.add_child(_label("MENTORED BY %s • SOLO GAIN %+.2f • PARTNERSHIP GAIN %+.2f" % [str(row.mentor_name).to_upper(), float(row.get("unmentored_gain",0)), float(row.gain)], 12, DS.GOLD))
		if not preview:
			card.modulate.a = 0.0
			create_tween().tween_property(card, "modulate:a", 1.0, 0.45)
	if not rows.is_empty() and not preview and sound_toggle.button_pressed:
		_play_chime()

func _play_chime() -> void:
	var wave = AudioStreamWAV.new()
	wave.format = AudioStreamWAV.FORMAT_16_BITS
	wave.mix_rate = 22050
	var bytes = PackedByteArray()
	bytes.resize(11025 * 2)
	for i in range(11025):
		var envelope = sin(PI * float(i) / 11025.0)
		var sample = int(5000 * envelope * sin(TAU * (660.0 if i < 5500 else 880.0) * float(i) / 22050.0))
		bytes.encode_s16(i * 2, sample)
	wave.data = bytes
	audio_player.stream = wave
	audio_player.play()

func _clear(parent: Node) -> void:
	for child in parent.get_children():
		parent.remove_child(child)
		child.queue_free()

func _card(parent: Node) -> VBoxContainer:
	var panel = PanelContainer.new()
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var style = StyleBoxFlat.new()
	style.bg_color = DS.PANEL_ALT
	style.border_color = Color(DS.GOLD, .3)
	style.set_border_width_all(1)
	style.set_corner_radius_all(14)
	style.content_margin_left = 16
	style.content_margin_right = 16
	style.content_margin_top = 16
	style.content_margin_bottom = 16
	panel.add_theme_stylebox_override("panel", style)
	parent.add_child(panel)
	var column = VBoxContainer.new()
	column.add_theme_constant_override("separation", 8)
	panel.add_child(column)
	return column

func _label(text: String, font_size: int, color: Color = DS.TEXT) -> Label:
	var label = Label.new()
	label.text = text
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.add_theme_font_size_override("font_size", font_size)
	label.add_theme_color_override("font_color", color)
	return label
