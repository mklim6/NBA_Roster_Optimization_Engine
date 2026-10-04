extends Control

# Batch 22 franchise presentation macro

const DesignSystemV3 = preload("res://scripts/design_system_v3.gd")
const TeamBrandingV3 = preload("res://scripts/team_branding_v3.gd")
const PageIdentityV3 = preload("res://scripts/page_identity_v3.gd")

const SUMMARY_URL := "http://127.0.0.1:8765/v3/scouting-draft"
const SCOUT_PREVIEW_URL := "http://127.0.0.1:8765/v3/scouting/preview"
const SCOUT_EXECUTE_URL := "http://127.0.0.1:8765/v3/scouting/advance"
const DRAFT_PREVIEW_URL := "http://127.0.0.1:8765/v3/draft/selection/preview"
const DRAFT_EXECUTE_URL := "http://127.0.0.1:8765/v3/draft/selection/execute"
const DRAFT_ADVANCE_PREVIEW_URL := "http://127.0.0.1:8765/v3/draft/advance/preview"
const DRAFT_ADVANCE_EXECUTE_URL := "http://127.0.0.1:8765/v3/draft/advance/execute"
const ROSTER_CUT_PREVIEW_URL := "http://127.0.0.1:8765/v3/draft/roster-cut/preview"
const ROSTER_CUT_EXECUTE_URL := "http://127.0.0.1:8765/v3/draft/roster-cut/execute"

const PANEL := DesignSystemV3.PANEL
const PANEL_ALT := DesignSystemV3.PANEL_ALT
const PANEL_HOVER := DesignSystemV3.PANEL_HOVER
const TEXT := DesignSystemV3.TEXT
const MUTED := DesignSystemV3.MUTED
const ACCENT := DesignSystemV3.ACCENT
const GOOD := DesignSystemV3.GOOD
const BAD := DesignSystemV3.BAD
const BORDER := DesignSystemV3.BORDER
const TEAM_PRIMARY := DesignSystemV3.TEAM_PRIMARY
const TEAM_PRIMARY_HOVER := DesignSystemV3.TEAM_PRIMARY_HOVER
const GOLD := DesignSystemV3.GOLD

var page_identity: Control
var page_brand_bar: ColorRect

var brand_heading: Label
var board_count: Label
var brand_color := TEAM_PRIMARY
var primary_buttons: Array = []
var board_available := false

var summary_request: HTTPRequest
var scout_preview_request: HTTPRequest
var scout_execute_request: HTTPRequest
var draft_preview_request: HTTPRequest
var draft_execute_request: HTTPRequest
var draft_advance_preview_request: HTTPRequest
var draft_advance_execute_request: HTTPRequest
var roster_cut_preview_request: HTTPRequest
var roster_cut_execute_request: HTTPRequest

var status_label: Label
var draft_phase_value: Label
var scouting_week_value: Label
var scout_value: Label
var confidence_value: Label
var search_box: LineEdit
var board_rows: VBoxContainer
var focus_label: Label
var scouting_preview_label: Label
var preview_week_button: Button
var advance_week_button: Button
var draft_status_label: Label
var selected_prospect_label: Label
var preview_pick_button: Button
var make_pick_button: Button
var preview_cpu_picks_button: Button
var advance_cpu_picks_button: Button
var roster_cut_status_label: Label
var roster_cut_selector: OptionButton
var preview_roster_cut_button: Button
var commit_roster_cut_button: Button
var scout_dialog: ConfirmationDialog
var draft_dialog: ConfirmationDialog
var cpu_draft_dialog: ConfirmationDialog
var roster_cut_dialog: ConfirmationDialog

var page_payload: Dictionary = {}
var prospects: Array = []
var focus_selected: Dictionary = {}
var selected_prospect: Dictionary = {}
var scouting_execution_enabled := false
var draft_execution_enabled := false
var draft_cpu_advance_enabled := false
var latest_scout_fingerprint := ""
var latest_scout_working_sha := ""
var latest_scout_focus_ids: Array = []
var latest_draft_fingerprint := ""
var latest_draft_working_sha := ""
var latest_draft_prospect_id := ""
var latest_cpu_draft_fingerprint := ""
var latest_cpu_draft_working_sha := ""
var latest_cpu_draft_pick_count := 0
var latest_cpu_draft_completes_draft := false
var post_draft_roster_cut_enabled := false
var latest_roster_cut_fingerprint := ""
var latest_roster_cut_working_sha := ""
var latest_roster_cut_player_id := ""
var latest_roster_cut_player_name := ""
var latest_roster_cut_remaining_after := 0
var scout_execute_in_flight := false
var draft_execute_in_flight := false
var draft_advance_execute_in_flight := false
var roster_cut_execute_in_flight := false


var long_action_manager = null


func apply_team_brand(_team: String, primary: Color, _secondary: Color) -> void:
	if page_identity != null:
		page_identity.configure(_team, primary, _secondary)
	if page_brand_bar != null:
		page_brand_bar.color = primary
	brand_color = primary
	if brand_heading != null:
		brand_heading.add_theme_color_override("font_color", primary.lerp(Color.WHITE, 0.45))
	for button in primary_buttons:
		TeamBrandingV3.apply_primary_button(button, primary)
	if board_rows != null:
		_render_board()


func _dict(value: Variant) -> Dictionary:
	return value if typeof(value) == TYPE_DICTIONARY else {}


func _array(value: Variant) -> Array:
	return value if typeof(value) == TYPE_ARRAY else []


func _display(value: Variant, fallback: String = "N/A") -> String:
	return fallback if value == null or str(value).strip_edges() == "" else str(value)


func _number(value: Variant, fallback: float = 0.0) -> float:
	return float(value) if typeof(value) in [TYPE_INT, TYPE_FLOAT] else fallback


func _confidence_text(value: Variant) -> String:
	return "%.0f%%" % float(value) if typeof(value) in [TYPE_INT, TYPE_FLOAT] else "N/A"


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
	_build_ui()
	_build_http()


func refresh() -> void:
	_request_summary()


func _build_http() -> void:
	summary_request = HTTPRequest.new()
	summary_request.timeout = 30.0
	summary_request.request_completed.connect(_on_summary_completed)
	add_child(summary_request)

	scout_preview_request = HTTPRequest.new()
	scout_preview_request.timeout = 30.0
	scout_preview_request.request_completed.connect(_on_scout_preview_completed)
	add_child(scout_preview_request)

	scout_execute_request = HTTPRequest.new()
	scout_execute_request.timeout = 90.0
	scout_execute_request.request_completed.connect(_on_scout_execute_completed)
	add_child(scout_execute_request)

	draft_preview_request = HTTPRequest.new()
	draft_preview_request.timeout = 30.0
	draft_preview_request.request_completed.connect(_on_draft_preview_completed)
	add_child(draft_preview_request)

	draft_execute_request = HTTPRequest.new()
	draft_execute_request.timeout = 90.0
	draft_execute_request.request_completed.connect(_on_draft_execute_completed)
	add_child(draft_execute_request)

	draft_advance_preview_request = HTTPRequest.new()
	draft_advance_preview_request.timeout = 90.0
	draft_advance_preview_request.request_completed.connect(_on_draft_advance_preview_completed)
	add_child(draft_advance_preview_request)

	draft_advance_execute_request = HTTPRequest.new()
	draft_advance_execute_request.timeout = 120.0
	draft_advance_execute_request.request_completed.connect(_on_draft_advance_execute_completed)
	add_child(draft_advance_execute_request)

	roster_cut_preview_request = HTTPRequest.new()
	roster_cut_preview_request.timeout = 60.0
	roster_cut_preview_request.request_completed.connect(_on_roster_cut_preview_completed)
	add_child(roster_cut_preview_request)

	roster_cut_execute_request = HTTPRequest.new()
	roster_cut_execute_request.timeout = 120.0
	roster_cut_execute_request.request_completed.connect(_on_roster_cut_execute_completed)
	add_child(roster_cut_execute_request)


func _build_ui() -> void:
	var page_scroll := ScrollContainer.new()
	page_scroll.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	page_scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	page_scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	page_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	add_child(page_scroll)

	var outer := MarginContainer.new()
	outer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_set_margins(outer, 28, 24, 28, 28)
	page_scroll.add_child(outer)

	var column := VBoxContainer.new()
	column.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	column.add_theme_constant_override("separation", 16)
	outer.add_child(column)

	var header := HBoxContainer.new()
	header.add_theme_constant_override("separation", 12)
	column.add_child(header)

	page_brand_bar = ColorRect.new()
	page_brand_bar.custom_minimum_size = Vector2(0, 4)
	page_brand_bar.color = TEAM_PRIMARY
	page_brand_bar.mouse_filter = Control.MOUSE_FILTER_IGNORE
	column.add_child(page_brand_bar)

	var titles := VBoxContainer.new()
	titles.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	header.add_child(titles)
	brand_heading = _small_label("FRANCHISE OPERATIONS • TALENT PIPELINE", TEAM_PRIMARY_HOVER)
	titles.add_child(brand_heading)
	var title := Label.new()
	title.text = "SCOUTING & DRAFT"
	title.add_theme_color_override("font_color", TEXT)
	title.add_theme_font_size_override("font_size", 36)
	titles.add_child(title)
	var subtitle := Label.new()
	subtitle.text = "Production scouting reports, priority assignments, and phase-safe Draft execution."
	subtitle.add_theme_color_override("font_color", MUTED)
	subtitle.add_theme_font_size_override("font_size", 12)
	titles.add_child(subtitle)

	page_identity = PageIdentityV3.new()
	header.add_child(page_identity)

	var refresh_button := _action_button("REFRESH BOARD", false)
	refresh_button.pressed.connect(_request_summary)
	header.add_child(refresh_button)

	var safety := _card(Vector2(0, 58))
	var safety_body := _card_body(safety, 12)
	status_label = Label.new()
	status_label.text = "Open Scouting to load the V3 draft class."
	status_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	status_label.add_theme_color_override("font_color", MUTED)
	status_label.add_theme_font_size_override("font_size", 11)
	safety_body.add_child(status_label)
	column.add_child(safety)

	var metrics := HBoxContainer.new()
	metrics.add_theme_constant_override("separation", 10)
	column.add_child(metrics)
	draft_phase_value = _metric(metrics, "DRAFT PHASE", "LOADING")
	scouting_week_value = _metric(metrics, "SCOUTING WEEK", "LOADING")
	scout_value = _metric(metrics, "LEAD SCOUT", "LOADING")
	confidence_value = _metric(metrics, "AVG CONFIDENCE", "LOADING")

	var content := HBoxContainer.new()
	content.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	content.add_theme_constant_override("separation", 14)
	column.add_child(content)

	var board_card := _card(Vector2(0, 650))
	board_card.add_theme_stylebox_override("panel", _box(PANEL, 16, Color(ACCENT, 0.44)))
	board_card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var board_body := _card_body(board_card, 16)
	var board_header := HBoxContainer.new()
	board_header.add_child(_section_title("DRAFT BOARD"))
	var spacer := Control.new()
	spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	board_header.add_child(spacer)
	board_header.add_child(_pill("SCOUTING-ONLY RATINGS", ACCENT))
	board_body.add_child(board_header)

	search_box = LineEdit.new()
	search_box.placeholder_text = "Search prospect, position, school, archetype..."
	search_box.text_changed.connect(_on_search_changed)
	board_body.add_child(search_box)

	board_count = _small_label("Board data unavailable", MUTED)
	board_body.add_child(board_count)

	var board_header_row := HBoxContainer.new()
	board_header_row.add_theme_constant_override("separation", 8)
	board_header_row.add_child(_column_label("FOCUS", 42))
	board_header_row.add_child(_column_label("RK", 28))
	var prospect_header := _column_label("PROSPECT", 150)
	prospect_header.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	board_header_row.add_child(prospect_header)
	board_header_row.add_child(_column_label("POS", 32))
	board_header_row.add_child(_column_label("OVR", 40))
	board_header_row.add_child(_column_label("POT", 40))
	board_header_row.add_child(_column_label("CONF", 42))
	board_header_row.add_child(_column_label("PROJECTED", 65))
	board_header_row.add_child(_column_label("DRAFT", 58))
	board_body.add_child(board_header_row)

	var board_scroll := ScrollContainer.new()
	board_scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	board_scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	board_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	board_body.add_child(board_scroll)
	board_rows = VBoxContainer.new()
	board_rows.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	board_rows.add_theme_constant_override("separation", 4)
	board_scroll.add_child(board_rows)
	content.add_child(board_card)

	var actions := VBoxContainer.new()
	actions.custom_minimum_size = Vector2(320, 0)
	actions.add_theme_constant_override("separation", 14)
	content.add_child(actions)

	var scout_card := _card(Vector2(320, 315))
	scout_card.add_theme_stylebox_override("panel", _box(PANEL, 16, Color(GOLD, 0.48)))
	var scout_body := _card_body(scout_card, 16)
	scout_body.add_child(_small_label("WEEKLY INTELLIGENCE CYCLE", GOLD))
	scout_body.add_child(_section_title("SCOUTING OPERATIONS"))
	focus_label = Label.new()
	focus_label.text = "Select up to 6 priority prospects from the board."
	focus_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	focus_label.add_theme_color_override("font_color", TEXT)
	focus_label.add_theme_font_size_override("font_size", 11)
	scout_body.add_child(focus_label)

	var scout_buttons := HBoxContainer.new()
	scout_buttons.add_theme_constant_override("separation", 8)
	preview_week_button = _action_button("PREVIEW WEEK", false)
	preview_week_button.pressed.connect(_preview_scouting_week)
	scout_buttons.add_child(preview_week_button)
	advance_week_button = _action_button("ADVANCE WEEK", true)
	advance_week_button.disabled = true
	advance_week_button.pressed.connect(_confirm_scouting_week)
	scout_buttons.add_child(advance_week_button)
	scout_body.add_child(scout_buttons)

	scouting_preview_label = Label.new()
	scouting_preview_label.text = "Preview the week before committing scouting progress."
	scouting_preview_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	scouting_preview_label.add_theme_color_override("font_color", MUTED)
	scouting_preview_label.add_theme_font_size_override("font_size", 10)
	scouting_preview_label.custom_minimum_size = Vector2(0, 115)
	scout_body.add_child(scouting_preview_label)
	actions.add_child(scout_card)

	var draft_card := _card(Vector2(320, 390))
	draft_card.add_theme_stylebox_override("panel", _box(PANEL, 16, Color(ACCENT, 0.54)))
	var draft_body := _card_body(draft_card, 16)
	draft_body.add_child(_small_label("PHASE-LOCKED TRANSACTION", ACCENT))
	draft_body.add_child(_section_title("DRAFT NIGHT DESK"))
	draft_status_label = Label.new()
	draft_status_label.text = "Draft state loading..."
	draft_status_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	draft_status_label.add_theme_color_override("font_color", MUTED)
	draft_status_label.add_theme_font_size_override("font_size", 10)
	draft_body.add_child(draft_status_label)
	selected_prospect_label = Label.new()
	selected_prospect_label.text = "Select a prospect from the board."
	selected_prospect_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	selected_prospect_label.add_theme_color_override("font_color", TEXT)
	selected_prospect_label.add_theme_font_size_override("font_size", 11)
	draft_body.add_child(selected_prospect_label)

	var draft_buttons := HBoxContainer.new()
	draft_buttons.add_theme_constant_override("separation", 8)
	preview_pick_button = _action_button("PREVIEW PICK", false)
	preview_pick_button.disabled = true
	preview_pick_button.pressed.connect(_preview_draft_pick)
	draft_buttons.add_child(preview_pick_button)
	make_pick_button = _action_button("MAKE SELECTION", true)
	make_pick_button.disabled = true
	make_pick_button.pressed.connect(_confirm_draft_pick)
	draft_buttons.add_child(make_pick_button)
	draft_body.add_child(draft_buttons)

	var cpu_draft_buttons := HBoxContainer.new()
	cpu_draft_buttons.add_theme_constant_override("separation", 8)
	preview_cpu_picks_button = _action_button("PREVIEW CPU PICKS", false)
	preview_cpu_picks_button.disabled = true
	preview_cpu_picks_button.pressed.connect(_preview_cpu_draft_picks)
	cpu_draft_buttons.add_child(preview_cpu_picks_button)
	advance_cpu_picks_button = _action_button("ADVANCE CPU PICKS", true)
	advance_cpu_picks_button.disabled = true
	advance_cpu_picks_button.pressed.connect(_confirm_cpu_draft_advance)
	cpu_draft_buttons.add_child(advance_cpu_picks_button)
	draft_body.add_child(cpu_draft_buttons)
	actions.add_child(draft_card)


	var roster_cut_card := _card(Vector2(320, 315))
	var roster_cut_body := _card_body(roster_cut_card, 16)
	roster_cut_body.add_child(_small_label("POST-DRAFT ROSTER GATE", GOLD))
	roster_cut_body.add_child(_section_title("ROSTER DECISIONS"))
	roster_cut_status_label = Label.new()
	roster_cut_status_label.text = "Post-Draft roster decisions unlock after the Draft is complete."
	roster_cut_status_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	roster_cut_status_label.add_theme_color_override("font_color", MUTED)
	roster_cut_status_label.add_theme_font_size_override("font_size", 10)
	roster_cut_body.add_child(roster_cut_status_label)

	roster_cut_selector = OptionButton.new()
	roster_cut_selector.disabled = true
	roster_cut_selector.item_selected.connect(_on_roster_cut_selection_changed)
	roster_cut_body.add_child(roster_cut_selector)

	var roster_cut_buttons := HBoxContainer.new()
	roster_cut_buttons.add_theme_constant_override("separation", 8)
	preview_roster_cut_button = _action_button("PREVIEW ROSTER CUT", false)
	preview_roster_cut_button.disabled = true
	preview_roster_cut_button.pressed.connect(_preview_roster_cut)
	roster_cut_buttons.add_child(preview_roster_cut_button)
	commit_roster_cut_button = _action_button("RELEASE PLAYER", true)
	commit_roster_cut_button.disabled = true
	commit_roster_cut_button.pressed.connect(_confirm_roster_cut)
	roster_cut_buttons.add_child(commit_roster_cut_button)
	roster_cut_body.add_child(roster_cut_buttons)
	actions.add_child(roster_cut_card)

	scout_dialog = ConfirmationDialog.new()
	scout_dialog.title = "Confirm scouting week"
	scout_dialog.confirmed.connect(_execute_scouting_week)
	add_child(scout_dialog)

	draft_dialog = ConfirmationDialog.new()
	draft_dialog.title = "Confirm Draft selection"
	draft_dialog.confirmed.connect(_execute_draft_pick)
	add_child(draft_dialog)

	cpu_draft_dialog = ConfirmationDialog.new()
	cpu_draft_dialog.title = "Confirm CPU Draft advancement"
	cpu_draft_dialog.confirmed.connect(_execute_cpu_draft_advance)
	add_child(cpu_draft_dialog)

	roster_cut_dialog = ConfirmationDialog.new()
	roster_cut_dialog.title = "Confirm post-Draft roster release"
	roster_cut_dialog.confirmed.connect(_execute_roster_cut)
	add_child(roster_cut_dialog)


func _request_summary() -> void:
	if summary_request == null:
		return
	if summary_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	_invalidate_scout_preview()
	_invalidate_draft_preview()
	_invalidate_draft_advance_preview()
	_invalidate_roster_cut_preview()
	status_label.text = "Loading production scouting reports and Draft state from the isolated V3 save..."
	status_label.add_theme_color_override("font_color", ACCENT)
	var error: int = summary_request.request(SUMMARY_URL)
	if error != OK:
		status_label.text = "Could not start the Scouting & Draft request."
		status_label.add_theme_color_override("font_color", BAD)


func _on_summary_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	var raw_payload = JSON.parse_string(body.get_string_from_utf8())
	if result != HTTPRequest.RESULT_SUCCESS or response_code != 200 or typeof(raw_payload) != TYPE_DICTIONARY:
		status_label.text = "Scouting & Draft data is unavailable. Make sure the Python bridge is online."
		status_label.add_theme_color_override("font_color", BAD)
		return
	if raw_payload.has("error"):
		status_label.text = str(raw_payload.get("detail", raw_payload.get("error", "Scouting request failed.")))
		status_label.add_theme_color_override("font_color", BAD)
		return
	if not bool(raw_payload.get("working_save_unchanged", false)) or not bool(raw_payload.get("active_v2_unchanged", false)):
		status_label.text = "SAFETY FAILURE • read-only scouting load changed a protected checkpoint."
		status_label.add_theme_color_override("font_color", BAD)
		return
	page_payload = raw_payload
	board_available = typeof(raw_payload.get("board")) == TYPE_ARRAY
	prospects = _array(raw_payload.get("board"))
	focus_selected.clear()
	var summary: Dictionary = _dict(raw_payload.get("summary"))
	var saved_focus: Array = _array(summary.get("focus_ids"))
	for raw_id in saved_focus:
		focus_selected[str(raw_id)] = true
	_apply_summary()
	_render_board()


func _apply_summary() -> void:
	var draft: Dictionary = _dict(page_payload.get("draft"))
	var summary: Dictionary = _dict(page_payload.get("summary"))
	var scout: Dictionary = _dict(page_payload.get("lead_scout"))
	var phase: String = _display(draft.get("phase"), "unavailable")
	draft_phase_value.text = phase.replace("_", " ").to_upper()
	var weeks_done: int = int(_number(summary.get("weeks_completed")))
	var weeks_remaining: int = int(_number(summary.get("weeks_remaining")))
	scouting_week_value.text = "%s / %s" % [str(weeks_done), str(weeks_done + weeks_remaining)] if summary.get("weeks_completed") != null and summary.get("weeks_remaining") != null else "N/A"
	scout_value.text = _display(scout.get("name"))
	confidence_value.text = _confidence_text(summary.get("average_confidence"))
	scouting_execution_enabled = bool(page_payload.get("scouting_execution_enabled", false)) and weeks_remaining > 0
	draft_execution_enabled = bool(page_payload.get("draft_execution_enabled", false))
	draft_cpu_advance_enabled = bool(page_payload.get("draft_cpu_advance_enabled", false))
	preview_week_button.disabled = not scouting_execution_enabled
	_update_draft_controls()
	_update_focus_label()
	_apply_post_draft_roster(page_payload.get("post_draft_roster", {}))

	var draft_year: int = int(draft.get("draft_year", 0))
	var source_label: String = str(draft.get("source_season", ""))
	status_label.text = "LIVE V3 • %s Draft • %s • Preview before advancing scouting or Draft actions" % [
		str(draft_year), source_label]
	status_label.add_theme_color_override("font_color", GOOD)

	var pick: Dictionary = _dict(draft.get("current_pick"))
	if phase == "draft_in_progress" and not pick.is_empty():
		var owner: String = str(pick.get("owner_team", ""))
		var overall_pick: int = int(pick.get("overall_pick", 0))
		var round_number: int = int(pick.get("round", 0))
		var round_pick: int = int(pick.get("round_pick", 0))
		draft_status_label.text = "ON THE CLOCK • Pick #%s • Round %s, Pick %s • %s\n%s" % [
			str(overall_pick), str(round_number), str(round_pick), owner,
			"Your franchise may select now." if draft_execution_enabled else "CPU-owned pick. Preview CPU PICKS to simulate safely to your next pick or Draft completion."
		]
		draft_status_label.add_theme_color_override("font_color", GOOD if draft_execution_enabled else GOLD)
	elif phase == "draft_complete":
		var roster_gate: Dictionary = _dict(page_payload.get("post_draft_roster"))
		var cuts_remaining: int = int(roster_gate.get("cuts_remaining", 0))
		if cuts_remaining > 0:
			draft_status_label.text = "DRAFT COMPLETE • %s post-Draft roster decision(s) remain. Use ROSTER DECISIONS below before opening the next season." % str(cuts_remaining)
			draft_status_label.add_theme_color_override("font_color", GOLD)
		else:
			draft_status_label.text = "DRAFT COMPLETE • Post-Draft roster gate cleared. Return to SEASON → OPEN NEXT SEASON."
			draft_status_label.add_theme_color_override("font_color", GOOD)
	else:
		draft_status_label.text = "Draft selection is locked during %s. Scouting remains available through its production phase rules." % phase.replace("_", " ").capitalize()
		draft_status_label.add_theme_color_override("font_color", MUTED)


func _render_board() -> void:
	_clear_children(board_rows)
	if not board_available:
		board_count.text = "Board data unavailable"
		board_rows.add_child(_small_label("Refresh to load the scouting board.", MUTED))
		return
	var query: String = search_box.text.strip_edges().to_lower()
	var matches: Array = []
	var total := 0
	for raw_row in prospects:
		if typeof(raw_row) != TYPE_DICTIONARY:
			continue
		total += 1
		var row: Dictionary = raw_row
		var haystack: String = "%s %s %s %s" % [
			_display(row.get("Prospect")), _display(row.get("Pos")),
			_display(row.get("School / Club")), _display(row.get("Archetype"))]
		if query == "" or query in haystack.to_lower():
			matches.append(row)
	var displayed := mini(50, matches.size())
	board_count.text = "Showing %d of %d matches" % [displayed, matches.size()] if matches.size() > 50 or query != "" else "Showing %d of %d prospects" % [displayed, total]
	for row in matches.slice(0, displayed):
		board_rows.add_child(_prospect_row(row))
	if displayed == 0:
		board_rows.add_child(_small_label("No prospects are available on this board." if total == 0 else "No prospects match the current search.", MUTED))


func _prospect_row(row: Dictionary) -> Control:
	var panel := PanelContainer.new()
	var is_selected: bool = not selected_prospect.is_empty() and row.get("prospect_id") != null and row.get("prospect_id") == selected_prospect.get("prospect_id")
	panel.add_theme_stylebox_override("panel", _box(PANEL_ALT, 8, brand_color if is_selected else BORDER))
	var margin := MarginContainer.new()
	_set_margins(margin, 8, 7, 8, 7)
	panel.add_child(margin)
	var line := HBoxContainer.new()
	line.add_theme_constant_override("separation", 8)
	margin.add_child(line)
	var prospect_id: String = str(row.get("prospect_id", ""))

	var focus := CheckBox.new()
	focus.custom_minimum_size = Vector2(42, 0)
	focus.button_pressed = focus_selected.has(prospect_id)
	focus.disabled = not scouting_execution_enabled
	focus.toggled.connect(_on_focus_toggled.bind(prospect_id))
	line.add_child(focus)
	line.add_child(_cell(_display(row.get("Rank")), 28, MUTED))
	var name := _cell(_display(row.get("Prospect"), prospect_id), 150, TEXT)
	name.tooltip_text = name.text
	name.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	line.add_child(name)
	line.add_child(_cell(_display(row.get("Pos")), 32, ACCENT))
	line.add_child(_cell(_rating_text(row.get("Scouted OVR")), 40, TEXT))
	line.add_child(_cell(_rating_text(row.get("Scouted POT")), 40, GOOD))
	line.add_child(_cell(_confidence_text(row.get("Confidence")), 42, MUTED))
	line.add_child(_cell(_display(row.get("Projected")), 65, MUTED))
	var select_button := _mini_button("SELECT")
	select_button.custom_minimum_size = Vector2(58, 30)
	select_button.disabled = bool(row.get("Drafted", false))
	select_button.pressed.connect(_select_prospect.bind(row.duplicate(true)))
	line.add_child(select_button)
	return panel


func _on_search_changed(_value: String) -> void:
	_render_board()


func _on_focus_toggled(pressed: bool, prospect_id: String) -> void:
	if pressed:
		if focus_selected.size() >= 6 and not focus_selected.has(prospect_id):
			status_label.text = "Scouting focus is limited to 6 prospects. Remove one before adding another."
			status_label.add_theme_color_override("font_color", GOLD)
			_render_board()
			return
		focus_selected[prospect_id] = true
	else:
		focus_selected.erase(prospect_id)
	_invalidate_scout_preview()
	_update_focus_label()


func _update_focus_label() -> void:
	var names: Array = []
	for raw_row in prospects:
		if typeof(raw_row) == TYPE_DICTIONARY:
			var row: Dictionary = raw_row
			if focus_selected.has(str(row.get("prospect_id", ""))):
				names.append(str(row.get("Prospect", row.get("prospect_id", ""))))
	focus_label.text = "Priority targets %s/6\n%s" % [
		str(focus_selected.size()),
		", ".join(names) if names.size() > 0 else "No priority prospects selected."
	]


func _focus_ids() -> Array:
	var result: Array = focus_selected.keys()
	result.sort()
	return result


func _preview_scouting_week() -> void:
	if not scouting_execution_enabled or scout_preview_request == null:
		return
	if scout_preview_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	_invalidate_scout_preview()
	var body: Dictionary = {"focus_ids": _focus_ids()}
	scouting_preview_label.text = "Building an in-memory production scouting candidate. No save will be written..."
	scouting_preview_label.add_theme_color_override("font_color", ACCENT)
	var headers := PackedStringArray(["Content-Type: application/json"])
	var error: int = scout_preview_request.request(SCOUT_PREVIEW_URL, headers, HTTPClient.METHOD_POST, JSON.stringify(body))
	if error != OK:
		scouting_preview_label.text = "Could not start scouting preview."
		scouting_preview_label.add_theme_color_override("font_color", BAD)


func _on_scout_preview_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	var raw_payload = JSON.parse_string(body.get_string_from_utf8())
	if result != HTTPRequest.RESULT_SUCCESS or typeof(raw_payload) != TYPE_DICTIONARY:
		scouting_preview_label.text = "Scouting preview failed before a valid bridge response was received."
		scouting_preview_label.add_theme_color_override("font_color", BAD)
		return
	if response_code != 200:
		scouting_preview_label.text = str(raw_payload.get("detail", raw_payload.get("error", "Scouting preview failed.")))
		scouting_preview_label.add_theme_color_override("font_color", BAD)
		return
	if not bool(raw_payload.get("working_save_unchanged", false)) or not bool(raw_payload.get("active_v2_unchanged", false)):
		scouting_preview_label.text = "SAFETY FAILURE • preview changed a protected checkpoint."
		scouting_preview_label.add_theme_color_override("font_color", BAD)
		return
	var can_commit: bool = bool(raw_payload.get("can_commit", false))
	var status: String = str(raw_payload.get("status", "blocked"))
	var before: Dictionary = raw_payload.get("summary_before", {})
	var after: Dictionary = raw_payload.get("summary_after", {})
	scouting_preview_label.text = "STATUS %s • COMMITTABLE %s\nWeek %s → %s • Avg confidence %.0f%% → %.0f%%\n%s" % [
		status.to_upper(), "YES" if can_commit else "NO",
		str(before.get("weeks_completed", 0)), str(after.get("weeks_completed", 0)),
		float(before.get("average_confidence", 0.0)), float(after.get("average_confidence", 0.0)),
		str(raw_payload.get("reason", "Fresh scouting token locked to the current V3 working save."))
	]
	scouting_preview_label.add_theme_color_override("font_color", GOOD if can_commit else GOLD)
	var fingerprint: String = str(raw_payload.get("action_fingerprint", ""))
	var working_sha: String = str(raw_payload.get("working_save_sha256", ""))
	if can_commit and fingerprint != "" and working_sha != "":
		latest_scout_fingerprint = fingerprint
		latest_scout_working_sha = working_sha
		latest_scout_focus_ids = _focus_ids()
		advance_week_button.disabled = false


func _confirm_scouting_week() -> void:
	if scout_execute_in_flight or latest_scout_fingerprint == "" or latest_scout_working_sha == "":
		return
	scout_dialog.dialog_text = "Advance one production scouting week with %s priority prospect(s)?\n\nThis writes ONLY the isolated V3 working save. A recovery checkpoint is created first, the result is reloaded and verified, and protected V2 must remain unchanged." % str(latest_scout_focus_ids.size())
	scout_dialog.popup_centered(Vector2i(560, 300))


func _execute_scouting_week() -> void:
	if scout_execute_request == null or scout_execute_in_flight:
		return
	if scout_execute_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	if not _begin_long_action(
		"scouting_week_advance",
		"ADVANCING SCOUTING WEEK",
		"Running the certified scouting progression and persisting new discovery state...",
		[
			"Rechecking the certified preview and exact V3 working-save fingerprint...",
			"Running the production scouting/Draft engine...",
			"Applying roster, prospect, and Draft-state updates...",
			"Persisting and reloading the isolated V3 checkpoint...",
			"Verifying the durable result and protected V2 checkpoint...",
		]
	):
		scouting_preview_label.text = "Another franchise-changing action is already running."
		scouting_preview_label.add_theme_color_override("font_color", GOLD)
		return
	var request_payload: Dictionary = {
		"focus_ids": latest_scout_focus_ids.duplicate(),
		"expected_action_fingerprint": latest_scout_fingerprint,
		"expected_working_save_sha256": latest_scout_working_sha
	}
	scout_execute_in_flight = true
	advance_week_button.disabled = true
	preview_week_button.disabled = true
	scouting_preview_label.text = "Advancing the production scouting cycle, then reloading and verifying V3..."
	scouting_preview_label.add_theme_color_override("font_color", ACCENT)
	var headers := PackedStringArray(["Content-Type: application/json"])
	var error: int = scout_execute_request.request(SCOUT_EXECUTE_URL, headers, HTTPClient.METHOD_POST, JSON.stringify(request_payload))
	if error != OK:
		_finish_long_action("scouting_week_advance", false, "The request could not start.")
		scout_execute_in_flight = false
		preview_week_button.disabled = not scouting_execution_enabled
		scouting_preview_label.text = "Could not start scouting execution."
		scouting_preview_label.add_theme_color_override("font_color", BAD)


func _on_scout_execute_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	_finish_long_action(
		"scouting_week_advance",
		result == HTTPRequest.RESULT_SUCCESS and response_code == 200,
		"Action completed." if result == HTTPRequest.RESULT_SUCCESS and response_code == 200 else "Action ended with an error."
	)
	scout_execute_in_flight = false
	preview_week_button.disabled = not scouting_execution_enabled
	var raw_payload = JSON.parse_string(body.get_string_from_utf8())
	if result != HTTPRequest.RESULT_SUCCESS or typeof(raw_payload) != TYPE_DICTIONARY:
		scouting_preview_label.text = "Scouting execution failed before a valid bridge response was received."
		scouting_preview_label.add_theme_color_override("font_color", BAD)
		_invalidate_scout_preview()
		return
	if response_code != 200:
		var detail: String = str(raw_payload.get("detail", raw_payload.get("error", "Scouting execution failed.")))
		if bool(raw_payload.get("rollback_performed", false)):
			detail += "\nRollback: %s" % ("VERIFIED" if bool(raw_payload.get("rollback_verified", false)) else "REQUIRES REVIEW")
		if str(raw_payload.get("error", "")) == "stale_scouting_preview":
			detail += "\nRun PREVIEW WEEK again."
		scouting_preview_label.text = detail
		scouting_preview_label.add_theme_color_override("font_color", GOLD if response_code == 409 else BAD)
		_invalidate_scout_preview()
		return
	if not bool(raw_payload.get("persisted_after_reload", false)) or not bool(raw_payload.get("active_v2_unchanged", false)):
		scouting_preview_label.text = "SCOUTING SAFETY FAILURE • reload persistence or V2 protection was not confirmed."
		scouting_preview_label.add_theme_color_override("font_color", BAD)
		_invalidate_scout_preview()
		return
	var verification: Dictionary = raw_payload.get("verification", {})
	scouting_preview_label.text = "SCOUTING WEEK COMMITTED • Week %s\nPersisted after reload • protected V2 unchanged\nRecovery: %s" % [
		str(verification.get("weeks_after", "")), str(raw_payload.get("recovery_checkpoint_path", ""))
	]
	scouting_preview_label.add_theme_color_override("font_color", GOOD)
	_invalidate_scout_preview()
	_request_summary()


func _select_prospect(row: Dictionary) -> void:
	selected_prospect = row
	selected_prospect_label.text = "%s • %s • Scouted %s OVR / %s POT • %s confidence" % [
		_display(row.get("Prospect"), _display(row.get("prospect_id"))),
		_display(row.get("Pos")), _rating_text(row.get("Scouted OVR")),
		_rating_text(row.get("Scouted POT")), _confidence_text(row.get("Confidence"))]
	_invalidate_draft_preview()
	_update_draft_controls()
	_render_board()


func _update_draft_controls() -> void:
	preview_pick_button.disabled = not draft_execution_enabled or selected_prospect.is_empty() or draft_execute_in_flight or draft_advance_execute_in_flight
	preview_cpu_picks_button.disabled = not draft_cpu_advance_enabled or draft_execute_in_flight or draft_advance_execute_in_flight
	if latest_draft_fingerprint == "":
		make_pick_button.disabled = true
	if latest_cpu_draft_fingerprint == "":
		advance_cpu_picks_button.disabled = true


func _preview_draft_pick() -> void:
	if not draft_execution_enabled or selected_prospect.is_empty() or draft_preview_request == null:
		return
	if draft_preview_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	_invalidate_draft_preview()
	var body: Dictionary = {"prospect_id": str(selected_prospect.get("prospect_id", ""))}
	draft_status_label.text = "Building a read-only production Draft selection preview..."
	draft_status_label.add_theme_color_override("font_color", ACCENT)
	var headers := PackedStringArray(["Content-Type: application/json"])
	var error: int = draft_preview_request.request(DRAFT_PREVIEW_URL, headers, HTTPClient.METHOD_POST, JSON.stringify(body))
	if error != OK:
		draft_status_label.text = "Could not start Draft preview."
		draft_status_label.add_theme_color_override("font_color", BAD)


func _on_draft_preview_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	var raw_payload = JSON.parse_string(body.get_string_from_utf8())
	if result != HTTPRequest.RESULT_SUCCESS or typeof(raw_payload) != TYPE_DICTIONARY:
		draft_status_label.text = "Draft preview failed before a valid bridge response was received."
		draft_status_label.add_theme_color_override("font_color", BAD)
		return
	if response_code != 200:
		draft_status_label.text = str(raw_payload.get("detail", raw_payload.get("error", "Draft preview failed.")))
		draft_status_label.add_theme_color_override("font_color", BAD)
		return
	if not bool(raw_payload.get("working_save_unchanged", false)) or not bool(raw_payload.get("active_v2_unchanged", false)):
		draft_status_label.text = "SAFETY FAILURE • Draft preview changed a protected checkpoint."
		draft_status_label.add_theme_color_override("font_color", BAD)
		return
	var can_commit: bool = bool(raw_payload.get("can_commit", false))
	var pick: Dictionary = raw_payload.get("current_pick", {})
	draft_status_label.text = "STATUS %s • COMMITTABLE %s\nPick #%s • %s\n%s" % [
		str(raw_payload.get("status", "blocked")).to_upper(), "YES" if can_commit else "NO",
		str(pick.get("overall_pick", "")), str(raw_payload.get("prospect_name", "")),
		str(raw_payload.get("reason", "Fresh Draft token locked to the current V3 working save."))
	]
	draft_status_label.add_theme_color_override("font_color", GOOD if can_commit else GOLD)
	var fingerprint: String = str(raw_payload.get("action_fingerprint", ""))
	var working_sha: String = str(raw_payload.get("working_save_sha256", ""))
	if can_commit and fingerprint != "" and working_sha != "":
		latest_draft_fingerprint = fingerprint
		latest_draft_working_sha = working_sha
		latest_draft_prospect_id = str(raw_payload.get("prospect_id", ""))
		make_pick_button.disabled = false


func _confirm_draft_pick() -> void:
	if draft_execute_in_flight or latest_draft_fingerprint == "" or latest_draft_working_sha == "":
		return
	draft_dialog.dialog_text = "Draft %s with the active franchise's current pick?\n\nThis uses the production Draft engine, integrates the rookie, advances the pick index, writes ONLY V3, reloads and verifies the result, and protects V2." % str(selected_prospect.get("Prospect", latest_draft_prospect_id))
	draft_dialog.popup_centered(Vector2i(580, 315))


func _execute_draft_pick() -> void:
	if draft_execute_request == null or draft_execute_in_flight:
		return
	if draft_execute_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	if not _begin_long_action(
		"draft_selection",
		"MAKING DRAFT SELECTION",
		"Committing the user Draft selection through the production Draft engine...",
		[
			"Rechecking the certified preview and exact V3 working-save fingerprint...",
			"Running the production scouting/Draft engine...",
			"Applying roster, prospect, and Draft-state updates...",
			"Persisting and reloading the isolated V3 checkpoint...",
			"Verifying the durable result and protected V2 checkpoint...",
		]
	):
		draft_status_label.text = "Another franchise-changing action is already running."
		draft_status_label.add_theme_color_override("font_color", GOLD)
		return
	var request_payload: Dictionary = {
		"prospect_id": latest_draft_prospect_id,
		"expected_action_fingerprint": latest_draft_fingerprint,
		"expected_working_save_sha256": latest_draft_working_sha
	}
	draft_execute_in_flight = true
	make_pick_button.disabled = true
	preview_pick_button.disabled = true
	draft_status_label.text = "Executing production Draft selection, then verifying rookie integration and V2 protection..."
	draft_status_label.add_theme_color_override("font_color", ACCENT)
	var headers := PackedStringArray(["Content-Type: application/json"])
	var error: int = draft_execute_request.request(DRAFT_EXECUTE_URL, headers, HTTPClient.METHOD_POST, JSON.stringify(request_payload))
	if error != OK:
		_finish_long_action("draft_selection", false, "The request could not start.")
		draft_execute_in_flight = false
		_update_draft_controls()
		draft_status_label.text = "Could not start Draft execution."
		draft_status_label.add_theme_color_override("font_color", BAD)


func _on_draft_execute_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	_finish_long_action(
		"draft_selection",
		result == HTTPRequest.RESULT_SUCCESS and response_code == 200,
		"Action completed." if result == HTTPRequest.RESULT_SUCCESS and response_code == 200 else "Action ended with an error."
	)
	draft_execute_in_flight = false
	var raw_payload = JSON.parse_string(body.get_string_from_utf8())
	if result != HTTPRequest.RESULT_SUCCESS or typeof(raw_payload) != TYPE_DICTIONARY:
		draft_status_label.text = "Draft execution failed before a valid bridge response was received."
		draft_status_label.add_theme_color_override("font_color", BAD)
		_invalidate_draft_preview()
		return
	if response_code != 200:
		var detail: String = str(raw_payload.get("detail", raw_payload.get("error", "Draft execution failed.")))
		if bool(raw_payload.get("rollback_performed", false)):
			detail += "\nRollback: %s" % ("VERIFIED" if bool(raw_payload.get("rollback_verified", false)) else "REQUIRES REVIEW")
		if str(raw_payload.get("error", "")) == "stale_draft_preview":
			detail += "\nRun PREVIEW PICK again."
		draft_status_label.text = detail
		draft_status_label.add_theme_color_override("font_color", GOLD if response_code == 409 else BAD)
		_invalidate_draft_preview()
		_update_draft_controls()
		return
	if not bool(raw_payload.get("persisted_after_reload", false)) or not bool(raw_payload.get("active_v2_unchanged", false)):
		draft_status_label.text = "DRAFT SAFETY FAILURE • reload persistence or V2 protection was not confirmed."
		draft_status_label.add_theme_color_override("font_color", BAD)
		_invalidate_draft_preview()
		return
	var verification: Dictionary = raw_payload.get("verification", {})
	draft_status_label.text = "DRAFT PICK COMMITTED • #%s %s\nRookie integrated • persisted after reload • protected V2 unchanged" % [
		str(verification.get("overall_pick", "")), str(verification.get("prospect_name", verification.get("prospect_id", "")))
	]
	draft_status_label.add_theme_color_override("font_color", GOOD)
	selected_prospect = {}
	selected_prospect_label.text = "Select a prospect from the board."
	_invalidate_draft_preview()
	_request_summary()


func _preview_cpu_draft_picks() -> void:
	if not draft_cpu_advance_enabled or draft_advance_preview_request == null:
		return
	if draft_advance_preview_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	_invalidate_draft_advance_preview()
	draft_status_label.text = "Building a read-only CPU Draft candidate through your next pick or Draft completion..."
	draft_status_label.add_theme_color_override("font_color", ACCENT)
	var headers := PackedStringArray(["Content-Type: application/json"])
	var error: int = draft_advance_preview_request.request(DRAFT_ADVANCE_PREVIEW_URL, headers, HTTPClient.METHOD_POST, "{}")
	if error != OK:
		draft_status_label.text = "Could not start CPU Draft preview."
		draft_status_label.add_theme_color_override("font_color", BAD)


func _on_draft_advance_preview_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	var raw_payload = JSON.parse_string(body.get_string_from_utf8())
	if result != HTTPRequest.RESULT_SUCCESS or typeof(raw_payload) != TYPE_DICTIONARY:
		draft_status_label.text = "CPU Draft preview failed before a valid bridge response was received."
		draft_status_label.add_theme_color_override("font_color", BAD)
		return
	if response_code != 200:
		draft_status_label.text = str(raw_payload.get("detail", raw_payload.get("error", "CPU Draft preview failed.")))
		draft_status_label.add_theme_color_override("font_color", BAD)
		return
	if not bool(raw_payload.get("working_save_unchanged", false)) or not bool(raw_payload.get("active_v2_unchanged", false)):
		draft_status_label.text = "SAFETY FAILURE • CPU Draft preview changed a protected checkpoint."
		draft_status_label.add_theme_color_override("font_color", BAD)
		return
	var can_commit: bool = bool(raw_payload.get("can_commit", false))
	var pick_count: int = int(raw_payload.get("picks_simulated", 0))
	var draft_complete: bool = bool(raw_payload.get("draft_complete", false))
	var next_pick: Dictionary = raw_payload.get("next_pick", {})
	var destination: String = "Draft completion" if draft_complete else "Pick #%s • %s on the clock" % [
		str(next_pick.get("overall_pick", "")), str(next_pick.get("owner_team", ""))
	]
	draft_status_label.text = "CPU DRAFT PREVIEW • %s pick(s) • %s\n%s" % [
		str(pick_count), destination,
		str(raw_payload.get("reason", "No save written. Commit will reproduce this production-AI progression from the same V3 checkpoint."))
	]
	draft_status_label.add_theme_color_override("font_color", GOOD if can_commit else GOLD)
	var fingerprint: String = str(raw_payload.get("action_fingerprint", ""))
	var working_sha: String = str(raw_payload.get("working_save_sha256", ""))
	if can_commit and fingerprint != "" and working_sha != "":
		latest_cpu_draft_fingerprint = fingerprint
		latest_cpu_draft_working_sha = working_sha
		latest_cpu_draft_pick_count = pick_count
		latest_cpu_draft_completes_draft = draft_complete
		advance_cpu_picks_button.disabled = false


func _confirm_cpu_draft_advance() -> void:
	if draft_advance_execute_in_flight or latest_cpu_draft_fingerprint == "" or latest_cpu_draft_working_sha == "":
		return
	var destination := "finish the Draft" if latest_cpu_draft_completes_draft else "stop at your next controlled pick"
	cpu_draft_dialog.dialog_text = "Advance %s CPU-owned Draft pick(s) and %s?\n\nThe existing production Draft AI makes every CPU selection. Your controlled pick is never auto-selected. This writes ONLY V3, creates a recovery checkpoint, reloads and verifies every simulated pick, and protects V2." % [
		str(latest_cpu_draft_pick_count), destination
	]
	cpu_draft_dialog.popup_centered(Vector2i(600, 340))


func _execute_cpu_draft_advance() -> void:
	if draft_advance_execute_request == null or draft_advance_execute_in_flight:
		return
	if draft_advance_execute_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	if not _begin_long_action(
		"cpu_draft_advance",
		"ADVANCING CPU DRAFT PICKS",
		"Simulating CPU-owned selections until the next controlled pick or Draft completion...",
		[
			"Rechecking the certified preview and exact V3 working-save fingerprint...",
			"Running the production scouting/Draft engine...",
			"Applying roster, prospect, and Draft-state updates...",
			"Persisting and reloading the isolated V3 checkpoint...",
			"Verifying the durable result and protected V2 checkpoint...",
		]
	):
		draft_status_label.text = "Another franchise-changing action is already running."
		draft_status_label.add_theme_color_override("font_color", GOLD)
		return
	var request_payload: Dictionary = {
		"expected_action_fingerprint": latest_cpu_draft_fingerprint,
		"expected_working_save_sha256": latest_cpu_draft_working_sha
	}
	draft_advance_execute_in_flight = true
	advance_cpu_picks_button.disabled = true
	preview_cpu_picks_button.disabled = true
	preview_pick_button.disabled = true
	make_pick_button.disabled = true
	draft_status_label.text = "Advancing production CPU Draft picks, then reloading and verifying every committed selection..."
	draft_status_label.add_theme_color_override("font_color", ACCENT)
	var headers := PackedStringArray(["Content-Type: application/json"])
	var error: int = draft_advance_execute_request.request(DRAFT_ADVANCE_EXECUTE_URL, headers, HTTPClient.METHOD_POST, JSON.stringify(request_payload))
	if error != OK:
		_finish_long_action("cpu_draft_advance", false, "The request could not start.")
		draft_advance_execute_in_flight = false
		_update_draft_controls()
		draft_status_label.text = "Could not start CPU Draft advancement."
		draft_status_label.add_theme_color_override("font_color", BAD)


func _on_draft_advance_execute_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	_finish_long_action(
		"cpu_draft_advance",
		result == HTTPRequest.RESULT_SUCCESS and response_code == 200,
		"Action completed." if result == HTTPRequest.RESULT_SUCCESS and response_code == 200 else "Action ended with an error."
	)
	draft_advance_execute_in_flight = false
	var raw_payload = JSON.parse_string(body.get_string_from_utf8())
	if result != HTTPRequest.RESULT_SUCCESS or typeof(raw_payload) != TYPE_DICTIONARY:
		draft_status_label.text = "CPU Draft advancement failed before a valid bridge response was received."
		draft_status_label.add_theme_color_override("font_color", BAD)
		_invalidate_draft_advance_preview()
		_update_draft_controls()
		return
	if response_code != 200:
		var detail: String = str(raw_payload.get("detail", raw_payload.get("error", "CPU Draft advancement failed.")))
		if bool(raw_payload.get("rollback_performed", false)):
			detail += "\nRollback: %s" % ("VERIFIED" if bool(raw_payload.get("rollback_verified", false)) else "REQUIRES REVIEW")
		if str(raw_payload.get("error", "")) == "stale_draft_advance_preview":
			detail += "\nRun PREVIEW CPU PICKS again."
		draft_status_label.text = detail
		draft_status_label.add_theme_color_override("font_color", GOLD if response_code == 409 else BAD)
		_invalidate_draft_advance_preview()
		_update_draft_controls()
		return
	if not bool(raw_payload.get("persisted_after_reload", false)) or not bool(raw_payload.get("active_v2_unchanged", false)):
		draft_status_label.text = "CPU DRAFT SAFETY FAILURE • reload persistence or V2 protection was not confirmed."
		draft_status_label.add_theme_color_override("font_color", BAD)
		_invalidate_draft_advance_preview()
		return
	var verification: Dictionary = raw_payload.get("verification", {})
	var completed: bool = bool(verification.get("draft_complete", false))
	var next_pick: Dictionary = verification.get("next_pick", {})
	var destination := "DRAFT COMPLETE • Continue from SEASON → OPEN NEXT SEASON." if completed else "NEXT USER PICK • #%s • %s" % [
		str(next_pick.get("overall_pick", "")), str(next_pick.get("owner_team", ""))
	]
	draft_status_label.text = "CPU DRAFT ADVANCE COMMITTED • %s pick(s)\n%s\nPersisted after reload • protected V2 unchanged" % [
		str(verification.get("picks_simulated", raw_payload.get("picks_simulated", 0))), destination
	]
	draft_status_label.add_theme_color_override("font_color", GOOD)
	_invalidate_draft_advance_preview()
	_invalidate_draft_preview()
	_request_summary()



func _apply_post_draft_roster(raw_payload) -> void:
	_invalidate_roster_cut_preview()
	var payload: Dictionary = raw_payload if typeof(raw_payload) == TYPE_DICTIONARY else {}
	var cuts_remaining: int = int(payload.get("cuts_remaining", 0))
	var roster_count: int = int(payload.get("roster_count", 0))
	var standard_count: int = int(payload.get("standard_contract_count", 0))
	var target_roster: int = int(payload.get("target_roster_size", 21))
	var target_standard: int = int(payload.get("target_standard_contract_count", 15))
	post_draft_roster_cut_enabled = bool(payload.get("enabled", false)) and cuts_remaining > 0

	roster_cut_selector.clear()
	var candidates: Array = payload.get("candidates", [])
	for raw_row in candidates:
		if typeof(raw_row) != TYPE_DICTIONARY:
			continue
		var row: Dictionary = raw_row
		if not bool(row.get("can_release", false)):
			continue
		var label := "%s • %s • %s OVR • %s" % [
			str(row.get("name", row.get("player_id", ""))),
			str(row.get("position", "")),
			_rating_text(row.get("overall")),
			_money_text(row.get("salary"))
		]
		roster_cut_selector.add_item(label)
		var index := roster_cut_selector.item_count - 1
		roster_cut_selector.set_item_metadata(index, str(row.get("player_id", "")))

	if cuts_remaining <= 0 and str(payload.get("status", "")) == "roster_cleared_for_next_season":
		roster_cut_status_label.text = "ROSTER CLEARED • %s players / %s standard contracts. Return to SEASON → OPEN NEXT SEASON." % [
			str(roster_count), str(standard_count)
		]
		roster_cut_status_label.add_theme_color_override("font_color", GOOD)
	elif cuts_remaining > 0:
		roster_cut_status_label.text = "%s RELEASE(S) REQUIRED • %s/%s roster • %s/%s standard contracts\nChoose the player you want to release. Every cut is previewed with its certified financial treatment before V3 is written." % [
			str(cuts_remaining), str(roster_count), str(target_roster),
			str(standard_count), str(target_standard)
		]
		roster_cut_status_label.add_theme_color_override("font_color", GOLD)
	else:
		roster_cut_status_label.text = "Post-Draft roster decisions unlock after the Draft is complete."
		roster_cut_status_label.add_theme_color_override("font_color", MUTED)

	roster_cut_selector.disabled = not post_draft_roster_cut_enabled or roster_cut_selector.item_count == 0
	preview_roster_cut_button.disabled = roster_cut_selector.disabled
	if roster_cut_selector.item_count > 0:
		roster_cut_selector.select(0)


func _selected_roster_cut_player_id() -> String:
	if roster_cut_selector == null or roster_cut_selector.item_count == 0:
		return ""
	var index := roster_cut_selector.selected
	if index < 0 or index >= roster_cut_selector.item_count:
		return ""
	return str(roster_cut_selector.get_item_metadata(index))


func _on_roster_cut_selection_changed(_index: int) -> void:
	_invalidate_roster_cut_preview()
	preview_roster_cut_button.disabled = not post_draft_roster_cut_enabled or _selected_roster_cut_player_id().is_empty()


func _preview_roster_cut() -> void:
	if not post_draft_roster_cut_enabled or roster_cut_preview_request == null:
		return
	if roster_cut_preview_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	var player_id := _selected_roster_cut_player_id()
	if player_id.is_empty():
		return
	_invalidate_roster_cut_preview()
	roster_cut_status_label.text = "Building a read-only post-Draft roster-release candidate..."
	roster_cut_status_label.add_theme_color_override("font_color", ACCENT)
	var headers := PackedStringArray(["Content-Type: application/json"])
	var error: int = roster_cut_preview_request.request(
		ROSTER_CUT_PREVIEW_URL,
		headers,
		HTTPClient.METHOD_POST,
		JSON.stringify({"player_id": player_id})
	)
	if error != OK:
		roster_cut_status_label.text = "Could not start post-Draft roster-cut preview."
		roster_cut_status_label.add_theme_color_override("font_color", BAD)


func _on_roster_cut_preview_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	var raw_payload = JSON.parse_string(body.get_string_from_utf8())
	if result != HTTPRequest.RESULT_SUCCESS or typeof(raw_payload) != TYPE_DICTIONARY:
		roster_cut_status_label.text = "Roster-cut preview failed before a valid bridge response was received."
		roster_cut_status_label.add_theme_color_override("font_color", BAD)
		return
	if response_code != 200 or not bool(raw_payload.get("can_commit", false)):
		roster_cut_status_label.text = str(raw_payload.get("reason", raw_payload.get("detail", "Roster cut is blocked.")))
		roster_cut_status_label.add_theme_color_override("font_color", GOLD if response_code == 409 else BAD)
		_invalidate_roster_cut_preview()
		return
	if not bool(raw_payload.get("working_save_unchanged", false)) or not bool(raw_payload.get("active_v2_unchanged", false)):
		roster_cut_status_label.text = "SAFETY FAILURE • roster-cut preview changed a protected checkpoint."
		roster_cut_status_label.add_theme_color_override("font_color", BAD)
		_invalidate_roster_cut_preview()
		return
	var player: Dictionary = raw_payload.get("player", {})
	var fingerprint: String = str(raw_payload.get("action_fingerprint", ""))
	var working_sha: String = str(raw_payload.get("working_save_sha256", ""))
	latest_roster_cut_player_id = str(player.get("player_id", ""))
	latest_roster_cut_player_name = str(player.get("name", latest_roster_cut_player_id))
	latest_roster_cut_remaining_after = int(raw_payload.get("cuts_remaining_after", 0))
	roster_cut_status_label.text = "ROSTER CUT PREVIEW • %s\n%s → %s required cut(s) • %s • dead money %s\nNo save written." % [
		latest_roster_cut_player_name,
		str(raw_payload.get("cuts_remaining_before", 0)),
		str(latest_roster_cut_remaining_after),
		str(player.get("financial_treatment", "certified")).replace("_", " ").capitalize(),
		_money_text(player.get("dead_money_current_season"))
	]
	roster_cut_status_label.add_theme_color_override("font_color", GOOD)
	if not fingerprint.is_empty() and not working_sha.is_empty() and not latest_roster_cut_player_id.is_empty():
		latest_roster_cut_fingerprint = fingerprint
		latest_roster_cut_working_sha = working_sha
		commit_roster_cut_button.disabled = false


func _confirm_roster_cut() -> void:
	if roster_cut_execute_in_flight or latest_roster_cut_fingerprint.is_empty() or latest_roster_cut_working_sha.is_empty():
		return
	roster_cut_dialog.dialog_text = "Release %s from the active franchise?\n\nThis is your explicit post-Draft roster decision. The certified financial/reconciliation engine will apply the release ONLY to V3, create a recovery checkpoint, reload and verify the result, and protect V2." % latest_roster_cut_player_name
	roster_cut_dialog.popup_centered(Vector2i(620, 340))


func _execute_roster_cut() -> void:
	if roster_cut_execute_request == null or roster_cut_execute_in_flight:
		return
	if roster_cut_execute_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	if not _begin_long_action(
		"post_draft_roster_cut",
		"RESOLVING POST-DRAFT ROSTER",
		"Applying the explicit roster decision and certified financial reconciliation...",
		[
			"Rechecking the certified preview and exact V3 working-save fingerprint...",
			"Running the production scouting/Draft engine...",
			"Applying roster, prospect, and Draft-state updates...",
			"Persisting and reloading the isolated V3 checkpoint...",
			"Verifying the durable result and protected V2 checkpoint...",
		]
	):
		roster_cut_status_label.text = "Another franchise-changing action is already running."
		roster_cut_status_label.add_theme_color_override("font_color", GOLD)
		return
	var request_payload: Dictionary = {
		"player_id": latest_roster_cut_player_id,
		"expected_action_fingerprint": latest_roster_cut_fingerprint,
		"expected_working_save_sha256": latest_roster_cut_working_sha
	}
	roster_cut_execute_in_flight = true
	preview_roster_cut_button.disabled = true
	commit_roster_cut_button.disabled = true
	roster_cut_selector.disabled = true
	roster_cut_status_label.text = "Applying the selected post-Draft roster release, then reloading and verifying V3..."
	roster_cut_status_label.add_theme_color_override("font_color", ACCENT)
	var headers := PackedStringArray(["Content-Type: application/json"])
	var error: int = roster_cut_execute_request.request(
		ROSTER_CUT_EXECUTE_URL,
		headers,
		HTTPClient.METHOD_POST,
		JSON.stringify(request_payload)
	)
	if error != OK:
		_finish_long_action("post_draft_roster_cut", false, "The request could not start.")
		roster_cut_execute_in_flight = false
		roster_cut_status_label.text = "Could not start post-Draft roster release."
		roster_cut_status_label.add_theme_color_override("font_color", BAD)
		_request_summary()


func _on_roster_cut_execute_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	_finish_long_action(
		"post_draft_roster_cut",
		result == HTTPRequest.RESULT_SUCCESS and response_code == 200,
		"Action completed." if result == HTTPRequest.RESULT_SUCCESS and response_code == 200 else "Action ended with an error."
	)
	roster_cut_execute_in_flight = false
	var raw_payload = JSON.parse_string(body.get_string_from_utf8())
	if result != HTTPRequest.RESULT_SUCCESS or typeof(raw_payload) != TYPE_DICTIONARY:
		roster_cut_status_label.text = "Post-Draft roster release failed before a valid bridge response was received."
		roster_cut_status_label.add_theme_color_override("font_color", BAD)
		_invalidate_roster_cut_preview()
		return
	if response_code != 200:
		var detail: String = str(raw_payload.get("detail", raw_payload.get("error", "Post-Draft roster release failed.")))
		if bool(raw_payload.get("rollback_performed", false)):
			detail += "\nRollback: %s" % ("VERIFIED" if bool(raw_payload.get("rollback_verified", false)) else "REQUIRES REVIEW")
		if str(raw_payload.get("error", "")) == "stale_post_draft_roster_cut_preview":
			detail += "\nRun PREVIEW ROSTER CUT again."
		roster_cut_status_label.text = detail
		roster_cut_status_label.add_theme_color_override("font_color", GOLD if response_code == 409 else BAD)
		_invalidate_roster_cut_preview()
		return
	if not bool(raw_payload.get("persisted_after_reload", false)) or not bool(raw_payload.get("active_v2_unchanged", false)):
		roster_cut_status_label.text = "ROSTER-CUT SAFETY FAILURE • reload persistence or V2 protection was not confirmed."
		roster_cut_status_label.add_theme_color_override("font_color", BAD)
		_invalidate_roster_cut_preview()
		return
	var verification: Dictionary = raw_payload.get("verification", {})
	var remaining: int = int(verification.get("cuts_remaining_after", latest_roster_cut_remaining_after))
	roster_cut_status_label.text = "ROSTER RELEASE COMMITTED • %s\n%s cut(s) remain • persisted after reload • protected V2 unchanged" % [
		str(verification.get("player_name", latest_roster_cut_player_name)), str(remaining)
	]
	roster_cut_status_label.add_theme_color_override("font_color", GOOD)
	_invalidate_roster_cut_preview()
	_request_summary()


func _invalidate_roster_cut_preview() -> void:
	latest_roster_cut_fingerprint = ""
	latest_roster_cut_working_sha = ""
	latest_roster_cut_player_id = ""
	latest_roster_cut_player_name = ""
	latest_roster_cut_remaining_after = 0
	if commit_roster_cut_button != null:
		commit_roster_cut_button.disabled = true


func _money_text(value) -> String:
	if value == null:
		return "$0"
	var amount := float(value)
	if abs(amount) >= 1000000.0:
		return "$%.1fM" % (amount / 1000000.0)
	if abs(amount) >= 1000.0:
		return "$%.0fK" % (amount / 1000.0)
	return "$%.0f" % amount

func _invalidate_scout_preview() -> void:
	latest_scout_fingerprint = ""
	latest_scout_working_sha = ""
	latest_scout_focus_ids = []
	if advance_week_button != null:
		advance_week_button.disabled = true


func _invalidate_draft_preview() -> void:
	latest_draft_fingerprint = ""
	latest_draft_working_sha = ""
	latest_draft_prospect_id = ""
	if make_pick_button != null:
		make_pick_button.disabled = true


func _invalidate_draft_advance_preview() -> void:
	latest_cpu_draft_fingerprint = ""
	latest_cpu_draft_working_sha = ""
	latest_cpu_draft_pick_count = 0
	latest_cpu_draft_completes_draft = false
	if advance_cpu_picks_button != null:
		advance_cpu_picks_button.disabled = true


func _rating_text(value) -> String:
	if typeof(value) != TYPE_INT and typeof(value) != TYPE_FLOAT:
		return "--"
	return "%.1f" % float(value)


func _metric(parent: HBoxContainer, title: String, value: String) -> Label:
	var card := _card(Vector2(0, 82))
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var body := _card_body(card, 12)
	body.add_child(_small_label(title, MUTED))
	var label := Label.new()
	label.text = value
	label.add_theme_color_override("font_color", TEXT)
	label.add_theme_font_size_override("font_size", 16)
	label.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	body.add_child(label)
	parent.add_child(card)
	return label


func _cell(text_value: String, width: int, color: Color) -> Label:
	var label := Label.new()
	label.text = text_value
	label.custom_minimum_size = Vector2(width, 0)
	label.add_theme_color_override("font_color", color)
	label.add_theme_font_size_override("font_size", 10)
	label.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	return label


func _column_label(text_value: String, width: int) -> Label:
	return _cell(text_value, width, MUTED)


func _mini_button(text_value: String) -> Button:
	var button := Button.new()
	button.text = text_value
	button.add_theme_font_size_override("font_size", 9)
	button.add_theme_color_override("font_color", TEXT)
	button.add_theme_stylebox_override("normal", _box(PANEL, 7, BORDER))
	button.add_theme_stylebox_override("hover", _box(PANEL_HOVER, 7, ACCENT))
	return button


func _clear_children(node: Node) -> void:
	for child in node.get_children():
		node.remove_child(child)
		child.queue_free()


func _action_button(text_value: String, primary: bool = false) -> Button:
	var button := Button.new()
	if primary:
		primary_buttons.append(button)
	button.custom_minimum_size = Vector2(0, 38)
	button.text = text_value
	button.add_theme_font_size_override("font_size", 10)
	button.add_theme_color_override("font_color", TEXT)
	button.add_theme_color_override("font_hover_color", TEXT)
	var normal_color := TEAM_PRIMARY if primary else PANEL_ALT
	var hover_color := TEAM_PRIMARY_HOVER if primary else PANEL_HOVER
	button.add_theme_stylebox_override("normal", _box(normal_color, 9, normal_color if primary else BORDER))
	button.add_theme_stylebox_override("hover", _box(hover_color, 9, hover_color if primary else ACCENT))
	button.add_theme_stylebox_override("pressed", _box(hover_color, 9, hover_color))
	return button


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
	label.add_theme_font_size_override("font_size", 10)
	return label


func _pill(text_value: String, color: Color) -> Label:
	var label := Label.new()
	label.text = "  %s  " % text_value
	label.add_theme_color_override("font_color", color)
	label.add_theme_font_size_override("font_size", 10)
	label.add_theme_stylebox_override("normal", _box(Color(color, 0.10), 7, Color(color, 0.35)))
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
	body.add_theme_constant_override("separation", 7)
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
