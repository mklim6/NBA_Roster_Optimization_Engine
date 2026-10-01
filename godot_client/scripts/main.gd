extends Control

const BRIDGE_URL := "http://127.0.0.1:8765/health"

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
	shell.add_child(_build_main_area())


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
	metrics.add_child(_metric_card("RECORD", "18-12", "3rd in East"))
	metrics.add_child(_metric_card("CHEMISTRY", "82", "Strong"))
	metrics.add_child(_metric_card("CAP SPACE", "$8.3M", "Available"))
	metrics.add_child(_metric_card("NEXT PICK", "2027 1st", "Owned"))
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

	var subtitle := Label.new()
	subtitle.text = "2026-27  •  NOVEMBER 18  •  REGULAR SEASON"
	subtitle.add_theme_color_override("font_color", MUTED)
	subtitle.add_theme_font_size_override("font_size", 12)
	titles.add_child(subtitle)
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

	var team := Label.new()
	team.text = "CHICAGO"
	team.add_theme_color_override("font_color", TEXT)
	team.add_theme_font_size_override("font_size", 30)
	body.add_child(team)

	var sub := Label.new()
	sub.text = "Eastern Conference\nContender • Year 1"
	sub.add_theme_color_override("font_color", MUTED)
	sub.add_theme_font_size_override("font_size", 13)
	body.add_child(sub)

	var spacer := Control.new()
	spacer.size_flags_vertical = Control.SIZE_EXPAND_FILL
	body.add_child(spacer)

	body.add_child(_pill("TEAM OVR 87", GOOD))
	return card


func _build_next_game_card() -> Control:
	var card := _card(Vector2(360, 190))
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var body := _card_body(card, 20)

	body.add_child(_small_label("NEXT GAME", ACCENT))

	var matchup := Label.new()
	matchup.text = "CHICAGO  vs  BOSTON"
	matchup.add_theme_color_override("font_color", TEXT)
	matchup.add_theme_font_size_override("font_size", 24)
	body.add_child(matchup)

	var detail := Label.new()
	detail.text = "Tomorrow • 7:30 PM\nHome • Game 31"
	detail.add_theme_color_override("font_color", MUTED)
	detail.add_theme_font_size_override("font_size", 13)
	body.add_child(detail)

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
	return card


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
	button.text = "%s\n%s" % [title_text, subtitle_text]
	button.alignment = HORIZONTAL_ALIGNMENT_LEFT
	button.add_theme_font_size_override("font_size", 12)
	button.add_theme_color_override("font_color", TEXT)
	button.add_theme_color_override("font_hover_color", TEXT)
	button.add_theme_stylebox_override("normal", _box(PANEL_ALT, 9, BORDER))
	button.add_theme_stylebox_override("hover", _box(PANEL_HOVER, 9, ACCENT))
	button.add_theme_stylebox_override("pressed", _box(PANEL_HOVER, 9, ACCENT))
	return button


func _nav_button(text_value: String, active: bool = false) -> Button:
	var button := Button.new()
	button.custom_minimum_size = Vector2(0, 42)
	button.text = text_value
	button.alignment = HORIZONTAL_ALIGNMENT_LEFT
	button.add_theme_font_size_override("font_size", 12)
	button.add_theme_color_override("font_color", TEXT if active else MUTED)
	button.add_theme_color_override("font_hover_color", TEXT)
	button.add_theme_color_override("font_disabled_color", Color("53647c"))
	button.add_theme_stylebox_override("normal", _box(PANEL_ALT if active else SIDEBAR, 8))
	button.add_theme_stylebox_override("hover", _box(PANEL_HOVER, 8))
	button.add_theme_stylebox_override("pressed", _box(PANEL_ALT, 8))
	button.add_theme_stylebox_override("disabled", _box(SIDEBAR, 8))
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
		"Python engine connected • API %s • read-only safe mode" % payload.get("api_version", "unknown")
	)


func _set_bridge_status(connected: bool, detail: String) -> void:
	bridge_status.text = "CONNECTED" if connected else "OFFLINE"
	bridge_status.add_theme_color_override("font_color", GOOD if connected else BAD)
	bridge_detail.text = detail
	retry_button.disabled = false
