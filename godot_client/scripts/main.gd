extends Control

const BRIDGE_URL := "http://127.0.0.1:8765/health"
const SUMMARY_URL := "http://127.0.0.1:8765/v3/franchise-summary"
const ROSTER_URL := "http://127.0.0.1:8765/v3/roster"
const ROTATION_PREVIEW_URL := "http://127.0.0.1:8765/v3/rotation/preview"
const ROTATION_APPLY_URL := "http://127.0.0.1:8765/v3/rotation/apply"
const GAME_DAY_URL := "http://127.0.0.1:8765/v3/game-day"
const GAME_DAY_SIMULATE_URL := "http://127.0.0.1:8765/v3/game-day/simulate"

const BG := Color("080b12")
const SIDEBAR := Color("0d111a")
const PANEL := Color("121824")
const PANEL_ALT := Color("171f2d")
const PANEL_HOVER := Color("202b3d")
const TEXT := Color("f7f8fb")
const MUTED := Color("8d99aa")
const ACCENT := Color("8ed8ff")
const GOOD := Color("61d69b")
const BAD := Color("ff6577")
const BORDER := Color("263247")
const SOFT_BORDER := Color("1d2737")
const TEAM_PRIMARY := Color("d9273c")
const TEAM_PRIMARY_HOVER := Color("ef4055")
const GOLD := Color("f3c96b")

var bridge_status: Label
var bridge_detail: Label
var retry_button: Button
var http_request: HTTPRequest
var summary_request: HTTPRequest
var roster_request: HTTPRequest
var rotation_request: HTTPRequest
var game_day_request: HTTPRequest
var game_day_simulate_request: HTTPRequest

var home_page: Control
var roster_page: Control
var current_page := "HOME"
var nav_buttons := {}
var roster_payload := {}

var roster_subtitle: Label
var roster_status: Label
var roster_count_value: Label
var roster_payroll_value: Label
var roster_cap_value: Label
var roster_chemistry_value: Label
var roster_rows: VBoxContainer
var player_detail_overlay: Control
var rotation_overlay: Control
var game_day_overlay: Control
var game_day_matchup_label: Label
var game_day_detail_label: Label
var game_day_status_label: Label
var game_day_simulate_button: Button
var game_day_result_label: Label
var game_day_result_badge: Label
var game_day_result_meta_label: Label
var game_day_active_postgame_title: Label
var game_day_opponent_postgame_title: Label
var game_day_active_shooting_label: Label
var game_day_opponent_shooting_label: Label
var game_day_active_leaders_label: Label
var game_day_opponent_leaders_label: Label
var game_day_active_team := ""
var game_day_team_badge: Label
var game_day_opponent_badge: Label
var game_day_team_record_label: Label
var game_day_opponent_record_label: Label
var game_day_meta_label: Label
var game_day_alerts_label: Label
var rotation_edit_rows := {}
var rotation_edit_order := []
var rotation_feedback: Label
var rotation_total_label: Label
var rotation_preview_button: Button
var rotation_apply_button: Button
var rotation_request_mode := ""
var rotation_pending_body := ""
var rotation_validated_body := ""
var rotation_syncing := false

var header_subtitle: Label
var team_name_label: Label
var team_detail_label: Label
var team_abbr_badge: Label
var next_game_matchup: Label
var next_game_detail: Label

var record_value: Label
var record_detail: Label
var chemistry_value: Label
var chemistry_detail: Label
var cap_value: Label
var cap_detail: Label
var draft_value: Label
var draft_detail: Label


func _ready() -> void:
	_build_background()
	_build_interface()
	_build_http_client()
	_check_bridge()


func _build_background() -> void:
	var background := ColorRect.new()
	background.color = BG
	add_child(background)
	background.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)

	var top_band := ColorRect.new()
	top_band.color = Color(TEAM_PRIMARY, 0.055)
	top_band.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(top_band)
	top_band.anchor_right = 1.0
	top_band.offset_bottom = 185.0

	var accent_line := ColorRect.new()
	accent_line.color = TEAM_PRIMARY
	accent_line.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(accent_line)
	accent_line.anchor_right = 1.0
	accent_line.offset_bottom = 3.0


func _build_interface() -> void:
	var shell := HBoxContainer.new()
	shell.add_theme_constant_override("separation", 0)
	add_child(shell)
	shell.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)

	shell.add_child(_build_sidebar())

	var content_stack := Control.new()
	content_stack.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	content_stack.size_flags_vertical = Control.SIZE_EXPAND_FILL
	shell.add_child(content_stack)

	home_page = _build_main_area()
	content_stack.add_child(home_page)
	home_page.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)

	roster_page = _build_roster_area()
	content_stack.add_child(roster_page)
	roster_page.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)

	_show_page("HOME")

func _build_sidebar() -> Control:
	var sidebar_panel := PanelContainer.new()
	sidebar_panel.custom_minimum_size = Vector2(228, 0)
	sidebar_panel.add_theme_stylebox_override("panel", _box(SIDEBAR, 0, SOFT_BORDER))

	var margin := MarginContainer.new()
	_set_margins(margin, 18, 22, 18, 22)
	sidebar_panel.add_child(margin)

	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 10)
	margin.add_child(column)

	var brand_row := HBoxContainer.new()
	brand_row.add_theme_constant_override("separation", 11)
	column.add_child(brand_row)

	var mark := PanelContainer.new()
	mark.custom_minimum_size = Vector2(44, 44)
	mark.add_theme_stylebox_override("panel", _box(TEAM_PRIMARY, 10, TEAM_PRIMARY))
	brand_row.add_child(mark)

	var mark_label := Label.new()
	mark_label.text = "FS"
	mark_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	mark_label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	mark_label.add_theme_color_override("font_color", TEXT)
	mark_label.add_theme_font_size_override("font_size", 16)
	mark.add_child(mark_label)

	var brand := Label.new()
	brand.text = "FRANCHISE\nSIMULATOR"
	brand.add_theme_color_override("font_color", TEXT)
	brand.add_theme_font_size_override("font_size", 19)
	brand_row.add_child(brand)

	var version := Label.new()
	version.text = "V3 DESKTOP • FRANCHISE ENGINE"
	version.add_theme_color_override("font_color", MUTED)
	version.add_theme_font_size_override("font_size", 10)
	column.add_child(version)

	var brand_spacer := Control.new()
	brand_spacer.custom_minimum_size = Vector2(0, 20)
	column.add_child(brand_spacer)

	column.add_child(_nav_button("HOME", true))
	column.add_child(_nav_button("ROSTER"))
	column.add_child(_nav_button("GAME DAY"))
	column.add_child(_nav_button("TRADES"))
	column.add_child(_nav_button("FREE AGENCY"))
	column.add_child(_nav_button("SCOUTING"))
	column.add_child(_nav_button("LEAGUE"))
	column.add_child(_nav_button("FRONT OFFICE"))

	var expanding_spacer := Control.new()
	expanding_spacer.size_flags_vertical = Control.SIZE_EXPAND_FILL
	column.add_child(expanding_spacer)

	var eras := _nav_button("ERAS  •  COMING IN V3")
	eras.disabled = true
	column.add_child(eras)

	var footer := Label.new()
	footer.text = "V2 engine preserved\nV3 desktop alpha"
	footer.add_theme_color_override("font_color", MUTED)
	footer.add_theme_font_size_override("font_size", 11)
	column.add_child(footer)

	return sidebar_panel


func _build_main_area() -> Control:
	var outer := MarginContainer.new()
	outer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	outer.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_set_margins(outer, 34, 28, 34, 30)

	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 20)
	outer.add_child(column)

	column.add_child(_build_header())

	var hero_row := HBoxContainer.new()
	hero_row.add_theme_constant_override("separation", 16)
	hero_row.add_child(_build_team_card())
	hero_row.add_child(_build_next_game_card())
	column.add_child(hero_row)

	column.add_child(_build_engine_status_strip())

	var metrics := GridContainer.new()
	metrics.columns = 4
	metrics.add_theme_constant_override("h_separation", 14)
	metrics.add_theme_constant_override("v_separation", 14)
	metrics.add_child(_metric_card("RECORD", "LOADING...", "Waiting for V3 save"))
	metrics.add_child(_metric_card("CHEMISTRY", "LOADING...", "Waiting for V3 save"))
	metrics.add_child(_metric_card("CAP SPACE", "LOADING...", "Waiting for V3 save"))
	metrics.add_child(_metric_card("DRAFT CLASS", "LOADING...", "Waiting for V3 save"))
	column.add_child(metrics)

	var lower := HBoxContainer.new()
	lower.size_flags_vertical = Control.SIZE_EXPAND_FILL
	lower.add_theme_constant_override("separation", 16)
	lower.add_child(_build_activity_panel())
	lower.add_child(_build_quick_actions_panel())
	column.add_child(lower)

	return outer


func _build_header() -> Control:
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 14)

	var titles := VBoxContainer.new()
	titles.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	titles.add_theme_constant_override("separation", 3)

	var eyebrow := Label.new()
	eyebrow.text = "NBA FRANCHISE OPERATIONS"
	eyebrow.add_theme_color_override("font_color", TEAM_PRIMARY_HOVER)
	eyebrow.add_theme_font_size_override("font_size", 10)
	titles.add_child(eyebrow)

	var title := Label.new()
	title.text = "FRANCHISE HQ"
	title.add_theme_color_override("font_color", TEXT)
	title.add_theme_font_size_override("font_size", 34)
	titles.add_child(title)

	header_subtitle = Label.new()
	header_subtitle.text = "LOADING V3 WORKING FRANCHISE..."
	header_subtitle.add_theme_color_override("font_color", MUTED)
	header_subtitle.add_theme_font_size_override("font_size", 12)
	titles.add_child(header_subtitle)
	row.add_child(titles)

	var alpha := _pill("V3 DESKTOP ALPHA", TEAM_PRIMARY_HOVER)
	alpha.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	row.add_child(alpha)

	return row

func _build_team_card() -> Control:
	var card := _card(Vector2(330, 220))
	card.add_theme_stylebox_override("panel", _box(PANEL, 16, Color(TEAM_PRIMARY, 0.72)))
	var body := _card_body(card, 20)
	body.add_theme_constant_override("separation", 12)

	var top := HBoxContainer.new()
	top.add_theme_constant_override("separation", 10)
	top.add_child(_small_label("YOUR FRANCHISE", TEAM_PRIMARY_HOVER))
	var top_spacer := Control.new()
	top_spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	top.add_child(top_spacer)
	top.add_child(_pill("V3 WORKING SAVE", GOOD))
	body.add_child(top)

	var identity := HBoxContainer.new()
	identity.add_theme_constant_override("separation", 15)
	body.add_child(identity)

	var badge := PanelContainer.new()
	badge.custom_minimum_size = Vector2(72, 72)
	badge.add_theme_stylebox_override("panel", _box(TEAM_PRIMARY, 16, TEAM_PRIMARY_HOVER))
	identity.add_child(badge)

	team_abbr_badge = Label.new()
	team_abbr_badge.text = "CHI"
	team_abbr_badge.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	team_abbr_badge.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	team_abbr_badge.add_theme_color_override("font_color", TEXT)
	team_abbr_badge.add_theme_font_size_override("font_size", 22)
	badge.add_child(team_abbr_badge)

	var identity_text := VBoxContainer.new()
	identity_text.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	identity_text.add_theme_constant_override("separation", 3)
	identity.add_child(identity_text)

	team_name_label = Label.new()
	team_name_label.text = "LOADING..."
	team_name_label.add_theme_color_override("font_color", TEXT)
	team_name_label.add_theme_font_size_override("font_size", 25)
	team_name_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	identity_text.add_child(team_name_label)

	team_detail_label = Label.new()
	team_detail_label.text = "Reading V3 working franchise..."
	team_detail_label.add_theme_color_override("font_color", MUTED)
	team_detail_label.add_theme_font_size_override("font_size", 12)
	identity_text.add_child(team_detail_label)

	return card

func _build_next_game_card() -> Control:
	var card := _card(Vector2(410, 220))
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	card.add_theme_stylebox_override("panel", _box(PANEL, 16, BORDER))
	var body := _card_body(card, 20)
	body.add_theme_constant_override("separation", 10)

	var top := HBoxContainer.new()
	top.add_child(_small_label("NEXT GAME", GOLD))
	var top_spacer := Control.new()
	top_spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	top.add_child(top_spacer)
	top.add_child(_pill("REGULAR SEASON", MUTED))
	body.add_child(top)

	next_game_matchup = Label.new()
	next_game_matchup.text = "LOADING..."
	next_game_matchup.add_theme_color_override("font_color", TEXT)
	next_game_matchup.add_theme_font_size_override("font_size", 34)
	body.add_child(next_game_matchup)

	next_game_detail = Label.new()
	next_game_detail.text = "Reading schedule..."
	next_game_detail.add_theme_color_override("font_color", MUTED)
	next_game_detail.add_theme_font_size_override("font_size", 13)
	body.add_child(next_game_detail)

	var spacer := Control.new()
	spacer.size_flags_vertical = Control.SIZE_EXPAND_FILL
	body.add_child(spacer)

	var actions := HBoxContainer.new()
	actions.add_theme_constant_override("separation", 8)
	actions.add_child(_action_button("GAME PLAN"))
	var open_game_day := _action_button("OPEN GAME DAY", true)
	open_game_day.pressed.connect(_open_game_day_overlay)
	actions.add_child(open_game_day)
	body.add_child(actions)
	return card

func _build_engine_status_strip() -> Control:
	var strip := PanelContainer.new()
	strip.custom_minimum_size = Vector2(0, 58)
	strip.add_theme_stylebox_override("panel", _box(Color("0f151f"), 12, SOFT_BORDER))

	var margin := MarginContainer.new()
	_set_margins(margin, 16, 10, 12, 10)
	strip.add_child(margin)

	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 12)
	margin.add_child(row)

	var engine_tag := _pill("DESKTOP ENGINE", ACCENT)
	row.add_child(engine_tag)

	bridge_status = Label.new()
	bridge_status.text = "CHECKING..."
	bridge_status.add_theme_color_override("font_color", MUTED)
	bridge_status.add_theme_font_size_override("font_size", 13)
	bridge_status.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	row.add_child(bridge_status)

	bridge_detail = Label.new()
	bridge_detail.text = "Looking for the local Python bridge on port 8765."
	bridge_detail.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	bridge_detail.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	bridge_detail.add_theme_color_override("font_color", MUTED)
	bridge_detail.add_theme_font_size_override("font_size", 10)
	bridge_detail.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	row.add_child(bridge_detail)

	retry_button = _action_button("RETRY")
	retry_button.custom_minimum_size = Vector2(88, 32)
	retry_button.pressed.connect(_check_bridge)
	row.add_child(retry_button)

	return strip


func _metric_card(label_text: String, value_text: String, detail_text: String) -> Control:
	var card := _card(Vector2(0, 118))
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	card.add_theme_stylebox_override("panel", _box(PANEL_ALT, 14, SOFT_BORDER))
	var body := _card_body(card, 16)
	body.add_theme_constant_override("separation", 6)

	body.add_child(_small_label(label_text, TEAM_PRIMARY_HOVER if label_text == "RECORD" else MUTED))

	var value := Label.new()
	value.text = value_text
	value.add_theme_color_override("font_color", TEXT)
	value.add_theme_font_size_override("font_size", 27)
	body.add_child(value)

	var detail := Label.new()
	detail.text = detail_text
	detail.add_theme_color_override("font_color", GOOD)
	detail.add_theme_font_size_override("font_size", 11)
	body.add_child(detail)

	match label_text:
		"RECORD":
			record_value = value
			record_detail = detail
		"CHEMISTRY":
			chemistry_value = value
			chemistry_detail = detail
		"CAP SPACE":
			cap_value = value
			cap_detail = detail
		"DRAFT CLASS":
			draft_value = value
			draft_detail = detail

	return card

func _build_roster_area() -> Control:
	var outer := MarginContainer.new()
	outer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	outer.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_set_margins(outer, 32, 26, 32, 28)

	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 16)
	outer.add_child(column)

	var header := HBoxContainer.new()
	header.add_theme_constant_override("separation", 12)

	var titles := VBoxContainer.new()
	titles.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	titles.add_theme_constant_override("separation", 3)

	var eyebrow := Label.new()
	eyebrow.text = "TEAM OPERATIONS"
	eyebrow.add_theme_color_override("font_color", TEAM_PRIMARY_HOVER)
	eyebrow.add_theme_font_size_override("font_size", 10)
	titles.add_child(eyebrow)

	var title := Label.new()
	title.text = "ROSTER MANAGEMENT"
	title.add_theme_color_override("font_color", TEXT)
	title.add_theme_font_size_override("font_size", 31)
	titles.add_child(title)

	roster_subtitle = Label.new()
	roster_subtitle.text = "LOADING V3 WORKING ROSTER..."
	roster_subtitle.add_theme_color_override("font_color", MUTED)
	roster_subtitle.add_theme_font_size_override("font_size", 12)
	titles.add_child(roster_subtitle)
	header.add_child(titles)

	var edit_rotation := _action_button("EDIT ROTATION", true)
	edit_rotation.pressed.connect(_show_rotation_editor)
	header.add_child(edit_rotation)

	var refresh := _action_button("REFRESH")
	refresh.pressed.connect(_request_roster)
	header.add_child(refresh)
	column.add_child(header)

	var metrics := GridContainer.new()
	metrics.columns = 4
	metrics.add_theme_constant_override("h_separation", 14)
	metrics.add_theme_constant_override("v_separation", 14)
	metrics.add_child(_roster_summary_card("ROSTER", "LOADING..."))
	metrics.add_child(_roster_summary_card("PAYROLL", "LOADING..."))
	metrics.add_child(_roster_summary_card("CAP ROOM EST.", "LOADING..."))
	metrics.add_child(_roster_summary_card("CHEMISTRY", "LOADING..."))
	column.add_child(metrics)

	var status_panel := PanelContainer.new()
	status_panel.add_theme_stylebox_override("panel", _box(Color("0f151f"), 10, SOFT_BORDER))
	column.add_child(status_panel)

	var status_margin := MarginContainer.new()
	_set_margins(status_margin, 12, 8, 12, 8)
	status_panel.add_child(status_margin)

	roster_status = Label.new()
	roster_status.text = "Waiting for the V3 roster endpoint."
	roster_status.add_theme_color_override("font_color", MUTED)
	roster_status.add_theme_font_size_override("font_size", 10)
	status_margin.add_child(roster_status)

	var roster_card := _card(Vector2(0, 0))
	roster_card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	roster_card.size_flags_vertical = Control.SIZE_EXPAND_FILL
	var body := _card_body(roster_card, 16)

	var roster_header_row := HBoxContainer.new()
	roster_header_row.add_child(_section_title("ACTIVE ROSTER"))
	var roster_header_spacer := Control.new()
	roster_header_spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	roster_header_row.add_child(roster_header_spacer)
	roster_header_row.add_child(_small_label("CLICK ANY PLAYER FOR FULL PROFILE", MUTED))
	body.add_child(roster_header_row)
	body.add_child(_roster_table_header())

	var scroll := ScrollContainer.new()
	scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	body.add_child(scroll)

	roster_rows = VBoxContainer.new()
	roster_rows.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	roster_rows.add_theme_constant_override("separation", 5)
	scroll.add_child(roster_rows)

	var loading := Label.new()
	loading.text = "Loading players from the V3 working checkpoint..."
	loading.add_theme_color_override("font_color", MUTED)
	loading.add_theme_font_size_override("font_size", 12)
	roster_rows.add_child(loading)

	column.add_child(roster_card)

	var note := Label.new()
	note.text = "V3 WORKING SAVE • Rotation edits are isolated from the protected V2 release checkpoint. Cap room remains an active-roster contract estimate."
	note.add_theme_color_override("font_color", MUTED)
	note.add_theme_font_size_override("font_size", 10)
	column.add_child(note)

	return outer


func _roster_summary_card(label_text: String, value_text: String) -> Control:
	var card := _card(Vector2(0, 96))
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	card.add_theme_stylebox_override("panel", _box(PANEL_ALT, 12, SOFT_BORDER))
	var body := _card_body(card, 14)
	body.add_theme_constant_override("separation", 5)

	body.add_child(
		_small_label(
			label_text,
			TEAM_PRIMARY_HOVER if label_text == "ROSTER" else MUTED
		)
	)

	var value := Label.new()
	value.text = value_text
	value.add_theme_color_override("font_color", TEXT)
	value.add_theme_font_size_override("font_size", 23)
	body.add_child(value)

	match label_text:
		"ROSTER":
			roster_count_value = value
		"PAYROLL":
			roster_payroll_value = value
		"CAP ROOM EST.":
			roster_cap_value = value
		"CHEMISTRY":
			roster_chemistry_value = value

	return card


func _roster_table_header() -> Control:
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 8)
	row.add_child(_roster_cell("PLAYER", 180, MUTED))
	row.add_child(_roster_cell("POS", 62, MUTED))
	row.add_child(_roster_cell("OVR", 48, MUTED, HORIZONTAL_ALIGNMENT_CENTER))
	row.add_child(_roster_cell("AGE", 44, MUTED, HORIZONTAL_ALIGNMENT_CENTER))
	row.add_child(_roster_cell("ROLE", 180, MUTED))
	row.add_child(_roster_cell("MIN", 48, MUTED, HORIZONTAL_ALIGNMENT_CENTER))
	row.add_child(_roster_cell("SALARY", 78, MUTED))
	row.add_child(_roster_cell("MORALE", 82, MUTED))
	row.add_child(_roster_cell("HEALTH", 128, MUTED))
	row.add_child(_roster_cell("PPG", 50, MUTED, HORIZONTAL_ALIGNMENT_RIGHT))
	return row


func _roster_row(player: Dictionary) -> Control:
	var panel := PanelContainer.new()
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	panel.add_theme_stylebox_override("panel", _box(PANEL_ALT, 7, BORDER))
	panel.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	panel.mouse_filter = Control.MOUSE_FILTER_STOP
	panel.tooltip_text = "Open %s player profile" % str(player.get("name", "player"))
	panel.gui_input.connect(_on_roster_row_input.bind(player))

	var margin := MarginContainer.new()
	margin.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_set_margins(margin, 11, 8, 11, 8)
	panel.add_child(margin)

	var row := HBoxContainer.new()
	row.mouse_filter = Control.MOUSE_FILTER_IGNORE
	row.add_theme_constant_override("separation", 8)
	margin.add_child(row)

	var player_name := str(player.get("name", "Unknown"))
	var starter := bool(player.get("is_starter", false))
	var name_color := TEAM_PRIMARY_HOVER if starter else TEXT
	if starter:
		player_name = "START • " + player_name
		panel.add_theme_stylebox_override(
			"panel",
			_box(Color("1b1821"), 9, Color(TEAM_PRIMARY, 0.52))
		)

	var morale = player.get("morale", {})
	var morale_text := str(morale.get("status", ""))
	var morale_color := MUTED
	if morale_text in ["Happy", "Thriving", "Content"]:
		morale_color = GOOD
	elif morale_text in ["Frustrated", "Angry", "Demanding Trade"]:
		morale_color = BAD

	var health = player.get("health", {})
	var health_text := str(health.get("display", "Unknown"))
	var health_status := str(health.get("status", "unknown"))
	var health_color := GOOD if health_status == "healthy" else BAD

	var contract = player.get("contract", {})
	var stats = player.get("season_stats", {})

	row.add_child(_roster_cell(player_name, 180, name_color))
	row.add_child(_roster_cell(str(player.get("position", "")), 62, TEXT))
	row.add_child(_roster_cell(_number_text(player.get("overall", null), 1), 48, TEXT, HORIZONTAL_ALIGNMENT_CENTER))
	row.add_child(_roster_cell(_number_text(player.get("age", null), 1), 44, MUTED, HORIZONTAL_ALIGNMENT_CENTER))
	row.add_child(_roster_cell(str(player.get("role", "")), 180, TEXT))
	row.add_child(_roster_cell(_number_text(player.get("target_minutes", 0.0), 0), 48, TEXT, HORIZONTAL_ALIGNMENT_CENTER))
	row.add_child(_roster_cell(str(contract.get("salary_display", "N/A")), 78, TEXT))
	row.add_child(_roster_cell(morale_text, 82, morale_color))
	row.add_child(_roster_cell(health_text, 128, health_color))
	row.add_child(_roster_cell(_number_text(stats.get("ppg", 0.0), 1), 50, TEXT, HORIZONTAL_ALIGNMENT_RIGHT))

	return panel


func _on_roster_row_input(event: InputEvent, player: Dictionary) -> void:
	if event is InputEventMouseButton:
		var mouse_event := event as InputEventMouseButton
		if mouse_event.button_index == MOUSE_BUTTON_LEFT and mouse_event.pressed:
			_show_player_detail(player)


func _show_player_detail(player: Dictionary) -> void:
	_close_player_detail()

	player_detail_overlay = Control.new()
	player_detail_overlay.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	player_detail_overlay.mouse_filter = Control.MOUSE_FILTER_STOP
	add_child(player_detail_overlay)
	player_detail_overlay.move_to_front()

	var dim := ColorRect.new()
	dim.color = Color(0, 0, 0, 0.72)
	dim.mouse_filter = Control.MOUSE_FILTER_STOP
	player_detail_overlay.add_child(dim)
	dim.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)

	var center := CenterContainer.new()
	center.mouse_filter = Control.MOUSE_FILTER_PASS
	player_detail_overlay.add_child(center)
	center.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)

	var card := _card(Vector2(940, 650))
	card.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	card.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	center.add_child(card)

	var body := _card_body(card, 20)
	body.add_theme_constant_override("separation", 14)

	var header := HBoxContainer.new()
	header.add_theme_constant_override("separation", 14)
	body.add_child(header)

	var title_box := VBoxContainer.new()
	title_box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	title_box.add_theme_constant_override("separation", 3)
	header.add_child(title_box)

	var player_name := Label.new()
	player_name.text = str(player.get("name", "Unknown Player"))
	player_name.add_theme_color_override("font_color", TEXT)
	player_name.add_theme_font_size_override("font_size", 28)
	title_box.add_child(player_name)

	var subtitle := Label.new()
	subtitle.text = "%s  •  Age %s  •  OVR %s  •  POT %s  •  %s" % [
		str(player.get("position", "")),
		_number_text(player.get("age", null), 1),
		_number_text(player.get("overall", null), 1),
		_number_text(player.get("potential", null), 1),
		str(player.get("development_direction", ""))
	]
	subtitle.add_theme_color_override("font_color", MUTED)
	subtitle.add_theme_font_size_override("font_size", 12)
	title_box.add_child(subtitle)

	var close_button := _action_button("CLOSE")
	close_button.pressed.connect(_close_player_detail)
	header.add_child(close_button)

	var tags := HBoxContainer.new()
	tags.add_theme_constant_override("separation", 8)
	body.add_child(tags)

	if bool(player.get("is_starter", false)):
		tags.add_child(_pill("STARTER", ACCENT))
	elif bool(player.get("in_rotation", false)):
		tags.add_child(_pill("ROTATION", GOOD))
	else:
		tags.add_child(_pill("RESERVE", MUTED))

	var health = player.get("health", {})
	var health_status := str(health.get("status", "unknown"))
	tags.add_child(
		_pill(
			str(health.get("display", "Unknown")),
			GOOD if health_status == "healthy" else BAD
		)
	)

	var morale = player.get("morale", {})
	var morale_status := str(morale.get("status", "Unknown"))
	var morale_color := MUTED
	if morale_status in ["Happy", "Thriving", "Content"]:
		morale_color = GOOD
	elif morale_status in ["Frustrated", "Angry", "Demanding Trade"]:
		morale_color = BAD
	tags.add_child(_pill(morale_status, morale_color))

	var scroll := ScrollContainer.new()
	scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	body.add_child(scroll)

	var content := VBoxContainer.new()
	content.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	content.add_theme_constant_override("separation", 12)
	scroll.add_child(content)

	var grid := GridContainer.new()
	grid.columns = 2
	grid.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	grid.add_theme_constant_override("h_separation", 12)
	grid.add_theme_constant_override("v_separation", 12)
	content.add_child(grid)

	var stats = player.get("season_stats", {})
	grid.add_child(
		_detail_card(
			"SEASON PRODUCTION",
			[
				"PPG   %s" % _number_text(stats.get("ppg", null), 1),
				"RPG   %s" % _number_text(stats.get("rpg", null), 1),
				"APG   %s" % _number_text(stats.get("apg", null), 1),
				"MPG   %s" % _number_text(stats.get("mpg", null), 1),
				"SPG   %s" % _number_text(stats.get("spg", null), 1),
				"BPG   %s" % _number_text(stats.get("bpg", null), 1),
				"FG%%   %s" % _pct_text(stats.get("fg_pct", null)),
				"3P%%   %s" % _pct_text(stats.get("three_pct", null)),
				"FT%%   %s" % _pct_text(stats.get("ft_pct", null)),
				"GP / GS   %s / %s" % [
					str(stats.get("games_played", 0)),
					str(stats.get("games_started", 0))
				]
			]
		)
	)

	var contract = player.get("contract", {})
	var contract_lines := [
		"Role   %s" % str(player.get("role", "")),
		"Target minutes   %s" % _number_text(player.get("target_minutes", 0), 0),
		"Salary   %s" % str(contract.get("salary_display", "N/A")),
		"Years remaining   %s" % str(contract.get("years_remaining", 0)),
		"Contract status   %s" % _pretty_phase(str(contract.get("status", ""))),
		"Option   %s" % _friendly_value(str(contract.get("option_type", ""))),
		"Rotation order   %s" % _friendly_value(str(player.get("rotation_order", "")))
	]
	grid.add_child(_detail_card("ROLE + CONTRACT", contract_lines))

	var morale_reasons := ""
	for reason in morale.get("reasons", []):
		if morale_reasons != "":
			morale_reasons += "\n"
		morale_reasons += "• " + str(reason)

	if morale_reasons == "":
		morale_reasons = "No active morale concerns."

	grid.add_child(
		_detail_card(
			"MORALE",
			[
				"Status   %s" % morale_status,
				"Score   %s" % _number_text(morale.get("score", null), 1),
				"Role satisfaction   %s" % _number_text(morale.get("role_satisfaction", null), 1),
				"Expected role   %s" % _friendly_value(str(morale.get("expected_role", ""))),
				"Recent minutes   %s" % _number_text(morale.get("recent_minutes", null), 1),
				"Trade request risk   %s%%" % _number_text(morale.get("trade_request_risk", null), 1),
				"Trade status   %s" % _friendly_value(str(morale.get("trade_request_status", ""))),
				morale_reasons
			]
		)
	)

	var health_lines := [
		"Status   %s" % str(health.get("display", "Unknown")),
		"Fatigue   %s" % _number_text(health.get("fatigue", null), 1),
		"Durability   %s" % _ratio_pct_text(health.get("durability", null)),
		"Risk tier   %s" % _friendly_value(str(health.get("risk_tier", ""))),
		"Games missed   %s" % str(health.get("season_games_missed", 0)),
		"Injuries suffered   %s" % str(health.get("injuries_suffered", 0))
	]

	var expected_return := int(health.get("expected_return_day", 0))
	if expected_return > 0:
		health_lines.append("Expected return day   %s" % expected_return)

	var health_notes := str(health.get("notes", ""))
	if health_notes != "":
		health_lines.append(health_notes)

	var risk_explanation := str(health.get("risk_explanation", ""))
	if risk_explanation != "":
		health_lines.append(risk_explanation)

	grid.add_child(_detail_card("HEALTH + WORKLOAD", health_lines))

	grid.add_child(
		_detail_card(
			"DEVELOPMENT",
			[
				"Overall   %s" % _number_text(player.get("overall", null), 1),
				"Potential   %s" % _number_text(player.get("potential", null), 1),
				"Future outlook   %s" % _number_text(player.get("future_outlook", null), 1),
				"Direction   %s" % _friendly_value(str(player.get("development_direction", ""))),
				"Age   %s" % _number_text(player.get("age", null), 1),
				"Generated prospect   %s" % ("Yes" if bool(player.get("generated_prospect", false)) else "No")
			]
		)
	)

	var skills = player.get("skills", {})
	grid.add_child(
		_detail_card(
			"SKILL RATINGS",
			[
				"Scoring   %s" % _number_text(skills.get("scoring_rating", null), 1),
				"Shooting   %s" % _number_text(skills.get("shooting_rating", null), 1),
				"Playmaking   %s" % _number_text(skills.get("playmaking_rating", null), 1),
				"Rebounding   %s" % _number_text(skills.get("rebounding_rating", null), 1),
				"Defense   %s" % _number_text(skills.get("defense_rating", null), 1),
				"Efficiency   %s" % _number_text(skills.get("efficiency_rating", null), 1),
				"Availability   %s" % _number_text(skills.get("availability_rating", null), 1)
			]
		)
	)

	var footer := Label.new()
	footer.text = "READ-ONLY PLAYER PROFILE • Data comes from the active V2 franchise checkpoint."
	footer.add_theme_color_override("font_color", MUTED)
	footer.add_theme_font_size_override("font_size", 10)
	content.add_child(footer)


func _detail_card(title_text: String, lines: Array) -> Control:
	var card := _card(Vector2(0, 0))
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var body := _card_body(card, 14)

	body.add_child(_small_label(title_text, ACCENT))

	for line in lines:
		var label := Label.new()
		label.text = str(line)
		label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		label.add_theme_color_override("font_color", TEXT)
		label.add_theme_font_size_override("font_size", 11)
		body.add_child(label)

	return card


func _close_player_detail() -> void:
	if player_detail_overlay != null and is_instance_valid(player_detail_overlay):
		player_detail_overlay.queue_free()
	player_detail_overlay = null


func _open_game_day_overlay() -> void:
	_close_game_day_overlay()

	game_day_overlay = Control.new()
	game_day_overlay.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	game_day_overlay.mouse_filter = Control.MOUSE_FILTER_STOP
	add_child(game_day_overlay)
	game_day_overlay.move_to_front()

	var dim := ColorRect.new()
	dim.color = Color(0, 0, 0, 0.82)
	dim.mouse_filter = Control.MOUSE_FILTER_STOP
	game_day_overlay.add_child(dim)
	dim.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)

	var center := CenterContainer.new()
	center.mouse_filter = Control.MOUSE_FILTER_PASS
	game_day_overlay.add_child(center)
	center.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)

	var card := _card(Vector2(980, 720))
	card.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	card.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	card.add_theme_stylebox_override("panel", _box(PANEL, 18, Color(TEAM_PRIMARY, 0.55)))
	center.add_child(card)

	var body := _card_body(card, 22)
	body.add_theme_constant_override("separation", 14)

	var header := HBoxContainer.new()
	header.add_theme_constant_override("separation", 12)
	body.add_child(header)

	var titles := VBoxContainer.new()
	titles.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	titles.add_theme_constant_override("separation", 2)
	header.add_child(titles)

	var eyebrow := Label.new()
	eyebrow.text = "FRANCHISE GAME DAY"
	eyebrow.add_theme_color_override("font_color", TEAM_PRIMARY_HOVER)
	eyebrow.add_theme_font_size_override("font_size", 10)
	titles.add_child(eyebrow)

	var title := Label.new()
	title.text = "GAME DAY"
	title.add_theme_color_override("font_color", TEXT)
	title.add_theme_font_size_override("font_size", 28)
	titles.add_child(title)

	var subtitle := Label.new()
	subtitle.text = "V3 WORKING SAVE • LIVE SIMULATION"
	subtitle.add_theme_color_override("font_color", MUTED)
	subtitle.add_theme_font_size_override("font_size", 11)
	titles.add_child(subtitle)

	var close_button := _action_button("CLOSE")
	close_button.pressed.connect(_close_game_day_overlay)
	header.add_child(close_button)

	var matchup_panel := PanelContainer.new()
	matchup_panel.custom_minimum_size = Vector2(0, 190)
	matchup_panel.add_theme_stylebox_override("panel", _box(PANEL_ALT, 16, SOFT_BORDER))
	body.add_child(matchup_panel)

	var matchup_margin := MarginContainer.new()
	_set_margins(matchup_margin, 20, 18, 20, 18)
	matchup_panel.add_child(matchup_margin)

	var matchup_row := HBoxContainer.new()
	matchup_row.add_theme_constant_override("separation", 18)
	matchup_margin.add_child(matchup_row)

	var left_team := VBoxContainer.new()
	left_team.custom_minimum_size = Vector2(220, 0)
	left_team.add_theme_constant_override("separation", 6)
	matchup_row.add_child(left_team)

	left_team.add_child(_small_label("YOUR TEAM", TEAM_PRIMARY_HOVER))

	var left_badge_panel := PanelContainer.new()
	left_badge_panel.custom_minimum_size = Vector2(100, 82)
	left_badge_panel.add_theme_stylebox_override("panel", _box(TEAM_PRIMARY, 14, TEAM_PRIMARY_HOVER))
	left_team.add_child(left_badge_panel)

	game_day_team_badge = Label.new()
	game_day_team_badge.text = "CHI"
	game_day_team_badge.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	game_day_team_badge.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	game_day_team_badge.add_theme_color_override("font_color", TEXT)
	game_day_team_badge.add_theme_font_size_override("font_size", 30)
	left_badge_panel.add_child(game_day_team_badge)

	game_day_team_record_label = Label.new()
	game_day_team_record_label.text = "Record --"
	game_day_team_record_label.add_theme_color_override("font_color", MUTED)
	game_day_team_record_label.add_theme_font_size_override("font_size", 12)
	left_team.add_child(game_day_team_record_label)

	var center_matchup := VBoxContainer.new()
	center_matchup.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	center_matchup.alignment = BoxContainer.ALIGNMENT_CENTER
	center_matchup.add_theme_constant_override("separation", 7)
	matchup_row.add_child(center_matchup)

	game_day_matchup_label = Label.new()
	game_day_matchup_label.text = "LOADING..."
	game_day_matchup_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	game_day_matchup_label.add_theme_color_override("font_color", TEXT)
	game_day_matchup_label.add_theme_font_size_override("font_size", 32)
	center_matchup.add_child(game_day_matchup_label)

	game_day_meta_label = Label.new()
	game_day_meta_label.text = "Reading schedule..."
	game_day_meta_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	game_day_meta_label.add_theme_color_override("font_color", GOLD)
	game_day_meta_label.add_theme_font_size_override("font_size", 12)
	center_matchup.add_child(game_day_meta_label)

	game_day_detail_label = Label.new()
	game_day_detail_label.text = "Reading V3 Game Day endpoint..."
	game_day_detail_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	game_day_detail_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	game_day_detail_label.add_theme_color_override("font_color", MUTED)
	game_day_detail_label.add_theme_font_size_override("font_size", 11)
	center_matchup.add_child(game_day_detail_label)

	var right_team := VBoxContainer.new()
	right_team.custom_minimum_size = Vector2(220, 0)
	right_team.add_theme_constant_override("separation", 6)
	matchup_row.add_child(right_team)

	right_team.add_child(_small_label("OPPONENT", MUTED))

	var right_badge_panel := PanelContainer.new()
	right_badge_panel.custom_minimum_size = Vector2(100, 82)
	right_badge_panel.add_theme_stylebox_override("panel", _box(Color("222b3b"), 14, BORDER))
	right_team.add_child(right_badge_panel)

	game_day_opponent_badge = Label.new()
	game_day_opponent_badge.text = "OPP"
	game_day_opponent_badge.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	game_day_opponent_badge.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	game_day_opponent_badge.add_theme_color_override("font_color", TEXT)
	game_day_opponent_badge.add_theme_font_size_override("font_size", 30)
	right_badge_panel.add_child(game_day_opponent_badge)

	game_day_opponent_record_label = Label.new()
	game_day_opponent_record_label.text = "Record --"
	game_day_opponent_record_label.add_theme_color_override("font_color", MUTED)
	game_day_opponent_record_label.add_theme_font_size_override("font_size", 12)
	right_team.add_child(game_day_opponent_record_label)

	var readiness := HBoxContainer.new()
	readiness.add_theme_constant_override("separation", 12)
	body.add_child(readiness)

	game_day_status_label = Label.new()
	game_day_status_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	game_day_status_label.text = "Connecting to Game Day state..."
	game_day_status_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	game_day_status_label.add_theme_color_override("font_color", MUTED)
	game_day_status_label.add_theme_font_size_override("font_size", 12)
	readiness.add_child(game_day_status_label)

	game_day_simulate_button = _action_button("SIMULATE GAME", true)
	game_day_simulate_button.custom_minimum_size = Vector2(160, 44)
	game_day_simulate_button.disabled = true
	game_day_simulate_button.pressed.connect(_simulate_game_day_overlay)
	readiness.add_child(game_day_simulate_button)

	var alert_panel := PanelContainer.new()
	alert_panel.add_theme_stylebox_override("panel", _box(Color("101722"), 12, SOFT_BORDER))
	body.add_child(alert_panel)

	var alert_margin := MarginContainer.new()
	_set_margins(alert_margin, 14, 10, 14, 10)
	alert_panel.add_child(alert_margin)

	game_day_alerts_label = Label.new()
	game_day_alerts_label.text = "GAME PLAN CHECK • Loading coaching, medical, and workload alerts..."
	game_day_alerts_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	game_day_alerts_label.add_theme_color_override("font_color", MUTED)
	game_day_alerts_label.add_theme_font_size_override("font_size", 11)
	alert_margin.add_child(game_day_alerts_label)

	var result_panel := PanelContainer.new()
	result_panel.size_flags_vertical = Control.SIZE_EXPAND_FILL
	result_panel.add_theme_stylebox_override("panel", _box(Color("0f151f"), 14, SOFT_BORDER))
	body.add_child(result_panel)

	var result_margin := MarginContainer.new()
	_set_margins(result_margin, 16, 14, 16, 14)
	result_panel.add_child(result_margin)

	var result_box := VBoxContainer.new()
	result_box.add_theme_constant_override("separation", 8)
	result_margin.add_child(result_box)

	var last_game_header := HBoxContainer.new()
	result_box.add_child(last_game_header)
	last_game_header.add_child(_small_label("LAST GAME", GOLD))
	var last_game_spacer := Control.new()
	last_game_spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	last_game_header.add_child(last_game_spacer)
	last_game_header.add_child(_pill("POSTGAME", MUTED))

	var result_score_row := HBoxContainer.new()
	result_score_row.add_theme_constant_override("separation", 10)
	result_box.add_child(result_score_row)

	game_day_result_label = Label.new()
	game_day_result_label.text = "No completed game is available yet."
	game_day_result_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	game_day_result_label.add_theme_color_override("font_color", TEXT)
	game_day_result_label.add_theme_font_size_override("font_size", 24)
	result_score_row.add_child(game_day_result_label)

	game_day_result_badge = _pill("WAITING", MUTED)
	result_score_row.add_child(game_day_result_badge)

	game_day_result_meta_label = Label.new()
	game_day_result_meta_label.text = "The latest completed controlled-team game will appear here."
	game_day_result_meta_label.add_theme_color_override("font_color", MUTED)
	game_day_result_meta_label.add_theme_font_size_override("font_size", 10)
	result_box.add_child(game_day_result_meta_label)

	var compare_row := HBoxContainer.new()
	compare_row.add_theme_constant_override("separation", 12)
	result_box.add_child(compare_row)

	var active_postgame := PanelContainer.new()
	active_postgame.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	active_postgame.add_theme_stylebox_override("panel", _box(PANEL_ALT, 12, Color(TEAM_PRIMARY, 0.55)))
	compare_row.add_child(active_postgame)

	var active_margin := MarginContainer.new()
	_set_margins(active_margin, 12, 10, 12, 10)
	active_postgame.add_child(active_margin)

	var active_box := VBoxContainer.new()
	active_box.add_theme_constant_override("separation", 5)
	active_margin.add_child(active_box)

	game_day_active_postgame_title = _small_label("YOUR TEAM", TEAM_PRIMARY_HOVER)
	active_box.add_child(game_day_active_postgame_title)

	game_day_active_shooting_label = Label.new()
	game_day_active_shooting_label.text = "FG -- • 3PT --"
	game_day_active_shooting_label.add_theme_color_override("font_color", TEXT)
	game_day_active_shooting_label.add_theme_font_size_override("font_size", 11)
	active_box.add_child(game_day_active_shooting_label)

	game_day_active_leaders_label = Label.new()
	game_day_active_leaders_label.text = "Leaders unavailable."
	game_day_active_leaders_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	game_day_active_leaders_label.add_theme_color_override("font_color", MUTED)
	game_day_active_leaders_label.add_theme_font_size_override("font_size", 10)
	active_box.add_child(game_day_active_leaders_label)

	var opponent_postgame := PanelContainer.new()
	opponent_postgame.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	opponent_postgame.add_theme_stylebox_override("panel", _box(PANEL_ALT, 12, BORDER))
	compare_row.add_child(opponent_postgame)

	var opponent_margin := MarginContainer.new()
	_set_margins(opponent_margin, 12, 10, 12, 10)
	opponent_postgame.add_child(opponent_margin)

	var opponent_box := VBoxContainer.new()
	opponent_box.add_theme_constant_override("separation", 5)
	opponent_margin.add_child(opponent_box)

	game_day_opponent_postgame_title = _small_label("OPPONENT", MUTED)
	opponent_box.add_child(game_day_opponent_postgame_title)

	game_day_opponent_shooting_label = Label.new()
	game_day_opponent_shooting_label.text = "FG -- • 3PT --"
	game_day_opponent_shooting_label.add_theme_color_override("font_color", TEXT)
	game_day_opponent_shooting_label.add_theme_font_size_override("font_size", 11)
	opponent_box.add_child(game_day_opponent_shooting_label)

	game_day_opponent_leaders_label = Label.new()
	game_day_opponent_leaders_label.text = "Leaders unavailable."
	game_day_opponent_leaders_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	game_day_opponent_leaders_label.add_theme_color_override("font_color", MUTED)
	game_day_opponent_leaders_label.add_theme_font_size_override("font_size", 10)
	opponent_box.add_child(game_day_opponent_leaders_label)

	_request_game_day_overlay()


func _request_game_day_overlay() -> void:
	if game_day_request == null:
		return
	if game_day_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		game_day_request.cancel_request()

	var error := game_day_request.request(GAME_DAY_URL)
	if error != OK and game_day_status_label != null:
		game_day_status_label.text = "Could not start Game Day request (error %s)." % error
		game_day_status_label.add_theme_color_override("font_color", BAD)


func _on_game_day_completed(
	result: int,
	response_code: int,
	_headers: PackedStringArray,
	body: PackedByteArray
) -> void:
	if game_day_overlay == null or not is_instance_valid(game_day_overlay):
		return

	if result != HTTPRequest.RESULT_SUCCESS or response_code != 200:
		game_day_status_label.text = "Game Day state could not be loaded."
		game_day_status_label.add_theme_color_override("font_color", BAD)
		return

	var payload = JSON.parse_string(body.get_string_from_utf8())
	if typeof(payload) != TYPE_DICTIONARY:
		game_day_status_label.text = "Game Day endpoint returned invalid data."
		game_day_status_label.add_theme_color_override("font_color", BAD)
		return

	var record = payload.get("record", {})
	var opponent_record = payload.get("opponent_record", {})
	game_day_active_team = str(payload.get("team", ""))
	var last_game = payload.get("last_game", null)
	var next_game = payload.get("next_game", null)
	var rotation = payload.get("rotation", {})
	var unavailable = payload.get("unavailable_players", [])
	var sync = payload.get("league_sync", {})

	if next_game == null or typeof(next_game) != TYPE_DICTIONARY:
		game_day_matchup_label.text = "NO GAME SCHEDULED"
		game_day_detail_label.text = "Record %s" % str(record.get("display", "N/A"))
		game_day_status_label.text = "No controlled-team game is currently scheduled."
		return

	var active_team := str(payload.get("team", "TEAM")).to_upper()
	var opponent_team := str(next_game.get("opponent", "OPP")).to_upper()
	var is_home := bool(next_game.get("is_home", false))

	if game_day_team_badge != null:
		game_day_team_badge.text = active_team
	if game_day_opponent_badge != null:
		game_day_opponent_badge.text = opponent_team
	if game_day_team_record_label != null:
		game_day_team_record_label.text = "Record %s" % str(record.get("display", "N/A"))
	if game_day_opponent_record_label != null:
		game_day_opponent_record_label.text = "Record %s" % str(opponent_record.get("display", "N/A"))

	game_day_matchup_label.text = "%s  %s  %s" % [
		active_team,
		"VS" if is_home else "@",
		opponent_team
	]

	if game_day_meta_label != null:
		game_day_meta_label.text = "DAY %s • %s" % [
			str(next_game.get("day_index", "?")),
			"HOME" if is_home else "AWAY"
		]

	game_day_detail_label.text = "%s rotation players • %.0f minutes • %s unavailable" % [
		str(rotation.get("rotation_player_ids", []).size()),
		float(rotation.get("total_minutes", 0.0)),
		str(unavailable.size())
	]

	if (
		game_day_result_label != null
		and game_day_result_label.text in ["No game simulated in this session.", "No completed game is available yet."]
		and last_game != null
		and typeof(last_game) == TYPE_DICTIONARY
	):
		var persisted_result := ""
		var persisted_home := str(last_game.get("home_team", ""))
		var persisted_away := str(last_game.get("away_team", ""))
		var persisted_home_score := int(last_game.get("home_score", 0))
		var persisted_away_score := int(last_game.get("away_score", 0))

		if game_day_active_team == persisted_home:
			persisted_result = "W" if persisted_home_score > persisted_away_score else "L"
		elif game_day_active_team == persisted_away:
			persisted_result = "W" if persisted_away_score > persisted_home_score else "L"

		_render_game_day_result(
			last_game,
			str(record.get("display", "N/A")),
			persisted_result,
			-1
		)

	var alerts: Array = payload.get("coaching_alerts", [])
	var alert_lines: Array = []
	for raw_alert in alerts:
		if typeof(raw_alert) != TYPE_DICTIONARY:
			continue
		var alert: Dictionary = raw_alert
		var title_text := str(alert.get("title", "Alert"))
		var severity := str(alert.get("severity", "info")).to_upper()
		alert_lines.append("%s • %s" % [severity, title_text])
		if alert_lines.size() >= 4:
			break

	if game_day_alerts_label != null:
		if alert_lines.size() > 0:
			game_day_alerts_label.text = "GAME PLAN CHECK • " + "   |   ".join(alert_lines)
		else:
			game_day_alerts_label.text = "GAME PLAN CHECK • No major coaching or medical alerts."

	var ready := bool(sync.get("ready_for_next_controlled_game", false))
	var pending := int(sync.get("cpu_games_before_next_controlled", 0))
	if ready:
		game_day_status_label.text = "READY • League synchronized • V2 release checkpoint protected"
		game_day_status_label.add_theme_color_override("font_color", GOOD)
		if game_day_simulate_button != null:
			game_day_simulate_button.disabled = false
	else:
		game_day_status_label.text = "WAITING • %s CPU game(s) remain before this matchup" % pending
		game_day_status_label.add_theme_color_override("font_color", BAD)
		if game_day_simulate_button != null:
			game_day_simulate_button.disabled = true


func _game_day_team_shooting_line(game: Dictionary, team: String) -> String:
	var fgm := 0
	var fga := 0
	var tpm := 0
	var tpa := 0

	var rows: Array = game.get("player_box_scores", [])
	for row in rows:
		if typeof(row) != TYPE_DICTIONARY:
			continue
		if str(row.get("team", "")) != team:
			continue

		fgm += int(row.get("field_goals_made", 0))
		fga += int(row.get("field_goals_attempted", 0))
		tpm += int(row.get("three_pointers_made", 0))
		tpa += int(row.get("three_pointers_attempted", 0))

	var fg_pct := 0.0
	if fga > 0:
		fg_pct = 100.0 * float(fgm) / float(fga)

	var tp_pct := 0.0
	if tpa > 0:
		tp_pct = 100.0 * float(tpm) / float(tpa)

	return "%s  FG %s/%s (%.1f%%)  •  3PT %s/%s (%.1f%%)" % [
		team,
		fgm,
		fga,
		fg_pct,
		tpm,
		tpa,
		tp_pct
	]


func _game_day_performer_better(left: Dictionary, right: Dictionary) -> bool:
	var left_points := int(left.get("points", 0))
	var right_points := int(right.get("points", 0))
	if left_points != right_points:
		return left_points > right_points

	var left_assists := int(left.get("assists", 0))
	var right_assists := int(right.get("assists", 0))
	if left_assists != right_assists:
		return left_assists > right_assists

	var left_rebounds := int(left.get("rebounds", 0))
	var right_rebounds := int(right.get("rebounds", 0))
	if left_rebounds != right_rebounds:
		return left_rebounds > right_rebounds

	return str(left.get("name", "")) < str(right.get("name", ""))


func _game_day_team_leader_lines(
	game: Dictionary,
	team: String,
	limit: int = 3
) -> Array:
	var leaders: Array = []
	var rows: Array = game.get("player_box_scores", [])

	for row in rows:
		if typeof(row) != TYPE_DICTIONARY:
			continue
		if str(row.get("team", "")) != team:
			continue

		var candidate: Dictionary = row
		var insert_index: int = leaders.size()

		for index in range(leaders.size()):
			var leader: Dictionary = leaders[index]
			if _game_day_performer_better(candidate, leader):
				insert_index = index
				break

		leaders.insert(insert_index, candidate)
		if leaders.size() > limit:
			leaders.pop_back()

	var lines: Array = []
	for leader in leaders:
		lines.append(
			"%s: %s PTS, %s REB, %s AST" % [
				str(leader.get("name", "Unknown")),
				str(leader.get("points", 0)),
				str(leader.get("rebounds", 0)),
				str(leader.get("assists", 0))
			]
		)

	return lines


func _render_game_day_result(
	game: Dictionary,
	record_display: String,
	result_code: String,
	cpu_games: int
) -> void:
	if game_day_result_label == null:
		return

	var home_team := str(game.get("home_team", "HOME"))
	var away_team := str(game.get("away_team", "AWAY"))
	var home_score := int(game.get("home_score", 0))
	var away_score := int(game.get("away_score", 0))

	var active_team := game_day_active_team
	if active_team == "":
		active_team = away_team

	var opponent_team := home_team if active_team == away_team else away_team

	var active_score := away_score if active_team == away_team else home_score
	var opponent_score := home_score if active_team == away_team else away_score

	var active_team_name := active_team
	var opponent_team_name := opponent_team
	if active_team == home_team:
		active_team_name = str(game.get("home_team_name", active_team))
		opponent_team_name = str(game.get("away_team_name", opponent_team))
	else:
		active_team_name = str(game.get("away_team_name", active_team))
		opponent_team_name = str(game.get("home_team_name", opponent_team))

	game_day_result_label.text = "%s %s   %s %s" % [
		active_team,
		active_score,
		opponent_score,
		opponent_team
	]
	game_day_result_label.add_theme_color_override("font_color", TEXT)

	if game_day_result_badge != null:
		var badge_text := "FINAL"
		var badge_color := MUTED
		if result_code == "W":
			badge_text = "WIN"
			badge_color = GOOD
		elif result_code == "L":
			badge_text = "LOSS"
			badge_color = BAD
		game_day_result_badge.text = "  %s  " % badge_text
		game_day_result_badge.add_theme_color_override("font_color", badge_color)
		game_day_result_badge.add_theme_stylebox_override(
			"normal",
			_box(Color(badge_color, 0.10), 7, Color(badge_color, 0.35))
		)

	if game_day_result_meta_label != null:
		var meta_bits: Array = ["FINAL"]
		if record_display != "":
			meta_bits.append("Record %s" % record_display)
		if int(game.get("overtime_periods", 0)) > 0:
			meta_bits.append("%s OT" % str(game.get("overtime_periods", 0)))
		if cpu_games >= 0:
			meta_bits.append("%s CPU game(s) synchronized" % cpu_games)
		game_day_result_meta_label.text = " • ".join(meta_bits)

	if game_day_active_postgame_title != null:
		game_day_active_postgame_title.text = active_team_name.to_upper()
	if game_day_opponent_postgame_title != null:
		game_day_opponent_postgame_title.text = opponent_team_name.to_upper()

	if game_day_active_shooting_label != null:
		game_day_active_shooting_label.text = _game_day_team_shooting_line(game, active_team)
	if game_day_opponent_shooting_label != null:
		game_day_opponent_shooting_label.text = _game_day_team_shooting_line(game, opponent_team)

	var active_leaders: Array = _game_day_team_leader_lines(game, active_team, 3)
	if game_day_active_leaders_label != null:
		if active_leaders.size() > 0:
			game_day_active_leaders_label.text = "\n".join(active_leaders)
		else:
			game_day_active_leaders_label.text = "No leaders available."

	var opponent_leaders: Array = _game_day_team_leader_lines(game, opponent_team, 3)
	if game_day_opponent_leaders_label != null:
		if opponent_leaders.size() > 0:
			game_day_opponent_leaders_label.text = "\n".join(opponent_leaders)
		else:
			game_day_opponent_leaders_label.text = "No leaders available."


func _simulate_game_day_overlay() -> void:
	if game_day_simulate_request == null:
		return
	if game_day_simulate_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return

	if game_day_simulate_button != null:
		game_day_simulate_button.disabled = true

	if game_day_status_label != null:
		game_day_status_label.text = "SIMULATING • Committing game, synchronizing league, saving V3, and verifying V2 protection..."
		game_day_status_label.add_theme_color_override("font_color", ACCENT)

	var error := game_day_simulate_request.request(
		GAME_DAY_SIMULATE_URL,
		PackedStringArray(),
		HTTPClient.METHOD_POST,
		""
	)

	if error != OK:
		if game_day_status_label != null:
			game_day_status_label.text = "Could not start simulation request (error %s)." % error
			game_day_status_label.add_theme_color_override("font_color", BAD)


func _on_game_day_simulate_completed(
	result: int,
	response_code: int,
	_headers: PackedStringArray,
	body: PackedByteArray
) -> void:
	if game_day_overlay == null or not is_instance_valid(game_day_overlay):
		return

	if result != HTTPRequest.RESULT_SUCCESS:
		game_day_status_label.text = "Simulation request failed before the Python engine responded."
		game_day_status_label.add_theme_color_override("font_color", BAD)
		return

	var payload = JSON.parse_string(body.get_string_from_utf8())
	if typeof(payload) != TYPE_DICTIONARY:
		game_day_status_label.text = "Simulation endpoint returned invalid data."
		game_day_status_label.add_theme_color_override("font_color", BAD)
		return

	if response_code != 200:
		game_day_status_label.text = str(
			payload.get("detail", payload.get("error", "Game Day simulation failed."))
		)
		game_day_status_label.add_theme_color_override("font_color", BAD)
		return

	var applied := str(payload.get("status", "")) == "applied"
	var persisted := bool(payload.get("persisted_after_reload", false))
	var v2_unchanged := bool(payload.get("active_v2_unchanged", false))

	if not applied or not persisted or not v2_unchanged:
		game_day_status_label.text = "Simulation did not pass persistence and V2 safety verification."
		game_day_status_label.add_theme_color_override("font_color", BAD)
		return

	var game = payload.get("game", {})
	var result_code := str(payload.get("result", ""))
	var after_record = payload.get("after_record", {})
	var cpu_games := int(payload.get("cpu_games_synchronized", 0))

	if typeof(game) == TYPE_DICTIONARY:
		_render_game_day_result(
			game,
			str(after_record.get("display", "N/A")),
			result_code,
			cpu_games
		)

	# Refresh the overlay and the existing live V3 surfaces after the durable save.
	_request_game_day_overlay()
	_request_franchise_summary()
	_request_roster()


func _close_game_day_overlay() -> void:
	if game_day_request != null and game_day_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		game_day_request.cancel_request()
	if game_day_overlay != null and is_instance_valid(game_day_overlay):
		game_day_overlay.queue_free()
	game_day_overlay = null
	game_day_matchup_label = null
	game_day_detail_label = null
	game_day_status_label = null
	game_day_simulate_button = null
	game_day_result_label = null
	game_day_result_badge = null
	game_day_result_meta_label = null
	game_day_active_postgame_title = null
	game_day_opponent_postgame_title = null
	game_day_active_shooting_label = null
	game_day_opponent_shooting_label = null
	game_day_active_leaders_label = null
	game_day_opponent_leaders_label = null
	game_day_active_team = ""
	game_day_team_badge = null
	game_day_opponent_badge = null
	game_day_team_record_label = null
	game_day_opponent_record_label = null
	game_day_meta_label = null
	game_day_alerts_label = null


func _friendly_value(value: String) -> String:
	if value == "" or value == "None" or value == "null":
		return "None"
	return value.replace("_", " ").capitalize()


func _pct_text(value) -> String:
	if value == null:
		return "N/A"
	return "%.1f%%" % float(value)


func _ratio_pct_text(value) -> String:
	if value == null:
		return "N/A"
	return "%.1f%%" % (float(value) * 100.0)


func _roster_cell(
	text_value: String,
	width: int,
	color: Color,
	alignment: int = HORIZONTAL_ALIGNMENT_LEFT
) -> Label:
	var label := Label.new()
	label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	label.custom_minimum_size = Vector2(width, 0)
	label.text = text_value
	label.horizontal_alignment = alignment
	label.add_theme_color_override("font_color", color)
	label.add_theme_font_size_override("font_size", 11)
	return label


func _number_text(value, decimals: int = 1) -> String:
	if value == null:
		return "N/A"

	var number := float(value)
	if decimals <= 0:
		return str(int(round(number)))

	return "%.1f" % number


func _show_page(page_name: String) -> void:
	current_page = page_name

	if home_page != null:
		home_page.visible = page_name == "HOME"

	if roster_page != null:
		roster_page.visible = page_name == "ROSTER"

	for key in nav_buttons.keys():
		var button: Button = nav_buttons[key]
		_apply_nav_button_style(button, str(key) == page_name)

	if page_name == "ROSTER":
		_request_roster()
	elif page_name == "HOME":
		_request_franchise_summary()


func _apply_nav_button_style(button: Button, active: bool) -> void:
	button.add_theme_color_override("font_color", TEXT if active else MUTED)
	button.add_theme_stylebox_override(
		"normal",
		_box(PANEL_ALT if active else SIDEBAR, 8)
	)


func _build_activity_panel() -> Control:
	var card := _card(Vector2(0, 0))
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	card.size_flags_vertical = Control.SIZE_EXPAND_FILL
	var body := _card_body(card, 20)

	body.add_child(_section_title("LEAGUE PULSE"))
	body.add_child(_activity("TRADE MARKET", "Multiple teams are evaluating early-season roster changes.", "2m"))
	body.add_child(_divider())
	body.add_child(_activity("ROOKIE WATCH", "The 2026 class is beginning to separate after the first month.", "18m"))
	body.add_child(_divider())
	body.add_child(_activity("TEAM UPDATE", "Rotation workload and chemistry are both trending positively.", "1h"))
	body.add_child(_divider())
	body.add_child(_activity("SCOUTING", "Your staff has new evaluations ready on the upcoming draft class.", "3h"))
	return card


func _build_quick_actions_panel() -> Control:
	var card := _card(Vector2(330, 0))
	card.size_flags_vertical = Control.SIZE_EXPAND_FILL
	var body := _card_body(card, 20)

	body.add_child(_section_title("FRANCHISE SHORTCUTS"))
	body.add_child(_wide_action("OPEN ROSTER", "Depth chart, roles, development"))
	body.add_child(_wide_action("TRADE CENTER", "Offers, finder, pick inventory"))
	body.add_child(_wide_action("SCOUTING BOARD", "Prospects and staff reports"))
	body.add_child(_wide_action("LEAGUE HUB", "Standings, awards, transactions"))

	var spacer := Control.new()
	spacer.size_flags_vertical = Control.SIZE_EXPAND_FILL
	body.add_child(spacer)

	var note := Label.new()
	note.text = "V3 edits use an isolated working save.\nThe validated V2 release checkpoint remains protected."
	note.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	note.add_theme_color_override("font_color", MUTED)
	note.add_theme_font_size_override("font_size", 11)
	body.add_child(note)
	return card


func _activity(category: String, text_value: String, age: String) -> Control:
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 14)

	var text_box := VBoxContainer.new()
	text_box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	text_box.add_theme_constant_override("separation", 4)

	text_box.add_child(_small_label(category, ACCENT))

	var description := Label.new()
	description.text = text_value
	description.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	description.add_theme_color_override("font_color", TEXT)
	description.add_theme_font_size_override("font_size", 13)
	text_box.add_child(description)
	row.add_child(text_box)

	var time := Label.new()
	time.text = age
	time.add_theme_color_override("font_color", MUTED)
	time.add_theme_font_size_override("font_size", 11)
	row.add_child(time)
	return row


func _wide_action(title_text: String, subtitle_text: String) -> Control:
	var button := Button.new()
	button.custom_minimum_size = Vector2(0, 64)
	button.text = "%s
%s" % [title_text, subtitle_text]
	button.alignment = HORIZONTAL_ALIGNMENT_LEFT
	button.add_theme_font_size_override("font_size", 12)
	button.add_theme_color_override("font_color", TEXT)
	button.add_theme_color_override("font_hover_color", TEXT)
	button.add_theme_stylebox_override("normal", _box(PANEL_ALT, 9, BORDER))
	button.add_theme_stylebox_override("hover", _box(PANEL_HOVER, 9, ACCENT))
	button.add_theme_stylebox_override("pressed", _box(PANEL_HOVER, 9, ACCENT))

	if title_text == "OPEN ROSTER":
		button.pressed.connect(_show_page.bind("ROSTER"))

	return button

func _nav_button(text_value: String, active: bool = false) -> Button:
	var button := Button.new()
	button.custom_minimum_size = Vector2(0, 42)
	button.text = text_value
	button.alignment = HORIZONTAL_ALIGNMENT_LEFT
	button.add_theme_font_size_override("font_size", 12)
	button.add_theme_color_override("font_hover_color", TEXT)
	button.add_theme_color_override("font_disabled_color", Color("53647c"))
	button.add_theme_stylebox_override("hover", _box(PANEL_HOVER, 8))
	button.add_theme_stylebox_override("pressed", _box(PANEL_ALT, 8))
	button.add_theme_stylebox_override("disabled", _box(SIDEBAR, 8))
	_apply_nav_button_style(button, active)

	if text_value == "HOME" or text_value == "ROSTER":
		nav_buttons[text_value] = button
		button.pressed.connect(_show_page.bind(text_value))
	elif text_value == "GAME DAY":
		nav_buttons[text_value] = button
		button.pressed.connect(_open_game_day_overlay)

	return button

func _action_button(text_value: String, primary: bool = false) -> Button:
	var button := Button.new()
	button.custom_minimum_size = Vector2(124, 38)
	button.text = text_value
	button.add_theme_font_size_override("font_size", 11)
	button.add_theme_color_override("font_color", TEXT)
	button.add_theme_color_override("font_hover_color", TEXT)
	var normal_color := TEAM_PRIMARY if primary else PANEL_ALT
	var hover_color := TEAM_PRIMARY_HOVER if primary else PANEL_HOVER
	button.add_theme_stylebox_override("normal", _box(normal_color, 10, normal_color if primary else BORDER))
	button.add_theme_stylebox_override("hover", _box(hover_color, 10, hover_color if primary else ACCENT))
	button.add_theme_stylebox_override("pressed", _box(hover_color, 10, hover_color))
	return button


func _pill(text_value: String, color: Color) -> Label:
	var pill := Label.new()
	pill.text = "  %s  " % text_value
	pill.add_theme_color_override("font_color", color)
	pill.add_theme_font_size_override("font_size", 11)
	pill.add_theme_stylebox_override("normal", _box(Color(color, 0.10), 7, Color(color, 0.35)))
	return pill


func _section_title(text_value: String) -> Label:
	var label := Label.new()
	label.text = text_value
	label.add_theme_color_override("font_color", TEXT)
	label.add_theme_font_size_override("font_size", 16)
	return label


func _small_label(text_value: String, color: Color) -> Label:
	var label := Label.new()
	label.text = text_value
	label.add_theme_color_override("font_color", color)
	label.add_theme_font_size_override("font_size", 11)
	return label


func _divider() -> HSeparator:
	var line := HSeparator.new()
	line.add_theme_constant_override("separation", 10)
	line.modulate = Color(1, 1, 1, 0.12)
	return line


func _card(minimum: Vector2) -> PanelContainer:
	var card := PanelContainer.new()
	card.custom_minimum_size = minimum
	card.add_theme_stylebox_override("panel", _box(PANEL, 16, BORDER))
	return card


func _card_body(card: PanelContainer, margin_size: int) -> VBoxContainer:
	var margin := MarginContainer.new()
	_set_margins(margin, margin_size, margin_size, margin_size, margin_size)
	card.add_child(margin)

	var body := VBoxContainer.new()
	body.add_theme_constant_override("separation", 8)
	margin.add_child(body)
	return body


func _box(color: Color, radius: int, border_color: Color = Color.TRANSPARENT) -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = color
	style.corner_radius_top_left = radius
	style.corner_radius_top_right = radius
	style.corner_radius_bottom_left = radius
	style.corner_radius_bottom_right = radius
	if border_color != Color.TRANSPARENT:
		style.border_width_left = 1
		style.border_width_top = 1
		style.border_width_right = 1
		style.border_width_bottom = 1
		style.border_color = border_color
	style.content_margin_left = 10
	style.content_margin_right = 10
	style.content_margin_top = 8
	style.content_margin_bottom = 8
	return style


func _set_margins(container: MarginContainer, left: int, top: int, right: int, bottom: int) -> void:
	container.add_theme_constant_override("margin_left", left)
	container.add_theme_constant_override("margin_top", top)
	container.add_theme_constant_override("margin_right", right)
	container.add_theme_constant_override("margin_bottom", bottom)


func _build_http_client() -> void:
	http_request = HTTPRequest.new()
	http_request.timeout = 2.5
	http_request.request_completed.connect(_on_health_completed)
	add_child(http_request)

	summary_request = HTTPRequest.new()
	summary_request.timeout = 4.0
	summary_request.request_completed.connect(_on_summary_completed)
	add_child(summary_request)

	roster_request = HTTPRequest.new()
	roster_request.timeout = 4.0
	roster_request.request_completed.connect(_on_roster_completed)
	add_child(roster_request)

	rotation_request = HTTPRequest.new()
	rotation_request.timeout = 8.0
	rotation_request.request_completed.connect(_on_rotation_request_completed)
	add_child(rotation_request)

	game_day_request = HTTPRequest.new()
	game_day_request.timeout = 6.0
	game_day_request.request_completed.connect(_on_game_day_completed)
	add_child(game_day_request)

	game_day_simulate_request = HTTPRequest.new()
	game_day_simulate_request.timeout = 60.0
	game_day_simulate_request.request_completed.connect(_on_game_day_simulate_completed)
	add_child(game_day_simulate_request)

func _check_bridge() -> void:
	if http_request == null:
		return
	if http_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		http_request.cancel_request()

	bridge_status.text = "CONNECTING..."
	bridge_status.add_theme_color_override("font_color", MUTED)
	bridge_detail.text = "Checking the local Python simulation bridge."
	retry_button.disabled = true

	var error := http_request.request(BRIDGE_URL)
	if error != OK:
		_set_bridge_status(false, "Could not start the bridge request (error %s)." % error)


func _on_health_completed(
	result: int,
	response_code: int,
	_headers: PackedStringArray,
	body: PackedByteArray
) -> void:
	if result != HTTPRequest.RESULT_SUCCESS or response_code != 200:
		_set_bridge_status(false, "Python bridge is offline. Start scripts/run_v3_bridge.py and retry.")
		return

	var payload = JSON.parse_string(body.get_string_from_utf8())
	if typeof(payload) != TYPE_DICTIONARY or payload.get("status", "") != "ok":
		_set_bridge_status(false, "Bridge responded, but its health payload was invalid.")
		return

	_set_bridge_status(
		true,
		"Python engine connected • API %s • V3 working save enabled • V2 release protected" % payload.get("api_version", "unknown")
	)

	_request_franchise_summary()
	_request_roster()


func _request_roster() -> void:
	if roster_request == null:
		return

	if roster_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		roster_request.cancel_request()

	if roster_status != null:
		roster_status.text = "Refreshing V3 working roster..."

	var error := roster_request.request(ROSTER_URL)
	if error != OK:
		_set_roster_error("Could not request the active roster.")


func _on_roster_completed(
	result: int,
	response_code: int,
	_headers: PackedStringArray,
	body: PackedByteArray
) -> void:
	if result != HTTPRequest.RESULT_SUCCESS or response_code != 200:
		_set_roster_error("V3 working roster could not be loaded.")
		return

	var payload = JSON.parse_string(body.get_string_from_utf8())

	if typeof(payload) != TYPE_DICTIONARY:
		_set_roster_error("Roster endpoint returned invalid data.")
		return

	if payload.has("error"):
		_set_roster_error(str(payload.get("error")))
		return

	_apply_roster_payload(payload)


func _apply_roster_payload(payload: Dictionary) -> void:
	roster_payload = payload

	var team = payload.get("team", {})
	var season = payload.get("season", {})
	var financial = payload.get("financial", {})
	var chemistry = payload.get("chemistry", {})
	var players = payload.get("players", [])

	var source_label := "V3 WORKING SAVE" if str(payload.get("source", "")) == "v3_working_checkpoint" else "PROTECTED V2 SAVE"

	roster_subtitle.text = "%s • %s • LEAGUE DAY %s • %s" % [
		str(team.get("name", "Active Franchise")).to_upper(),
		str(season.get("label", "")),
		str(season.get("day_index", "?")),
		source_label
	]

	roster_count_value.text = "%s rostered" % str(team.get("roster_size", "?"))
	roster_payroll_value.text = str(financial.get("payroll_display", "N/A"))
	roster_cap_value.text = str(financial.get("cap_room_estimate_display", "N/A"))
	roster_chemistry_value.text = _number_text(chemistry.get("score", null), 1)

	roster_status.text = "%s active • %s inactive • %s starters • %s rotation • %s injured • Click a player for full profile" % [
		str(team.get("active_players", "?")),
		str(team.get("inactive_players", "?")),
		str(team.get("starters", "?")),
		str(team.get("rotation_players", "?")),
		str(team.get("injured_players", "?"))
	]

	for child in roster_rows.get_children():
		roster_rows.remove_child(child)
		child.queue_free()

	for player in players:
		if typeof(player) == TYPE_DICTIONARY:
			roster_rows.add_child(_roster_row(player))



func _show_rotation_editor() -> void:
	if roster_payload.is_empty():
		if roster_status != null:
			roster_status.text = "Load the roster before editing the rotation."
		return

	if not bool(roster_payload.get("editable", false)):
		if roster_status != null:
			roster_status.text = "Initialize the V3 working save before editing the rotation."
		return

	_close_rotation_editor()

	rotation_overlay = Control.new()
	rotation_overlay.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	rotation_overlay.mouse_filter = Control.MOUSE_FILTER_STOP
	add_child(rotation_overlay)
	rotation_overlay.move_to_front()

	var dim := ColorRect.new()
	dim.color = Color(0, 0, 0, 0.76)
	dim.mouse_filter = Control.MOUSE_FILTER_STOP
	rotation_overlay.add_child(dim)
	dim.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)

	var center := CenterContainer.new()
	center.mouse_filter = Control.MOUSE_FILTER_PASS
	rotation_overlay.add_child(center)
	center.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)

	var card := _card(Vector2(1040, 680))
	card.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	card.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	center.add_child(card)

	var body := _card_body(card, 20)
	body.add_theme_constant_override("separation", 12)

	var header := HBoxContainer.new()
	header.add_theme_constant_override("separation", 12)
	body.add_child(header)

	var titles := VBoxContainer.new()
	titles.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	titles.add_theme_constant_override("separation", 3)
	header.add_child(titles)

	var title := Label.new()
	title.text = "EDIT ROTATION"
	title.add_theme_color_override("font_color", TEXT)
	title.add_theme_font_size_override("font_size", 26)
	titles.add_child(title)

	var subtitle := Label.new()
	subtitle.text = "V3 WORKING SAVE • Changes are validated by the existing V2 rotation engine before they can be applied."
	subtitle.add_theme_color_override("font_color", MUTED)
	subtitle.add_theme_font_size_override("font_size", 11)
	titles.add_child(subtitle)

	var close_button := _action_button("CANCEL")
	close_button.pressed.connect(_close_rotation_editor)
	header.add_child(close_button)

	var summary_row := HBoxContainer.new()
	summary_row.add_theme_constant_override("separation", 12)
	body.add_child(summary_row)

	rotation_total_label = Label.new()
	rotation_total_label.custom_minimum_size = Vector2(170, 38)
	rotation_total_label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	rotation_total_label.add_theme_font_size_override("font_size", 18)
	summary_row.add_child(rotation_total_label)

	rotation_feedback = Label.new()
	rotation_feedback.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	rotation_feedback.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	rotation_feedback.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	rotation_feedback.add_theme_font_size_override("font_size", 11)
	summary_row.add_child(rotation_feedback)

	rotation_preview_button = _action_button("PREVIEW VALIDATION")
	rotation_preview_button.pressed.connect(_preview_rotation)
	summary_row.add_child(rotation_preview_button)

	rotation_apply_button = _action_button("APPLY ROTATION", true)
	rotation_apply_button.disabled = true
	rotation_apply_button.pressed.connect(_apply_rotation)
	summary_row.add_child(rotation_apply_button)

	var table_header := HBoxContainer.new()
	table_header.add_theme_constant_override("separation", 8)
	table_header.add_child(_roster_cell("PLAYER", 220, MUTED))
	table_header.add_child(_roster_cell("POS", 60, MUTED))
	table_header.add_child(_roster_cell("HEALTH", 180, MUTED))
	table_header.add_child(_roster_cell("START", 70, MUTED, HORIZONTAL_ALIGNMENT_CENTER))
	table_header.add_child(_roster_cell("ROTATION", 86, MUTED, HORIZONTAL_ALIGNMENT_CENTER))
	table_header.add_child(_roster_cell("MINUTES", 100, MUTED, HORIZONTAL_ALIGNMENT_CENTER))
	body.add_child(table_header)

	var scroll := ScrollContainer.new()
	scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	body.add_child(scroll)

	var rows_box := VBoxContainer.new()
	rows_box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	rows_box.add_theme_constant_override("separation", 5)
	scroll.add_child(rows_box)

	rotation_edit_rows.clear()
	rotation_edit_order.clear()
	rotation_validated_body = ""

	var players = roster_payload.get("players", [])
	for player in players:
		if typeof(player) == TYPE_DICTIONARY:
			rows_box.add_child(_rotation_editor_row(player))

	_refresh_rotation_editor_state()


func _rotation_editor_row(player: Dictionary) -> Control:
	var panel := PanelContainer.new()
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	panel.add_theme_stylebox_override("panel", _box(PANEL_ALT, 7, BORDER))

	var margin := MarginContainer.new()
	_set_margins(margin, 10, 7, 10, 7)
	panel.add_child(margin)

	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 8)
	margin.add_child(row)

	var player_id := str(player.get("player_id", ""))
	rotation_edit_order.append(player_id)

	row.add_child(_roster_cell(str(player.get("name", "Unknown")), 220, TEXT))
	row.add_child(_roster_cell(str(player.get("position", "")), 60, MUTED))

	var health = player.get("health", {})
	var health_status := str(health.get("status", "unknown"))
	var health_color := GOOD if health_status == "healthy" else BAD
	row.add_child(_roster_cell(str(health.get("display", "Unknown")), 180, health_color))

	var starter_box := CheckBox.new()
	starter_box.custom_minimum_size = Vector2(70, 32)
	starter_box.button_pressed = bool(player.get("is_starter", false))
	starter_box.tooltip_text = "Starter"
	row.add_child(starter_box)

	var rotation_box := CheckBox.new()
	rotation_box.custom_minimum_size = Vector2(86, 32)
	rotation_box.button_pressed = bool(player.get("in_rotation", false))
	rotation_box.tooltip_text = "In rotation"
	row.add_child(rotation_box)

	var minutes_spin := SpinBox.new()
	minutes_spin.custom_minimum_size = Vector2(100, 32)
	minutes_spin.min_value = 0.0
	minutes_spin.max_value = 48.0
	minutes_spin.step = 1.0
	minutes_spin.value = float(player.get("target_minutes", 0.0))
	minutes_spin.editable = rotation_box.button_pressed
	minutes_spin.suffix = " min"
	row.add_child(minutes_spin)

	rotation_edit_rows[player_id] = {
		"player": player,
		"starter": starter_box,
		"rotation": rotation_box,
		"minutes": minutes_spin,
	}

	starter_box.toggled.connect(_on_rotation_starter_toggled.bind(player_id))
	rotation_box.toggled.connect(_on_rotation_member_toggled.bind(player_id))
	minutes_spin.value_changed.connect(_on_rotation_minutes_changed.bind(player_id))

	return panel


func _on_rotation_starter_toggled(pressed: bool, player_id: String) -> void:
	if rotation_syncing:
		return

	var entry = rotation_edit_rows.get(player_id, {})
	if entry.is_empty():
		return

	if pressed and not entry["rotation"].button_pressed:
		rotation_syncing = true
		entry["rotation"].button_pressed = true
		entry["minutes"].editable = true
		rotation_syncing = false

	_rotation_editor_dirty()


func _on_rotation_member_toggled(pressed: bool, player_id: String) -> void:
	if rotation_syncing:
		return

	var entry = rotation_edit_rows.get(player_id, {})
	if entry.is_empty():
		return

	rotation_syncing = true
	entry["minutes"].editable = pressed

	if not pressed:
		if entry["starter"].button_pressed:
			entry["starter"].button_pressed = false
		entry["minutes"].value = 0.0

	rotation_syncing = false
	_rotation_editor_dirty()


func _on_rotation_minutes_changed(_value: float, _player_id: String) -> void:
	if rotation_syncing:
		return
	_rotation_editor_dirty()


func _rotation_editor_dirty() -> void:
	rotation_validated_body = ""
	if rotation_apply_button != null:
		rotation_apply_button.disabled = true
	_refresh_rotation_editor_state()


func _rotation_rows_payload() -> Array:
	var rows := []

	for player_id in rotation_edit_order:
		var entry = rotation_edit_rows.get(player_id, {})
		if entry.is_empty():
			continue

		rows.append(
			{
				"player_id": player_id,
				"starter": bool(entry["starter"].button_pressed),
				"in_rotation": bool(entry["rotation"].button_pressed),
				"minutes": float(entry["minutes"].value),
			}
		)

	return rows


func _rotation_body_json() -> String:
	return JSON.stringify({"rows": _rotation_rows_payload()})


func _rotation_local_validation() -> Dictionary:
	var rules = roster_payload.get("rotation_rules", {})
	var required_starters := int(rules.get("required_starters", 5))
	var minimum_players := int(rules.get("minimum_game_players", 8))
	var maximum_players := int(rules.get("maximum_rotation_players", 15))
	var required_minutes := float(rules.get("required_total_minutes", 240.0))
	var maximum_minutes := float(rules.get("maximum_player_minutes", 48.0))

	var starters := 0
	var rotation_players := 0
	var total_minutes := 0.0
	var bad_minutes := false
	var unavailable_names := []

	for player_id in rotation_edit_order:
		var entry = rotation_edit_rows.get(player_id, {})
		if entry.is_empty():
			continue

		var is_starter := bool(entry["starter"].button_pressed)
		var in_rotation := bool(entry["rotation"].button_pressed)
		var minutes := float(entry["minutes"].value)
		var player = entry["player"]

		if is_starter:
			starters += 1

		if in_rotation:
			rotation_players += 1
			total_minutes += minutes

			if minutes <= 0.0 or minutes > maximum_minutes:
				bad_minutes = true

			var health = player.get("health", {})
			var health_status := str(health.get("status", "unknown"))
			if health_status not in ["", "healthy", "unknown"]:
				unavailable_names.append(str(player.get("name", player_id)))

	var issues := []

	if starters != required_starters:
		issues.append("Need exactly %s starters" % required_starters)

	if rotation_players < minimum_players or rotation_players > maximum_players:
		issues.append(
			"Rotation must contain %s-%s players" % [
				minimum_players,
				maximum_players
			]
		)

	if bad_minutes:
		issues.append("Every rotation player needs 1-%s minutes" % int(maximum_minutes))

	if abs(total_minutes - required_minutes) > 0.1:
		issues.append("Minutes must total %.0f" % required_minutes)

	if unavailable_names.size() > 0:
		issues.append("Unavailable: %s" % ", ".join(unavailable_names))

	return {
		"valid": issues.is_empty(),
		"issues": issues,
		"starters": starters,
		"rotation_players": rotation_players,
		"total_minutes": total_minutes,
		"required_minutes": required_minutes,
	}


func _refresh_rotation_editor_state() -> void:
	if rotation_total_label == null or rotation_feedback == null:
		return

	var check := _rotation_local_validation()
	var total := float(check.get("total_minutes", 0.0))
	var required := float(check.get("required_minutes", 240.0))
	var valid := bool(check.get("valid", false))

	rotation_total_label.text = "%.0f / %.0f MIN" % [total, required]
	rotation_total_label.add_theme_color_override(
		"font_color",
		GOOD if abs(total - required) <= 0.1 else BAD
	)

	if valid:
		rotation_feedback.text = "%s starters • %s rotation players • Ready for server validation." % [
			str(check.get("starters", 0)),
			str(check.get("rotation_players", 0))
		]
		rotation_feedback.add_theme_color_override("font_color", GOOD)
	else:
		var issues: Array = check.get("issues", [])
		rotation_feedback.text = " • ".join(issues)
		rotation_feedback.add_theme_color_override("font_color", BAD)

	if rotation_preview_button != null:
		rotation_preview_button.disabled = not valid


func _preview_rotation() -> void:
	_send_rotation_request("preview")


func _apply_rotation() -> void:
	var current_body := _rotation_body_json()

	if rotation_validated_body == "" or current_body != rotation_validated_body:
		rotation_feedback.text = "Preview validation is required again before applying."
		rotation_feedback.add_theme_color_override("font_color", BAD)
		rotation_apply_button.disabled = true
		return

	_send_rotation_request("apply")


func _send_rotation_request(mode: String) -> void:
	if rotation_request == null:
		return

	var check := _rotation_local_validation()
	if not bool(check.get("valid", false)):
		_refresh_rotation_editor_state()
		return

	if rotation_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		rotation_request.cancel_request()

	var body := _rotation_body_json()
	var url := ROTATION_PREVIEW_URL if mode == "preview" else ROTATION_APPLY_URL
	var headers := PackedStringArray(["Content-Type: application/json"])

	rotation_request_mode = mode
	rotation_pending_body = body
	rotation_preview_button.disabled = true
	rotation_apply_button.disabled = true

	rotation_feedback.text = (
		"Validating rotation with the Python engine..."
		if mode == "preview"
		else "Applying rotation to the isolated V3 working save..."
	)
	rotation_feedback.add_theme_color_override("font_color", MUTED)

	var error := rotation_request.request(
		url,
		headers,
		HTTPClient.METHOD_POST,
		body
	)

	if error != OK:
		rotation_feedback.text = "Could not start the rotation request (error %s)." % error
		rotation_feedback.add_theme_color_override("font_color", BAD)
		_refresh_rotation_editor_state()


func _on_rotation_request_completed(
	result: int,
	response_code: int,
	_headers: PackedStringArray,
	body: PackedByteArray
) -> void:
	if result != HTTPRequest.RESULT_SUCCESS:
		if rotation_feedback != null:
			rotation_feedback.text = "Rotation request failed before the server responded."
			rotation_feedback.add_theme_color_override("font_color", BAD)
		rotation_validated_body = ""
		_refresh_rotation_editor_state()
		return

	var payload = JSON.parse_string(body.get_string_from_utf8())

	if typeof(payload) != TYPE_DICTIONARY:
		if rotation_feedback != null:
			rotation_feedback.text = "Rotation endpoint returned invalid data."
			rotation_feedback.add_theme_color_override("font_color", BAD)
		rotation_validated_body = ""
		_refresh_rotation_editor_state()
		return

	if response_code != 200:
		if rotation_feedback != null:
			rotation_feedback.text = str(payload.get("detail", payload.get("error", "Rotation validation failed.")))
			rotation_feedback.add_theme_color_override("font_color", BAD)
		rotation_validated_body = ""
		_refresh_rotation_editor_state()
		return

	if rotation_request_mode == "preview":
		if str(payload.get("status", "")) == "valid":
			rotation_validated_body = rotation_pending_body
			rotation_feedback.text = "ENGINE VALIDATION PASSED • Ready to apply to the V3 working save."
			rotation_feedback.add_theme_color_override("font_color", GOOD)
			rotation_preview_button.disabled = false
			rotation_apply_button.disabled = false
		else:
			rotation_validated_body = ""
			rotation_feedback.text = "Rotation preview did not validate."
			rotation_feedback.add_theme_color_override("font_color", BAD)
			_refresh_rotation_editor_state()

	elif rotation_request_mode == "apply":
		var applied := str(payload.get("status", "")) == "applied"
		var persisted := bool(payload.get("persisted_after_reload", false))
		var v2_unchanged := bool(payload.get("active_v2_unchanged", false))

		if applied and persisted and v2_unchanged:
			rotation_feedback.text = "ROTATION SAVED • Reload verified • V2 release checkpoint unchanged."
			rotation_feedback.add_theme_color_override("font_color", GOOD)
			_close_rotation_editor()
			_request_roster()
		else:
			rotation_feedback.text = "Rotation write did not pass persistence and safety verification."
			rotation_feedback.add_theme_color_override("font_color", BAD)
			rotation_validated_body = ""
			_refresh_rotation_editor_state()


func _close_rotation_editor() -> void:
	if rotation_request != null and rotation_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		rotation_request.cancel_request()

	if rotation_overlay != null and is_instance_valid(rotation_overlay):
		rotation_overlay.queue_free()

	rotation_overlay = null
	rotation_edit_rows.clear()
	rotation_edit_order.clear()
	rotation_feedback = null
	rotation_total_label = null
	rotation_preview_button = null
	rotation_apply_button = null
	rotation_request_mode = ""
	rotation_pending_body = ""
	rotation_validated_body = ""


func _set_roster_error(message: String) -> void:
	if roster_subtitle != null:
		roster_subtitle.text = "V3 ROSTER DATA UNAVAILABLE"

	if roster_status != null:
		roster_status.text = message

	if roster_count_value != null:
		roster_count_value.text = "N/A"
	if roster_payroll_value != null:
		roster_payroll_value.text = "N/A"
	if roster_cap_value != null:
		roster_cap_value.text = "N/A"
	if roster_chemistry_value != null:
		roster_chemistry_value.text = "N/A"


func _request_franchise_summary() -> void:
	if summary_request == null:
		return

	if summary_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		summary_request.cancel_request()

	var error := summary_request.request(SUMMARY_URL)
	if error != OK:
		_set_live_data_error("Could not request active franchise summary.")


func _on_summary_completed(
	result: int,
	response_code: int,
	_headers: PackedStringArray,
	body: PackedByteArray
) -> void:
	if result != HTTPRequest.RESULT_SUCCESS or response_code != 200:
		_set_live_data_error("Active V2 franchise data could not be loaded.")
		return

	var payload = JSON.parse_string(body.get_string_from_utf8())

	if typeof(payload) != TYPE_DICTIONARY:
		_set_live_data_error("Franchise summary returned invalid data.")
		return

	if payload.has("error"):
		_set_live_data_error(str(payload.get("error")))
		return

	_apply_franchise_summary(payload)


func _apply_franchise_summary(payload: Dictionary) -> void:
	var team = payload.get("team", {})
	var season = payload.get("season", {})
	var record = payload.get("record", {})
	var chemistry = payload.get("chemistry", {})
	var financial = payload.get("financial", {})
	var next_game = payload.get("next_game", {})
	var draft = payload.get("draft", {})

	var season_label := str(season.get("label", "Unknown season"))
	var phase_label := _pretty_phase(str(season.get("phase", "")))
	var day_index := str(season.get("day_index", "?"))

	header_subtitle.text = "%s  •  LEAGUE DAY %s  •  %s" % [
		season_label,
		day_index,
		phase_label
	]

	team_name_label.text = str(team.get("name", "Unknown Team")).to_upper()
	if team_abbr_badge != null:
		team_abbr_badge.text = str(team.get("abbreviation", "TEAM")).to_upper()

	team_detail_label.text = "%s • %s Division
%s rostered • %s active" % [
		str(team.get("conference", "Unknown")),
		str(team.get("division", "Unknown")),
		str(team.get("roster_size", "?")),
		str(team.get("active_players", "?"))
	]

	record_value.text = str(record.get("display", "N/A"))

	var rank_text = record.get("conference_rank_display", null)
	var streak_text = record.get("streak", null)
	var record_text := "Live standings"

	if rank_text != null:
		record_text = str(rank_text)

	if streak_text != null:
		if record_text == "Live standings":
			record_text = str(streak_text)
		else:
			record_text += " • " + str(streak_text)

	record_detail.text = record_text

	var chemistry_score = chemistry.get("score", null)
	if chemistry_score == null:
		chemistry_value.text = "N/A"
	else:
		chemistry_value.text = str(chemistry_score)

	chemistry_detail.text = str(chemistry.get("label", "Live chemistry"))

	var cap_display = financial.get("cap_space_display", null)
	if cap_display == null:
		cap_value.text = "N/A"
		cap_detail.text = "Live cap field pending"
	else:
		cap_value.text = str(cap_display)
		if bool(financial.get("is_estimate", false)):
			cap_detail.text = "Roster-contract estimate"
		else:
			cap_detail.text = "Available"

	var draft_year = draft.get("draft_year", null)
	if draft_year == null:
		draft_value.text = "N/A"
	else:
		draft_value.text = "%s Draft" % str(draft_year)

	draft_detail.text = _pretty_phase(str(draft.get("phase", "Live draft state")))

	if typeof(next_game) == TYPE_DICTIONARY and next_game.size() > 0:
		var team_abbr := str(team.get("abbreviation", "TEAM"))
		var opponent_abbr := str(next_game.get("opponent", "OPP"))
		var is_home: bool = bool(next_game.get("is_home", false))

		next_game_matchup.text = "%s  %s  %s" % [
			team_abbr,
			"vs" if is_home else "at",
			opponent_abbr
		]

		var days_away := int(next_game.get("days_away", 0))
		var when_text := "Today"

		if days_away == 1:
			when_text = "Tomorrow"
		elif days_away > 1:
			when_text = "In %s days" % days_away

		var venue_text := "Home" if is_home else "Away"
		var next_game_number := int(record.get("games_played", 0)) + 1

		next_game_detail.text = "%s • %s
%s • Game %s" % [
			when_text,
			venue_text,
			str(next_game.get("opponent_name", opponent_abbr)),
			next_game_number
		]
	else:
		next_game_matchup.text = "NO GAME SCHEDULED"
		next_game_detail.text = "No future game was found in the active schedule."


func _set_live_data_error(message: String) -> void:
	header_subtitle.text = "V2 SAVE DATA UNAVAILABLE"

	record_value.text = "N/A"
	record_detail.text = message

	chemistry_value.text = "N/A"
	chemistry_detail.text = "Unavailable"

	cap_value.text = "N/A"
	cap_detail.text = "Unavailable"

	draft_value.text = "N/A"
	draft_detail.text = "Unavailable"

	next_game_matchup.text = "DATA OFFLINE"
	next_game_detail.text = message


func _pretty_phase(value: String) -> String:
	return value.replace("_", " ").to_upper()

func _set_bridge_status(connected: bool, detail: String) -> void:
	bridge_status.text = "CONNECTED" if connected else "OFFLINE"
	bridge_status.add_theme_color_override("font_color", GOOD if connected else BAD)
	bridge_detail.text = detail
	retry_button.disabled = false
