extends Control

const SUMMARY_URL := "http://127.0.0.1:8765/v3/scouting-draft"
const SCOUT_PREVIEW_URL := "http://127.0.0.1:8765/v3/scouting/preview"
const SCOUT_EXECUTE_URL := "http://127.0.0.1:8765/v3/scouting/advance"
const DRAFT_PREVIEW_URL := "http://127.0.0.1:8765/v3/draft/selection/preview"
const DRAFT_EXECUTE_URL := "http://127.0.0.1:8765/v3/draft/selection/execute"

const PANEL := Color("121824")
const PANEL_ALT := Color("171f2d")
const PANEL_HOVER := Color("202b3d")
const TEXT := Color("f7f8fb")
const MUTED := Color("8d99aa")
const ACCENT := Color("8ed8ff")
const GOOD := Color("61d69b")
const BAD := Color("ff6577")
const BORDER := Color("263247")
const TEAM_PRIMARY := Color("d9273c")
const TEAM_PRIMARY_HOVER := Color("ef4055")
const GOLD := Color("f3c96b")

var summary_request: HTTPRequest
var scout_preview_request: HTTPRequest
var scout_execute_request: HTTPRequest
var draft_preview_request: HTTPRequest
var draft_execute_request: HTTPRequest

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
var scout_dialog: ConfirmationDialog
var draft_dialog: ConfirmationDialog

var page_payload: Dictionary = {}
var prospects: Array = []
var focus_selected: Dictionary = {}
var selected_prospect: Dictionary = {}
var scouting_execution_enabled := false
var draft_execution_enabled := false
var latest_scout_fingerprint := ""
var latest_scout_working_sha := ""
var latest_scout_focus_ids: Array = []
var latest_draft_fingerprint := ""
var latest_draft_working_sha := ""
var latest_draft_prospect_id := ""
var scout_execute_in_flight := false
var draft_execute_in_flight := false


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


func _build_ui() -> void:
	var page_scroll := ScrollContainer.new()
	page_scroll.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	page_scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	page_scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
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

	var titles := VBoxContainer.new()
	titles.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	header.add_child(titles)
	titles.add_child(_small_label("FRANCHISE OPERATIONS • TALENT PIPELINE", TEAM_PRIMARY_HOVER))
	var title := Label.new()
	title.text = "SCOUTING & DRAFT"
	title.add_theme_color_override("font_color", TEXT)
	title.add_theme_font_size_override("font_size", 31)
	titles.add_child(title)
	var subtitle := Label.new()
	subtitle.text = "Production scouting reports, priority assignments, and phase-safe Draft execution."
	subtitle.add_theme_color_override("font_color", MUTED)
	subtitle.add_theme_font_size_override("font_size", 12)
	titles.add_child(subtitle)

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

	var board_card := _card(Vector2(720, 650))
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

	var board_header_row := HBoxContainer.new()
	board_header_row.add_theme_constant_override("separation", 8)
	board_header_row.add_child(_column_label("FOCUS", 58))
	board_header_row.add_child(_column_label("RK", 34))
	var prospect_header := _column_label("PROSPECT", 220)
	prospect_header.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	board_header_row.add_child(prospect_header)
	board_header_row.add_child(_column_label("POS", 42))
	board_header_row.add_child(_column_label("OVR", 48))
	board_header_row.add_child(_column_label("POT", 48))
	board_header_row.add_child(_column_label("CONF", 54))
	board_header_row.add_child(_column_label("PROJECTED", 92))
	board_header_row.add_child(_column_label("DRAFT", 68))
	board_body.add_child(board_header_row)

	var board_scroll := ScrollContainer.new()
	board_scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	board_scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	board_body.add_child(board_scroll)
	board_rows = VBoxContainer.new()
	board_rows.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	board_rows.add_theme_constant_override("separation", 4)
	board_scroll.add_child(board_rows)
	content.add_child(board_card)

	var actions := VBoxContainer.new()
	actions.custom_minimum_size = Vector2(385, 0)
	actions.add_theme_constant_override("separation", 14)
	content.add_child(actions)

	var scout_card := _card(Vector2(385, 315))
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

	var draft_card := _card(Vector2(385, 315))
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
	actions.add_child(draft_card)

	scout_dialog = ConfirmationDialog.new()
	scout_dialog.title = "Confirm scouting week"
	scout_dialog.confirmed.connect(_execute_scouting_week)
	add_child(scout_dialog)

	draft_dialog = ConfirmationDialog.new()
	draft_dialog.title = "Confirm Draft selection"
	draft_dialog.confirmed.connect(_execute_draft_pick)
	add_child(draft_dialog)


func _request_summary() -> void:
	if summary_request == null:
		return
	if summary_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	_invalidate_scout_preview()
	_invalidate_draft_preview()
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
	prospects = raw_payload.get("board", [])
	focus_selected.clear()
	var summary: Dictionary = raw_payload.get("summary", {})
	var saved_focus: Array = summary.get("focus_ids", [])
	for raw_id in saved_focus:
		focus_selected[str(raw_id)] = true
	_apply_summary()
	_render_board()


func _apply_summary() -> void:
	var draft: Dictionary = page_payload.get("draft", {})
	var summary: Dictionary = page_payload.get("summary", {})
	var scout: Dictionary = page_payload.get("lead_scout", {})
	var phase: String = str(draft.get("phase", "unavailable"))
	draft_phase_value.text = phase.replace("_", " ").to_upper()
	var weeks_done: int = int(summary.get("weeks_completed", 0))
	var weeks_remaining: int = int(summary.get("weeks_remaining", 0))
	scouting_week_value.text = "%s / %s" % [str(weeks_done), str(weeks_done + weeks_remaining)]
	scout_value.text = str(scout.get("name", "N/A"))
	confidence_value.text = "%.0f%%" % float(summary.get("average_confidence", 0.0))
	scouting_execution_enabled = bool(page_payload.get("scouting_execution_enabled", false)) and weeks_remaining > 0
	draft_execution_enabled = bool(page_payload.get("draft_execution_enabled", false))
	preview_week_button.disabled = not scouting_execution_enabled
	_update_draft_controls()
	_update_focus_label()

	var draft_year: int = int(draft.get("draft_year", 0))
	var source_label: String = str(draft.get("source_season", ""))
	status_label.text = "LIVE V3 • %s Draft • %s • production scouting v%s" % [
		str(draft_year),
		source_label,
		str(page_payload.get("foundation_version", "")).replace("v3-transaction-foundation-", "")
	]
	status_label.add_theme_color_override("font_color", GOOD)

	var pick: Dictionary = draft.get("current_pick", {})
	if phase == "draft_in_progress" and not pick.is_empty():
		var owner: String = str(pick.get("owner_team", ""))
		var overall_pick: int = int(pick.get("overall_pick", 0))
		var round_number: int = int(pick.get("round", 0))
		var round_pick: int = int(pick.get("round_pick", 0))
		draft_status_label.text = "ON THE CLOCK • Pick #%s • Round %s, Pick %s • %s\n%s" % [
			str(overall_pick), str(round_number), str(round_pick), owner,
			"Your franchise may select now." if draft_execution_enabled else "CPU-owned pick. Selection remains protected."
		]
		draft_status_label.add_theme_color_override("font_color", GOOD if draft_execution_enabled else GOLD)
	else:
		draft_status_label.text = "Draft selection is locked during %s. Scouting remains available through its production phase rules." % phase.replace("_", " ").capitalize()
		draft_status_label.add_theme_color_override("font_color", MUTED)


func _render_board() -> void:
	_clear_children(board_rows)
	var query: String = search_box.text.strip_edges().to_lower()
	var displayed := 0
	for raw_row in prospects:
		if typeof(raw_row) != TYPE_DICTIONARY:
			continue
		var row: Dictionary = raw_row
		var haystack: String = "%s %s %s %s" % [
			str(row.get("Prospect", "")), str(row.get("Pos", "")),
			str(row.get("School / Club", "")), str(row.get("Archetype", ""))
		]
		if query != "" and not query in haystack.to_lower():
			continue
		board_rows.add_child(_prospect_row(row))
		displayed += 1
		if displayed >= 50:
			break
	if displayed == 0:
		board_rows.add_child(_small_label("No prospects match the current search.", MUTED))


func _prospect_row(row: Dictionary) -> Control:
	var panel := PanelContainer.new()
	panel.add_theme_stylebox_override("panel", _box(PANEL_ALT, 8, BORDER))
	var margin := MarginContainer.new()
	_set_margins(margin, 8, 7, 8, 7)
	panel.add_child(margin)
	var line := HBoxContainer.new()
	line.add_theme_constant_override("separation", 8)
	margin.add_child(line)
	var prospect_id: String = str(row.get("prospect_id", ""))

	var focus := CheckBox.new()
	focus.custom_minimum_size = Vector2(58, 0)
	focus.button_pressed = focus_selected.has(prospect_id)
	focus.disabled = not scouting_execution_enabled
	focus.toggled.connect(_on_focus_toggled.bind(prospect_id))
	line.add_child(focus)
	line.add_child(_cell(str(row.get("Rank", "")), 34, MUTED))
	var name := _cell(str(row.get("Prospect", prospect_id)), 220, TEXT)
	name.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	line.add_child(name)
	line.add_child(_cell(str(row.get("Pos", "")), 42, ACCENT))
	line.add_child(_cell(_rating_text(row.get("Scouted OVR")), 48, TEXT))
	line.add_child(_cell(_rating_text(row.get("Scouted POT")), 48, GOOD))
	line.add_child(_cell("%.0f%%" % float(row.get("Confidence", 0.0)), 54, MUTED))
	line.add_child(_cell(str(row.get("Projected", "")), 92, MUTED))
	var select_button := _mini_button("SELECT")
	select_button.custom_minimum_size = Vector2(68, 30)
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
		scout_execute_in_flight = false
		preview_week_button.disabled = not scouting_execution_enabled
		scouting_preview_label.text = "Could not start scouting execution."
		scouting_preview_label.add_theme_color_override("font_color", BAD)


func _on_scout_execute_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
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
	selected_prospect_label.text = "%s • %s • Scouted %.1f OVR / %.1f POT • %.0f%% confidence" % [
		str(row.get("Prospect", row.get("prospect_id", ""))),
		str(row.get("Pos", "")),
		float(row.get("Scouted OVR", 0.0)),
		float(row.get("Scouted POT", 0.0)),
		float(row.get("Confidence", 0.0))
	]
	_invalidate_draft_preview()
	_update_draft_controls()


func _update_draft_controls() -> void:
	preview_pick_button.disabled = not draft_execution_enabled or selected_prospect.is_empty() or draft_execute_in_flight
	if latest_draft_fingerprint == "":
		make_pick_button.disabled = true


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
		draft_execute_in_flight = false
		_update_draft_controls()
		draft_status_label.text = "Could not start Draft execution."
		draft_status_label.add_theme_color_override("font_color", BAD)


func _on_draft_execute_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
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


func _rating_text(value) -> String:
	if value == null:
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
