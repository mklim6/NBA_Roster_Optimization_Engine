extends Control

const DS = preload("res://scripts/design_system_v3.gd")
const TeamLogoV3 = preload("res://scripts/team_logo_v3.gd")
const Portrait = preload("res://scripts/player_portrait_v3.gd")
const OffseasonTimelineV3 = preload("res://scripts/offseason_timeline_v3.gd")
const OffseasonRosterWarRoomV3 = preload("res://scripts/offseason_roster_war_room_v3.gd")
const TrainingCampV3 = preload("res://scripts/training_camp_v3.gd")

const OFFSEASON_URL = "http://127.0.0.1:8765/v3/offseason-command"

signal navigate_requested(page_name: String)

var http_request: HTTPRequest
var scroll: ScrollContainer
var content: VBoxContainer
var status_label: Label
var timeline: Control
var roster_war_room: Control

var payload: Dictionary = {}
var active_team = ""
var active_primary = DS.TEAM_PRIMARY
var active_secondary = Color("000000")
var active_foreground = DS.TEXT


func _ready() -> void:
	name = "OffseasonCommandCenter"
	_ensure_ui()
	_build_http()
	refresh()


func refresh() -> void:
	_ensure_ui()
	if http_request == null:
		_build_http()

	if http_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		http_request.cancel_request()

	status_label.text = "LOADING OFFSEASON WAR ROOM • Read-only command aggregation"
	status_label.add_theme_color_override("font_color", DS.MUTED)

	var error = http_request.request(OFFSEASON_URL)
	if error != OK:
		status_label.text = "Offseason Command request could not be started."
		status_label.add_theme_color_override("font_color", DS.BAD)


func apply_team_brand(
	team_abbreviation: String,
	primary: Color,
	secondary: Color
) -> void:
	active_team = team_abbreviation.strip_edges().to_upper()
	active_primary = primary
	active_secondary = secondary
	active_foreground = _readable(primary)
	if not payload.is_empty():
		configure(payload)


func configure(data: Dictionary) -> void:
	_ensure_ui()
	payload = data.duplicate(true)
	active_team = str(data.get("team", active_team)).strip_edges().to_upper()

	_clear_below_status()

	status_label.text = "LIVE V3 OFFSEASON INTELLIGENCE • %s" % str(
		data.get("foundation_version", "Expansion 40")
	)
	status_label.add_theme_color_override("font_color", DS.GOOD)

	_build_hero(data)
	_build_shortcuts(data)
	_build_mission_control(data)
	_build_roadmap(data)
	_build_split_operations(data)
	_build_roster_war_room(data)
	content.add_child(TrainingCampV3.new())
	_build_decision_board(data)
	_build_scope_card(data)
	_build_bottom_safe_area()


func _build_http() -> void:
	if http_request != null:
		return
	http_request = HTTPRequest.new()
	http_request.name = "OffseasonCommandHTTPRequest"
	http_request.timeout = 45.0
	add_child(http_request)
	http_request.request_completed.connect(_on_request_completed)


func _ensure_ui() -> void:
	if scroll != null:
		return

	scroll = ScrollContainer.new()
	scroll.name = "OffseasonCommandScroll"
	scroll.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	scroll.vertical_scroll_mode = ScrollContainer.SCROLL_MODE_AUTO
	scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	add_child(scroll)

	var outer = MarginContainer.new()
	outer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	outer.size_flags_vertical = Control.SIZE_SHRINK_BEGIN
	_set_margins(outer, 18, 22, 18, 120)
	scroll.add_child(outer)

	content = VBoxContainer.new()
	content.name = "OffseasonCommandContent"
	content.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	content.size_flags_vertical = Control.SIZE_SHRINK_BEGIN
	content.add_theme_constant_override("separation", 15)
	outer.add_child(content)

	status_label = _label(
		"Connecting to the V3 Offseason Command foundation...",
		9,
		DS.MUTED
	)
	content.add_child(status_label)


func _on_request_completed(
	result: int,
	response_code: int,
	_headers: PackedStringArray,
	body: PackedByteArray
) -> void:
	if result != HTTPRequest.RESULT_SUCCESS:
		_show_error("Offseason Command endpoint did not respond.")
		return

	var parsed = JSON.parse_string(body.get_string_from_utf8())
	if typeof(parsed) != TYPE_DICTIONARY:
		_show_error("Offseason Command endpoint returned invalid JSON.")
		return

	if response_code != 200:
		_show_error(
			str(parsed.get("detail", parsed.get("error", "Offseason Command unavailable.")))
		)
		return

	if not bool(parsed.get("working_save_unchanged", false)):
		_show_error("Safety check failed: the read-only Offseason endpoint changed the V3 working save.")
		return
	if not bool(parsed.get("active_v2_unchanged", false)):
		_show_error("Safety check failed: the protected V2 release checkpoint changed.")
		return

	configure(parsed)


func _show_error(message: String) -> void:
	_clear_below_status()
	status_label.text = "OFFSEASON COMMAND UNAVAILABLE"
	status_label.add_theme_color_override("font_color", DS.BAD)

	var panel = _card(Color("171219"), Color(DS.BAD, 0.35), 14)
	var body = _body(panel, 15)
	body.add_child(_label(message, 12, DS.TEXT))
	var note = _label(
		"This page is an orchestration surface. Existing Season, Scouting, Free Agency, Roster, and Legacy pages remain available and no write was attempted.",
		9,
		DS.MUTED
	)
	note.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	body.add_child(note)
	content.add_child(panel)


func _build_hero(data: Dictionary) -> void:
	var command = _dict(data.get("command"))
	var season = _dict(data.get("season"))
	var roster = _dict(data.get("roster"))
	var camp = _dict(data.get("camp_readiness"))
	var stage = _dict(command.get("current_stage"))

	var hero = _card(
		Color("07151a").lerp(active_primary, 0.08),
		Color(active_primary, 0.66),
		20
	)
	hero.name = "OffseasonHero"
	hero.custom_minimum_size = Vector2(0, 290)
	var body = _body(hero, 20)

	var top = HBoxContainer.new()
	top.add_theme_constant_override("separation", 18)
	body.add_child(top)

	var logo_shell = PanelContainer.new()
	logo_shell.custom_minimum_size = Vector2(142, 142)
	logo_shell.add_theme_stylebox_override(
		"panel",
		_box(Color(active_primary, 0.12), 19, Color(active_primary, 0.52))
	)
	top.add_child(logo_shell)

	var logo = TeamLogoV3.new()
	logo.name = "OffseasonTeamLogo"
	logo.configure(str(data.get("team", active_team)))
	logo_shell.add_child(logo)

	var title_box = VBoxContainer.new()
	title_box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	title_box.alignment = BoxContainer.ALIGNMENT_CENTER
	title_box.add_theme_constant_override("separation", 4)
	top.add_child(title_box)

	title_box.add_child(_label("FRANCHISE OPERATIONS • EXPANSION 40", 9, DS.GOOD))
	title_box.add_child(_label(
		str(data.get("team_name", data.get("team", "FRANCHISE"))).to_upper(),
		30,
		DS.TEXT
	))
	title_box.add_child(_label(
		str(command.get("headline", "OFFSEASON COMMAND CENTER")),
		22,
		active_primary.lightened(0.40)
	))
	title_box.add_child(_label(
		"%s • %s • DAY %s" % [
			str(season.get("label", "")),
			str(season.get("phase", "")).replace("_", " ").to_upper(),
			str(season.get("day_index", 0))
		],
		10,
		DS.MUTED
	))

	var stage_card = _card(
		Color(active_primary, 0.08),
		Color(active_primary, 0.38),
		14
	)
	stage_card.custom_minimum_size = Vector2(300, 142)
	var stage_body = _body(stage_card, 13)
	stage_body.add_child(_label("CURRENT FRONT-OFFICE FOCUS", 8, active_primary.lightened(0.38)))
	stage_body.add_child(_label(
		str(stage.get("label", "OFFSEASON PLAN")).to_upper(),
		17,
		DS.TEXT
	))
	stage_body.add_child(_label(
		str(stage.get("kicker", "FRANCHISE OPERATIONS")).to_upper(),
		9,
		DS.GOLD
	))
	var stage_detail = _label(str(stage.get("detail", "")), 9, DS.MUTED)
	stage_detail.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	stage_body.add_child(stage_detail)
	top.add_child(stage_card)

	var metrics = GridContainer.new()
	metrics.columns = 5
	metrics.add_theme_constant_override("h_separation", 8)
	metrics.add_theme_constant_override("v_separation", 8)
	body.add_child(metrics)

	_metric(metrics, "STANDARD ROSTER", "%s / 15" % str(roster.get("standard_count", 0)), DS.TEXT)
	_metric(metrics, "OPEN SLOTS", str(roster.get("open_standard_slots", 0)), DS.ACCENT)
	_metric(metrics, "TWO-WAY", "%s / 3" % str(roster.get("two_way_count", 0)), active_primary.lightened(0.38))
	_metric(metrics, "CAMP GRADE", "%s • %s" % [str(camp.get("grade", "—")), str(camp.get("score", 0))], DS.GOLD)
	_metric(metrics, "NEXT GATE", str(command.get("next_certified_action_label", "NO ACTION")).replace("_", " "), DS.GOOD)

	content.add_child(hero)


func _build_shortcuts(data: Dictionary) -> void:
	var shortcuts = _array(data.get("shortcuts"))
	var panel = _card(Color("0e151d"), Color(DS.BORDER, 0.80), 13)
	panel.name = "OffseasonShortcuts"
	var body = _body(panel, 12)

	var row = GridContainer.new()
	row.columns = 3
	row.add_theme_constant_override("h_separation", 8)
	row.add_theme_constant_override("v_separation", 8)
	body.add_child(row)

	for raw in shortcuts:
		if typeof(raw) != TYPE_DICTIONARY:
			continue
		var item: Dictionary = raw
		var destination = str(item.get("destination", ""))
		var button = Button.new()
		button.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		button.custom_minimum_size = Vector2(0, 40)
		button.text = str(item.get("label", destination))
		button.clip_text = true
		button.tooltip_text = str(item.get("detail", ""))
		button.add_theme_font_size_override("font_size", 8)
		button.add_theme_color_override("font_color", DS.TEXT)
		button.add_theme_color_override("font_hover_color", DS.TEXT)
		button.add_theme_stylebox_override(
			"normal",
			_box(Color("101821"), 9, Color(DS.BORDER, 0.75))
		)
		button.add_theme_stylebox_override(
			"hover",
			_box(Color(active_primary, 0.09), 9, Color(active_primary, 0.58))
		)
		button.pressed.connect(_emit_navigation.bind(destination))
		row.add_child(button)

	content.add_child(panel)


func _build_mission_control(data: Dictionary) -> void:
	var command = _dict(data.get("command"))
	var last = _dict(data.get("last_season"))
	var diagnostics = _array(data.get("diagnostics"))

	var panel = _section_card(
		"FRONT OFFICE MISSION CONTROL",
		"One command surface for the production season boundary, Draft pipeline, player market, roster construction, and historical handoff."
	)
	panel.name = "OffseasonMissionControl"
	var body = panel.get_meta("body") as VBoxContainer

	var split = GridContainer.new()
	split.columns = 3
	split.add_theme_constant_override("h_separation", 10)
	split.add_theme_constant_override("v_separation", 10)
	body.add_child(split)

	var next_card = _card(Color(active_primary, 0.06), Color(active_primary, 0.34), 11)
	next_card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var next_body = _body(next_card, 12)
	next_body.add_child(_label("NEXT CERTIFIED LIFECYCLE GATE", 8, active_primary.lightened(0.40)))
	var next_title = _label(
		str(command.get("next_certified_action_label", "NO DURABLE ACTION AVAILABLE")),
		16,
		DS.TEXT
	)
	next_title.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	next_body.add_child(next_title)
	next_body.add_child(_label(
		"Stage • %s" % str(command.get("lifecycle_stage", "waiting")).replace("_", " ").to_upper(),
		9,
		DS.MUTED
	))
	var season_button = _action_button("OPEN SEASON COMMAND", active_primary)
	season_button.pressed.connect(_emit_navigation.bind("SEASON"))
	next_body.add_child(season_button)
	split.add_child(next_card)

	var recap_card = _card(Color("111923"), Color(DS.GOLD, 0.24), 11)
	recap_card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var recap_body = _body(recap_card, 12)
	recap_body.add_child(_label("LAST COMPLETED SEASON", 8, DS.GOLD))
	if bool(last.get("available", false)):
		recap_body.add_child(_label(
			"%s • %s" % [
				str(last.get("season", "")),
				str(last.get("record", ""))
			],
			16,
			DS.TEXT
		))
		recap_body.add_child(_label(str(last.get("result", "")), 10, _result_color(str(last.get("result", "")))))
		if str(last.get("champion", "")) != "":
			recap_body.add_child(_label(
				"NBA Champion • %s" % str(last.get("champion_name", last.get("champion", ""))),
				8,
				DS.MUTED
			))
	else:
		recap_body.add_child(_label("FIRST V3 SEASON", 16, DS.TEXT))
		recap_body.add_child(_label(
			"Year-in-review history will appear here after the first completed season.",
			9,
			DS.MUTED
		))
	var legacy_button = _action_button("OPEN LEGACY", DS.GOLD)
	legacy_button.pressed.connect(_emit_navigation.bind("LEGACY"))
	recap_body.add_child(legacy_button)
	split.add_child(recap_card)

	var safety_card = _card(Color("0d1916"), Color(DS.GOOD, 0.26), 11)
	safety_card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var safety_body = _body(safety_card, 12)
	safety_body.add_child(_label("EXPANSION 40 SAFETY MODEL", 8, DS.GOOD))
	var safety_title = _label("ORCHESTRATE HERE • COMMIT IN CERTIFIED CENTERS", 13, DS.TEXT)
	safety_title.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	safety_body.add_child(safety_title)
	var safety_text = _label(
		"Expansion 40 does not duplicate transaction writes. Lifecycle changes remain in Season Command, Draft writes remain in Scouting & Draft, and contract writes remain in Free Agency with their existing preview/fingerprint/reload/V2-protection contracts.",
		9,
		DS.MUTED
	)
	safety_text.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	safety_body.add_child(safety_text)
	if not diagnostics.is_empty():
		safety_body.add_child(_label(
			"%s read-only subsystem diagnostic(s) degraded gracefully." % str(diagnostics.size()),
			8,
			DS.GOLD
		))
	split.add_child(safety_card)

	content.add_child(panel)


func _build_roadmap(data: Dictionary) -> void:
	var panel = _section_card(
		"THE COMPLETE OFFSEASON",
		"Every major roster-building stage is tracked from real production state. Open the authoritative center for any action that changes the franchise."
	)
	panel.name = "OffseasonRoadmapSection"
	var body = panel.get_meta("body") as VBoxContainer

	timeline = OffseasonTimelineV3.new()
	timeline.destination_requested.connect(_emit_navigation)
	body.add_child(timeline)
	timeline.configure(_array(data.get("roadmap")), active_primary)
	content.add_child(panel)


func _build_split_operations(data: Dictionary) -> void:
	var row = VBoxContainer.new()
	row.name = "OffseasonDraftMarketSplit"
	row.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row.add_theme_constant_override("separation", 12)
	content.add_child(row)

	var draft_card = _card(DS.PANEL, Color(active_primary, 0.30), 15)
	draft_card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var draft_body = _body(draft_card, 15)
	_build_draft_war_room(draft_body, _dict(data.get("draft_watch")))
	row.add_child(draft_card)

	var market_card = _card(DS.PANEL, Color(DS.ACCENT, 0.30), 15)
	market_card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var market_body = _body(market_card, 15)
	_build_market_war_room(market_body, _dict(data.get("market_watch")))
	row.add_child(market_card)


func _build_draft_war_room(body: VBoxContainer, draft: Dictionary) -> void:
	var header = HBoxContainer.new()
	header.add_theme_constant_override("separation", 8)
	body.add_child(header)

	var titles = VBoxContainer.new()
	titles.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	header.add_child(titles)
	titles.add_child(_label("DRAFT OPERATIONS", 8, active_primary.lightened(0.42)))
	titles.add_child(_label("SCOUTING WAR ROOM", 18, DS.TEXT))

	var button = _action_button("OPEN SCOUTING", active_primary)
	button.pressed.connect(_emit_navigation.bind("SCOUTING"))
	header.add_child(button)

	var phase = str(draft.get("phase", "not initialized")).replace("_", " ").to_upper()
	body.add_child(_label(
		"%s Draft • %s • %s prospects available" % [
			str(draft.get("draft_year", "NEXT")),
			phase,
			str(draft.get("available_prospect_count", 0))
		],
		9,
		DS.MUTED
	))

	var scout = _dict(draft.get("lead_scout"))
	if not scout.is_empty():
		body.add_child(_label(
			"LEAD SCOUT • %s • OVR %s" % [
				str(scout.get("name", "Scout")),
				_display(scout.get("overall"))
			],
			9,
			DS.ACCENT
		))

	var prospects = _array(draft.get("top_prospects"))
	if prospects.is_empty():
		body.add_child(_empty("Draft class intelligence is not available at the current lifecycle stage."))
		return

	var grid = GridContainer.new()
	grid.columns = 2
	grid.add_theme_constant_override("h_separation", 7)
	grid.add_theme_constant_override("v_separation", 7)
	body.add_child(grid)

	for raw in prospects.slice(0, 6):
		if typeof(raw) != TYPE_DICTIONARY:
			continue
		var prospect: Dictionary = raw
		var card = _card(Color("0f1820"), Color(active_primary, 0.22), 9)
		card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		var prospect_body = _body(card, 9)
		prospect_body.add_child(_label(str(prospect.get("name", "")), 10, DS.TEXT))
		prospect_body.add_child(_label(
			"%s • %s" % [
				str(prospect.get("position", "")),
				str(prospect.get("archetype", ""))
			],
			8,
			DS.MUTED
		))
		prospect_body.add_child(_label(
			"SCOUT OVR %s • POT %s • CONF %s" % [
				_display(prospect.get("scouted_overall")),
				_display(prospect.get("scouted_potential")),
				_display(prospect.get("confidence"))
			],
			8,
			active_primary.lightened(0.40)
		))
		grid.add_child(card)


func _build_market_war_room(body: VBoxContainer, market: Dictionary) -> void:
	var header = HBoxContainer.new()
	header.add_theme_constant_override("separation", 8)
	body.add_child(header)

	var titles = VBoxContainer.new()
	titles.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	header.add_child(titles)
	titles.add_child(_label("PLAYER MARKET", 8, DS.ACCENT))
	titles.add_child(_label("FREE-AGENCY WAR ROOM", 18, DS.TEXT))

	var button = _action_button("OPEN FREE AGENCY", DS.ACCENT)
	button.pressed.connect(_emit_navigation.bind("FREE AGENCY"))
	header.add_child(button)

	body.add_child(_label(
		"%s PLAYER(S) IN MARKET SNAPSHOT • %s" % [
			str(market.get("total_available", 0)),
			str(market.get("market_source", "")).replace("_", " ").to_upper()
		],
		9,
		DS.MUTED
	))

	var players = _array(market.get("top_available"))
	if players.is_empty():
		body.add_child(_empty("No free-agent market player is available in the current snapshot."))
		return

	for raw in players.slice(0, 6):
		if typeof(raw) != TYPE_DICTIONARY:
			continue
		var player: Dictionary = raw

		var line = HBoxContainer.new()
		line.add_theme_constant_override("separation", 8)

		var portrait = Portrait.new()
		portrait.custom_minimum_size = Vector2(54, 52)
		portrait.configure(player)
		line.add_child(portrait)

		var copy = VBoxContainer.new()
		copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		copy.add_child(_label(str(player.get("name", "")), 10, DS.TEXT))
		copy.add_child(_label(
			"%s • AGE %s" % [
				str(player.get("position", "")),
				_display(player.get("age"))
			],
			8,
			DS.MUTED
		))
		line.add_child(copy)

		var ratings = VBoxContainer.new()
		ratings.custom_minimum_size = Vector2(115, 0)
		ratings.add_child(_label("OVR %s" % _display(player.get("overall")), 10, DS.ACCENT))
		ratings.add_child(_label("POT %s" % _display(player.get("potential")), 8, DS.MUTED))
		line.add_child(ratings)

		body.add_child(line)


func _build_roster_war_room(data: Dictionary) -> void:
	var panel = _section_card(
		"ROSTER CONSTRUCTION + TRAINING CAMP",
		"Expansion 40 turns roster size, two-way capacity, position redundancy, young-core development, and bubble contracts into one opening-night planning board."
	)
	panel.name = "OffseasonRosterWarRoomSection"
	var body = panel.get_meta("body") as VBoxContainer

	roster_war_room = OffseasonRosterWarRoomV3.new()
	roster_war_room.destination_requested.connect(_emit_navigation)
	body.add_child(roster_war_room)
	roster_war_room.configure(
		_dict(data.get("roster")),
		_dict(data.get("camp_readiness")),
		_array(data.get("young_core")),
		_array(data.get("roster_battles")),
		active_primary
	)
	content.add_child(panel)


func _build_decision_board(data: Dictionary) -> void:
	var panel = _section_card(
		"GENERAL MANAGER DECISION BOARD",
		"Priority flags are generated from the certified lifecycle, roster construction, Draft state, and free-agent market. They are recommendations, not automatic writes."
	)
	panel.name = "OffseasonDecisionBoard"
	var body = panel.get_meta("body") as VBoxContainer

	var rows = _array(data.get("decision_checklist"))
	if rows.is_empty():
		body.add_child(_empty("No offseason planning task is available."))
		content.add_child(panel)
		return

	for raw in rows:
		if typeof(raw) != TYPE_DICTIONARY:
			continue
		var task: Dictionary = raw
		var tone = _priority_color(str(task.get("priority", "LOW")))

		var card = _card(Color(tone, 0.04), Color(tone, 0.22), 10)
		var card_body = _body(card, 10)
		var header = HBoxContainer.new()
		header.add_theme_constant_override("separation", 8)
		card_body.add_child(header)

		var priority = _pill(str(task.get("priority", "LOW")), tone)
		header.add_child(priority)

		var title = _label(str(task.get("title", "")), 11, DS.TEXT)
		header.add_child(title)

		var status = _pill(str(task.get("status", "")), DS.MUTED)
		header.add_child(status)

		var detail = _label(str(task.get("detail", "")), 9, DS.MUTED)
		detail.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		card_body.add_child(detail)

		var destination = str(task.get("destination", ""))
		if destination != "":
			var button = _action_button("OPEN %s" % destination, tone)
			button.pressed.connect(_emit_navigation.bind(destination))
			card_body.add_child(button)

		body.add_child(card)

	content.add_child(panel)


func _build_scope_card(data: Dictionary) -> void:
	var scope = _dict(data.get("system_scope"))
	var panel = _card(Color("0e151d"), Color(DS.BORDER, 0.70), 12)
	panel.name = "OffseasonScopeDisclosure"
	var body = _body(panel, 12)
	body.add_child(_label("EXPANSION 40 • SYSTEM SCOPE", 8, DS.MUTED))

	var text = _label(str(scope.get("note", "")), 9, DS.MUTED)
	text.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	body.add_child(text)

	var row = GridContainer.new()
	row.columns = 3
	row.add_theme_constant_override("h_separation", 8)
	row.add_theme_constant_override("v_separation", 8)
	body.add_child(row)
	row.add_child(_pill(
		"SUMMER DEVELOPMENT • PLANNING",
		DS.ACCENT if bool(scope.get("planning_surfaces_available", true)) else DS.MUTED
	))
	row.add_child(_pill(
		"TRAINING CAMP • PLANNING",
		DS.GOLD if bool(scope.get("planning_surfaces_available", true)) else DS.MUTED
	))
	row.add_child(_pill("NO DUPLICATE WRITES", DS.GOOD))

	content.add_child(panel)



func _build_bottom_safe_area() -> void:
	var spacer = Control.new()
	spacer.name = "OffseasonBottomSafeArea"
	spacer.custom_minimum_size = Vector2(0, 180)
	spacer.mouse_filter = Control.MOUSE_FILTER_IGNORE
	content.add_child(spacer)

func _section_card(title_text: String, detail_text: String) -> PanelContainer:
	var panel = _card(DS.PANEL, Color(DS.BORDER, 0.84), 15)
	var body = _body(panel, 16)
	panel.set_meta("body", body)
	body.add_child(_label(title_text, 19, DS.TEXT))
	var detail = _label(detail_text, 9, DS.MUTED)
	detail.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	body.add_child(detail)
	body.add_child(_divider())
	return panel


func _metric(
	parent: GridContainer,
	title_text: String,
	value_text: String,
	tone: Color
) -> void:
	var card = _card(Color(tone, 0.05), Color(tone, 0.25), 10)
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	card.custom_minimum_size = Vector2(0, 70)
	var body = _body(card, 9)
	body.add_child(_label(title_text, 8, tone))
	var value = _label(value_text, 14, DS.TEXT)
	value.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	body.add_child(value)
	parent.add_child(card)


func _action_button(text_value: String, tone: Color) -> Button:
	var button = Button.new()
	button.text = text_value
	button.custom_minimum_size = Vector2(0, 34)
	button.add_theme_font_size_override("font_size", 8)
	button.add_theme_color_override("font_color", DS.TEXT)
	button.add_theme_color_override("font_hover_color", DS.TEXT)
	button.add_theme_stylebox_override(
		"normal",
		_box(Color("111923"), 8, Color(DS.BORDER, 0.76))
	)
	button.add_theme_stylebox_override(
		"hover",
		_box(Color(tone, 0.10), 8, Color(tone, 0.62))
	)
	return button


func _emit_navigation(page_name: String) -> void:
	if page_name.strip_edges() == "":
		return
	navigate_requested.emit(page_name)


func _priority_color(priority: String) -> Color:
	match priority.to_upper():
		"CRITICAL":
			return DS.BAD
		"HIGH":
			return DS.GOLD
		"MEDIUM":
			return DS.ACCENT
		_:
			return DS.MUTED


func _result_color(result: String) -> Color:
	match result:
		"NBA CHAMPION":
			return DS.GOLD
		"NBA FINALS", "CONFERENCE CHAMPION":
			return DS.ACCENT
		"PLAYOFFS":
			return DS.GOOD
		_:
			return DS.MUTED


func _empty(text_value: String) -> Control:
	var panel = _card(Color("101821"), Color(DS.BORDER, 0.70), 9)
	var body = _body(panel, 10)
	var label = _label(text_value, 9, DS.MUTED)
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	body.add_child(label)
	return panel


func _pill(text_value: String, tone: Color) -> Label:
	var label = _label("  %s  " % text_value, 8, tone)
	label.autowrap_mode = TextServer.AUTOWRAP_OFF
	label.size_flags_horizontal = Control.SIZE_SHRINK_BEGIN
	label.add_theme_stylebox_override(
		"normal",
		_box(Color(tone, 0.07), 7, Color(tone, 0.28))
	)
	return label


func _card(fill: Color, border: Color, radius: int) -> PanelContainer:
	var card = PanelContainer.new()
	card.add_theme_stylebox_override("panel", _box(fill, radius, border))
	return card


func _body(card: PanelContainer, padding: int) -> VBoxContainer:
	var margin = MarginContainer.new()
	_set_margins(margin, padding, padding, padding, padding)
	card.add_child(margin)

	var body = VBoxContainer.new()
	body.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	body.add_theme_constant_override("separation", 6)
	margin.add_child(body)
	return body


func _label(text_value: String, font_size: int, color: Color) -> Label:
	var label = Label.new()
	label.text = text_value
	label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	label.add_theme_font_size_override("font_size", font_size)
	label.add_theme_color_override("font_color", color)
	return label


func _divider() -> HSeparator:
	var line = HSeparator.new()
	line.modulate = Color(1, 1, 1, 0.10)
	return line


func _box(fill: Color, radius: int, border: Color) -> StyleBoxFlat:
	var box = StyleBoxFlat.new()
	box.bg_color = fill
	box.border_color = border
	box.border_width_left = 1
	box.border_width_top = 1
	box.border_width_right = 1
	box.border_width_bottom = 1
	box.corner_radius_top_left = radius
	box.corner_radius_top_right = radius
	box.corner_radius_bottom_left = radius
	box.corner_radius_bottom_right = radius
	return box


func _set_margins(container: MarginContainer, left: int, top: int, right: int, bottom: int) -> void:
	container.add_theme_constant_override("margin_left", left)
	container.add_theme_constant_override("margin_top", top)
	container.add_theme_constant_override("margin_right", right)
	container.add_theme_constant_override("margin_bottom", bottom)


func _clear_below_status() -> void:
	if content == null:
		return
	var children = content.get_children()
	for index in range(children.size() - 1, 0, -1):
		var child = children[index]
		content.remove_child(child)
		child.queue_free()


func _dict(value) -> Dictionary:
	return value if typeof(value) == TYPE_DICTIONARY else {}


func _array(value) -> Array:
	return value if typeof(value) == TYPE_ARRAY else []


func _display(value) -> String:
	return "—" if value == null or str(value).strip_edges() == "" else str(value)


func _readable(color: Color) -> Color:
	var luminance = 0.2126 * color.r + 0.7152 * color.g + 0.0722 * color.b
	return Color("071014") if luminance > 0.57 else Color("f5f7fa")
