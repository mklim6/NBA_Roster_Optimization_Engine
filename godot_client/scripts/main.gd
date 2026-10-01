extends Control

const BRIDGE_URL := "http://127.0.0.1:8765/health"
const SUMMARY_URL := "http://127.0.0.1:8765/v3/franchise-summary"
const ROSTER_URL := "http://127.0.0.1:8765/v3/roster"

const BG := Color("07101d")
const SIDEBAR := Color("0b1525")
const PANEL := Color("101d30")
const PANEL_ALT := Color("14243a")
const PANEL_HOVER := Color("1a2d47")
const TEXT := Color("f5f7fb")
const MUTED := Color("91a3bd")
const ACCENT := Color("64d2ff")
const GOOD := Color("65d68d")
const BAD := Color("ff7383")
const BORDER := Color("223552")

var bridge_status: Label
var bridge_detail: Label
var retry_button: Button
var http_request: HTTPRequest
var summary_request: HTTPRequest
var roster_request: HTTPRequest

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

var header_subtitle: Label
var team_name_label: Label
var team_detail_label: Label
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
	sidebar_panel.custom_minimum_size = Vector2(250, 0)
	sidebar_panel.add_theme_stylebox_override("panel", _box(SIDEBAR, 0))

	var margin := MarginContainer.new()
	_set_margins(margin, 22, 24, 22, 24)
	sidebar_panel.add_child(margin)

	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 10)
	margin.add_child(column)

	var brand := Label.new()
	brand.text = "FRANCHISE\nSIMULATOR"
	brand.add_theme_color_override("font_color", TEXT)
	brand.add_theme_font_size_override("font_size", 24)
	column.add_child(brand)

	var version := Label.new()
	version.text = "V3 • DESKTOP ALPHA"
	version.add_theme_color_override("font_color", ACCENT)
	version.add_theme_font_size_override("font_size", 11)
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
	footer.text = "V2 engine preserved\nV3 client prototype"
	footer.add_theme_color_override("font_color", MUTED)
	footer.add_theme_font_size_override("font_size", 11)
	column.add_child(footer)

	return sidebar_panel


func _build_main_area() -> Control:
	var outer := MarginContainer.new()
	outer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	outer.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_set_margins(outer, 32, 26, 32, 28)

	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 18)
	outer.add_child(column)

	column.add_child(_build_header())

	var hero_row := HBoxContainer.new()
	hero_row.add_theme_constant_override("separation", 16)
	hero_row.add_child(_build_team_card())
	hero_row.add_child(_build_next_game_card())
	hero_row.add_child(_build_engine_card())
	column.add_child(hero_row)

	var metrics := GridContainer.new()
	metrics.columns = 4
	metrics.add_theme_constant_override("h_separation", 14)
	metrics.add_theme_constant_override("v_separation", 14)
	metrics.add_child(_metric_card("RECORD", "LOADING...", "Waiting for V2 save"))
	metrics.add_child(_metric_card("CHEMISTRY", "LOADING...", "Waiting for V2 save"))
	metrics.add_child(_metric_card("CAP SPACE", "LOADING...", "Waiting for V2 save"))
	metrics.add_child(_metric_card("DRAFT CLASS", "LOADING...", "Waiting for V2 save"))
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

	var title := Label.new()
	title.text = "FRANCHISE COMMAND CENTER"
	title.add_theme_color_override("font_color", TEXT)
	title.add_theme_font_size_override("font_size", 28)
	titles.add_child(title)

	header_subtitle = Label.new()
	header_subtitle.text = "LOADING ACTIVE V2 FRANCHISE..."
	header_subtitle.add_theme_color_override("font_color", MUTED)
	header_subtitle.add_theme_font_size_override("font_size", 12)
	titles.add_child(header_subtitle)
	row.add_child(titles)

	var alpha := Label.new()
	alpha.text = "PHASE 1"
	alpha.add_theme_color_override("font_color", ACCENT)
	alpha.add_theme_font_size_override("font_size", 12)
	alpha.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	row.add_child(alpha)

	return row

func _build_team_card() -> Control:
	var card := _card(Vector2(250, 190))
	var body := _card_body(card, 20)

	var kicker := _small_label("YOUR FRANCHISE", ACCENT)
	body.add_child(kicker)

	team_name_label = Label.new()
	team_name_label.text = "LOADING..."
	team_name_label.add_theme_color_override("font_color", TEXT)
	team_name_label.add_theme_font_size_override("font_size", 30)
	body.add_child(team_name_label)

	team_detail_label = Label.new()
	team_detail_label.text = "Reading active franchise checkpoint..."
	team_detail_label.add_theme_color_override("font_color", MUTED)
	team_detail_label.add_theme_font_size_override("font_size", 13)
	body.add_child(team_detail_label)

	var spacer := Control.new()
	spacer.size_flags_vertical = Control.SIZE_EXPAND_FILL
	body.add_child(spacer)

	body.add_child(_pill("LIVE V2 SAVE", GOOD))
	return card

func _build_next_game_card() -> Control:
	var card := _card(Vector2(360, 190))
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var body := _card_body(card, 20)

	body.add_child(_small_label("NEXT GAME", ACCENT))

	next_game_matchup = Label.new()
	next_game_matchup.text = "LOADING..."
	next_game_matchup.add_theme_color_override("font_color", TEXT)
	next_game_matchup.add_theme_font_size_override("font_size", 24)
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
	actions.add_child(_action_button("PLAY / SIM", true))
	body.add_child(actions)
	return card

func _build_engine_card() -> Control:
	var card := _card(Vector2(300, 190))
	var body := _card_body(card, 20)

	body.add_child(_small_label("DESKTOP ENGINE", ACCENT))

	bridge_status = Label.new()
	bridge_status.text = "CHECKING..."
	bridge_status.add_theme_color_override("font_color", MUTED)
	bridge_status.add_theme_font_size_override("font_size", 20)
	body.add_child(bridge_status)

	bridge_detail = Label.new()
	bridge_detail.text = "Looking for the local Python bridge on port 8765."
	bridge_detail.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	bridge_detail.add_theme_color_override("font_color", MUTED)
	bridge_detail.add_theme_font_size_override("font_size", 12)
	body.add_child(bridge_detail)

	var spacer := Control.new()
	spacer.size_flags_vertical = Control.SIZE_EXPAND_FILL
	body.add_child(spacer)

	retry_button = _action_button("RETRY CONNECTION")
	retry_button.pressed.connect(_check_bridge)
	body.add_child(retry_button)
	return card


func _metric_card(label_text: String, value_text: String, detail_text: String) -> Control:
	var card := _card(Vector2(0, 105))
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var body := _card_body(card, 16)

	body.add_child(_small_label(label_text, MUTED))

	var value := Label.new()
	value.text = value_text
	value.add_theme_color_override("font_color", TEXT)
	value.add_theme_font_size_override("font_size", 23)
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

	var title := Label.new()
	title.text = "ROSTER COMMAND CENTER"
	title.add_theme_color_override("font_color", TEXT)
	title.add_theme_font_size_override("font_size", 28)
	titles.add_child(title)

	roster_subtitle = Label.new()
	roster_subtitle.text = "LOADING ACTIVE V2 ROSTER..."
	roster_subtitle.add_theme_color_override("font_color", MUTED)
	roster_subtitle.add_theme_font_size_override("font_size", 12)
	titles.add_child(roster_subtitle)
	header.add_child(titles)

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

	roster_status = Label.new()
	roster_status.text = "Waiting for the read-only roster endpoint."
	roster_status.add_theme_color_override("font_color", MUTED)
	roster_status.add_theme_font_size_override("font_size", 11)
	column.add_child(roster_status)

	var roster_card := _card(Vector2(0, 0))
	roster_card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	roster_card.size_flags_vertical = Control.SIZE_EXPAND_FILL
	var body := _card_body(roster_card, 16)

	body.add_child(_section_title("ACTIVE ROSTER"))
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
	loading.text = "Loading players from the active V2 checkpoint..."
	loading.add_theme_color_override("font_color", MUTED)
	loading.add_theme_font_size_override("font_size", 12)
	roster_rows.add_child(loading)

	column.add_child(roster_card)

	var note := Label.new()
	note.text = "READ-ONLY • Cap room is an active-roster contract estimate while full team financial tables are unavailable in this save."
	note.add_theme_color_override("font_color", MUTED)
	note.add_theme_font_size_override("font_size", 10)
	column.add_child(note)

	return outer


func _roster_summary_card(label_text: String, value_text: String) -> Control:
	var card := _card(Vector2(0, 88))
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var body := _card_body(card, 14)

	body.add_child(_small_label(label_text, MUTED))

	var value := Label.new()
	value.text = value_text
	value.add_theme_color_override("font_color", TEXT)
	value.add_theme_font_size_override("font_size", 21)
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

	var margin := MarginContainer.new()
	_set_margins(margin, 10, 7, 10, 7)
	panel.add_child(margin)

	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 8)
	margin.add_child(row)

	var player_name := str(player.get("name", "Unknown"))
	var starter := bool(player.get("is_starter", false))
	var name_color := ACCENT if starter else TEXT
	if starter:
		player_name = "[S] " + player_name

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


func _roster_cell(
	text_value: String,
	width: int,
	color: Color,
	alignment: int = HORIZONTAL_ALIGNMENT_LEFT
) -> Label:
	var label := Label.new()
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

	body.add_child(_section_title("LEAGUE ACTIVITY"))
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

	body.add_child(_section_title("QUICK ACTIONS"))
	body.add_child(_wide_action("OPEN ROSTER", "Depth chart, roles, development"))
	body.add_child(_wide_action("TRADE CENTER", "Offers, finder, pick inventory"))
	body.add_child(_wide_action("SCOUTING BOARD", "Prospects and staff reports"))
	body.add_child(_wide_action("LEAGUE HUB", "Standings, awards, transactions"))

	var spacer := Control.new()
	spacer.size_flags_vertical = Control.SIZE_EXPAND_FILL
	body.add_child(spacer)

	var note := Label.new()
	note.text = "Phase 1 is intentionally read-only.\nNo V2 franchise save can be mutated by this prototype."
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

	return button

func _action_button(text_value: String, primary: bool = false) -> Button:
	var button := Button.new()
	button.custom_minimum_size = Vector2(120, 36)
	button.text = text_value
	button.add_theme_font_size_override("font_size", 11)
	button.add_theme_color_override("font_color", BG if primary else TEXT)
	button.add_theme_color_override("font_hover_color", BG if primary else TEXT)
	var normal_color := ACCENT if primary else PANEL_ALT
	var hover_color := Color("8be0ff") if primary else PANEL_HOVER
	button.add_theme_stylebox_override("normal", _box(normal_color, 8, normal_color if primary else BORDER))
	button.add_theme_stylebox_override("hover", _box(hover_color, 8, hover_color if primary else ACCENT))
	button.add_theme_stylebox_override("pressed", _box(hover_color, 8, hover_color))
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
	card.add_theme_stylebox_override("panel", _box(PANEL, 12, BORDER))
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
		"Python engine connected • API %s • live V2 save • read-only safe mode" % payload.get("api_version", "unknown")
	)

	_request_franchise_summary()
	_request_roster()


func _request_roster() -> void:
	if roster_request == null:
		return

	if roster_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		roster_request.cancel_request()

	if roster_status != null:
		roster_status.text = "Refreshing live V2 roster..."

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
		_set_roster_error("Active V2 roster could not be loaded.")
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

	roster_subtitle.text = "%s • %s • LEAGUE DAY %s • LIVE V2 SAVE" % [
		str(team.get("name", "Active Franchise")).to_upper(),
		str(season.get("label", "")),
		str(season.get("day_index", "?"))
	]

	roster_count_value.text = "%s rostered" % str(team.get("roster_size", "?"))
	roster_payroll_value.text = str(financial.get("payroll_display", "N/A"))
	roster_cap_value.text = str(financial.get("cap_room_estimate_display", "N/A"))
	roster_chemistry_value.text = _number_text(chemistry.get("score", null), 1)

	roster_status.text = "%s active • %s inactive • %s starters • %s rotation • %s injured" % [
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


func _set_roster_error(message: String) -> void:
	if roster_subtitle != null:
		roster_subtitle.text = "V2 ROSTER DATA UNAVAILABLE"

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
