extends Control

const MARKET_URL := "http://127.0.0.1:8765/v3/free-agency/market"
const PREVIEW_URL := "http://127.0.0.1:8765/v3/free-agency/preview"
const EXECUTE_URL := "http://127.0.0.1:8765/v3/free-agency/execute"

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

var market_request: HTTPRequest
var preview_request: HTTPRequest
var execute_request: HTTPRequest

var status_label: Label
var search_box: LineEdit
var position_filter: OptionButton
var market_rows: VBoxContainer
var selection_label: Label
var offer_salary: LineEdit
var offer_years: OptionButton
var offer_option: OptionButton
var preview_button: Button
var sign_button: Button
var preview_label: Label
var execute_dialog: ConfirmationDialog

var market_payload := {}
var free_agents: Array = []
var selected_player := {}
var latest_preview_fingerprint := ""
var latest_preview_working_sha := ""
var latest_preview_request_payload := {}
var execute_in_flight := false


func _ready() -> void:
	_build_ui()
	_build_http()


func refresh() -> void:
	_request_market()


func _build_http() -> void:
	market_request = HTTPRequest.new()
	market_request.timeout = 30.0
	market_request.request_completed.connect(_on_market_completed)
	add_child(market_request)

	preview_request = HTTPRequest.new()
	preview_request.timeout = 30.0
	preview_request.request_completed.connect(_on_preview_completed)
	add_child(preview_request)

	execute_request = HTTPRequest.new()
	execute_request.timeout = 90.0
	execute_request.request_completed.connect(_on_execute_completed)
	add_child(execute_request)


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
	titles.add_child(_small_label("FRANCHISE OPERATIONS • PLAYER MARKET", TEAM_PRIMARY_HOVER))

	var title := Label.new()
	title.text = "FREE AGENCY"
	title.add_theme_color_override("font_color", TEXT)
	title.add_theme_font_size_override("font_size", 31)
	titles.add_child(title)

	var subtitle := Label.new()
	subtitle.text = "Full live market board with contract construction and CBA preview."
	subtitle.add_theme_color_override("font_color", MUTED)
	subtitle.add_theme_font_size_override("font_size", 12)
	titles.add_child(subtitle)

	var refresh_button := _action_button("REFRESH MARKET", false)
	refresh_button.pressed.connect(_request_market)
	header.add_child(refresh_button)

	var safety := _card(Vector2(0, 58))
	var safety_body := _card_body(safety, 12)
	status_label = Label.new()
	status_label.text = "Open Free Agency to load the V3 market."
	status_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	status_label.add_theme_color_override("font_color", MUTED)
	status_label.add_theme_font_size_override("font_size", 11)
	safety_body.add_child(status_label)
	column.add_child(safety)

	var content_row := HBoxContainer.new()
	content_row.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	content_row.add_theme_constant_override("separation", 14)
	column.add_child(content_row)

	var market_card := _card(Vector2(660, 590))
	market_card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var market_body := _card_body(market_card, 16)

	var market_header := HBoxContainer.new()
	market_header.add_child(_section_title("MARKET BOARD"))
	var market_spacer := Control.new()
	market_spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	market_header.add_child(market_spacer)
	market_header.add_child(_pill("LIVE POOL", GOOD))
	market_body.add_child(market_header)

	var filters := HBoxContainer.new()
	filters.add_theme_constant_override("separation", 8)
	market_body.add_child(filters)

	search_box = LineEdit.new()
	search_box.placeholder_text = "Search player..."
	search_box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	search_box.text_changed.connect(_on_filter_changed)
	filters.add_child(search_box)

	position_filter = OptionButton.new()
	for value in ["ALL", "PG", "SG", "SF", "PF", "C"]:
		position_filter.add_item(value)
	position_filter.item_selected.connect(_on_position_filter_changed)
	filters.add_child(position_filter)

	var market_scroll := ScrollContainer.new()
	market_scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	market_scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	market_body.add_child(market_scroll)

	market_rows = VBoxContainer.new()
	market_rows.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	market_rows.add_theme_constant_override("separation", 4)
	market_scroll.add_child(market_rows)

	var negotiation_card := _card(Vector2(360, 590))
	var negotiation_body := _card_body(negotiation_card, 16)
	negotiation_body.add_child(_small_label("CONTRACT DESK", GOLD))
	negotiation_body.add_child(_section_title("NEGOTIATION PREVIEW"))

	selection_label = Label.new()
	selection_label.text = "Select a player from the market board."
	selection_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	selection_label.add_theme_color_override("font_color", TEXT)
	selection_label.add_theme_font_size_override("font_size", 12)
	negotiation_body.add_child(selection_label)

	negotiation_body.add_child(_small_label("ANNUAL SALARY", MUTED))
	offer_salary = LineEdit.new()
	offer_salary.placeholder_text = "10000000"
	offer_salary.text_changed.connect(_on_offer_changed)
	negotiation_body.add_child(offer_salary)

	negotiation_body.add_child(_small_label("CONTRACT YEARS", MUTED))
	offer_years = OptionButton.new()
	for years_value in [1, 2, 3, 4]:
		offer_years.add_item("%s year%s" % [years_value, "" if years_value == 1 else "s"])
	offer_years.select(1)
	offer_years.item_selected.connect(_on_offer_option_changed)
	negotiation_body.add_child(offer_years)

	negotiation_body.add_child(_small_label("OPTION", MUTED))
	offer_option = OptionButton.new()
	offer_option.add_item("No option")
	offer_option.add_item("Team option")
	offer_option.add_item("Player option")
	offer_option.item_selected.connect(_on_offer_option_changed)
	negotiation_body.add_child(offer_option)

	preview_button = _action_button("PREVIEW OFFER", true)
	preview_button.disabled = true
	preview_button.pressed.connect(_request_preview)
	negotiation_body.add_child(preview_button)

	sign_button = _action_button("SIGN PLAYER", false)
	sign_button.disabled = true
	sign_button.pressed.connect(_confirm_sign_player)
	negotiation_body.add_child(sign_button)

	var lock_note := Label.new()
	lock_note.text = "BATCH 09 WRITE GATE\nExecution requires offseason phase, a fresh PASS preview, the exact V3 working-save hash, confirmation, durable reload verification, and an unchanged protected V2 checkpoint."
	lock_note.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	lock_note.add_theme_color_override("font_color", MUTED)
	lock_note.add_theme_font_size_override("font_size", 9)
	negotiation_body.add_child(lock_note)

	var negotiation_spacer := Control.new()
	negotiation_spacer.size_flags_vertical = Control.SIZE_EXPAND_FILL
	negotiation_body.add_child(negotiation_spacer)

	preview_label = Label.new()
	preview_label.text = "No offer preview yet."
	preview_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	preview_label.add_theme_color_override("font_color", MUTED)
	preview_label.add_theme_font_size_override("font_size", 10)
	negotiation_body.add_child(preview_label)

	content_row.add_child(market_card)
	content_row.add_child(negotiation_card)

	execute_dialog = ConfirmationDialog.new()
	execute_dialog.title = "Confirm free-agent signing"
	execute_dialog.dialog_text = "Sign this player on the isolated V3 working save?"
	execute_dialog.confirmed.connect(_execute_signing)
	add_child(execute_dialog)
	execute_dialog.get_ok_button().text = "SIGN PLAYER"


func _request_market() -> void:
	if market_request == null:
		return
	if market_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	status_label.text = "Loading the complete live free-agent pool..."
	status_label.add_theme_color_override("font_color", ACCENT)
	var error := market_request.request(MARKET_URL)
	if error != OK:
		status_label.text = "Could not start the free-agency market request."
		status_label.add_theme_color_override("font_color", BAD)


func _on_market_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	if result != HTTPRequest.RESULT_SUCCESS or response_code != 200:
		status_label.text = "Free-agency market unavailable • HTTP %s" % response_code
		status_label.add_theme_color_override("font_color", BAD)
		return
	var raw_payload = JSON.parse_string(body.get_string_from_utf8())
	if typeof(raw_payload) != TYPE_DICTIONARY:
		status_label.text = "Free-agency market returned invalid data."
		status_label.add_theme_color_override("font_color", BAD)
		return
	market_payload = raw_payload
	if not bool(market_payload.get("working_save_unchanged", false)) or not bool(market_payload.get("active_v2_unchanged", false)):
		status_label.text = "FREE-AGENCY SAFETY CHECK FAILED"
		status_label.add_theme_color_override("font_color", BAD)
		return

	free_agents = market_payload.get("players", [])
	var season = market_payload.get("season", {})
	status_label.text = "LIVE • %s free agents • %s • Day %s • %s • working save unchanged • V2 protected" % [
		str(free_agents.size()),
		str(season.get("label", "")),
		str(season.get("day_index", "?")),
		str(season.get("phase", "")).replace("_", " ").capitalize()
	]
	status_label.add_theme_color_override("font_color", GOOD)
	_render_market_rows()


func _on_filter_changed(_value: String) -> void:
	_render_market_rows()


func _on_position_filter_changed(_index: int) -> void:
	_render_market_rows()


func _render_market_rows() -> void:
	_clear_children(market_rows)
	var query := search_box.text.strip_edges().to_lower()
	var position_value := position_filter.get_item_text(position_filter.selected) if position_filter.item_count > 0 else "ALL"
	var shown := 0

	for raw_player in free_agents:
		if typeof(raw_player) != TYPE_DICTIONARY:
			continue
		var player_data: Dictionary = raw_player
		var player_name := str(player_data.get("name", ""))
		var player_position := str(player_data.get("position", ""))
		if query != "" and query not in player_name.to_lower():
			continue
		if position_value != "ALL" and position_value not in player_position.split("/"):
			continue

		var button := Button.new()
		button.custom_minimum_size = Vector2(0, 54)
		button.alignment = HORIZONTAL_ALIGNMENT_LEFT
		button.text = "%s   •   %s   •   OVR %s   •   Age %s   •   Ref %s" % [
			player_name,
			player_position,
			str(player_data.get("overall", "N/A")),
			str(player_data.get("age", "N/A")),
			_money_text(player_data.get("salary", null))
		]
		button.add_theme_color_override("font_color", TEXT)
		button.add_theme_font_size_override("font_size", 10)
		button.add_theme_stylebox_override("normal", _box(PANEL_ALT, 8, BORDER))
		button.add_theme_stylebox_override("hover", _box(PANEL_HOVER, 8, ACCENT))
		button.pressed.connect(_select_player.bind(player_data))
		market_rows.add_child(button)
		shown += 1
		if shown >= 80:
			break

	if shown == 0:
		var empty := Label.new()
		empty.text = "No players match the current search/filter."
		empty.add_theme_color_override("font_color", MUTED)
		market_rows.add_child(empty)
	elif shown >= 80:
		var more := Label.new()
		more.text = "Showing the first 80 matches. Narrow the search to reach deeper market entries."
		more.add_theme_color_override("font_color", MUTED)
		more.add_theme_font_size_override("font_size", 9)
		market_rows.add_child(more)


func _select_player(player_data: Dictionary) -> void:
	selected_player = player_data.duplicate(true)
	var salary_value := float(selected_player.get("salary", 0.0) or 0.0)
	if salary_value <= 0.0:
		salary_value = 5000000.0
	offer_salary.text = str(int(round(salary_value)))
	offer_years.select(1)
	offer_option.select(0)
	selection_label.text = "%s\n%s • OVR %s • POT %s • Age %s\nMarket reference %s" % [
		str(selected_player.get("name", "")),
		str(selected_player.get("position", "")),
		str(selected_player.get("overall", "N/A")),
		str(selected_player.get("potential", "N/A")),
		str(selected_player.get("age", "N/A")),
		_money_text(selected_player.get("salary", null))
	]
	preview_label.text = "Offer changed. Run a fresh contract/CBA preview."
	preview_label.add_theme_color_override("font_color", MUTED)
	_invalidate_signing_execution()
	_update_preview_button()


func _invalidate_signing_execution() -> void:
	latest_preview_fingerprint = ""
	latest_preview_working_sha = ""
	latest_preview_request_payload = {}
	if sign_button != null:
		sign_button.disabled = true


func _on_offer_changed(_value: String) -> void:
	preview_label.text = "Offer changed. Run a fresh contract/CBA preview."
	preview_label.add_theme_color_override("font_color", MUTED)
	_invalidate_signing_execution()
	_update_preview_button()


func _on_offer_option_changed(_index: int) -> void:
	preview_label.text = "Offer changed. Run a fresh contract/CBA preview."
	preview_label.add_theme_color_override("font_color", MUTED)
	_invalidate_signing_execution()
	_update_preview_button()


func _update_preview_button() -> void:
	var salary_valid := false
	if offer_salary.text.strip_edges().is_valid_float():
		salary_valid = float(offer_salary.text.strip_edges()) > 0.0
	preview_button.disabled = selected_player.is_empty() or not salary_valid


func _option_code() -> String:
	match offer_option.selected:
		1:
			return "team_option"
		2:
			return "player_option"
	return ""


func _current_offer_request_payload() -> Dictionary:
	return {
		"player_id": str(selected_player.get("player_id", "")),
		"annual_salary": float(offer_salary.text.strip_edges()) if offer_salary.text.strip_edges().is_valid_float() else 0.0,
		"years": int(offer_years.selected + 1),
		"guaranteed": true,
		"option_type": _option_code()
	}


func _request_preview() -> void:
	if selected_player.is_empty() or preview_request == null:
		return
	if preview_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	if not offer_salary.text.strip_edges().is_valid_float():
		return

	var request_payload: Dictionary = _current_offer_request_payload()
	_invalidate_signing_execution()
	preview_button.disabled = true
	preview_label.text = "Running structural, salary, and CBA preview..."
	preview_label.add_theme_color_override("font_color", ACCENT)
	var headers := PackedStringArray(["Content-Type: application/json"])
	var error := preview_request.request(PREVIEW_URL, headers, HTTPClient.METHOD_POST, JSON.stringify(request_payload))
	if error != OK:
		preview_label.text = "Could not start free-agency preview."
		preview_label.add_theme_color_override("font_color", BAD)
		_update_preview_button()


func _on_preview_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	_update_preview_button()
	if result != HTTPRequest.RESULT_SUCCESS:
		_invalidate_signing_execution()
		preview_label.text = "Free-agency preview failed before the Python engine responded."
		preview_label.add_theme_color_override("font_color", BAD)
		return
	var raw_payload = JSON.parse_string(body.get_string_from_utf8())
	if typeof(raw_payload) != TYPE_DICTIONARY:
		_invalidate_signing_execution()
		preview_label.text = "Free-agency preview returned invalid data."
		preview_label.add_theme_color_override("font_color", BAD)
		return
	if response_code != 200:
		_invalidate_signing_execution()
		preview_label.text = str(raw_payload.get("detail", raw_payload.get("error", "Free-agency preview failed.")))
		preview_label.add_theme_color_override("font_color", BAD)
		return
	if not bool(raw_payload.get("working_save_unchanged", false)) or not bool(raw_payload.get("active_v2_unchanged", false)):
		_invalidate_signing_execution()
		preview_label.text = "SAFETY FAILURE • preview changed a protected checkpoint"
		preview_label.add_theme_color_override("font_color", BAD)
		return

	var gate: Dictionary = raw_payload.get("contract_cba_gate", {})
	var transaction: Dictionary = raw_payload.get("transaction_preview", {})
	var gate_status: String = str(gate.get("status", "manual_review"))
	var transaction_status: String = str(transaction.get("status", "blocked"))
	var can_commit: bool = bool(transaction.get("can_commit", false))
	var detail: String = "CONTRACT/CBA %s\n%s\n\nTRANSACTION %s • ENGINE COMMITTABLE %s\n%s" % [
		gate_status.to_upper(),
		str(gate.get("reason", "")),
		transaction_status.to_upper(),
		"YES" if can_commit else "NO",
		str(transaction.get("message", ""))
	]
	var committable: bool = gate_status == "pass" and transaction_status == "pass" and can_commit
	preview_label.text = detail
	preview_label.add_theme_color_override("font_color", GOOD if committable else GOLD)

	var fingerprint: String = str(transaction.get("candidate_fingerprint", ""))
	var working_sha: String = str(raw_payload.get("working_save_sha256", ""))
	if committable and fingerprint != "" and working_sha != "":
		latest_preview_fingerprint = fingerprint
		latest_preview_working_sha = working_sha
		latest_preview_request_payload = _current_offer_request_payload().duplicate(true)
		sign_button.disabled = false
		detail += "\n\nEXECUTION READY • Fresh signing token locked to the current V3 working save."
		preview_label.text = detail
	else:
		_invalidate_signing_execution()


func _confirm_sign_player() -> void:
	if execute_in_flight or latest_preview_fingerprint == "" or latest_preview_working_sha == "":
		return
	var player_name: String = str(selected_player.get("name", selected_player.get("player_id", "Free agent")))
	var years_value: int = int(latest_preview_request_payload.get("years", 0))
	var salary_value: float = float(latest_preview_request_payload.get("annual_salary", 0.0))
	execute_dialog.dialog_text = "Sign %s for %s year(s) at %s annually?\n\nThis writes ONLY the isolated V3 working save. A recovery checkpoint is created first, the result is reloaded and verified, and the protected V2 checkpoint must remain unchanged." % [
		player_name,
		str(years_value),
		_money_text(salary_value)
	]
	execute_dialog.popup_centered(Vector2i(560, 310))


func _execute_signing() -> void:
	if execute_request == null or execute_in_flight:
		return
	if execute_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	if latest_preview_fingerprint == "" or latest_preview_working_sha == "":
		preview_label.text = "Signing token is stale. Run PREVIEW OFFER again."
		preview_label.add_theme_color_override("font_color", GOLD)
		_invalidate_signing_execution()
		return

	var request_payload: Dictionary = latest_preview_request_payload.duplicate(true)
	request_payload["expected_candidate_fingerprint"] = latest_preview_fingerprint
	request_payload["expected_working_save_sha256"] = latest_preview_working_sha
	execute_in_flight = true
	sign_button.disabled = true
	preview_button.disabled = true
	preview_label.text = "Signing through the production free-agency engine, then verifying the V3 save and protected V2 hash..."
	preview_label.add_theme_color_override("font_color", ACCENT)
	var headers := PackedStringArray(["Content-Type: application/json"])
	var error: int = execute_request.request(EXECUTE_URL, headers, HTTPClient.METHOD_POST, JSON.stringify(request_payload))
	if error != OK:
		execute_in_flight = false
		_update_preview_button()
		preview_label.text = "Could not start free-agency execution."
		preview_label.add_theme_color_override("font_color", BAD)
		_invalidate_signing_execution()


func _on_execute_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	execute_in_flight = false
	_update_preview_button()
	var raw_payload = JSON.parse_string(body.get_string_from_utf8())
	if result != HTTPRequest.RESULT_SUCCESS or typeof(raw_payload) != TYPE_DICTIONARY:
		preview_label.text = "Signing request failed before a valid bridge response was received."
		preview_label.add_theme_color_override("font_color", BAD)
		_invalidate_signing_execution()
		return

	if response_code != 200:
		var detail: String = str(raw_payload.get("detail", raw_payload.get("error", "Free-agency execution failed.")))
		if bool(raw_payload.get("rollback_performed", false)):
			detail += "\nRollback: %s" % ("VERIFIED" if bool(raw_payload.get("rollback_verified", false)) else "REQUIRES REVIEW")
		if str(raw_payload.get("error", "")) == "stale_free_agency_preview":
			detail += "\nRun PREVIEW OFFER again before retrying."
		preview_label.text = detail
		preview_label.add_theme_color_override("font_color", GOLD if response_code == 409 else BAD)
		_invalidate_signing_execution()
		return

	if not bool(raw_payload.get("persisted_after_reload", false)) or not bool(raw_payload.get("active_v2_unchanged", false)):
		preview_label.text = "SIGNING SAFETY FAILURE • bridge did not confirm reload persistence and V2 protection."
		preview_label.add_theme_color_override("font_color", BAD)
		_invalidate_signing_execution()
		return

	var player_name: String = str(raw_payload.get("player_name", raw_payload.get("player_id", "Player")))
	preview_label.text = "SIGNING COMMITTED • %s\nPersisted after reload • V3 working save updated • protected V2 unchanged\nRecovery checkpoint: %s" % [
		player_name,
		str(raw_payload.get("recovery_checkpoint_path", ""))
	]
	preview_label.add_theme_color_override("font_color", GOOD)
	status_label.text = "LIVE • %s signed successfully • refreshing free-agent market..." % player_name
	status_label.add_theme_color_override("font_color", GOOD)
	selected_player = {}
	selection_label.text = "Select a player from the market board."
	offer_salary.text = ""
	_invalidate_signing_execution()
	_request_market()


func _money_text(value) -> String:
	if value == null:
		return "N/A"
	var amount := float(value)
	if abs(amount) >= 1000000.0:
		return "$%.1fM" % (amount / 1000000.0)
	if abs(amount) >= 1000.0:
		return "$%.0fK" % (amount / 1000.0)
	return "$%.0f" % amount


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
