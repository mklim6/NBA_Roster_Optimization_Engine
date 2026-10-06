extends Control
const DS = preload("res://scripts/design_system_v3.gd")
const Portrait = preload("res://scripts/player_portrait_v3.gd")
const Logo = preload("res://scripts/team_logo_v3.gd")
const URL = "http://127.0.0.1:8765/v3/development-goals"

# V3_50B_R1_DEVELOPMENT_VISUAL_REDESIGN
const VERSION := "v3-50b-r1-development-visual-redesign-v1.0.0-2026-10-05"

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
var secondary = DS.GOLD
var focused_player_id = ""


func focus_player(player_id: String) -> void:
	focused_player_id = player_id


func _ready() -> void:
	name = "DevelopmentCommandCenter"

	var background := ColorRect.new()
	background.color = DS.BG
	background.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(background)

	var scroll := ScrollContainer.new()
	scroll.name = "DevelopmentCommandScroll"
	scroll.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	scroll.vertical_scroll_mode = ScrollContainer.SCROLL_MODE_AUTO
	add_child(scroll)

	var margin := MarginContainer.new()
	margin.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	margin.add_theme_constant_override("margin_left", 24)
	margin.add_theme_constant_override("margin_right", 24)
	margin.add_theme_constant_override("margin_top", 18)
	margin.add_theme_constant_override("margin_bottom", 160)
	scroll.add_child(margin)

	content = VBoxContainer.new()
	content.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	content.add_theme_constant_override("separation", 14)
	margin.add_child(content)

	status = _label("Loading development center…", 11, DS.MUTED)
	status.name = "DevelopmentStatus"
	content.add_child(status)

	request = HTTPRequest.new()
	request.timeout = 45
	add_child(request)
	request.request_completed.connect(_completed)


func apply_team_brand(_team: String, color: Color, _secondary: Color) -> void:
	primary = color
	secondary = _secondary


func refresh() -> void:
	if request == null:
		return
	request.cancel_request()
	pending_action = ""
	board.clear()
	_clear_content()
	status.text = "Loading development center…"
	status.add_theme_color_override("font_color", DS.MUTED)
	if request.request(URL) != OK:
		status.text = "Development center could not load. Return to this page to retry."


func _completed(result: int, code: int, _headers: PackedStringArray, bytes: PackedByteArray) -> void:
	var data = JSON.parse_string(bytes.get_string_from_utf8())
	if result != HTTPRequest.RESULT_SUCCESS or typeof(data) != TYPE_DICTIONARY or code != 200:
		_set_form_busy(false)
		status.text = str(data.get("detail", "Development staff unavailable. Refresh this page to retry.")) if typeof(data) == TYPE_DICTIONARY else "Development staff unavailable. Refresh this page to retry."
		status.add_theme_color_override("font_color", DS.WARNING)
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
		for goal in data.get("goals", []):
			_goal_card(review, goal)
		confirm_button.visible = true
		confirm_button.disabled = false
		preview_button.disabled = false
		status.text = "PLAN REVIEW • Confirm when these are the development priorities you want to carry through the season."
		status.add_theme_color_override("font_color", DS.GOOD)
	else:
		configure(data)

	pending_action = ""


func configure(data: Dictionary) -> void:
	board = data.duplicate(true)
	_clear_content()

	var season_text := str(board.get("season", ""))
	var phase_text := str(board.get("phase", "")).replace("_", " ").to_upper()
	status.text = "%s • %s" % [season_text, phase_text]
	status.add_theme_color_override("font_color", primary.lerp(Color.WHITE, 0.34))

	_build_hero()
	_build_player_review()

	if bool(board.get("committed", false)):
		_build_committed_goals()
	elif bool(board.get("can_commit", false)):
		_build_planner()
	else:
		var unavailable := _surface_card(content, DS.BORDER, 0.04, 14)
		unavailable.add_child(_label("SEASON PLAN LOCKED", 16, DS.TEXT_STRONG))
		unavailable.add_child(_label("New development commitments open during the regular season or offseason.", 13, DS.MUTED))

	_build_archive()


func _build_hero() -> void:
	var panel := PanelContainer.new()
	panel.name = "DevelopmentHero"
	panel.custom_minimum_size = Vector2(0, 272)
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	panel.clip_contents = true
	panel.add_theme_stylebox_override("panel", _panel_style(Color(DS.PANEL, 0.96), Color(primary, 0.55), 20))
	content.add_child(panel)

	var gradient := Gradient.new()
	gradient.colors = PackedColorArray([Color(primary, 0.46), Color(primary, 0.18), Color(DS.BG, 0.98)])
	gradient.offsets = PackedFloat32Array([0.0, 0.44, 1.0])

	var texture := GradientTexture2D.new()
	texture.gradient = gradient
	texture.width = 256
	texture.height = 64
	texture.fill_from = Vector2(0.0, 0.18)
	texture.fill_to = Vector2(1.0, 0.82)

	var backdrop := TextureRect.new()
	backdrop.name = "DevelopmentHeroGradient"
	backdrop.texture = texture
	backdrop.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	backdrop.stretch_mode = TextureRect.STRETCH_SCALE
	backdrop.mouse_filter = Control.MOUSE_FILTER_IGNORE
	panel.add_child(backdrop)

	var margin := MarginContainer.new()
	margin.add_theme_constant_override("margin_left", 20)
	margin.add_theme_constant_override("margin_top", 16)
	margin.add_theme_constant_override("margin_right", 20)
	margin.add_theme_constant_override("margin_bottom", 16)
	panel.add_child(margin)

	var stack := VBoxContainer.new()
	stack.add_theme_constant_override("separation", 12)
	margin.add_child(stack)

	var top := HBoxContainer.new()
	top.add_theme_constant_override("separation", 16)
	stack.add_child(top)

	var logo := Logo.new()
	logo.custom_minimum_size = Vector2(104, 92)
	logo.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	logo.configure(str(board.get("team", "")))
	top.add_child(logo)

	var copy := VBoxContainer.new()
	copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	copy.alignment = BoxContainer.ALIGNMENT_CENTER
	copy.add_theme_constant_override("separation", 3)
	top.add_child(copy)

	copy.add_child(_label("PLAYER DEVELOPMENT • %s" % str(board.get("season", "")), 10, primary.lerp(Color.WHITE, 0.56)))

	var title := _label("DEVELOPMENT CENTER", 34, DS.TEXT_STRONG)
	title.custom_minimum_size = Vector2(0, 40)
	copy.add_child(title)

	copy.add_child(_label(
		"Build the next generation. Set measurable priorities, follow real progress, and connect development to the roles your players actually earn.",
		13,
		DS.MUTED
	))

	var actions := HBoxContainer.new()
	actions.alignment = BoxContainer.ALIGNMENT_END
	actions.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	actions.add_theme_constant_override("separation", 8)
	top.add_child(actions)

	var camp := _action_button("TRAINING CAMP", false)
	camp.pressed.connect(func(): navigate_requested.emit("OFFSEASON"))
	actions.add_child(camp)

	var history := _action_button("CAREER HISTORIES", true)
	history.pressed.connect(func(): navigate_requested.emit("FRONT OFFICE"))
	actions.add_child(history)

	var divider := HSeparator.new()
	divider.modulate = Color(primary, 0.34)
	stack.add_child(divider)

	var watch_header := HBoxContainer.new()
	watch_header.add_theme_constant_override("separation", 12)
	stack.add_child(watch_header)

	var watch_title := _nowrap_label("CORE DEVELOPMENT WATCH", 10, DS.GOLD)
	watch_title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	watch_header.add_child(watch_title)

	var rules := _nowrap_label(_short_rules(), 10, DS.MUTED)
	rules.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	rules.size_flags_horizontal = Control.SIZE_SHRINK_END
	watch_header.add_child(rules)

	var featured := GridContainer.new()
	featured.name = "DevelopmentFeaturedPlayers"
	featured.columns = 3
	featured.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	featured.add_theme_constant_override("h_separation", 10)
	featured.add_theme_constant_override("v_separation", 10)
	stack.add_child(featured)

	var players: Array = board.get("players", []).duplicate(true)
	players.sort_custom(func(a, b): return float(a.get("overall", 0.0)) > float(b.get("overall", 0.0)))

	if players.is_empty():
		featured.add_child(_label("No development-eligible players are available.", 13, DS.MUTED))
	else:
		for row in players.slice(0, 3):
			featured.add_child(_featured_player_card(row))


func _featured_player_card(player: Dictionary) -> Control:
	var panel := PanelContainer.new()
	panel.custom_minimum_size = Vector2(300, 124)
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	panel.add_theme_stylebox_override("panel", _panel_style(Color(DS.PANEL_ALT, 0.78), Color(primary, 0.30), 13))

	var margin := MarginContainer.new()
	margin.add_theme_constant_override("margin_left", 10)
	margin.add_theme_constant_override("margin_top", 8)
	margin.add_theme_constant_override("margin_right", 10)
	margin.add_theme_constant_override("margin_bottom", 8)
	panel.add_child(margin)

	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 10)
	margin.add_child(row)

	var portrait := Portrait.new()
	portrait.custom_minimum_size = Vector2(92, 98)
	portrait.configure({"player_id": str(player.get("player_id", "")), "name": str(player.get("name", ""))})
	row.add_child(portrait)

	var copy := VBoxContainer.new()
	copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	copy.alignment = BoxContainer.ALIGNMENT_CENTER
	copy.add_theme_constant_override("separation", 2)
	row.add_child(copy)

	var name := _nowrap_label(str(player.get("name", "Unknown Player")), 14, DS.TEXT_STRONG)
	name.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	copy.add_child(name)

	copy.add_child(_label(
		"OVR %s  •  %s MPG  •  %s G" % [
			_number(player.get("overall")),
			_number(player.get("minutes_per_game")),
			str(player.get("games", 0)),
		],
		10,
		primary.lerp(Color.WHITE, 0.42)
	))

	var best := _best_skill(player)
	copy.add_child(_label("%s %s" % [best.get("label", "Core skill"), best.get("value", "—")], 11, DS.GOLD))
	return panel


func _build_player_review() -> void:
	if focused_player_id.is_empty():
		return

	var player: Dictionary = {}
	for row in board.get("players", []):
		if str(row.get("player_id", "")) == focused_player_id:
			player = row
			break

	if player.is_empty():
		focused_player_id = ""
		return

	var panel := PanelContainer.new()
	panel.name = "FocusedDevelopmentPlayer"
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	panel.add_theme_stylebox_override("panel", _panel_style(Color(primary, 0.095), Color(primary, 0.52), 16))
	content.add_child(panel)

	var margin := MarginContainer.new()
	margin.add_theme_constant_override("margin_left", 16)
	margin.add_theme_constant_override("margin_top", 14)
	margin.add_theme_constant_override("margin_right", 16)
	margin.add_theme_constant_override("margin_bottom", 14)
	panel.add_child(margin)

	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 16)
	margin.add_child(row)

	var portrait := Portrait.new()
	portrait.custom_minimum_size = Vector2(132, 118)
	portrait.configure({"player_id": focused_player_id, "name": str(player.get("name", ""))})
	row.add_child(portrait)

	var copy := VBoxContainer.new()
	copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	copy.add_theme_constant_override("separation", 5)
	row.add_child(copy)

	copy.add_child(_label("FOCUSED PLAYER", 10, primary.lerp(Color.WHITE, 0.50)))
	copy.add_child(_label(str(player.get("name", "")), 25, DS.TEXT_STRONG))
	copy.add_child(_label(
		"%s OVR  •  %s MPG  •  %s APPEARANCES" % [
			_number(player.get("overall")),
			_number(player.get("minutes_per_game")),
			str(player.get("games", 0)),
		],
		12,
		DS.MUTED
	))

	var skills := HBoxContainer.new()
	skills.add_theme_constant_override("separation", 7)
	copy.add_child(skills)

	for skill in ["shooting", "playmaking", "defense", "rebounding"]:
		skills.add_child(_skill_chip(skill.capitalize(), player.get("skills", {}).get(skill)))

	var action_col := VBoxContainer.new()
	action_col.custom_minimum_size = Vector2(210, 0)
	action_col.alignment = BoxContainer.ALIGNMENT_CENTER
	action_col.add_theme_constant_override("separation", 8)
	row.add_child(action_col)

	if not bool(board.get("committed", false)) and bool(board.get("can_commit", false)):
		var draft := _action_button("ADD TO SEASON PLAN", true)
		draft.name = "DraftFocusedPlayerGoal"
		draft.pressed.connect(_draft_focused_player)
		action_col.add_child(draft)
		action_col.add_child(_label("Draft only. Nothing saves until you confirm the plan.", 10, DS.MUTED))
	else:
		action_col.add_child(_label("Your current season plan is already committed.", 11, DS.MUTED))


func _draft_focused_player() -> void:
	var player_index = -1
	for index in range(board.get("players", []).size()):
		if str(board.players[index].get("player_id", "")) == focused_player_id:
			player_index = index + 1

	if player_index < 1 or pending_action != "":
		return

	for form in forms:
		if form.player.selected == player_index:
			status.text = "This player is already on your development board."
			_reveal_form(form)
			return

	for index in range(forms.size()):
		if forms[index].player.selected == 0:
			forms[index].player.select(player_index)
			_update_form(index)
			status.text = "Player added to the season-plan draft. Choose the metric and target, then review."
			_reveal_form(forms[index])
			return

	status.text = "All three development priorities are occupied. Clear a slot to add this player."


func _reveal_form(form: Dictionary) -> void:
	var scroll = find_child("DevelopmentCommandScroll", true, false)
	if scroll != null:
		scroll.ensure_control_visible(form.player)
	form.player.grab_focus()


func _build_planner() -> void:
	var heading := VBoxContainer.new()
	heading.add_theme_constant_override("separation", 2)
	content.add_child(heading)
	heading.add_child(_label("SEASON DEVELOPMENT PLAN", 10, DS.GOLD))
	heading.add_child(_label("Three priorities. One view.", 23, DS.TEXT_STRONG))
	heading.add_child(_label("Choose up to three players and define exactly what you want this season to prove.", 12, DS.MUTED))

	var grid := GridContainer.new()
	grid.name = "DevelopmentPlannerGrid"
	grid.columns = 3
	grid.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	grid.add_theme_constant_override("h_separation", 10)
	grid.add_theme_constant_override("v_separation", 10)
	content.add_child(grid)

	for i in range(3):
		var slot_index := i

		var panel := PanelContainer.new()
		panel.name = "DevelopmentPriorityCard%s" % i
		panel.custom_minimum_size = Vector2(0, 300)
		panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		panel.add_theme_stylebox_override("panel", _panel_style(Color(DS.PANEL_ALT, 0.92), Color(primary, 0.30), 15))
		grid.add_child(panel)

		var margin := MarginContainer.new()
		margin.add_theme_constant_override("margin_left", 13)
		margin.add_theme_constant_override("margin_top", 12)
		margin.add_theme_constant_override("margin_right", 13)
		margin.add_theme_constant_override("margin_bottom", 12)
		panel.add_child(margin)

		var body := VBoxContainer.new()
		body.add_theme_constant_override("separation", 8)
		margin.add_child(body)

		var top := HBoxContainer.new()
		top.add_theme_constant_override("separation", 8)
		body.add_child(top)

		var priority_label := _nowrap_label(
			"PRIORITY %s" % (i + 1),
			10,
			primary.lerp(Color.WHITE, 0.48)
		)
		priority_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		top.add_child(priority_label)

		var state := _status_pill("OPEN", DS.MUTED)
		state.name = "GoalState%s" % i
		top.add_child(state)

		var visual := HBoxContainer.new()
		visual.custom_minimum_size = Vector2(0, 80)
		visual.add_theme_constant_override("separation", 9)
		body.add_child(visual)

		var portrait := Portrait.new()
		portrait.name = "GoalPortrait%s" % i
		portrait.custom_minimum_size = Vector2(74, 70)
		portrait.visible = false
		visual.add_child(portrait)

		var player_copy := VBoxContainer.new()
		player_copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		player_copy.alignment = BoxContainer.ALIGNMENT_CENTER
		visual.add_child(player_copy)

		var player_name := _nowrap_label("Select a player", 15, DS.TEXT_STRONG)
		player_name.name = "GoalPlayerName%s" % i
		player_copy.add_child(player_name)

		var player_meta := _label("Build a measurable priority", 10, DS.MUTED)
		player_meta.name = "GoalPlayerMeta%s" % i
		player_copy.add_child(player_meta)

		var player := OptionButton.new()
		player.name = "GoalPlayer%s" % i
		player.add_item("Leave this priority empty")
		player.custom_minimum_size.y = 42
		player.clip_text = true
		for row in board.get("players", []):
			player.add_item(str(row.name))
		body.add_child(player)

		var metric := OptionButton.new()
		metric.name = "GoalMetric%s" % i
		for text in ["Shooting growth", "Playmaking growth", "Defense growth", "Rebounding growth", "Playing opportunity"]:
			metric.add_item(text)
		metric.custom_minimum_size.y = 40
		body.add_child(metric)

		var target := OptionButton.new()
		target.name = "GoalTarget%s" % i
		target.custom_minimum_size.y = 40
		body.add_child(target)

		var detail := _label("Choose a player to inspect the baseline.", 10, DS.MUTED)
		detail.custom_minimum_size.y = 28
		body.add_child(detail)

		forms.append({
			"player": player,
			"metric": metric,
			"target": target,
			"detail": detail,
			"portrait": portrait,
			"player_name": player_name,
			"player_meta": player_meta,
			"state": state,
			"panel": panel,
		})

		player.item_selected.connect(func(_index): _update_form(slot_index))
		metric.item_selected.connect(func(_index): _update_form(slot_index))
		target.item_selected.connect(func(_index): _invalidate_preview())
		_update_form(slot_index)

	var actions := HBoxContainer.new()
	actions.add_theme_constant_override("separation", 10)
	content.add_child(actions)

	preview_button = _action_button("REVIEW SEASON PLAN", true)
	preview_button.custom_minimum_size = Vector2(0, 48)
	preview_button.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	preview_button.pressed.connect(func(): _submit("preview"))
	actions.add_child(preview_button)

	confirm_button = _action_button("COMMIT SEASON GOALS", true)
	confirm_button.custom_minimum_size = Vector2(0, 48)
	confirm_button.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	confirm_button.visible = false
	confirm_button.pressed.connect(func(): _submit("execute"))
	actions.add_child(confirm_button)

	review = VBoxContainer.new()
	review.name = "DevelopmentPlanReview"
	review.add_theme_constant_override("separation", 10)
	content.add_child(review)


func _update_form(index: int) -> void:
	var form: Dictionary = forms[index]
	form.target.clear()

	var opportunity = form.metric.selected == 4
	for value in ([10, 15, 20, 25, 30] if opportunity else [1, 2, 3]):
		form.target.add_item("%s MPG • at least 10 games" % value if opportunity else "+%s skill points" % value)

	form.metric.disabled = form.player.selected == 0
	form.target.disabled = form.player.selected == 0

	if form.player.selected > 0:
		var row: Dictionary = board.players[form.player.selected - 1]
		var metric = ["shooting", "playmaking", "defense", "rebounding", "opportunity"][form.metric.selected]
		var value = row.get("minutes_per_game", null) if opportunity else row.get("skills", {}).get(metric, null)

		form.detail.text = "BASELINE %s  •  %s GAMES PLAYED" % [_number(value), row.get("games", 0)]
		form.player_name.text = str(row.get("name", "Unknown Player"))
		form.player_meta.text = "OVR %s  •  %s MPG" % [_number(row.get("overall")), _number(row.get("minutes_per_game"))]
		form.portrait.visible = true
		form.portrait.configure({"player_id": str(row.get("player_id", "")), "name": str(row.get("name", ""))})
		form.state.text = "  ACTIVE  "
		form.state.add_theme_color_override("font_color", primary.lerp(Color.WHITE, 0.40))
		form.panel.add_theme_stylebox_override("panel", _panel_style(Color(primary, 0.075), Color(primary, 0.54), 15))
	else:
		form.detail.text = "Choose a player to inspect the baseline."
		form.player_name.text = "Select a player"
		form.player_meta.text = "Build a measurable priority"
		form.portrait.visible = false
		form.state.text = "  OPEN  "
		form.state.add_theme_color_override("font_color", DS.MUTED)
		form.panel.add_theme_stylebox_override("panel", _panel_style(Color(DS.PANEL_ALT, 0.92), Color(primary, 0.30), 15))

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
		var row: Dictionary = board.players[form.player.selected - 1]
		var metric = ["shooting", "playmaking", "defense", "rebounding", "opportunity"][form.metric.selected]
		var choice = {"player_id": str(row.player_id), "metric": metric}
		if metric == "opportunity":
			choice["target"] = [10, 15, 20, 25, 30][form.target.selected]
		else:
			choice["delta"] = form.target.selected + 1
		selections.append(choice)
	return selections


func _submit(action: String) -> void:
	submitted = _selections()
	if submitted.is_empty():
		status.text = "Choose at least one development priority."
		status.add_theme_color_override("font_color", DS.WARNING)
		return

	pending_action = action
	_set_form_busy(action == "execute")
	preview_button.disabled = true
	confirm_button.disabled = true

	var body = {
		"action": action,
		"selections": submitted,
		"expected_working_save_sha256": board.get("working_save_sha256", ""),
	}
	status.text = "Reviewing development plan…"

	if request.request(URL, ["Content-Type: application/json"], HTTPClient.METHOD_POST, JSON.stringify(body)) != OK:
		status.text = "Development request could not start. Refresh this page."
		confirm_button.visible = false
		preview_button.disabled = false
		_set_form_busy(false)


func _set_form_busy(busy: bool) -> void:
	for form in forms:
		form.player.disabled = busy
		form.metric.disabled = busy or form.player.selected == 0
		form.target.disabled = busy or form.player.selected == 0


func _build_committed_goals() -> void:
	var goals: Array = board.get("goals", [])
	var met := 0
	for goal in goals:
		if str(goal.get("status", "")) in ["target_met", "achieved"]:
			met += 1

	var header := HBoxContainer.new()
	content.add_child(header)

	var titles := VBoxContainer.new()
	titles.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	header.add_child(titles)
	titles.add_child(_label("SEASON COMMITMENTS", 10, DS.GOLD))
	titles.add_child(_label("%s / %s TARGETS MET" % [met, goals.size()], 23, DS.TEXT_STRONG))
	header.add_child(_status_pill("%s ACTIVE" % max(goals.size() - met, 0), primary))

	var grid := GridContainer.new()
	grid.name = "CommittedDevelopmentGrid"
	grid.columns = 3
	grid.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	grid.add_theme_constant_override("h_separation", 10)
	grid.add_theme_constant_override("v_separation", 10)
	content.add_child(grid)

	for goal in goals:
		_goal_card(grid, goal)

	content.add_child(_label("Targets are fixed for this season. Archived outcomes use closing-season evidence.", 11, DS.MUTED))


func _goal_card(parent: Node, goal: Dictionary) -> void:
	var met = str(goal.get("status", "")) in ["target_met", "achieved"]
	var tone: Color = DS.GOOD if met else primary

	var panel := PanelContainer.new()
	panel.custom_minimum_size = Vector2(0, 224)
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	panel.add_theme_stylebox_override("panel", _panel_style(Color(tone, 0.07), Color(tone, 0.46), 14))
	parent.add_child(panel)

	var margin := MarginContainer.new()
	margin.add_theme_constant_override("margin_left", 12)
	margin.add_theme_constant_override("margin_top", 11)
	margin.add_theme_constant_override("margin_right", 12)
	margin.add_theme_constant_override("margin_bottom", 11)
	panel.add_child(margin)

	var body := VBoxContainer.new()
	body.add_theme_constant_override("separation", 7)
	margin.add_child(body)

	var top := HBoxContainer.new()
	top.add_theme_constant_override("separation", 9)
	body.add_child(top)

	var portrait := Portrait.new()
	portrait.custom_minimum_size = Vector2(88, 80)
	portrait.configure({"player_id": str(goal.player_id), "name": str(goal.name)})
	top.add_child(portrait)

	var copy := VBoxContainer.new()
	copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	copy.alignment = BoxContainer.ALIGNMENT_CENTER
	top.add_child(copy)
	copy.add_child(_label(str(goal.name), 15, DS.TEXT_STRONG))
	copy.add_child(_label(str(goal.metric).replace("_", " ").to_upper(), 10, tone))
	copy.add_child(_label(str(goal.status).replace("_", " ").to_upper(), 9, DS.GOOD if met else DS.MUTED))

	body.add_child(_label(
		"BASE %s   NOW %s   TARGET %s" % [_number(goal.baseline), _number(goal.get("current", null)), _number(goal.target)],
		11,
		DS.TEXT
	))

	if goal.get("current", null) != null:
		var bar := ProgressBar.new()
		bar.name = "GoalProgress_" + str(goal.player_id)
		bar.value = float(goal.get("progress", 0)) * 100
		bar.show_percentage = false
		bar.custom_minimum_size.y = 12

		var fill := StyleBoxFlat.new()
		fill.bg_color = DS.GOOD if met else tone
		fill.set_corner_radius_all(6)

		var track := StyleBoxFlat.new()
		track.bg_color = Color(DS.BG, 0.72)
		track.set_corner_radius_all(6)

		bar.add_theme_stylebox_override("fill", fill)
		bar.add_theme_stylebox_override("background", track)
		body.add_child(bar)
	else:
		body.add_child(_label("Progress appears when closing evidence is available.", 10, DS.WARNING))

	var evidence := _label(str(goal.get("evidence", "")), 10, DS.MUTED)
	evidence.custom_minimum_size.y = 28
	body.add_child(evidence)

	if goal.metric == "opportunity":
		body.add_child(_label("%s / 10 REQUIRED APPEARANCES" % goal.get("games", 0), 10, DS.ACCENT))
	if bool(goal.get("departed", false)):
		body.add_child(_label("PLAYER LEFT ROSTER • Commitment retained in history.", 9, DS.WARNING))


func _build_archive() -> void:
	var archive: Array = board.get("archive", [])

	var section := HBoxContainer.new()
	section.add_theme_constant_override("separation", 10)
	content.add_child(section)

	var copy := VBoxContainer.new()
	copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	section.add_child(copy)
	copy.add_child(_label("FRANCHISE DEVELOPMENT HISTORY", 10, DS.GOLD))
	copy.add_child(_label("Past season agendas", 20, DS.TEXT_STRONG))

	if archive.is_empty():
		copy.add_child(_label("Your first completed season agenda will appear here after the franchise advances.", 11, DS.MUTED))
		return

	var toggle := CheckButton.new()
	toggle.text = "SHOW %s RECORDED" % board.get("archived_count", archive.size())
	toggle.custom_minimum_size = Vector2(170, 40)
	section.add_child(toggle)

	var history := GridContainer.new()
	history.columns = 3
	history.visible = false
	history.add_theme_constant_override("h_separation", 10)
	history.add_theme_constant_override("v_separation", 10)
	content.add_child(history)
	toggle.toggled.connect(func(value): history.visible = value)

	for goal in archive:
		_goal_card(history, goal)

	if int(board.get("archived_count", 0)) > archive.size():
		content.add_child(_label("Showing the latest %s archived commitments." % archive.size(), 10, DS.MUTED))


func _short_rules() -> String:
	return "UP TO 3 PLAYERS • GOALS TRACK RESULTS • ROTATION REMAINS SEPARATE"


func _best_skill(player: Dictionary) -> Dictionary:
	var labels := {"shooting": "Shooting", "playmaking": "Playmaking", "defense": "Defense", "rebounding": "Rebounding"}
	var skills: Dictionary = player.get("skills", {})
	var best_key := ""
	var best_value := -9999.0

	for key in labels.keys():
		var value = skills.get(key, null)
		if value == null:
			continue
		var number := float(value)
		if number > best_value:
			best_value = number
			best_key = key

	if best_key.is_empty():
		return {"label": "Core skill", "value": "—"}

	return {"label": str(labels.get(best_key, best_key.capitalize())), "value": _number(best_value)}


func _skill_chip(title: String, value) -> Control:
	var panel := PanelContainer.new()
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	panel.add_theme_stylebox_override("panel", _panel_style(Color(DS.PANEL_ALT, 0.78), Color(primary, 0.24), 8))

	var margin := MarginContainer.new()
	margin.add_theme_constant_override("margin_left", 8)
	margin.add_theme_constant_override("margin_top", 5)
	margin.add_theme_constant_override("margin_right", 8)
	margin.add_theme_constant_override("margin_bottom", 5)
	panel.add_child(margin)

	var label := _label("%s  %s" % [title, _number(value)], 10, DS.TEXT)
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	margin.add_child(label)
	return panel


func _status_pill(text_value: String, tone: Color) -> Label:
	var pill := Label.new()
	pill.text = "  %s  " % text_value
	pill.add_theme_font_size_override("font_size", 9)
	pill.add_theme_color_override("font_color", tone.lerp(Color.WHITE, 0.20))
	pill.add_theme_stylebox_override("normal", _panel_style(Color(tone, 0.09), Color(tone, 0.34), 7))
	return pill


func _action_button(text_value: String, primary_action: bool) -> Button:
	var button := Button.new()
	button.text = text_value
	button.custom_minimum_size = Vector2(150, 42)
	button.add_theme_font_size_override("font_size", 11)

	var normal_fill: Color = primary if primary_action else Color(DS.PANEL_ALT, 0.94)
	var normal_border: Color = Color(primary, 0.82) if primary_action else Color(DS.BORDER, 0.88)
	var hover_fill: Color = primary.lightened(0.12) if primary_action else Color(primary, 0.13)

	button.add_theme_stylebox_override("normal", _button_style(normal_fill, normal_border))
	button.add_theme_stylebox_override("hover", _button_style(hover_fill, Color(primary, 0.92)))
	button.add_theme_stylebox_override("pressed", _button_style(primary.darkened(0.10), Color(primary, 1.0)))
	button.add_theme_color_override("font_color", Color.WHITE if primary_action else DS.TEXT)
	return button


func _button_style(fill: Color, border: Color) -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = fill
	style.border_color = border
	style.set_border_width_all(1)
	style.set_corner_radius_all(10)
	style.content_margin_left = 12
	style.content_margin_right = 12
	style.content_margin_top = 9
	style.content_margin_bottom = 9
	return style


func _surface_card(parent: Node, tone: Color, strength: float, radius: int) -> VBoxContainer:
	var panel := PanelContainer.new()
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	panel.add_theme_stylebox_override("panel", _panel_style(Color(tone, strength), Color(tone, 0.38), radius))
	parent.add_child(panel)

	var margin := MarginContainer.new()
	margin.add_theme_constant_override("margin_left", 16)
	margin.add_theme_constant_override("margin_top", 14)
	margin.add_theme_constant_override("margin_right", 16)
	margin.add_theme_constant_override("margin_bottom", 14)
	panel.add_child(margin)

	var body := VBoxContainer.new()
	body.add_theme_constant_override("separation", 8)
	margin.add_child(body)
	return body


func _panel_style(fill: Color, border: Color, radius: int) -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = fill
	style.border_color = border
	style.set_border_width_all(1)
	style.set_corner_radius_all(radius)
	return style


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
	if parent == null:
		return
	for child in parent.get_children():
		parent.remove_child(child)
		child.queue_free()


func _number(value) -> String:
	return "—" if value == null else "%.1f" % float(value)


func _nowrap_label(text: String, font_size: int, color: Color = DS.TEXT) -> Label:
	var label := Label.new()
	label.text = text
	label.autowrap_mode = TextServer.AUTOWRAP_OFF
	label.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	label.add_theme_font_size_override("font_size", font_size)
	label.add_theme_color_override("font_color", color)
	return label


func _label(text: String, font_size: int, color: Color = DS.TEXT) -> Label:
	var label := Label.new()
	label.text = text
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.add_theme_font_size_override("font_size", font_size)
	label.add_theme_color_override("font_color", color)
	return label
