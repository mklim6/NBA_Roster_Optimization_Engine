extends Control

const DesignSystemV3 = preload("res://scripts/design_system_v3.gd")
const TeamBrandingV3 = preload("res://scripts/team_branding_v3.gd")
const TeamLogoV3 = preload("res://scripts/team_logo_v3.gd")

const GAME_DAY_URL := "http://127.0.0.1:8765/v3/game-day"
const GAME_DAY_SIMULATE_URL := "http://127.0.0.1:8765/v3/game-day/simulate"
const ROSTER_URL := "http://127.0.0.1:8765/v3/roster"
const ROTATION_PREVIEW_URL := "http://127.0.0.1:8765/v3/rotation/preview"
const ROTATION_APPLY_URL := "http://127.0.0.1:8765/v3/rotation/apply"

const BG := DesignSystemV3.BG
const PANEL := DesignSystemV3.PANEL
const PANEL_ALT := DesignSystemV3.PANEL_ALT
const PANEL_HOVER := DesignSystemV3.PANEL_HOVER
const TEXT := DesignSystemV3.TEXT
const MUTED := DesignSystemV3.MUTED
const GOOD := DesignSystemV3.GOOD
const BAD := DesignSystemV3.BAD
const BORDER := DesignSystemV3.BORDER
const SOFT_BORDER := DesignSystemV3.SOFT_BORDER
const GOLD := DesignSystemV3.GOLD
const ACCENT := DesignSystemV3.ACCENT
const TEAM_PRIMARY := Color("d9273c")
const TEAM_PRIMARY_HOVER := Color("ef4055")

# Batch 20D Game Day presentation foundation
# Batch 21B Game Day broadcast spectacle
var team_brand_panel: PanelContainer
var opponent_brand_panel: PanelContainer
var matchup_card: PanelContainer
var branded_top_band: ColorRect
var team_logo_control: Control
var opponent_logo_control: Control
var team_accent_bar: ColorRect
var opponent_accent_bar: ColorRect
var team_context_label: Label
var opponent_context_label: Label
var broadcast_network_label: Label
var broadcast_context_label: Label
var postgame_scoreboard_panel: PanelContainer
var postgame_home_logo: Control
var postgame_away_logo: Control
var postgame_home_team_label: Label
var postgame_away_team_label: Label
var readiness_values := {}
var primary_buttons: Array = []

var game_request: HTTPRequest
var roster_request: HTTPRequest
var simulate_request: HTTPRequest
var rotation_request: HTTPRequest

var status_label: Label
var team_badge: Label
var opponent_badge: Label
var team_name_label: Label
var opponent_name_label: Label
var team_record_label: Label
var opponent_record_label: Label
var matchup_label: Label
var game_meta_label: Label
var simulation_button: Button
var availability_label: Label
var alerts_label: Label
var rotation_summary_label: Label
var sync_label: Label

var rotation_rows_box: VBoxContainer
var rotation_total_label: Label
var rotation_feedback: Label
var rotation_preview_button: Button
var rotation_apply_button: Button

var postgame_title_label: Label
var postgame_result_label: Label
var postgame_active_card: PanelContainer
var postgame_team_color := TEAM_PRIMARY_HOVER
var postgame_meta_label: Label
var postgame_active_box: VBoxContainer
var postgame_opponent_box: VBoxContainer

var game_payload := {}
var roster_payload := {}
var active_team := ""
var active_opponent := ""

var rotation_entries := {}
var rotation_order := []
var rotation_request_mode := ""
var rotation_pending_body := ""
var rotation_validated_body := ""
var rotation_syncing := false
var simulate_armed := false


var long_action_manager = null


func apply_team_brand(_team: String, primary: Color, _secondary: Color) -> void:
	postgame_team_color = TeamBrandingV3.hover_color(primary)
	if branded_top_band != null:
		branded_top_band.color = Color(primary, 0.08)
	if team_brand_panel != null:
		team_brand_panel.add_theme_stylebox_override("panel", _box(Color(primary, 0.88), 16, TeamBrandingV3.hover_color(primary)))
		if team_badge != null:
			team_badge.add_theme_color_override("font_color", TeamBrandingV3.readable_foreground(primary))
	if team_accent_bar != null:
		team_accent_bar.color = primary
	if broadcast_network_label != null:
		broadcast_network_label.add_theme_color_override("font_color", TeamBrandingV3.hover_color(primary))
	if matchup_card != null:
		matchup_card.add_theme_stylebox_override("panel", _box(PANEL, 16, Color(primary, 0.58)))
	if postgame_scoreboard_panel != null:
		postgame_scoreboard_panel.add_theme_stylebox_override("panel", _box(Color("0d141f"), 16, Color(primary, 0.52)))
	if postgame_active_card != null:
		postgame_active_card.add_theme_stylebox_override("panel", _box(PANEL_ALT, 12, Color(primary, 0.48)))
		if postgame_active_box.get_child_count() > 0:
			postgame_active_box.get_child(0).add_theme_color_override("font_color", postgame_team_color)
	for button in primary_buttons:
		TeamBrandingV3.apply_primary_button(button, primary)


func set_long_action_manager(manager) -> void:
	long_action_manager = manager


func _begin_long_action(key: String, title: String, detail: String, steps: Array) -> bool:
	if long_action_manager == null:
		return true
	return bool(long_action_manager.begin_action(key, title, detail, steps))


func _finish_long_action(key: String, success: bool, message: String = "") -> void:
	if long_action_manager != null:
		long_action_manager.finish_action(key, success, message)


func _ready() -> void:
	_build_page()
	_build_http()


func refresh() -> void:
	_reset_simulate_arm()
	if simulation_button != null:
		simulation_button.disabled = true
	if status_label != null:
		status_label.text = "REFRESHING LIVE V3 GAME DAY..."
		status_label.add_theme_color_override("font_color", MUTED)
	_request_game_day()
	_request_roster()


func _build_page() -> void:
	var background := ColorRect.new()
	background.color = BG
	add_child(background)
	background.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)

	var top_band := ColorRect.new()
	branded_top_band = top_band
	top_band.color = Color(TEAM_PRIMARY, 0.05)
	top_band.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(top_band)
	top_band.anchor_right = 1.0
	top_band.offset_bottom = 185.0

	var outer := MarginContainer.new()
	_set_margins(outer, 30, 24, 30, 28)
	add_child(outer)
	outer.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)

	var page_column := VBoxContainer.new()
	page_column.add_theme_constant_override("separation", 14)
	outer.add_child(page_column)

	page_column.add_child(_build_header())

	status_label = _label("LOADING V3 GAME DAY...", 11, GOOD)
	page_column.add_child(status_label)

	var scroll := ScrollContainer.new()
	scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	# Batch 14.0.1: keep Game Day vertically scrollable without allowing the
	# two-team box score to create a page-wide horizontal scrollbar.
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	page_column.add_child(scroll)

	var content := VBoxContainer.new()
	content.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	content.add_theme_constant_override("separation", 14)
	scroll.add_child(content)

	content.add_child(_build_matchup_card())
	content.add_child(_build_readiness_metrics())
	content.add_child(_build_readiness_row())
	content.add_child(_build_rotation_card())
	content.add_child(_build_postgame_card())


func _build_header() -> Control:
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 14)

	var titles := VBoxContainer.new()
	titles.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	titles.add_theme_constant_override("separation", 4)
	row.add_child(titles)

	titles.add_child(_label("FRANCHISE OPERATIONS • GAME DAY", 10, TEAM_PRIMARY_HOVER))
	titles.add_child(_label("GAME DAY COMMAND CENTER", 31, TEXT))
	var subtitle := _label(
		"Live matchup prep, rotation control, production simulation, and complete postgame review from the isolated V3 franchise.",
		12,
		MUTED
	)
	subtitle.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	titles.add_child(subtitle)

	var refresh_button := _button("REFRESH GAME DAY")
	refresh_button.custom_minimum_size = Vector2(165, 56)
	refresh_button.pressed.connect(refresh)
	row.add_child(refresh_button)
	return row


# Batch 21B.1 cinematic Game Day polish
# Batch 22 franchise presentation macro
func _build_matchup_card() -> Control:
	var card := _card(Vector2(0, 326))
	card.name = "BroadcastMatchupHero"
	matchup_card = card
	card.add_theme_stylebox_override("panel", _box(Color("101823"), 20, Color(TEAM_PRIMARY, 0.62)))
	var body := _card_body(card, 20)
	body.add_theme_constant_override("separation", 12)

	var broadcast_strip := HBoxContainer.new()
	broadcast_strip.name = "BroadcastPregameStrip"
	broadcast_strip.add_theme_constant_override("separation", 10)
	body.add_child(broadcast_strip)

	broadcast_network_label = _label("FRANCHISE NETWORK • PRIME TIME", 10, TEAM_PRIMARY_HOVER)
	broadcast_network_label.name = "BroadcastNetworkLabel"
	broadcast_strip.add_child(broadcast_network_label)

	var broadcast_spacer := Control.new()
	broadcast_spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	broadcast_strip.add_child(broadcast_spacer)

	broadcast_context_label = _label("PREGAME • LIVE", 10, GOLD)
	broadcast_context_label.name = "BroadcastContextLabel"
	broadcast_strip.add_child(broadcast_context_label)

	var broadcast_rule := HSeparator.new()
	broadcast_rule.modulate = Color(1, 1, 1, 0.10)
	body.add_child(broadcast_rule)

	var matchup_row := HBoxContainer.new()
	matchup_row.add_theme_constant_override("separation", 18)
	body.add_child(matchup_row)

	var left := VBoxContainer.new()
	left.custom_minimum_size = Vector2(270, 0)
	left.add_theme_constant_override("separation", 7)
	matchup_row.add_child(left)

	team_brand_panel = PanelContainer.new()
	team_brand_panel.name = "BroadcastActiveTeamPanel"
	team_brand_panel.custom_minimum_size = Vector2(270, 166)
	team_brand_panel.add_theme_stylebox_override("panel", _box(Color(TEAM_PRIMARY, 0.90), 18, TEAM_PRIMARY_HOVER))
	left.add_child(team_brand_panel)

	var left_stack := VBoxContainer.new()
	left_stack.add_theme_constant_override("separation", 2)
	team_brand_panel.add_child(left_stack)

	team_accent_bar = ColorRect.new()
	team_accent_bar.custom_minimum_size = Vector2(0, 5)
	team_accent_bar.color = TEAM_PRIMARY_HOVER
	team_accent_bar.mouse_filter = Control.MOUSE_FILTER_IGNORE
	left_stack.add_child(team_accent_bar)

	var left_logo_center := CenterContainer.new()
	left_logo_center.size_flags_vertical = Control.SIZE_EXPAND_FILL
	left_stack.add_child(left_logo_center)

	team_logo_control = TeamLogoV3.new()
	team_logo_control.name = "PregameTeamLogo"
	team_logo_control.custom_minimum_size = Vector2(158, 138)
	left_logo_center.add_child(team_logo_control)

	team_name_label = _label("ACTIVE FRANCHISE", 17, TEXT)
	team_name_label.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	left.add_child(team_name_label)

	var left_meta := HBoxContainer.new()
	left_meta.add_theme_constant_override("separation", 9)
	left.add_child(left_meta)

	team_record_label = _label("Record --", 11, MUTED)
	team_record_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	left_meta.add_child(team_record_label)

	team_context_label = _label("YOUR TEAM", 9, TEAM_PRIMARY_HOVER)
	left_meta.add_child(team_context_label)

	var center := VBoxContainer.new()
	center.custom_minimum_size = Vector2(340, 0)
	center.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	center.alignment = BoxContainer.ALIGNMENT_CENTER
	center.add_theme_constant_override("separation", 9)
	matchup_row.add_child(center)

	var center_plate := PanelContainer.new()
	center_plate.name = "BroadcastCenterPlate"
	center_plate.custom_minimum_size = Vector2(330, 118)
	center_plate.add_theme_stylebox_override("panel", _box(Color("0b111a"), 18, Color(GOLD, 0.28)))
	center.add_child(center_plate)

	var center_plate_margin := MarginContainer.new()
	_set_margins(center_plate_margin, 14, 12, 14, 12)
	center_plate.add_child(center_plate_margin)

	var center_copy := VBoxContainer.new()
	center_copy.alignment = BoxContainer.ALIGNMENT_CENTER
	center_copy.add_theme_constant_override("separation", 6)
	center_plate_margin.add_child(center_copy)

	var versus_kicker := _label("TONIGHT'S MATCHUP", 9, GOLD)
	versus_kicker.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	center_copy.add_child(versus_kicker)

	matchup_label = _label("LOADING MATCHUP...", 42, TEXT)
	matchup_label.name = "BroadcastMatchupTitle"
	matchup_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	matchup_label.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	center_copy.add_child(matchup_label)

	game_meta_label = _label("Reading production schedule...", 11, MUTED)
	game_meta_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	center_copy.add_child(game_meta_label)

	var action_center := CenterContainer.new()
	action_center.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	center.add_child(action_center)

	simulation_button = _button("SIMULATE GAME", true)
	simulation_button.custom_minimum_size = Vector2(304, 48)
	simulation_button.disabled = true
	simulation_button.pressed.connect(_on_simulate_pressed)
	action_center.add_child(simulation_button)

	var confirm_note := _label("Arm simulation • confirm on second click", 10, MUTED)
	confirm_note.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	center.add_child(confirm_note)

	var right := VBoxContainer.new()
	right.custom_minimum_size = Vector2(270, 0)
	right.add_theme_constant_override("separation", 7)
	matchup_row.add_child(right)

	opponent_brand_panel = PanelContainer.new()
	opponent_brand_panel.name = "BroadcastOpponentTeamPanel"
	opponent_brand_panel.custom_minimum_size = Vector2(270, 166)
	opponent_brand_panel.add_theme_stylebox_override("panel", _box(Color("222b3b"), 18, BORDER))
	right.add_child(opponent_brand_panel)

	var right_stack := VBoxContainer.new()
	right_stack.add_theme_constant_override("separation", 2)
	opponent_brand_panel.add_child(right_stack)

	opponent_accent_bar = ColorRect.new()
	opponent_accent_bar.custom_minimum_size = Vector2(0, 5)
	opponent_accent_bar.color = MUTED
	opponent_accent_bar.mouse_filter = Control.MOUSE_FILTER_IGNORE
	right_stack.add_child(opponent_accent_bar)

	var right_logo_center := CenterContainer.new()
	right_logo_center.size_flags_vertical = Control.SIZE_EXPAND_FILL
	right_stack.add_child(right_logo_center)

	opponent_logo_control = TeamLogoV3.new()
	opponent_logo_control.name = "PregameOpponentLogo"
	opponent_logo_control.custom_minimum_size = Vector2(158, 138)
	right_logo_center.add_child(opponent_logo_control)

	opponent_name_label = _label("OPPONENT", 17, TEXT)
	opponent_name_label.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	right.add_child(opponent_name_label)

	var right_meta := HBoxContainer.new()
	right_meta.add_theme_constant_override("separation", 9)
	right.add_child(right_meta)

	opponent_record_label = _label("Record --", 11, MUTED)
	opponent_record_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	right_meta.add_child(opponent_record_label)

	opponent_context_label = _label("OPPONENT", 9, MUTED)
	right_meta.add_child(opponent_context_label)
	return card


func _build_readiness_metrics() -> Control:
	var row := HBoxContainer.new()
	row.name = "GameDayReadinessMetrics"
	row.add_theme_constant_override("separation", 10)
	for label_text in ["UNAVAILABLE", "COACHING ALERTS", "ROTATION", "TARGET MINUTES"]:
		var tone := MUTED
		match label_text:
			"UNAVAILABLE":
				tone = GOOD
			"COACHING ALERTS":
				tone = GOLD
			"ROTATION":
				tone = ACCENT
			"TARGET MINUTES":
				tone = TEAM_PRIMARY_HOVER

		var card := _card(Vector2(0, 94))
		card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		card.add_theme_stylebox_override("panel", _box(PANEL_ALT, 13, Color(tone, 0.36)))
		var body := _card_body(card, 12)
		body.add_theme_constant_override("separation", 5)

		var accent := ColorRect.new()
		accent.custom_minimum_size = Vector2(0, 3)
		accent.color = tone
		accent.mouse_filter = Control.MOUSE_FILTER_IGNORE
		body.add_child(accent)

		body.add_child(_label(label_text, 9, Color(tone, 0.92)))
		var value := _label("N/A", 25, TEXT)
		readiness_values[label_text] = value
		body.add_child(value)
		row.add_child(card)
	return row


func _render_readiness_metrics() -> void:
	var unavailable = game_payload.get("unavailable_players", null)
	var alerts = game_payload.get("coaching_alerts", null)
	var rotation := _dict(game_payload.get("rotation"))
	var ids = rotation.get("rotation_player_ids", null)
	var minutes = rotation.get("total_minutes", null)
	readiness_values["UNAVAILABLE"].text = str(unavailable.size()) if typeof(unavailable) == TYPE_ARRAY else "N/A"
	readiness_values["COACHING ALERTS"].text = str(alerts.size()) if typeof(alerts) == TYPE_ARRAY else "N/A"
	readiness_values["ROTATION"].text = str(ids.size()) if typeof(ids) == TYPE_ARRAY else "N/A"
	readiness_values["TARGET MINUTES"].text = "%.0f" % float(minutes) if minutes != null else "N/A"
	readiness_values["UNAVAILABLE"].add_theme_color_override("font_color", BAD if typeof(unavailable) == TYPE_ARRAY and not unavailable.is_empty() else TEXT)
	readiness_values["COACHING ALERTS"].add_theme_color_override("font_color", GOLD if typeof(alerts) == TYPE_ARRAY and not alerts.is_empty() else TEXT)


func _build_readiness_row() -> Control:
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 14)

	var readiness_card := _card(Vector2(0, 235))
	readiness_card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var readiness := _card_body(readiness_card, 16)
	readiness.add_child(_section_title("GAME PLAN READINESS"))
	availability_label = _label("Loading availability...", 11, MUTED)
	availability_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	readiness.add_child(availability_label)
	alerts_label = _label("Loading coaching alerts...", 11, MUTED)
	alerts_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	readiness.add_child(alerts_label)
	row.add_child(readiness_card)

	var rotation_card := _card(Vector2(0, 235))
	rotation_card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var rotation_body := _card_body(rotation_card, 16)
	rotation_body.add_child(_section_title("CURRENT ROTATION"))
	rotation_summary_label = _label("Loading rotation...", 11, MUTED)
	rotation_summary_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	rotation_body.add_child(rotation_summary_label)
	sync_label = _label("Loading league calendar sync...", 10, MUTED)
	sync_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	rotation_body.add_child(sync_label)
	row.add_child(rotation_card)
	return row


func _build_rotation_card() -> Control:
	var card := _card(Vector2(0, 360))
	var body := _card_body(card, 16)

	var header := HBoxContainer.new()
	header.add_theme_constant_override("separation", 10)
	body.add_child(header)

	var titles := VBoxContainer.new()
	titles.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	titles.add_theme_constant_override("separation", 3)
	header.add_child(titles)
	titles.add_child(_section_title("ROTATION + MINUTES"))
	var note := _label(
		"Every change uses the production rotation validator. Preview must pass before Apply is enabled.",
		10,
		MUTED
	)
	note.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	titles.add_child(note)

	rotation_preview_button = _button("PREVIEW GAME PLAN")
	rotation_preview_button.disabled = true
	rotation_preview_button.pressed.connect(_on_rotation_preview_pressed)
	header.add_child(rotation_preview_button)

	rotation_apply_button = _button("APPLY GAME PLAN", true)
	rotation_apply_button.disabled = true
	rotation_apply_button.pressed.connect(_on_rotation_apply_pressed)
	header.add_child(rotation_apply_button)

	var summary_row := HBoxContainer.new()
	summary_row.add_theme_constant_override("separation", 10)
	body.add_child(summary_row)

	rotation_total_label = _label("0 / 240 MIN", 17, MUTED)
	rotation_total_label.custom_minimum_size = Vector2(155, 34)
	rotation_total_label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	summary_row.add_child(rotation_total_label)

	rotation_feedback = _label("Roster is loading...", 10, MUTED)
	rotation_feedback.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	rotation_feedback.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	rotation_feedback.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	summary_row.add_child(rotation_feedback)

	var table_header := HBoxContainer.new()
	table_header.add_theme_constant_override("separation", 6)
	table_header.add_child(_cell("PLAYER", 210, MUTED))
	table_header.add_child(_cell("POS", 54, MUTED, HORIZONTAL_ALIGNMENT_CENTER))
	table_header.add_child(_cell("HEALTH", 150, MUTED))
	table_header.add_child(_cell("START", 64, MUTED, HORIZONTAL_ALIGNMENT_CENTER))
	table_header.add_child(_cell("ROT", 72, MUTED, HORIZONTAL_ALIGNMENT_CENTER))
	table_header.add_child(_cell("MIN", 100, MUTED, HORIZONTAL_ALIGNMENT_CENTER))
	body.add_child(table_header)

	rotation_rows_box = VBoxContainer.new()
	rotation_rows_box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	rotation_rows_box.add_theme_constant_override("separation", 4)
	body.add_child(rotation_rows_box)
	return card


func _build_postgame_card() -> Control:
	var card := _card(Vector2(0, 530))
	card.name = "BroadcastPostgameReview"
	var body := _card_body(card, 16)
	body.add_theme_constant_override("separation", 12)

	postgame_scoreboard_panel = PanelContainer.new()
	postgame_scoreboard_panel.name = "PostgameBroadcastScoreboard"
	postgame_scoreboard_panel.custom_minimum_size = Vector2(0, 190)
	postgame_scoreboard_panel.add_theme_stylebox_override("panel", _box(Color("0b111a"), 18, Color(TEAM_PRIMARY, 0.48)))
	body.add_child(postgame_scoreboard_panel)

	var scoreboard_margin := MarginContainer.new()
	_set_margins(scoreboard_margin, 20, 14, 20, 14)
	postgame_scoreboard_panel.add_child(scoreboard_margin)

	var scoreboard := VBoxContainer.new()
	scoreboard.alignment = BoxContainer.ALIGNMENT_CENTER
	scoreboard.add_theme_constant_override("separation", 7)
	scoreboard_margin.add_child(scoreboard)

	postgame_result_label = _label("FRANCHISE NETWORK • POSTGAME", 10, MUTED)
	postgame_result_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	scoreboard.add_child(postgame_result_label)

	var score_row := HBoxContainer.new()
	score_row.alignment = BoxContainer.ALIGNMENT_CENTER
	score_row.add_theme_constant_override("separation", 18)
	scoreboard.add_child(score_row)

	var home_identity := VBoxContainer.new()
	home_identity.custom_minimum_size = Vector2(190, 0)
	home_identity.alignment = BoxContainer.ALIGNMENT_CENTER
	score_row.add_child(home_identity)

	var home_logo_center := CenterContainer.new()
	home_identity.add_child(home_logo_center)
	postgame_home_logo = TeamLogoV3.new()
	postgame_home_logo.custom_minimum_size = Vector2(96, 84)
	home_logo_center.add_child(postgame_home_logo)

	postgame_home_team_label = _label("HOME", 14, TEXT)
	postgame_home_team_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	home_identity.add_child(postgame_home_team_label)

	var score_center := VBoxContainer.new()
	score_center.custom_minimum_size = Vector2(300, 0)
	score_center.alignment = BoxContainer.ALIGNMENT_CENTER
	score_center.add_theme_constant_override("separation", 3)
	score_row.add_child(score_center)

	var final_kicker := _label("FINAL SCORE", 9, GOLD)
	final_kicker.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	score_center.add_child(final_kicker)

	postgame_title_label = _section_title("--   —   --")
	postgame_title_label.name = "PostgameBroadcastScore"
	postgame_title_label.add_theme_font_size_override("font_size", 52)
	postgame_title_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	postgame_title_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	score_center.add_child(postgame_title_label)

	postgame_meta_label = _label("Full player box scores will appear here after a completed controlled-team game.", 10, MUTED)
	postgame_meta_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	postgame_meta_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	score_center.add_child(postgame_meta_label)

	var away_identity := VBoxContainer.new()
	away_identity.custom_minimum_size = Vector2(190, 0)
	away_identity.alignment = BoxContainer.ALIGNMENT_CENTER
	score_row.add_child(away_identity)

	var away_logo_center := CenterContainer.new()
	away_identity.add_child(away_logo_center)
	postgame_away_logo = TeamLogoV3.new()
	postgame_away_logo.custom_minimum_size = Vector2(96, 84)
	away_logo_center.add_child(postgame_away_logo)

	postgame_away_team_label = _label("AWAY", 14, TEXT)
	postgame_away_team_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	away_identity.add_child(postgame_away_team_label)

	var box_header := HBoxContainer.new()
	box_header.add_theme_constant_override("separation", 10)
	box_header.add_child(_label("FULL BOX SCORE", 10, GOLD))
	var box_header_spacer := Control.new()
	box_header_spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	box_header.add_child(box_header_spacer)
	box_header.add_child(_label("TEAM TOTALS • SHOOTING • PLAYER LINES", 9, MUTED))
	body.add_child(box_header)

	var teams := HBoxContainer.new()
	teams.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	teams.add_theme_constant_override("separation", 10)
	body.add_child(teams)

	var active_card := _card(Vector2(0, 0))
	postgame_active_card = active_card
	active_card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	active_card.add_theme_stylebox_override("panel", _box(PANEL_ALT, 12, Color(TEAM_PRIMARY, 0.48)))
	active_card.size_flags_stretch_ratio = 1.0
	postgame_active_box = _card_body(active_card, 10)
	teams.add_child(active_card)

	var opponent_card := _card(Vector2(0, 0))
	opponent_card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	opponent_card.add_theme_stylebox_override("panel", _box(PANEL_ALT, 12, BORDER))
	opponent_card.size_flags_stretch_ratio = 1.0
	postgame_opponent_box = _card_body(opponent_card, 10)
	teams.add_child(opponent_card)

	_render_empty_box_score(postgame_active_box, "YOUR TEAM")
	_render_empty_box_score(postgame_opponent_box, "OPPONENT")
	return card


func _build_http() -> void:
	game_request = HTTPRequest.new()
	game_request.timeout = 8.0
	game_request.request_completed.connect(_on_game_request_completed)
	add_child(game_request)

	roster_request = HTTPRequest.new()
	roster_request.timeout = 8.0
	roster_request.request_completed.connect(_on_roster_request_completed)
	add_child(roster_request)

	simulate_request = HTTPRequest.new()
	simulate_request.timeout = 75.0
	simulate_request.request_completed.connect(_on_simulate_request_completed)
	add_child(simulate_request)

	rotation_request = HTTPRequest.new()
	rotation_request.timeout = 10.0
	rotation_request.request_completed.connect(_on_rotation_request_completed)
	add_child(rotation_request)


func _request_game_day() -> void:
	if game_request == null:
		return
	if game_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		game_request.cancel_request()
	var error := game_request.request(GAME_DAY_URL)
	if error != OK:
		_set_status("GAME DAY REQUEST COULD NOT START • error %s" % error, BAD)


func _request_roster() -> void:
	if roster_request == null:
		return
	if roster_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		roster_request.cancel_request()
	var error := roster_request.request(ROSTER_URL)
	if error != OK:
		_set_status("ROSTER REQUEST COULD NOT START • error %s" % error, BAD)


func _on_game_request_completed(
	result: int,
	response_code: int,
	_headers: PackedStringArray,
	body: PackedByteArray
) -> void:
	if result != HTTPRequest.RESULT_SUCCESS:
		_set_status("GAME DAY DATA REQUEST FAILED BEFORE THE BRIDGE RESPONDED", BAD)
		return

	var parsed = JSON.parse_string(body.get_string_from_utf8())
	if response_code != 200 or typeof(parsed) != TYPE_DICTIONARY:
		var detail := "HTTP %s" % response_code
		if typeof(parsed) == TYPE_DICTIONARY:
			detail = _text(parsed.get("detail"), _text(parsed.get("error"), detail))
		_set_status("GAME DAY DATA UNAVAILABLE • %s" % detail, BAD)
		return

	if not bool(parsed.get("working_save_only", false)) or not bool(parsed.get("active_v2_read_only", false)):
		_set_status("GAME DAY SAFETY CONTRACT FAILED • V3/V2 isolation was not confirmed", BAD)
		return

	game_payload = parsed
	_render_game_day()


func _on_roster_request_completed(
	result: int,
	response_code: int,
	_headers: PackedStringArray,
	body: PackedByteArray
) -> void:
	if result != HTTPRequest.RESULT_SUCCESS:
		rotation_feedback.text = "Roster request failed before the bridge responded."
		rotation_feedback.add_theme_color_override("font_color", BAD)
		return

	var parsed = JSON.parse_string(body.get_string_from_utf8())
	if response_code != 200 or typeof(parsed) != TYPE_DICTIONARY:
		rotation_feedback.text = "Roster data unavailable for rotation editing."
		rotation_feedback.add_theme_color_override("font_color", BAD)
		return

	if not bool(parsed.get("editable", false)) or not bool(parsed.get("active_v2_read_only", false)):
		rotation_feedback.text = "Rotation editing requires the isolated writable V3 working save."
		rotation_feedback.add_theme_color_override("font_color", BAD)
		return

	roster_payload = parsed
	_render_rotation_editor()
	_render_rotation_summary()


func _render_game_day() -> void:
	active_team = _text(game_payload.get("team"), "TEAM").to_upper()
	var team_name := _text(game_payload.get("team_name"), active_team)
	var season := _text(game_payload.get("season"), "UNKNOWN SEASON")
	var phase := _text(game_payload.get("phase"), "").replace("_", " ").to_upper()
	var day_index := _int_value(game_payload.get("day_index"), 0)
	var record := _dict(game_payload.get("record"))
	var next_game = game_payload.get("next_game", null)

	if team_logo_control != null:
		team_logo_control.configure(active_team)
	team_name_label.text = team_name.to_upper()
	team_record_label.text = "Record %s" % _text(record.get("display"), "N/A")

	if next_game == null or typeof(next_game) != TYPE_DICTIONARY:
		active_opponent = ""
		if opponent_logo_control != null:
			opponent_logo_control.configure("")
		if team_context_label != null:
			team_context_label.text = "YOUR TEAM"
		if opponent_context_label != null:
			opponent_context_label.text = "NO GAME"
		if opponent_brand_panel != null:
			opponent_brand_panel.add_theme_stylebox_override("panel", _box(Color("222b3b"), 16, BORDER))
		if broadcast_context_label != null:
			broadcast_context_label.text = "NO GAME ON DECK"
		opponent_name_label.text = "NO OPPONENT"
		opponent_record_label.text = "Record --"
		matchup_label.text = "NO GAME SCHEDULED"
		game_meta_label.text = "%s • %s • LEAGUE DAY %d" % [season, phase, day_index]
		simulation_button.disabled = true
		_render_readiness()
		_render_rotation_summary()
		var last_game = game_payload.get("last_game", null)
		if typeof(last_game) == TYPE_DICTIONARY:
			_render_postgame(last_game)
		else:
			_reset_postgame()
		_set_status("LIVE V3 GAME DAY • NO CONTROLLED-TEAM GAME IS CURRENTLY SCHEDULED • V2 PROTECTED", GOOD)
		return

	var game := _dict(next_game)
	active_opponent = _text(game.get("opponent"), "OPP").to_upper()
	var opponent_name := _text(game.get("opponent_name"), active_opponent)
	var opponent_record := _dict(game_payload.get("opponent_record"))
	var is_home := bool(game.get("is_home", false))

	if opponent_logo_control != null:
		opponent_logo_control.configure(active_opponent)
	var opponent_palette := DesignSystemV3.team_palette(active_opponent)
	var opponent_primary = opponent_palette.get("primary", Color("222b3b"))
	if opponent_brand_panel != null:
		opponent_brand_panel.add_theme_stylebox_override(
			"panel",
			_box(Color(opponent_primary, 0.90), 18, TeamBrandingV3.hover_color(opponent_primary))
		)
	if opponent_accent_bar != null:
		opponent_accent_bar.color = TeamBrandingV3.hover_color(opponent_primary)
	if team_context_label != null:
		team_context_label.text = "HOME TEAM" if is_home else "AWAY TEAM"
		team_context_label.add_theme_color_override("font_color", postgame_team_color)
	if opponent_context_label != null:
		opponent_context_label.text = "AWAY TEAM" if is_home else "HOME TEAM"
		opponent_context_label.add_theme_color_override("font_color", TeamBrandingV3.hover_color(opponent_primary))
	if broadcast_context_label != null:
		broadcast_context_label.text = "HOME COURT • PRIME TIME" if is_home else "ON THE ROAD • PRIME TIME"
	opponent_name_label.text = opponent_name.to_upper()
	opponent_record_label.text = "Record %s" % _text(opponent_record.get("display"), "N/A")
	matchup_label.text = "%s  %s  %s" % [active_team, "VS" if is_home else "@", active_opponent]
	game_meta_label.text = "%s • %s • DAY %s • %s" % [
		season,
		phase,
		str(game.get("day_index", day_index)),
		"HOME" if is_home else "AWAY"
	]

	var regular_season := _text(game_payload.get("phase"), "").to_lower() == "regular_season"
	simulation_button.disabled = not regular_season
	_reset_simulate_arm()
	_render_readiness()
	_render_rotation_summary()

	var last_game = game_payload.get("last_game", null)
	if typeof(last_game) == TYPE_DICTIONARY:
		_render_postgame(last_game)
	else:
		_reset_postgame()

	_set_status("LIVE V3 GAME DAY • PRODUCTION SIMULATION READY • V2 RELEASE CHECKPOINT PROTECTED", GOOD)


func _render_readiness() -> void:
	_render_readiness_metrics()
	var unavailable := _array(game_payload.get("unavailable_players"))
	var availability_lines := []
	if typeof(game_payload.get("unavailable_players", null)) != TYPE_ARRAY:
		availability_lines.append("AVAILABILITY • Data unavailable for this refresh.")
	elif unavailable.is_empty():
		availability_lines.append("AVAILABILITY • Full roster available for the current matchup.")
	else:
		availability_lines.append("AVAILABILITY • %d player(s) unavailable or limited" % unavailable.size())
		for raw in unavailable.slice(0, 6):
			var row := _dict(raw)
			var line := "%s • %s" % [
				_text(row.get("name"), "Unknown"),
				_text(row.get("status"), "unavailable").replace("_", " ").capitalize()
			]
			var injury_type := _text(row.get("injury_type"), "")
			var games := _int_value(row.get("games_remaining"), 0)
			if injury_type != "":
				line += " • %s" % injury_type
			if games > 0:
				line += " • %d game(s)" % games
			availability_lines.append(line)
	availability_label.text = "\n".join(availability_lines)
	availability_label.add_theme_color_override("font_color", MUTED if typeof(game_payload.get("unavailable_players", null)) != TYPE_ARRAY else (GOOD if unavailable.is_empty() else BAD))

	var alerts := _array(game_payload.get("coaching_alerts"))
	var alert_lines := []
	if typeof(game_payload.get("coaching_alerts", null)) != TYPE_ARRAY:
		alert_lines.append("COACHING ALERTS • Data unavailable for this refresh.")
	elif alerts.is_empty():
		alert_lines.append("COACHING ALERTS • No production game-plan alerts are active.")
	else:
		alert_lines.append("COACHING ALERTS • %d active" % alerts.size())
		for raw in alerts.slice(0, 6):
			var row := _dict(raw)
			var title := _text(row.get("title"), "Game-plan alert")
			var detail := _text(row.get("detail"), "")
			var severity := _text(row.get("severity"), "").to_upper()
			var line := "%s%s" % [severity + " • " if severity != "" else "", title]
			if detail != "":
				line += " • %s" % detail
			alert_lines.append(line)
	alerts_label.text = "\n".join(alert_lines)
	alerts_label.add_theme_color_override("font_color", MUTED if alerts.is_empty() else GOLD)

	var sync := _dict(game_payload.get("league_sync"))
	if sync.is_empty():
		sync_label.text = "League calendar sync metadata is unavailable for this refresh."
	else:
		sync_label.text = "Production league-calendar synchronization metadata loaded for this decision point."


func _render_rotation_summary() -> void:
	if rotation_summary_label == null:
		return
	var rotation := _dict(game_payload.get("rotation"))
	if rotation.is_empty():
		rotation_summary_label.text = "No active rotation snapshot is available."
		return

	var starters := _array(rotation.get("starter_ids"))
	var rotation_ids := _array(rotation.get("rotation_player_ids"))
	var minutes := _dict(rotation.get("minutes_targets"))
	var player_names := _roster_name_map()
	var lines := []
	lines.append("%d rotation players • %.0f target minutes" % [
		rotation_ids.size(),
		_float_value(rotation.get("total_minutes"), 0.0)
	])
	for player_id_value in rotation_ids.slice(0, 10):
		var player_id := str(player_id_value)
		var name := _text(player_names.get(player_id), player_id)
		var marker := "START" if player_id in starters else "BENCH"
		lines.append("%s • %s • %.0f min" % [marker, name, _float_value(minutes.get(player_id), 0.0)])
	rotation_summary_label.text = "\n".join(lines)


func _roster_name_map() -> Dictionary:
	var result := {}
	for raw in _array(roster_payload.get("players")):
		var row := _dict(raw)
		var player_id := _text(row.get("player_id"), "")
		if player_id != "":
			result[player_id] = _text(row.get("name"), player_id)
	return result


func _render_rotation_editor() -> void:
	_clear_children(rotation_rows_box)
	rotation_entries.clear()
	rotation_order.clear()
	rotation_validated_body = ""

	var players := _array(roster_payload.get("players"))
	if players.is_empty():
		rotation_feedback.text = "No roster rows are available."
		rotation_feedback.add_theme_color_override("font_color", BAD)
		rotation_preview_button.disabled = true
		rotation_apply_button.disabled = true
		return

	for raw in players:
		var player := _dict(raw)
		if not player.is_empty():
			rotation_rows_box.add_child(_rotation_row(player))
	_update_rotation_validation()


func _rotation_row(player: Dictionary) -> Control:
	var panel := PanelContainer.new()
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	panel.add_theme_stylebox_override("panel", _box(PANEL_ALT, 7, BORDER))

	var margin := MarginContainer.new()
	_set_margins(margin, 9, 6, 9, 6)
	panel.add_child(margin)

	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 6)
	margin.add_child(row)

	var player_id := _text(player.get("player_id"), "")
	rotation_order.append(player_id)
	row.add_child(_cell(_text(player.get("name"), "Unknown"), 210, TEXT))
	row.add_child(_cell(_text(player.get("position"), ""), 54, MUTED, HORIZONTAL_ALIGNMENT_CENTER))

	var health := _dict(player.get("health"))
	var health_status := _text(health.get("status"), "unknown")
	var health_color := GOOD if health_status in ["", "healthy", "unknown"] else BAD
	row.add_child(_cell(_text(health.get("display"), "Unknown"), 150, health_color))

	var starter_box := CheckBox.new()
	starter_box.custom_minimum_size = Vector2(64, 30)
	starter_box.button_pressed = bool(player.get("is_starter", false))
	starter_box.tooltip_text = "Starter"
	row.add_child(starter_box)

	var rotation_box := CheckBox.new()
	rotation_box.custom_minimum_size = Vector2(72, 30)
	rotation_box.button_pressed = bool(player.get("in_rotation", false))
	rotation_box.tooltip_text = "In rotation"
	row.add_child(rotation_box)

	var minutes_spin := SpinBox.new()
	minutes_spin.custom_minimum_size = Vector2(100, 30)
	minutes_spin.min_value = 0.0
	minutes_spin.max_value = 48.0
	minutes_spin.step = 1.0
	minutes_spin.value = _float_value(player.get("target_minutes"), 0.0)
	minutes_spin.editable = rotation_box.button_pressed
	minutes_spin.suffix = " min"
	row.add_child(minutes_spin)

	rotation_entries[player_id] = {
		"player": player,
		"starter": starter_box,
		"rotation": rotation_box,
		"minutes": minutes_spin,
	}

	starter_box.toggled.connect(_on_starter_toggled.bind(player_id))
	rotation_box.toggled.connect(_on_rotation_member_toggled.bind(player_id))
	minutes_spin.value_changed.connect(_on_minutes_changed.bind(player_id))
	return panel


func _on_starter_toggled(pressed: bool, player_id: String) -> void:
	if rotation_syncing:
		return
	var entry = rotation_entries.get(player_id, {})
	if entry.is_empty():
		return
	if pressed and not entry["rotation"].button_pressed:
		rotation_syncing = true
		entry["rotation"].button_pressed = true
		entry["minutes"].editable = true
		rotation_syncing = false
	_rotation_dirty()


func _on_rotation_member_toggled(pressed: bool, player_id: String) -> void:
	if rotation_syncing:
		return
	var entry = rotation_entries.get(player_id, {})
	if entry.is_empty():
		return
	rotation_syncing = true
	entry["minutes"].editable = pressed
	if not pressed:
		entry["starter"].button_pressed = false
		entry["minutes"].value = 0.0
	rotation_syncing = false
	_rotation_dirty()


func _on_minutes_changed(_value: float, _player_id: String) -> void:
	if rotation_syncing:
		return
	_rotation_dirty()


func _rotation_dirty() -> void:
	rotation_validated_body = ""
	rotation_apply_button.disabled = true
	_update_rotation_validation()


func _rotation_rows_payload() -> Array:
	var rows := []
	for player_id in rotation_order:
		var entry = rotation_entries.get(player_id, {})
		if entry.is_empty():
			continue
		rows.append({
			"player_id": player_id,
			"starter": bool(entry["starter"].button_pressed),
			"in_rotation": bool(entry["rotation"].button_pressed),
			"minutes": float(entry["minutes"].value),
		})
	return rows


func _rotation_body_json() -> String:
	return JSON.stringify({"rows": _rotation_rows_payload()})


func _rotation_local_validation() -> Dictionary:
	var rules := _dict(roster_payload.get("rotation_rules"))
	var required_starters := _int_value(rules.get("required_starters"), 5)
	var minimum_players := _int_value(rules.get("minimum_game_players"), 8)
	var maximum_players := _int_value(rules.get("maximum_rotation_players"), 15)
	var required_minutes := _float_value(rules.get("required_total_minutes"), 240.0)
	var maximum_minutes := _float_value(rules.get("maximum_player_minutes"), 48.0)

	var starters := 0
	var rotation_players := 0
	var total_minutes := 0.0
	var bad_minutes := false
	var unavailable_names := []

	for player_id in rotation_order:
		var entry = rotation_entries.get(player_id, {})
		if entry.is_empty():
			continue
		var is_starter := bool(entry["starter"].button_pressed)
		var in_rotation := bool(entry["rotation"].button_pressed)
		var minutes := float(entry["minutes"].value)
		var player := _dict(entry["player"])
		if is_starter:
			starters += 1
		if in_rotation:
			rotation_players += 1
			total_minutes += minutes
			if minutes <= 0.0 or minutes > maximum_minutes:
				bad_minutes = true
			var health := _dict(player.get("health"))
			var health_status := _text(health.get("status"), "unknown")
			if health_status not in ["", "healthy", "unknown"]:
				unavailable_names.append(_text(player.get("name"), player_id))

	var issues := []
	if starters != required_starters:
		issues.append("Need exactly %d starters" % required_starters)
	if rotation_players < minimum_players or rotation_players > maximum_players:
		issues.append("Rotation must contain %d-%d players" % [minimum_players, maximum_players])
	if bad_minutes:
		issues.append("Every rotation player needs 1-%d minutes" % int(maximum_minutes))
	if abs(total_minutes - required_minutes) > 0.1:
		issues.append("Minutes must total %.0f" % required_minutes)
	if not unavailable_names.is_empty():
		issues.append("Unavailable: %s" % ", ".join(unavailable_names))

	return {
		"valid": issues.is_empty(),
		"issues": issues,
		"starters": starters,
		"rotation_players": rotation_players,
		"total_minutes": total_minutes,
		"required_minutes": required_minutes,
	}


func _update_rotation_validation() -> void:
	if rotation_entries.is_empty():
		rotation_preview_button.disabled = true
		rotation_apply_button.disabled = true
		return
	var check := _rotation_local_validation()
	var total := _float_value(check.get("total_minutes"), 0.0)
	var required := _float_value(check.get("required_minutes"), 240.0)
	var valid := bool(check.get("valid", false))
	rotation_total_label.text = "%.0f / %.0f MIN" % [total, required]
	rotation_total_label.add_theme_color_override("font_color", GOOD if abs(total - required) <= 0.1 else BAD)
	if valid:
		rotation_feedback.text = "%d starters • %d rotation players • Ready for production preview validation." % [
			_int_value(check.get("starters"), 0),
			_int_value(check.get("rotation_players"), 0)
		]
		rotation_feedback.add_theme_color_override("font_color", GOOD)
	else:
		rotation_feedback.text = " • ".join(_array(check.get("issues")))
		rotation_feedback.add_theme_color_override("font_color", BAD)
	rotation_preview_button.disabled = not valid
	rotation_apply_button.disabled = rotation_validated_body == "" or rotation_validated_body != _rotation_body_json()


func _on_rotation_preview_pressed() -> void:
	_send_rotation_request("preview")


func _on_rotation_apply_pressed() -> void:
	var body := _rotation_body_json()
	if rotation_validated_body == "" or rotation_validated_body != body:
		rotation_feedback.text = "Preview validation is required again before Apply."
		rotation_feedback.add_theme_color_override("font_color", BAD)
		rotation_apply_button.disabled = true
		return
	_send_rotation_request("apply")


func _send_rotation_request(mode: String) -> void:
	if rotation_request == null or rotation_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	var check := _rotation_local_validation()
	if not bool(check.get("valid", false)):
		_update_rotation_validation()
		return

	var body := _rotation_body_json()
	rotation_request_mode = mode
	rotation_pending_body = body
	rotation_preview_button.disabled = true
	rotation_apply_button.disabled = true
	rotation_feedback.text = "Production rotation preview is running..." if mode == "preview" else "Applying validated game plan to the isolated V3 working save..."
	rotation_feedback.add_theme_color_override("font_color", ACCENT)

	var url := ROTATION_PREVIEW_URL if mode == "preview" else ROTATION_APPLY_URL
	var headers := PackedStringArray(["Content-Type: application/json"])
	var error := rotation_request.request(url, headers, HTTPClient.METHOD_POST, body)
	if error != OK:
		rotation_feedback.text = "Rotation request could not start (error %s)." % error
		rotation_feedback.add_theme_color_override("font_color", BAD)
		rotation_validated_body = ""
		_update_rotation_validation()


func _on_rotation_request_completed(
	result: int,
	response_code: int,
	_headers: PackedStringArray,
	body: PackedByteArray
) -> void:
	if result != HTTPRequest.RESULT_SUCCESS:
		rotation_feedback.text = "Rotation request failed before the bridge responded."
		rotation_feedback.add_theme_color_override("font_color", BAD)
		rotation_validated_body = ""
		_update_rotation_validation()
		return

	var parsed = JSON.parse_string(body.get_string_from_utf8())
	if typeof(parsed) != TYPE_DICTIONARY:
		rotation_feedback.text = "Rotation endpoint returned invalid data."
		rotation_feedback.add_theme_color_override("font_color", BAD)
		rotation_validated_body = ""
		_update_rotation_validation()
		return

	if response_code != 200:
		rotation_feedback.text = _text(parsed.get("detail"), _text(parsed.get("error"), "Rotation validation failed."))
		rotation_feedback.add_theme_color_override("font_color", BAD)
		rotation_validated_body = ""
		_update_rotation_validation()
		return

	if rotation_request_mode == "preview":
		if _text(parsed.get("status"), "") == "valid":
			rotation_validated_body = rotation_pending_body
			rotation_feedback.text = "ENGINE PREVIEW PASSED • Apply Game Plan is now enabled."
			rotation_feedback.add_theme_color_override("font_color", GOOD)
			rotation_preview_button.disabled = false
			rotation_apply_button.disabled = false
		else:
			rotation_validated_body = ""
			rotation_feedback.text = "Production rotation preview did not validate."
			rotation_feedback.add_theme_color_override("font_color", BAD)
			_update_rotation_validation()
	elif rotation_request_mode == "apply":
		var applied := _text(parsed.get("status"), "") == "applied"
		var persisted := bool(parsed.get("persisted_after_reload", false))
		var v2_unchanged := bool(parsed.get("active_v2_unchanged", false))
		if applied and persisted and v2_unchanged:
			rotation_feedback.text = "GAME PLAN SAVED • Reload verified • Protected V2 unchanged."
			rotation_feedback.add_theme_color_override("font_color", GOOD)
			rotation_validated_body = ""
			_request_roster()
			_request_game_day()
		else:
			rotation_feedback.text = "Rotation write did not pass persistence and V2 safety verification."
			rotation_feedback.add_theme_color_override("font_color", BAD)
			rotation_validated_body = ""
			_update_rotation_validation()


func _on_simulate_pressed() -> void:
	if simulate_request == null or simulate_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	if simulation_button.disabled:
		return
	if not simulate_armed:
		simulate_armed = true
		simulation_button.text = "CONFIRM & SIMULATE"
		_set_status("SIMULATION ARMED • Click CONFIRM & SIMULATE to commit exactly one controlled-team game to the V3 working save.", GOLD)
		return
	_execute_simulation()


func _execute_simulation() -> void:
	if not _begin_long_action(
		"game_day_simulation",
		"SIMULATING GAME",
		"Running the production game simulation and synchronizing the league calendar...",
		[
			"Preparing the controlled-team matchup...",
			"Running the production game simulation engine...",
			"Synchronizing CPU games, standings, statistics, and awards...",
			"Saving and reloading the isolated V3 checkpoint...",
			"Verifying the durable result and protected V2 checkpoint...",
		]
	):
		_set_status("ANOTHER FRANCHISE ACTION IS ALREADY RUNNING", GOLD)
		return
	simulate_armed = false
	simulation_button.disabled = true
	simulation_button.text = "SIMULATING..."
	_set_status("SIMULATING • Production engine, CPU calendar catch-up, V3 save/reload verification, and V2 protection checks are running...", ACCENT)
	var error := simulate_request.request(
		GAME_DAY_SIMULATE_URL,
		PackedStringArray(),
		HTTPClient.METHOD_POST,
		""
	)
	if error != OK:
		_finish_long_action("game_day_simulation", false, "Simulation request could not start.")
		_set_status("SIMULATION REQUEST COULD NOT START • error %s" % error, BAD)
		_reset_simulate_arm()


func _on_simulate_request_completed(
	result: int,
	response_code: int,
	_headers: PackedStringArray,
	body: PackedByteArray
) -> void:
	_finish_long_action(
		"game_day_simulation",
		result == HTTPRequest.RESULT_SUCCESS and response_code == 200,
		"Game simulation completed." if result == HTTPRequest.RESULT_SUCCESS and response_code == 200 else "Game simulation ended with an error."
	)
	if result != HTTPRequest.RESULT_SUCCESS:
		_set_status("SIMULATION REQUEST FAILED BEFORE THE PYTHON ENGINE RESPONDED", BAD)
		_reset_simulate_arm()
		return

	var parsed = JSON.parse_string(body.get_string_from_utf8())
	if typeof(parsed) != TYPE_DICTIONARY:
		_set_status("SIMULATION ENDPOINT RETURNED INVALID DATA", BAD)
		_reset_simulate_arm()
		return

	if response_code != 200:
		_set_status("SIMULATION REJECTED • %s" % _text(parsed.get("detail"), _text(parsed.get("error"), "Unknown error")), BAD)
		_reset_simulate_arm()
		return

	var applied := _text(parsed.get("status"), "") == "applied"
	var persisted := bool(parsed.get("persisted_after_reload", false))
	var v2_unchanged := bool(parsed.get("active_v2_unchanged", false))
	if not applied or not persisted or not v2_unchanged:
		_set_status("SIMULATION SAFETY VERIFICATION FAILED • Result was not accepted by the Game Day Center.", BAD)
		_reset_simulate_arm()
		return

	var game := _dict(parsed.get("game"))
	if not game.is_empty():
		_render_postgame(game)

	var after_record := _dict(parsed.get("after_record"))
	var result_code := _text(parsed.get("result"), "FINAL")
	var cpu_games := _int_value(parsed.get("cpu_games_synchronized"), 0)
	_set_status("%s • GAME COMMITTED • Record %s • %d CPU game(s) synchronized • Reload verified • V2 unchanged" % [
		result_code,
		_text(after_record.get("display"), "N/A"),
		cpu_games
	], GOOD if result_code == "W" else GOLD)

	_request_game_day()
	_request_roster()


func _reset_simulate_arm() -> void:
	simulate_armed = false
	if simulation_button != null:
		simulation_button.text = "SIMULATE GAME"
		var next_game = game_payload.get("next_game", null)
		var can_simulate := (
			typeof(next_game) == TYPE_DICTIONARY
			and _text(game_payload.get("phase"), "").to_lower() == "regular_season"
		)
		if simulate_request != null and simulate_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
			can_simulate = false
		simulation_button.disabled = not can_simulate


func _render_postgame(game: Dictionary) -> void:
	var home_team := _text(game.get("home_team"), "HOME").to_upper()
	var away_team := _text(game.get("away_team"), "AWAY").to_upper()
	var home_name := _text(game.get("home_team_name"), home_team)
	var away_name := _text(game.get("away_team_name"), away_team)
	var home_score := _int_value(game.get("home_score"), 0)
	var away_score := _int_value(game.get("away_score"), 0)
	var day_index := _int_value(game.get("day_index"), 0)
	var overtime := _int_value(game.get("overtime_periods"), 0)

	var controlled_team := active_team
	if controlled_team == "":
		controlled_team = home_team
	var controlled_score := home_score if controlled_team == home_team else away_score
	var opponent_score := away_score if controlled_team == home_team else home_score
	var result_code := "WIN" if controlled_score > opponent_score else "LOSS"
	var result_color := GOOD if controlled_score > opponent_score else BAD
	if controlled_score == opponent_score:
		result_code = "TIED RESULT"
		result_color = MUTED
	postgame_result_label.text = "POSTGAME REVIEW • " + result_code
	postgame_result_label.add_theme_color_override("font_color", result_color)

	postgame_title_label.text = "%d   —   %d" % [home_score, away_score]
	postgame_title_label.add_theme_color_override("font_color", TEXT)
	if postgame_home_logo != null:
		postgame_home_logo.configure(home_team)
	if postgame_away_logo != null:
		postgame_away_logo.configure(away_team)
	if postgame_home_team_label != null:
		postgame_home_team_label.text = home_name.to_upper()
	if postgame_away_team_label != null:
		postgame_away_team_label.text = away_name.to_upper()
	var meta_bits := ["FINAL", "DAY %d" % day_index]
	if overtime > 0:
		meta_bits.append("%d OT" % overtime)
	postgame_meta_label.text = " • ".join(meta_bits)

	var active_box_team := controlled_team
	var opponent_box_team := away_team if controlled_team == home_team else home_team
	var active_box_name := home_name if controlled_team == home_team else away_name
	var opponent_box_name := away_name if controlled_team == home_team else home_name
	var active_box_score := home_score if controlled_team == home_team else away_score
	var opponent_box_score := away_score if controlled_team == home_team else home_score

	_render_team_box_score(postgame_active_box, game, active_box_team, active_box_name, active_box_score, postgame_team_color)
	_render_team_box_score(postgame_opponent_box, game, opponent_box_team, opponent_box_name, opponent_box_score, MUTED)
	_animate_postgame_reveal()


func _render_team_box_score(
	container: VBoxContainer,
	game: Dictionary,
	team: String,
	team_name: String,
	score: int,
	title_color: Color
) -> void:
	_clear_children(container)

	var score_header := HBoxContainer.new()
	score_header.name = "BroadcastTeamBoxHeader_" + team.to_upper()
	score_header.add_theme_constant_override("separation", 9)
	container.add_child(score_header)

	var logo := TeamLogoV3.new()
	logo.custom_minimum_size = Vector2(70, 62)
	logo.configure(team)
	score_header.add_child(logo)

	var team_copy := VBoxContainer.new()
	team_copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	team_copy.alignment = BoxContainer.ALIGNMENT_CENTER
	team_copy.add_theme_constant_override("separation", 2)
	score_header.add_child(team_copy)

	var team_title := _label(team_name.to_upper(), 14, title_color)
	team_title.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	team_copy.add_child(team_title)
	team_copy.add_child(_label(team.to_upper() + " • FINAL", 9, MUTED))

	var score_label := _label(str(score), 34, TEXT)
	score_label.custom_minimum_size = Vector2(62, 0)
	score_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	score_label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	score_header.add_child(score_label)

	var team_rows: Array = []
	for raw in _array(game.get("player_box_scores")):
		var line := _dict(raw)
		if _text(line.get("team"), "").to_upper() == team.to_upper():
			team_rows.append(line)

	var totals := _label("TEAM TOTALS • REB %s • AST %s • TO %s" % [
		_box_total(team_rows, "rebounds"), _box_total(team_rows, "assists"), _box_total(team_rows, "turnovers")], 10, MUTED)
	totals.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	container.add_child(totals)

	var shooting := _label("SHOOTING • FG %s/%s • 3PT %s/%s" % [
		_box_total(team_rows, "field_goals_made"), _box_total(team_rows, "field_goals_attempted"),
		_box_total(team_rows, "three_pointers_made"), _box_total(team_rows, "three_pointers_attempted")], 10, MUTED)
	shooting.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	container.add_child(shooting)

	var leader := _label(_scoring_leader(team_rows), 11, GOLD)
	leader.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	container.add_child(leader)

	var header := HBoxContainer.new()
	header.add_theme_constant_override("separation", 2)
	header.add_child(_box_cell("PLAYER", 126, MUTED))
	header.add_child(_box_cell("MIN", 30, MUTED, HORIZONTAL_ALIGNMENT_CENTER))
	header.add_child(_box_cell("PTS", 30, MUTED, HORIZONTAL_ALIGNMENT_CENTER))
	header.add_child(_box_cell("REB", 30, MUTED, HORIZONTAL_ALIGNMENT_CENTER))
	header.add_child(_box_cell("AST", 30, MUTED, HORIZONTAL_ALIGNMENT_CENTER))
	header.add_child(_box_cell("STL", 28, MUTED, HORIZONTAL_ALIGNMENT_CENTER))
	header.add_child(_box_cell("BLK", 28, MUTED, HORIZONTAL_ALIGNMENT_CENTER))
	header.add_child(_box_cell("TO", 28, MUTED, HORIZONTAL_ALIGNMENT_CENTER))
	header.add_child(_box_cell("FG", 50, MUTED, HORIZONTAL_ALIGNMENT_CENTER))
	header.add_child(_box_cell("3PT", 50, MUTED, HORIZONTAL_ALIGNMENT_CENTER))
	container.add_child(header)

	var rows := _array(game.get("player_box_scores"))
	var emitted := 0
	for raw in rows:
		var line := _dict(raw)
		if _text(line.get("team"), "").to_upper() != team.to_upper():
			continue
		var row := HBoxContainer.new()
		row.add_theme_constant_override("separation", 2)
		var player_name := _text(line.get("name"), "Unknown")
		if bool(line.get("starter", false)):
			player_name = "• " + player_name
		var name_cell := _box_cell(player_name, 126, TEXT)
		name_cell.tooltip_text = player_name
		row.add_child(name_cell)
		row.add_child(_box_cell("%.0f" % _float_value(line.get("minutes"), 0.0), 30, TEXT, HORIZONTAL_ALIGNMENT_CENTER))
		row.add_child(_box_cell(str(_int_value(line.get("points"), 0)), 30, TEXT, HORIZONTAL_ALIGNMENT_CENTER))
		row.add_child(_box_cell(str(_int_value(line.get("rebounds"), 0)), 30, TEXT, HORIZONTAL_ALIGNMENT_CENTER))
		row.add_child(_box_cell(str(_int_value(line.get("assists"), 0)), 30, TEXT, HORIZONTAL_ALIGNMENT_CENTER))
		row.add_child(_box_cell(str(_int_value(line.get("steals"), 0)), 28, TEXT, HORIZONTAL_ALIGNMENT_CENTER))
		row.add_child(_box_cell(str(_int_value(line.get("blocks"), 0)), 28, TEXT, HORIZONTAL_ALIGNMENT_CENTER))
		row.add_child(_box_cell(str(_int_value(line.get("turnovers"), 0)), 28, TEXT, HORIZONTAL_ALIGNMENT_CENTER))
		row.add_child(_box_cell("%d/%d" % [
			_int_value(line.get("field_goals_made"), 0),
			_int_value(line.get("field_goals_attempted"), 0)
		], 50, TEXT, HORIZONTAL_ALIGNMENT_CENTER))
		row.add_child(_box_cell("%d/%d" % [
			_int_value(line.get("three_pointers_made"), 0),
			_int_value(line.get("three_pointers_attempted"), 0)
		], 50, TEXT, HORIZONTAL_ALIGNMENT_CENTER))
		container.add_child(row)
		emitted += 1

	if emitted == 0:
		container.add_child(_label("No player box-score rows are available for %s." % team, 10, MUTED))


func _animate_postgame_reveal() -> void:
	if postgame_scoreboard_panel == null or postgame_title_label == null:
		return

	postgame_scoreboard_panel.modulate = Color(1, 1, 1, 0.34)
	postgame_title_label.pivot_offset = postgame_title_label.size * 0.5
	postgame_title_label.scale = Vector2(0.975, 0.975)

	var tween := create_tween()
	tween.set_parallel(true)
	tween.set_trans(Tween.TRANS_QUAD)
	tween.set_ease(Tween.EASE_OUT)
	tween.tween_property(
		postgame_scoreboard_panel,
		"modulate:a",
		1.0,
		DesignSystemV3.MOTION_NORMAL
	)
	tween.tween_property(
		postgame_title_label,
		"scale",
		Vector2.ONE,
		DesignSystemV3.MOTION_NORMAL
	)


func _reset_postgame() -> void:
	postgame_result_label.text = "POSTGAME REVIEW"
	postgame_result_label.add_theme_color_override("font_color", MUTED)
	postgame_title_label.text = "--   —   --"
	postgame_title_label.add_theme_color_override("font_color", TEXT)
	if postgame_home_logo != null:
		postgame_home_logo.configure("")
	if postgame_away_logo != null:
		postgame_away_logo.configure("")
	if postgame_home_team_label != null:
		postgame_home_team_label.text = "HOME"
	if postgame_away_team_label != null:
		postgame_away_team_label.text = "AWAY"
	postgame_meta_label.text = "Full player box scores will appear here after a completed controlled-team game."
	_render_empty_box_score(postgame_active_box, "YOUR TEAM")
	_render_empty_box_score(postgame_opponent_box, "OPPONENT")


func _box_total(rows: Array, key: String) -> String:
	if rows.is_empty():
		return "N/A"
	var total := 0.0
	for line in rows:
		var value = line.get(key)
		if typeof(value) != TYPE_INT and typeof(value) != TYPE_FLOAT:
			return "N/A"
		total += float(value)
	return "%.0f" % total


func _scoring_leader(rows: Array) -> String:
	var names: Array = []
	var highest := -1
	for line in rows:
		var points = line.get("points")
		if typeof(points) != TYPE_INT and typeof(points) != TYPE_FLOAT:
			return "SCORING LEADER • N/A"
		if int(points) > highest:
			highest = int(points)
			names.clear()
		if int(points) == highest:
			names.append(_text(line.get("name"), "Unknown"))
	if names.is_empty():
		return "SCORING LEADER • N/A"
	return "SCORING LEADER • %s • %d PTS" % [" / ".join(names), highest]


func _render_empty_box_score(container: VBoxContainer, title: String) -> void:
	_clear_children(container)
	container.add_child(_label(title, 15, MUTED))
	container.add_child(_label("No completed game loaded.", 10, MUTED))


func _set_status(text_value: String, color: Color) -> void:
	if status_label == null:
		return
	status_label.text = text_value
	status_label.add_theme_color_override("font_color", color)


func _label(text_value: String, font_size: int, color: Color) -> Label:
	var label := Label.new()
	label.text = text_value
	label.add_theme_font_size_override("font_size", font_size)
	label.add_theme_color_override("font_color", color)
	return label


func _section_title(text_value: String) -> Label:
	return _label(text_value, 16, TEXT)


func _button(text_value: String, primary: bool = false) -> Button:
	var button := Button.new()
	button.text = text_value
	if primary:
		primary_buttons.append(button)
	button.custom_minimum_size = Vector2(140, 38)
	button.add_theme_font_size_override("font_size", 10)
	button.add_theme_color_override("font_color", TEXT)
	button.add_theme_color_override("font_hover_color", TEXT)
	var normal_color := TEAM_PRIMARY if primary else PANEL_ALT
	var hover_color := TEAM_PRIMARY_HOVER if primary else PANEL_HOVER
	button.add_theme_stylebox_override("normal", _box(normal_color, 9, normal_color if primary else BORDER))
	button.add_theme_stylebox_override("hover", _box(hover_color, 9, hover_color if primary else ACCENT))
	button.add_theme_stylebox_override("pressed", _box(hover_color, 9, hover_color))
	button.add_theme_stylebox_override("disabled", _box(Color("101722"), 9, SOFT_BORDER))
	return button


func _cell(
	text_value: String,
	width: int,
	color: Color,
	alignment: int = HORIZONTAL_ALIGNMENT_LEFT
) -> Label:
	var label := _label(text_value, 10, color)
	label.custom_minimum_size = Vector2(width, 28)
	label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	label.horizontal_alignment = alignment
	label.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	return label


func _box_cell(
	text_value: String,
	width: int,
	color: Color,
	alignment: int = HORIZONTAL_ALIGNMENT_LEFT
) -> Label:
	var label := _label(text_value, 9, color)
	label.custom_minimum_size = Vector2(width, 23)
	label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	label.horizontal_alignment = alignment
	label.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	return label


func _card(minimum: Vector2) -> PanelContainer:
	var card := PanelContainer.new()
	card.custom_minimum_size = minimum
	card.add_theme_stylebox_override("panel", _box(PANEL, 14, BORDER))
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


func _clear_children(container: Node) -> void:
	for child in container.get_children():
		container.remove_child(child)
		child.queue_free()


func _dict(value) -> Dictionary:
	if typeof(value) == TYPE_DICTIONARY:
		return value
	return {}


func _array(value) -> Array:
	if typeof(value) == TYPE_ARRAY:
		return value
	return []


func _text(value, fallback: String = "") -> String:
	if value == null:
		return fallback
	var result := str(value)
	return fallback if result in ["", "None", "null"] else result


func _int_value(value, fallback: int = 0) -> int:
	if value == null:
		return fallback
	if typeof(value) == TYPE_INT:
		return int(value)
	if typeof(value) == TYPE_FLOAT:
		return int(value)
	var raw := str(value).strip_edges()
	return fallback if raw == "" or not raw.is_valid_int() else raw.to_int()


func _float_value(value, fallback: float = 0.0) -> float:
	if value == null:
		return fallback
	if typeof(value) == TYPE_INT or typeof(value) == TYPE_FLOAT:
		return float(value)
	var raw := str(value).strip_edges()
	return fallback if raw == "" or not raw.is_valid_float() else raw.to_float()
