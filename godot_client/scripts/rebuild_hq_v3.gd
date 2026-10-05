extends Control

const DS = preload("res://scripts/design_system_v3.gd")
const TeamLogo = preload("res://scripts/team_logo_v3.gd")
const Portrait = preload("res://scripts/player_portrait_v3.gd")
const Branding = preload("res://scripts/team_branding_v3.gd")

signal navigate_requested(page: String)
signal player_development_requested(player_id: String)
signal onboarding_finished(started_from_startup: bool)

const REBUILD_URL = "http://127.0.0.1:8765/v3/rebuild-hq"

var primary = DS.TEAM_PRIMARY
var secondary = Color("000000")
var payload: Dictionary = {}

var content: VBoxContainer
var status_label: Label
var summary_request: HTTPRequest
var action_request: HTTPRequest
var pending_action = ""
var pending_onboarding_finish = false

var onboarding_overlay: Control
var onboarding_step_label: Label
var onboarding_title_label: Label
var onboarding_body_label: Label
var onboarding_back_button: Button
var onboarding_next_button: Button
var onboarding_skip_button: Button
var onboarding_index = 0
var onboarding_started_from_startup = false
var expanded_sections: Dictionary = {}

const ONBOARDING_STEPS = [
	{
		"title": "WELCOME TO YOUR REBUILD",
		"eyebrow": "FRANCHISE JOURNEY • 1 OF 6",
		"body": "The simulator is deep, but you should not have to discover it by accident. Rebuild HQ turns the major systems into one clear path: understand the roster, develop the core, build the future, shape the team, then prove it on court."
	},
	{
		"title": "START WITH PLAYER DEVELOPMENT",
		"eyebrow": "BUILD YOUR CORE • 2 OF 6",
		"body": "Development is the first major system to learn. Young players can become the identity of your franchise. Set season goals, track real rating progress, review development runway, and use training camp instead of treating every weakness as a trade problem."
	},
	{
		"title": "CHOOSE A TEAM-BUILDING DIRECTION",
		"eyebrow": "FRONT OFFICE IDENTITY • 3 OF 6",
		"body": "Choose a rebuild lens: develop the young core, contend now, rebuild through the Draft, create cap flexibility, or stay balanced. This does not secretly change ratings or CPU logic. It changes what Rebuild HQ puts in front of you."
	},
	{
		"title": "SCOUT BEFORE YOU NEED THE PICK",
		"eyebrow": "BUILD THE FUTURE • 4 OF 6",
		"body": "The Draft is not a one-night menu. Scout the class during the season, build confidence, choose focus prospects and arrive at Draft Night with information your front office actually earned."
	},
	{
		"title": "USE THE MARKET WITH A REASON",
		"eyebrow": "ROSTER BUILDING • 5 OF 6",
		"body": "Trades and Free Agency matter most after you understand the internal core. Rebuild HQ will point out roster pressure, cap context and future needs, then send you into the production transaction systems when an outside move actually makes sense."
	},
	{
		"title": "LIVE WITH THE TEAM YOU BUILT",
		"eyebrow": "SEASON STORY • 6 OF 6",
		"body": "Game Day, Locker Room, Franchise Pulse, Stories and Legacy make the save react to your decisions. Finish this tour by opening Development Command Center and giving your young core a real plan."
	},
]


func _ready() -> void:
	name = "RebuildHQV3"
	_build_ui()
	_build_http()


func apply_team_brand(_team: String, team_primary: Color, team_secondary: Color) -> void:
	primary = team_primary
	secondary = team_secondary


func set_long_action_manager(_manager) -> void:
	pass


func refresh() -> void:
	if summary_request == null:
		return
	if summary_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		summary_request.cancel_request()
	status_label.text = "Reading your franchise plan and rebuild priorities..."
	status_label.add_theme_color_override("font_color", DS.ACCENT)
	var error = summary_request.request(REBUILD_URL)
	if error != OK:
		_set_error("Could not start Rebuild HQ request.")


func configure(data: Dictionary) -> void:
	payload = data.duplicate(true)
	_clear(content, status_label)
	status_label.text = "%s • %s • DAY %s • REBUILD HQ READY" % [
		str(data.get("season", "")),
		str(data.get("phase", "")).replace("_", " ").to_upper(),
		str(data.get("day", 0)),
	]
	status_label.add_theme_color_override("font_color", DS.GOOD)

	_build_hero(data)
	_build_first_priority(data)
	_build_next_moves(data)
	_build_fold("OPPORTUNITY LAB • PLAN YOUR CORE'S MINUTES", func(): _build_opportunity_lab(data))
	_build_fold("TEAM DIRECTION", func(): _build_strategy(data))
	_build_fold("FRANCHISE JOURNEY", func(): _build_journey(data))
	_build_fold("FEATURE ACADEMY • EXPLORE THE SYSTEMS", func(): _build_feature_academy(data))
	_build_fold("SYSTEM MAP + HOW GUIDANCE WORKS", func(): _build_system_map(data); _build_scope(data))

	var spacer = Control.new()
	spacer.name = "RebuildHQBottomSafeArea"
	spacer.custom_minimum_size = Vector2(0, 150)
	spacer.mouse_filter = Control.MOUSE_FILTER_IGNORE
	content.add_child(spacer)


func start_onboarding(started_from_startup: bool = false) -> void:
	onboarding_started_from_startup = started_from_startup
	onboarding_index = 0
	_build_onboarding_overlay()
	_render_onboarding_step()


func _build_fold(title: String, builder: Callable) -> void:
	var before = content.get_child_count()
	builder.call()
	var sections: Array = []
	for index in range(before, content.get_child_count()):
		sections.append(content.get_child(index))
	var group = VBoxContainer.new()
	group.add_theme_constant_override("separation", 10)
	content.add_child(group)
	var button = Button.new()
	button.name = "RebuildFold" + title.split(" ")[0]
	button.custom_minimum_size.y = 48
	button.alignment = HORIZONTAL_ALIGNMENT_LEFT
	group.add_child(button)
	var body = VBoxContainer.new()
	group.add_child(body)
	for section in sections:
		content.remove_child(section)
		body.add_child(section)
	body.visible = bool(expanded_sections.get(title, false))
	button.text = ("−  " if body.visible else "+  ") + title
	button.pressed.connect(func():
		body.visible = not body.visible
		expanded_sections[title] = body.visible
		button.text = ("−  " if body.visible else "+  ") + title
	)

func _build_opportunity_lab(data: Dictionary) -> void:
	var section = _section("BUILD THROUGH OPPORTUNITY", "Development needs a role in the team you build.", DS.ACCENT)
	var lab = preload("res://scripts/rebuild_opportunity_v3.gd").new()
	section.add_child(lab)
	lab.configure(_dict(data.get("opportunity_lab")))
	lab.navigate_requested.connect(func(destination): navigate_requested.emit(destination))


func _build_http() -> void:
	summary_request = HTTPRequest.new()
	summary_request.timeout = 45.0
	summary_request.request_completed.connect(_on_summary_completed)
	add_child(summary_request)

	action_request = HTTPRequest.new()
	action_request.timeout = 20.0
	action_request.request_completed.connect(_on_action_completed)
	add_child(action_request)


func _build_ui() -> void:
	var background = ColorRect.new()
	background.color = DS.BG
	background.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	background.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(background)

	var scroll = ScrollContainer.new()
	scroll.name = "RebuildHQScroll"
	scroll.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	scroll.vertical_scroll_mode = ScrollContainer.SCROLL_MODE_AUTO
	add_child(scroll)

	var outer = MarginContainer.new()
	outer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	outer.size_flags_vertical = Control.SIZE_SHRINK_BEGIN
	_set_margins(outer, 24, 24, 24, 150)
	scroll.add_child(outer)

	content = VBoxContainer.new()
	content.name = "RebuildHQContent"
	content.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	content.size_flags_vertical = Control.SIZE_SHRINK_BEGIN
	content.add_theme_constant_override("separation", 16)
	outer.add_child(content)

	status_label = _label("Preparing Rebuild HQ...", 11, DS.MUTED)
	content.add_child(status_label)


func _on_summary_completed(
	result: int,
	response_code: int,
	_headers: PackedStringArray,
	body: PackedByteArray
) -> void:
	var parsed = JSON.parse_string(body.get_string_from_utf8())
	if (
		result != HTTPRequest.RESULT_SUCCESS
		or response_code != 200
		or typeof(parsed) != TYPE_DICTIONARY
	):
		var detail = (
			str(parsed.get("detail", "Rebuild HQ unavailable."))
			if typeof(parsed) == TYPE_DICTIONARY
			else "Rebuild HQ unavailable."
		)
		_set_error(detail)
		return
	configure(parsed)


func _post_action(action_body: Dictionary, action_name: String) -> void:
	if action_request == null:
		return
	if action_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	pending_action = action_name
	var headers = PackedStringArray(["Content-Type: application/json"])
	var error = action_request.request(
		REBUILD_URL,
		headers,
		HTTPClient.METHOD_POST,
		JSON.stringify(action_body)
	)
	if error != OK:
		pending_action = ""
		_set_error("Could not start Rebuild HQ metadata update.")


func _on_action_completed(
	result: int,
	response_code: int,
	_headers: PackedStringArray,
	body: PackedByteArray
) -> void:
	var parsed = JSON.parse_string(body.get_string_from_utf8())
	var action_name = pending_action
	pending_action = ""

	if (
		result != HTTPRequest.RESULT_SUCCESS
		or response_code != 200
		or typeof(parsed) != TYPE_DICTIONARY
	):
		var detail = (
			str(parsed.get("detail", "Rebuild HQ update failed."))
			if typeof(parsed) == TYPE_DICTIONARY
			else "Rebuild HQ update failed."
		)
		_set_error(detail)
		return

	configure(parsed)

	if action_name == "complete_onboarding" and pending_onboarding_finish:
		pending_onboarding_finish = false
		var started = onboarding_started_from_startup
		_close_onboarding()
		onboarding_finished.emit(started)


func _set_error(message: String) -> void:
	_clear(content, status_label)
	status_label.text = "REBUILD HQ UNAVAILABLE"
	status_label.add_theme_color_override("font_color", DS.BAD)
	var body = _section(
		"REBUILD HQ COULD NOT LOAD",
		"Your franchise was not changed.",
		DS.BAD
	)
	body.add_child(_label(message, 13))
	body.add_child(_button("RETRY", refresh, true))


func _build_hero(data: Dictionary) -> void:
	var hero = preload("res://scripts/franchise_hero_v3.gd").new()
	hero.name = "RebuildHQHero"
	content.add_child(hero)
	var record = _dict(data.get("record"))
	var strategy = _dict(data.get("strategy"))
	var active_choice = _strategy_choice(strategy, str(strategy.get("active", "")))
	hero.configure(str(data.get("team", "BOS")), str(data.get("team_name", "Your franchise")), "FRANCHISE COMMAND CENTER • " + str(data.get("season", "")), "%s  •  %s\nBuild your core. Shape the roster. Own the next chapter." % [record.get("display", "0-0"), active_choice.get("label", "Balanced front office")], data.get("young_core", []))
	var body = VBoxContainer.new()
	body.add_theme_constant_override("separation", 10)
	content.add_child(body)

	var metrics = GridContainer.new()
	metrics.columns = 4
	metrics.add_theme_constant_override("h_separation", 8)
	metrics.add_theme_constant_override("v_separation", 8)
	body.add_child(metrics)

	var journey = _dict(data.get("journey"))
	var development = _dict(data.get("development"))
	var scouting = _dict(data.get("scouting"))

	_metric(metrics, "RECORD", str(record.get("display", "0-0")), primary)
	_metric(
		metrics,
		"JOURNEY",
		"%s/%s" % [str(journey.get("completed", 0)), str(journey.get("total", 0))],
		DS.GOLD
	)
	_metric(
		metrics,
		"DEV GOALS",
		str(development.get("active_goal_count", 0)),
		DS.GOOD if bool(development.get("committed", false)) else DS.GOLD
	)
	_metric(
		metrics,
		"SCOUTING",
		"%s WK" % str(scouting.get("weeks_completed", 0)),
		DS.ACCENT
	)

	var actions = HBoxContainer.new()
	actions.add_theme_constant_override("separation", 8)
	body.add_child(actions)
	actions.add_child(_button("GUIDED TOUR", func(): start_onboarding(false), true))
	actions.add_child(_nav_button("OPEN DEVELOPMENT", "DEVELOPMENT"))
	actions.add_child(_nav_button("FRANCHISE PULSE", "PULSE"))


func _build_first_priority(data: Dictionary) -> void:
	var section = _section(
		"FIRST PRIORITY • BUILD YOUR CORE",
		"Player development is deliberately the first major system Rebuild HQ puts in front of you.",
		primary
	)
	section.get_parent().name = "RebuildHQYoungCore"

	var development = _dict(data.get("development"))
	var callout = PanelContainer.new()
	callout.add_theme_stylebox_override(
		"panel",
		_box(Color(primary, 0.045), 12, Color(primary, 0.30))
	)
	section.add_child(callout)

	var call_margin = MarginContainer.new()
	_set_margins(call_margin, 14, 12, 14, 12)
	callout.add_child(call_margin)

	var call_body = HBoxContainer.new()
	call_body.add_theme_constant_override("separation", 12)
	call_margin.add_child(call_body)

	var call_copy = VBoxContainer.new()
	call_copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	call_body.add_child(call_copy)
	call_copy.add_child(_label(
		"SEASON DEVELOPMENT PLAN",
		9,
		DS.GOLD if not bool(development.get("committed", false)) else DS.GOOD
	))
	call_copy.add_child(_label(
		"SET GOALS BEFORE CHASING OUTSIDE FIXES"
		if not bool(development.get("committed", false))
		else "YOUR DEVELOPMENT PLAN IS ACTIVE",
		18
	))
	call_copy.add_child(_label(
		"Commit up to %s meaningful player goals. Goals track production and ratings; they do not grant artificial boosts." % str(
			development.get("slots", 3)
		),
		11,
		DS.MUTED
	))
	call_body.add_child(_nav_button(
		"SET DEVELOPMENT GOALS"
		if not bool(development.get("committed", false))
		else "REVIEW DEVELOPMENT",
		"DEVELOPMENT"
	))

	var young_core = _array(data.get("young_core"))
	if young_core.is_empty():
		section.add_child(_empty(
			"No age-25-or-younger development core is available in the current roster snapshot."
		))
		return

	var grid = GridContainer.new()
	grid.columns = 3
	grid.add_theme_constant_override("h_separation", 10)
	grid.add_theme_constant_override("v_separation", 10)
	section.add_child(grid)

	for player in young_core.slice(0, 6):
		grid.add_child(_young_core_card(player))


func _young_core_card(player: Dictionary) -> Control:
	var panel = PanelContainer.new()
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	panel.add_theme_stylebox_override(
		"panel",
		_box(Color("111923"), 13, Color(primary, 0.24))
	)

	var margin = MarginContainer.new()
	_set_margins(margin, 11, 10, 11, 10)
	panel.add_child(margin)

	var body = VBoxContainer.new()
	body.add_theme_constant_override("separation", 6)
	margin.add_child(body)

	var portrait = Portrait.new()
	portrait.custom_minimum_size = Vector2(0, 118)
	body.add_child(portrait)
	portrait.configure({
		"player_id": str(player.get("player_id", "")),
		"name": str(player.get("name", ""))
	})
	var develop = _button("BUILD THIS PLAYER'S PLAN", func(): player_development_requested.emit(str(player.get("player_id", ""))))
	develop.name = "DevelopPlayer_" + str(player.get("player_id", ""))
	body.add_child(develop)

	var name = _label(str(player.get("name", "UNKNOWN")), 16)
	name.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	body.add_child(name)

	var meta = _label(
		"%s • AGE %s" % [
			str(player.get("position", "")),
			str(int(player.get("age", 0)))
		],
		9,
		DS.MUTED
	)
	meta.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	body.add_child(meta)

	var ratings = HBoxContainer.new()
	ratings.alignment = BoxContainer.ALIGNMENT_CENTER
	ratings.add_theme_constant_override("separation", 10)
	body.add_child(ratings)
	ratings.add_child(_rating_badge("OVR", player.get("overall"), DS.TEXT))
	ratings.add_child(_rating_badge("POT", player.get("potential"), primary))

	var gap = player.get("growth_gap")
	var runway = "UNKNOWN RUNWAY"
	var tone = DS.MUTED
	if gap != null:
		var growth = float(gap)
		if growth >= 8.0:
			runway = "HIGH RUNWAY +%.1f" % growth
			tone = DS.GOOD
		elif growth >= 4.0:
			runway = "REAL RUNWAY +%.1f" % growth
			tone = DS.ACCENT
		else:
			runway = "LIMITED RUNWAY +%.1f" % growth
			tone = DS.MUTED
	var runway_label = _label(runway, 9, tone)
	runway_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	body.add_child(runway_label)

	var goal_text = (
		"GOAL • %s • %s" % [
			str(player.get("goal_metric", "")).replace("_", " ").to_upper(),
			str(player.get("goal_status", "")).replace("_", " ").to_upper()
		]
		if bool(player.get("goal_active", false))
		else "NO SEASON GOAL"
	)
	var goal = _label(goal_text, 9, DS.GOOD if bool(player.get("goal_active", false)) else DS.GOLD)
	goal.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	body.add_child(goal)
	return panel


func _build_next_moves(data: Dictionary) -> void:
	var section = _section(
		"WHAT SHOULD I CARE ABOUT RIGHT NOW?",
		"Rebuild HQ ranks real franchise needs instead of asking you to browse every feature.",
		DS.GOLD
	)
	section.get_parent().name = "RebuildHQNextMoves"

	var moves = _array(data.get("next_moves"))
	if moves.is_empty():
		section.add_child(_empty("No priority move is currently available."))
		return

	for move in moves:
		var row = PanelContainer.new()
		row.add_theme_stylebox_override(
			"panel",
			_box(Color(DS.GOLD, 0.025), 11, Color(DS.GOLD, 0.18))
		)
		section.add_child(row)

		var margin = MarginContainer.new()
		_set_margins(margin, 12, 10, 12, 10)
		row.add_child(margin)

		var body = HBoxContainer.new()
		body.add_theme_constant_override("separation", 12)
		margin.add_child(body)

		var rank = _rank_badge(int(move.get("rank", 0)))
		body.add_child(rank)

		var copy = VBoxContainer.new()
		copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		copy.add_theme_constant_override("separation", 3)
		body.add_child(copy)
		copy.add_child(_label(str(move.get("category", "")), 8, DS.GOLD))
		copy.add_child(_label(str(move.get("title", "")), 16))
		copy.add_child(_label(str(move.get("detail", "")), 10, DS.MUTED))

		body.add_child(_nav_button(
			str(move.get("action", "OPEN")),
			str(move.get("destination", "HOME"))
		))


func _build_strategy(data: Dictionary) -> void:
	var section = _section(
		"CHOOSE YOUR DIRECTION",
		"This is a front-office lens, not a hidden gameplay modifier. It changes emphasis inside Rebuild HQ only.",
		DS.ACCENT
	)
	section.get_parent().name = "RebuildHQStrategy"

	var strategy = _dict(data.get("strategy"))
	var active = str(strategy.get("active", "balanced"))
	var recommended = str(strategy.get("recommended", "balanced"))

	var recommendation = PanelContainer.new()
	recommendation.add_theme_stylebox_override(
		"panel",
		_box(Color(DS.ACCENT, 0.03), 10, Color(DS.ACCENT, 0.20))
	)
	section.add_child(recommendation)
	var rec_margin = MarginContainer.new()
	_set_margins(rec_margin, 12, 9, 12, 9)
	recommendation.add_child(rec_margin)
	rec_margin.add_child(_label(
		"MODEL RECOMMENDATION • %s\n%s" % [
			str(_strategy_choice(strategy, recommended).get("label", recommended)),
			str(strategy.get("recommendation_reason", ""))
		],
		10,
		DS.MUTED
	))

	var grid = GridContainer.new()
	grid.columns = 5
	grid.add_theme_constant_override("h_separation", 8)
	grid.add_theme_constant_override("v_separation", 8)
	section.add_child(grid)

	for choice in _array(strategy.get("choices")):
		var id = str(choice.get("id", ""))
		var selected = id == active
		var card = PanelContainer.new()
		card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		card.add_theme_stylebox_override(
			"panel",
			_box(
				Color(primary, 0.07) if selected else Color("111923"),
				11,
				Color(primary, 0.55) if selected else Color(DS.BORDER, 0.70)
			)
		)
		grid.add_child(card)

		var margin = MarginContainer.new()
		_set_margins(margin, 10, 9, 10, 9)
		card.add_child(margin)

		var body = VBoxContainer.new()
		body.add_theme_constant_override("separation", 5)
		margin.add_child(body)
		body.add_child(_label(
			"SELECTED" if selected else ("RECOMMENDED" if bool(choice.get("recommended", false)) else "DIRECTION"),
			8,
			DS.GOOD if selected else DS.GOLD if bool(choice.get("recommended", false)) else DS.MUTED
		))
		body.add_child(_label(str(choice.get("short", "")), 14))
		body.add_child(_label(str(choice.get("detail", "")), 9, DS.MUTED))
		var button = _button(
			"ACTIVE" if selected else "CHOOSE",
			_set_strategy.bind(id),
			selected
		)
		button.disabled = selected
		body.add_child(button)


func _set_strategy(strategy_id: String) -> void:
	_post_action(
		{"action": "set_strategy", "strategy": strategy_id},
		"set_strategy"
	)


func _build_journey(data: Dictionary) -> void:
	var journey = _dict(data.get("journey"))
	var section = _section(
		"YOUR FRANCHISE JOURNEY",
		"Meaningful milestones are derived from the save itself. This is not an achievement checklist or fake progress meter.",
		primary
	)
	section.get_parent().name = "RebuildHQJourney"

	var total = int(journey.get("total", 0))
	var completed = int(journey.get("completed", 0))
	var progress = ProgressBar.new()
	progress.name = "RebuildJourneyProgress"
	progress.max_value = max(total, 1)
	progress.value = completed
	progress.show_percentage = false
	progress.custom_minimum_size = Vector2(0, 8)
	section.add_child(progress)
	section.add_child(_label(
		"%s OF %s MEANINGFUL MILESTONES COMPLETE" % [str(completed), str(total)],
		9,
		DS.GOOD if completed == total and total > 0 else DS.MUTED
	))

	var stages = _array(journey.get("stages"))
	for stage in stages:
		var stage_panel = PanelContainer.new()
		stage_panel.add_theme_stylebox_override(
			"panel",
			_box(Color("101821"), 11, Color(DS.BORDER, 0.65))
		)
		section.add_child(stage_panel)

		var margin = MarginContainer.new()
		_set_margins(margin, 12, 10, 12, 10)
		stage_panel.add_child(margin)

		var body = VBoxContainer.new()
		body.add_theme_constant_override("separation", 7)
		margin.add_child(body)

		var header = HBoxContainer.new()
		body.add_child(header)
		header.add_child(_label(str(stage.get("title", "")), 14, DS.GOLD))
		var spacer = Control.new()
		spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		header.add_child(spacer)
		header.add_child(_pill(
			"%s/%s" % [str(stage.get("completed", 0)), str(stage.get("total", 0))],
			DS.GOOD if int(stage.get("completed", 0)) == int(stage.get("total", 0)) else DS.MUTED
		))
		body.add_child(_label(str(stage.get("subtitle", "")), 9, DS.MUTED))

		for task in _array(stage.get("tasks")):
			var task_row = HBoxContainer.new()
			task_row.add_theme_constant_override("separation", 8)
			body.add_child(task_row)
			var done = bool(task.get("complete", false))
			var mark = _label("✓" if done else "○", 14, DS.GOOD if done else DS.GOLD)
			mark.custom_minimum_size = Vector2(22, 0)
			task_row.add_child(mark)

			var task_copy = VBoxContainer.new()
			task_copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
			task_row.add_child(task_copy)
			task_copy.add_child(_label(str(task.get("title", "")), 10))
			task_copy.add_child(_label(str(task.get("evidence", "")), 8, DS.MUTED))

			if not done:
				task_row.add_child(_nav_button(
					"OPEN",
					str(task.get("destination", "HOME"))
				))


func _build_feature_academy(data: Dictionary) -> void:
	var section = _section(
		"FEATURE ACADEMY",
		"Every major system answers a specific franchise question. Learn the reason to use it before learning every button.",
		DS.GOLD
	)
	section.get_parent().name = "RebuildHQFeatureAcademy"

	var guides = _array(data.get("feature_guides"))
	var grid = GridContainer.new()
	grid.columns = 2
	grid.add_theme_constant_override("h_separation", 10)
	grid.add_theme_constant_override("v_separation", 10)
	section.add_child(grid)

	for guide in guides:
		var card = PanelContainer.new()
		card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		var is_development = str(guide.get("id", "")) == "development"
		card.add_theme_stylebox_override(
			"panel",
			_box(
				Color(primary, 0.055) if is_development else Color("101821"),
				12,
				Color(primary, 0.38) if is_development else Color(DS.BORDER, 0.65)
			)
		)
		grid.add_child(card)

		var margin = MarginContainer.new()
		_set_margins(margin, 12, 10, 12, 10)
		card.add_child(margin)

		var body = VBoxContainer.new()
		body.add_theme_constant_override("separation", 6)
		margin.add_child(body)
		body.add_child(_label(str(guide.get("eyebrow", "")), 8, DS.GOLD if is_development else DS.ACCENT))
		body.add_child(_label(str(guide.get("title", "")), 16))
		body.add_child(_label(str(guide.get("why", "")), 10, DS.MUTED))
		body.add_child(_label(str(guide.get("status", "")), 8, DS.GOOD if is_development else DS.MUTED))
		body.add_child(_nav_button(
			str(guide.get("action", "OPEN")),
			str(guide.get("destination", "HOME"))
		))


func _build_system_map(data: Dictionary) -> void:
	var section = _section(
		"HOW THE FRANCHISE FITS TOGETHER",
		"Deep pages such as Theater, Stories, Pulse and Front Office still exist, but they no longer need permanent sidebar space.",
		DS.ACCENT
	)
	section.get_parent().name = "RebuildHQSystemMap"

	var grid = GridContainer.new()
	grid.columns = 4
	grid.add_theme_constant_override("h_separation", 8)
	grid.add_theme_constant_override("v_separation", 8)
	section.add_child(grid)

	_system_tile(grid, "BUILD YOUR CORE", "Development\nRoster\nLocker Room", "DEVELOPMENT", primary)
	_system_tile(grid, "BUILD THE FUTURE", "Scouting\nTrades\nFree Agency", "SCOUTING", DS.GOLD)
	_system_tile(grid, "PLAY THE SEASON", "Game Day\nSeason\nTheater", "GAME DAY", DS.ACCENT)
	_system_tile(grid, "LIVE WITH THE SAVE", "Pulse\nStories\nLeague\nLegacy", "PULSE", Color("8ca8d8"))


func _system_tile(
	parent: GridContainer,
	title_text: String,
	detail_text: String,
	destination: String,
	tone: Color
) -> void:
	var panel = PanelContainer.new()
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	panel.add_theme_stylebox_override(
		"panel",
		_box(Color(tone, 0.035), 11, Color(tone, 0.22))
	)
	parent.add_child(panel)

	var margin = MarginContainer.new()
	_set_margins(margin, 10, 9, 10, 9)
	panel.add_child(margin)

	var body = VBoxContainer.new()
	body.add_theme_constant_override("separation", 6)
	margin.add_child(body)
	body.add_child(_label(title_text, 11, tone))
	body.add_child(_label(detail_text, 10, DS.MUTED))
	body.add_child(_nav_button("OPEN", destination))


func _build_scope(data: Dictionary) -> void:
	var scope = _dict(data.get("scope"))
	var section = _section(
		"REBUILD HQ SCOPE",
		"Guidance should make the simulator clearer, not secretly play it for you.",
		DS.MUTED
	)
	section.get_parent().name = "RebuildHQScope"
	section.add_child(_label(str(scope.get("note", "")), 10, DS.MUTED))

	var grid = GridContainer.new()
	grid.columns = 4
	grid.add_theme_constant_override("h_separation", 8)
	grid.add_theme_constant_override("v_separation", 8)
	section.add_child(grid)
	grid.add_child(_scope_pill("NO RATING BOOSTS", DS.GOOD))
	grid.add_child(_scope_pill("NO HIDDEN TRADES", DS.GOOD))
	grid.add_child(_scope_pill("NO ROTATION EDITS", DS.GOOD))
	grid.add_child(_scope_pill("V2 PROTECTED", DS.GOOD))


func _build_onboarding_overlay() -> void:
	_close_onboarding()

	onboarding_overlay = Control.new()
	onboarding_overlay.name = "RebuildOnboardingOverlay"
	onboarding_overlay.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	onboarding_overlay.mouse_filter = Control.MOUSE_FILTER_STOP
	add_child(onboarding_overlay)
	onboarding_overlay.move_to_front()

	var dim = ColorRect.new()
	dim.color = Color(0, 0, 0, 0.84)
	dim.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	dim.mouse_filter = Control.MOUSE_FILTER_STOP
	onboarding_overlay.add_child(dim)

	var center = CenterContainer.new()
	center.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	onboarding_overlay.add_child(center)

	var panel = PanelContainer.new()
	panel.custom_minimum_size = Vector2(760, 450)
	panel.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	panel.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	panel.add_theme_stylebox_override(
		"panel",
		_box(Color("0d141d"), 18, Color(primary, 0.62))
	)
	center.add_child(panel)

	var margin = MarginContainer.new()
	_set_margins(margin, 28, 24, 28, 24)
	panel.add_child(margin)

	var body = VBoxContainer.new()
	body.add_theme_constant_override("separation", 14)
	margin.add_child(body)

	onboarding_step_label = _label("", 9, DS.GOLD)
	body.add_child(onboarding_step_label)

	onboarding_title_label = _label("", 29)
	body.add_child(onboarding_title_label)

	onboarding_body_label = _label("", 14, DS.MUTED)
	onboarding_body_label.custom_minimum_size = Vector2(0, 150)
	body.add_child(onboarding_body_label)

	var principle = PanelContainer.new()
	principle.add_theme_stylebox_override(
		"panel",
		_box(Color(primary, 0.035), 10, Color(primary, 0.20))
	)
	body.add_child(principle)
	var principle_margin = MarginContainer.new()
	_set_margins(principle_margin, 12, 10, 12, 10)
	principle.add_child(principle_margin)
	principle_margin.add_child(_label(
		"DESIGN RULE • A feature belongs in the simulator only when the player knows where they encounter it, why they care about it, and what decision it helps them make.",
		10,
		primary.lightened(0.35)
	))

	var buttons = HBoxContainer.new()
	buttons.add_theme_constant_override("separation", 8)
	body.add_child(buttons)

	onboarding_skip_button = _button("SKIP FOR NOW", _skip_onboarding)
	buttons.add_child(onboarding_skip_button)

	var spacer = Control.new()
	spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	buttons.add_child(spacer)

	onboarding_back_button = _button("BACK", _onboarding_back)
	buttons.add_child(onboarding_back_button)

	onboarding_next_button = _button("NEXT", _onboarding_next, true)
	buttons.add_child(onboarding_next_button)


func _render_onboarding_step() -> void:
	if onboarding_overlay == null:
		return
	var step = ONBOARDING_STEPS[onboarding_index]
	onboarding_step_label.text = str(step.get("eyebrow", ""))
	onboarding_title_label.text = str(step.get("title", ""))
	onboarding_body_label.text = str(step.get("body", ""))
	onboarding_back_button.disabled = onboarding_index == 0
	onboarding_next_button.text = (
		"FINISH • OPEN DEVELOPMENT"
		if onboarding_index == ONBOARDING_STEPS.size() - 1
		else "NEXT"
	)


func _onboarding_back() -> void:
	onboarding_index = maxi(0, onboarding_index - 1)
	_render_onboarding_step()


func _onboarding_next() -> void:
	if onboarding_index < ONBOARDING_STEPS.size() - 1:
		onboarding_index += 1
		_render_onboarding_step()
		return

	pending_onboarding_finish = true
	_post_action({"action": "complete_onboarding"}, "complete_onboarding")


func _skip_onboarding() -> void:
	_close_onboarding()


func _close_onboarding() -> void:
	if onboarding_overlay != null and is_instance_valid(onboarding_overlay):
		onboarding_overlay.queue_free()
	onboarding_overlay = null


func _strategy_choice(strategy: Dictionary, strategy_id: String) -> Dictionary:
	for choice in _array(strategy.get("choices")):
		if str(choice.get("id", "")) == strategy_id:
			return choice
	return {}


func _section(title_text: String, detail_text: String, tone: Color) -> VBoxContainer:
	var panel = PanelContainer.new()
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	panel.add_theme_stylebox_override(
		"panel",
		_box(DS.PANEL_ALT, 15, Color(tone, 0.36))
	)
	content.add_child(panel)

	var margin = MarginContainer.new()
	_set_margins(margin, 16, 14, 16, 14)
	panel.add_child(margin)

	var body = VBoxContainer.new()
	body.add_theme_constant_override("separation", 10)
	margin.add_child(body)
	body.add_child(_label(title_text, 20))
	body.add_child(_label(detail_text, 10, DS.MUTED))
	return body


func _metric(parent: GridContainer, title_text: String, value_text: String, tone: Color) -> void:
	var panel = PanelContainer.new()
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	panel.add_theme_stylebox_override(
		"panel",
		_box(Color(tone, 0.035), 9, Color(tone, 0.18))
	)
	parent.add_child(panel)

	var margin = MarginContainer.new()
	_set_margins(margin, 9, 7, 9, 7)
	panel.add_child(margin)

	var body = VBoxContainer.new()
	margin.add_child(body)
	body.add_child(_label(title_text, 8, tone))
	body.add_child(_label(value_text, 15))


func _rating_badge(title_text: String, value, tone: Color) -> Control:
	var panel = PanelContainer.new()
	panel.custom_minimum_size = Vector2(72, 44)
	panel.add_theme_stylebox_override(
		"panel",
		_box(Color(tone, 0.05), 9, Color(tone, 0.24))
	)
	var body = VBoxContainer.new()
	panel.add_child(body)
	var title = _label(title_text, 7, DS.MUTED)
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	body.add_child(title)
	var number = _label(_display(value), 15, tone)
	number.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	body.add_child(number)
	return panel


func _rank_badge(rank: int) -> Control:
	var panel = PanelContainer.new()
	panel.custom_minimum_size = Vector2(42, 42)
	panel.add_theme_stylebox_override(
		"panel",
		_box(Color(DS.GOLD, 0.07), 21, Color(DS.GOLD, 0.34))
	)
	var label = _label(str(rank), 16, DS.GOLD)
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	panel.add_child(label)
	return panel


func _scope_pill(text_value: String, tone: Color) -> Control:
	var panel = PanelContainer.new()
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	panel.add_theme_stylebox_override(
		"panel",
		_box(Color(tone, 0.035), 8, Color(tone, 0.18))
	)
	var label = _label(text_value, 8, tone)
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	panel.add_child(label)
	return panel


func _empty(text_value: String) -> Control:
	var panel = PanelContainer.new()
	panel.add_theme_stylebox_override(
		"panel",
		_box(Color("101821"), 10, Color(DS.BORDER, 0.65))
	)
	var margin = MarginContainer.new()
	_set_margins(margin, 10, 9, 10, 9)
	panel.add_child(margin)
	margin.add_child(_label(text_value, 10, DS.MUTED))
	return panel


func _nav_button(text_value: String, destination: String) -> Button:
	return _button(
		text_value,
		func(): navigate_requested.emit(destination)
	)


func _button(
	text_value: String,
	callback: Callable,
	primary_action: bool = false
) -> Button:
	var button = Button.new()
	button.text = text_value
	button.custom_minimum_size.y = 40
	button.add_theme_font_size_override("font_size", 9)
	button.pressed.connect(callback)
	if primary_action:
		Branding.apply_primary_button(button, primary)
	return button


func _pill(text_value: String, tone: Color) -> Label:
	var label = _label(text_value, 8, tone)
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	label.custom_minimum_size = Vector2(0, 26)
	return label


func _label(
	text_value: String,
	font_size: int,
	color: Color = DS.TEXT
) -> Label:
	var label = Label.new()
	label.text = text_value
	label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.add_theme_font_size_override("font_size", font_size)
	label.add_theme_color_override("font_color", color)
	return label


func _box(
	fill: Color,
	radius: int,
	border: Color
) -> StyleBoxFlat:
	var style = StyleBoxFlat.new()
	style.bg_color = fill
	style.border_color = border
	style.set_border_width_all(1)
	style.set_corner_radius_all(radius)
	return style


func _set_margins(
	container: MarginContainer,
	left: int,
	top: int,
	right: int,
	bottom: int
) -> void:
	container.add_theme_constant_override("margin_left", left)
	container.add_theme_constant_override("margin_top", top)
	container.add_theme_constant_override("margin_right", right)
	container.add_theme_constant_override("margin_bottom", bottom)


func _clear(parent: Node, keep: Node = null) -> void:
	for child in parent.get_children():
		if child != keep:
			parent.remove_child(child)
			child.queue_free()


func _dict(value) -> Dictionary:
	return value if typeof(value) == TYPE_DICTIONARY else {}


func _array(value) -> Array:
	return value if typeof(value) == TYPE_ARRAY else []


func _display(value) -> String:
	if value == null or str(value).strip_edges() == "":
		return "—"
	if typeof(value) == TYPE_FLOAT:
		return "%.1f" % float(value)
	return str(value)
