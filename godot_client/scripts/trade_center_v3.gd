extends Control

const FOUNDATION_URL := "http://127.0.0.1:8765/v3/transaction-foundation?trade_finder=1"
const TEAM_ASSETS_URL := "http://127.0.0.1:8765/v3/trade/team-assets"
const TRADE_PREVIEW_URL := "http://127.0.0.1:8765/v3/trade/preview"
const TRADE_EXECUTE_URL := "http://127.0.0.1:8765/v3/trade/execute"

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

var foundation_request: HTTPRequest
var partner_assets_request: HTTPRequest
var preview_request: HTTPRequest
var execute_request: HTTPRequest

var status_label: Label
var proposal_rows: VBoxContainer
var partner_selector: OptionButton
var active_assets_rows: VBoxContainer
var partner_assets_rows: VBoxContainer
var package_label: Label
var preview_label: Label
var preview_button: Button
var execute_button: Button
var execute_dialog: ConfirmationDialog

var foundation_payload := {}
var partner_payload := {}
var active_team := ""
var partner_codes: Array = []
var proposals: Array = []
var pending_proposal := {}
var latest_preview_fingerprint := ""
var latest_preview_working_sha := ""
var latest_preview_request_payload := {}
var execute_in_flight := false

var selected_active_players := {}
var selected_active_picks := {}
var selected_partner_players := {}
var selected_partner_picks := {}


var long_action_manager = null


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
	_request_foundation()


func _build_http() -> void:
	foundation_request = HTTPRequest.new()
	foundation_request.timeout = 60.0
	foundation_request.request_completed.connect(_on_foundation_completed)
	add_child(foundation_request)

	partner_assets_request = HTTPRequest.new()
	partner_assets_request.timeout = 20.0
	partner_assets_request.request_completed.connect(_on_partner_assets_completed)
	add_child(partner_assets_request)

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
	titles.add_child(_small_label("FRANCHISE OPERATIONS • TRANSACTIONS", TEAM_PRIMARY_HOVER))

	var title := Label.new()
	title.text = "TRADE CENTER"
	title.add_theme_color_override("font_color", TEXT)
	title.add_theme_font_size_override("font_size", 31)
	titles.add_child(title)

	var subtitle := Label.new()
	subtitle.text = "Production Trade Finder, exact live assets, and CBA-aware package previews."
	subtitle.add_theme_color_override("font_color", MUTED)
	subtitle.add_theme_font_size_override("font_size", 12)
	titles.add_child(subtitle)

	var refresh_button := _action_button("REFRESH MARKET", false)
	refresh_button.pressed.connect(_request_foundation)
	header.add_child(refresh_button)

	var safety := _card(Vector2(0, 58))
	var safety_body := _card_body(safety, 12)
	status_label = Label.new()
	status_label.text = "Open Trade Center to load the V3 transaction foundation."
	status_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	status_label.add_theme_color_override("font_color", MUTED)
	status_label.add_theme_font_size_override("font_size", 11)
	safety_body.add_child(status_label)
	column.add_child(safety)

	var finder_card := _card(Vector2(0, 205))
	var finder_body := _card_body(finder_card, 16)
	var finder_header := HBoxContainer.new()
	finder_header.add_child(_section_title("CPU TRADE FINDER"))
	var finder_spacer := Control.new()
	finder_spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	finder_header.add_child(finder_spacer)
	finder_header.add_child(_pill("PRODUCTION ENGINE", GOOD))
	finder_body.add_child(finder_header)

	var finder_hint := Label.new()
	finder_hint.text = "Load any production proposal directly into the builder, or construct your own package below."
	finder_hint.add_theme_color_override("font_color", MUTED)
	finder_hint.add_theme_font_size_override("font_size", 10)
	finder_body.add_child(finder_hint)

	var proposal_scroll := ScrollContainer.new()
	proposal_scroll.custom_minimum_size = Vector2(0, 120)
	proposal_scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	finder_body.add_child(proposal_scroll)

	proposal_rows = VBoxContainer.new()
	proposal_rows.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	proposal_rows.add_theme_constant_override("separation", 5)
	proposal_scroll.add_child(proposal_rows)
	column.add_child(finder_card)

	var builder_row := HBoxContainer.new()
	builder_row.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	builder_row.add_theme_constant_override("separation", 12)
	column.add_child(builder_row)

	var active_panel := _asset_panel("YOUR ASSETS", true)
	active_panel.custom_minimum_size = Vector2(345, 500)
	active_panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	builder_row.add_child(active_panel)

	var command_card := _card(Vector2(280, 500))
	var command_body := _card_body(command_card, 16)
	command_body.add_child(_small_label("TRADE BUILDER", GOLD))
	command_body.add_child(_section_title("PACKAGE CONTROL"))
	command_body.add_child(_small_label("TRADE PARTNER", MUTED))

	partner_selector = OptionButton.new()
	partner_selector.custom_minimum_size = Vector2(0, 38)
	partner_selector.item_selected.connect(_on_partner_selected)
	command_body.add_child(partner_selector)

	var clear_button := _action_button("CLEAR PACKAGE", false)
	clear_button.pressed.connect(_clear_package)
	command_body.add_child(clear_button)

	package_label = Label.new()
	package_label.text = "Select assets from each side."
	package_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	package_label.add_theme_color_override("font_color", TEXT)
	package_label.add_theme_font_size_override("font_size", 11)
	command_body.add_child(package_label)

	var control_spacer := Control.new()
	control_spacer.size_flags_vertical = Control.SIZE_EXPAND_FILL
	command_body.add_child(control_spacer)

	preview_button = _action_button("PREVIEW LEGALITY", true)
	preview_button.disabled = true
	preview_button.pressed.connect(_request_trade_preview)
	command_body.add_child(preview_button)

	execute_button = _action_button("EXECUTE TRADE", false)
	execute_button.disabled = true
	execute_button.pressed.connect(_confirm_execute_trade)
	command_body.add_child(execute_button)

	var locked := Label.new()
	locked.text = "BATCH 08 WRITE GATE\nExecution requires a fresh PASS preview, the exact working-save SHA, confirmation, durable reload verification, and an unchanged V2 checkpoint."
	locked.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	locked.add_theme_color_override("font_color", MUTED)
	locked.add_theme_font_size_override("font_size", 9)
	command_body.add_child(locked)
	builder_row.add_child(command_card)

	var partner_panel := _asset_panel("PARTNER ASSETS", false)
	partner_panel.custom_minimum_size = Vector2(345, 500)
	partner_panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	builder_row.add_child(partner_panel)

	var preview_card := _card(Vector2(0, 130))
	var preview_body := _card_body(preview_card, 16)
	var preview_header := HBoxContainer.new()
	preview_header.add_child(_section_title("LEGALITY + FINANCIAL PREVIEW"))
	var preview_spacer := Control.new()
	preview_spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	preview_header.add_child(preview_spacer)
	preview_header.add_child(_pill("READ ONLY", ACCENT))
	preview_body.add_child(preview_header)

	preview_label = Label.new()
	preview_label.text = "Build a package and select PREVIEW LEGALITY."
	preview_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	preview_label.add_theme_color_override("font_color", MUTED)
	preview_label.add_theme_font_size_override("font_size", 11)
	preview_body.add_child(preview_label)
	column.add_child(preview_card)

	execute_dialog = ConfirmationDialog.new()
	execute_dialog.title = "Confirm franchise trade"
	execute_dialog.dialog_text = "Execute this trade on the isolated V3 working save?"
	execute_dialog.confirmed.connect(_execute_trade)
	add_child(execute_dialog)
	execute_dialog.get_ok_button().text = "EXECUTE TRADE"


func _asset_panel(title_text: String, active_side: bool) -> PanelContainer:
	var card := _card(Vector2(0, 0))
	var body := _card_body(card, 14)
	var side_color := TEAM_PRIMARY_HOVER if active_side else ACCENT
	body.add_child(_small_label("ACTIVE FRANCHISE" if active_side else "TRADE PARTNER", side_color))
	body.add_child(_section_title(title_text))

	var hint := Label.new()
	hint.text = "Select players and exact draft-right assets to include."
	hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	hint.add_theme_color_override("font_color", MUTED)
	hint.add_theme_font_size_override("font_size", 9)
	body.add_child(hint)

	var scroll := ScrollContainer.new()
	scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	body.add_child(scroll)

	var rows := VBoxContainer.new()
	rows.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	rows.add_theme_constant_override("separation", 4)
	scroll.add_child(rows)

	if active_side:
		active_assets_rows = rows
	else:
		partner_assets_rows = rows
	return card


func _request_foundation() -> void:
	if foundation_request == null:
		return
	if foundation_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	status_label.text = "Scanning the production Trade Finder and live asset ledger..."
	status_label.add_theme_color_override("font_color", ACCENT)
	preview_button.disabled = true
	var error := foundation_request.request(FOUNDATION_URL)
	if error != OK:
		status_label.text = "Could not start the transaction-foundation request."
		status_label.add_theme_color_override("font_color", BAD)


func _on_foundation_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	if result != HTTPRequest.RESULT_SUCCESS or response_code != 200:
		status_label.text = "Transaction foundation unavailable • HTTP %s" % response_code
		status_label.add_theme_color_override("font_color", BAD)
		return

	var raw_payload = JSON.parse_string(body.get_string_from_utf8())
	if typeof(raw_payload) != TYPE_DICTIONARY:
		status_label.text = "Transaction foundation returned invalid data."
		status_label.add_theme_color_override("font_color", BAD)
		return

	foundation_payload = raw_payload
	if not bool(foundation_payload.get("working_save_unchanged", false)) or not bool(foundation_payload.get("active_v2_unchanged", false)):
		status_label.text = "TRANSACTION SAFETY CHECK FAILED • no further action enabled"
		status_label.add_theme_color_override("font_color", BAD)
		return

	active_team = str(foundation_payload.get("team", ""))
	partner_codes = foundation_payload.get("teams", [])
	proposals = foundation_payload.get("trade_finder", {}).get("proposals", [])
	_render_active_assets()
	_render_proposals()
	_populate_partner_selector()

	var finder = foundation_payload.get("trade_finder", {})
	status_label.text = "LIVE • %s • %s legal packages • %s proposal(s) • %.2fs search • working save unchanged • V2 protected" % [
		active_team,
		str(finder.get("legal_packages", 0)),
		str(proposals.size()),
		float(finder.get("search_elapsed_seconds", 0.0))
	]
	status_label.add_theme_color_override("font_color", GOOD)


func _populate_partner_selector() -> void:
	partner_selector.clear()
	for raw_code in partner_codes:
		partner_selector.add_item(str(raw_code))
	if partner_selector.item_count == 0:
		return

	var preferred := ""
	if not proposals.is_empty() and typeof(proposals[0]) == TYPE_DICTIONARY:
		preferred = str(proposals[0].get("partner_team", ""))

	var preferred_index := 0
	for index in range(partner_selector.item_count):
		if partner_selector.get_item_text(index) == preferred:
			preferred_index = index
			break

	partner_selector.select(preferred_index)
	_request_partner_assets(partner_selector.get_item_text(preferred_index))


func _on_partner_selected(index: int) -> void:
	if index < 0 or index >= partner_selector.item_count:
		return
	pending_proposal = {}
	selected_partner_players.clear()
	selected_partner_picks.clear()
	_request_partner_assets(partner_selector.get_item_text(index))
	_update_package_summary()


func _request_partner_assets(team_code: String) -> void:
	if partner_assets_request == null:
		return
	if partner_assets_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		partner_assets_request.cancel_request()
	_clear_children(partner_assets_rows)
	var loading := Label.new()
	loading.text = "Loading %s assets..." % team_code
	loading.add_theme_color_override("font_color", MUTED)
	partner_assets_rows.add_child(loading)
	var error := partner_assets_request.request("%s?team=%s" % [TEAM_ASSETS_URL, team_code])
	if error != OK:
		status_label.text = "Could not request %s trade assets." % team_code
		status_label.add_theme_color_override("font_color", BAD)


func _on_partner_assets_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	if result != HTTPRequest.RESULT_SUCCESS or response_code != 200:
		status_label.text = "Partner asset request failed • HTTP %s" % response_code
		status_label.add_theme_color_override("font_color", BAD)
		return
	var raw_payload = JSON.parse_string(body.get_string_from_utf8())
	if typeof(raw_payload) != TYPE_DICTIONARY:
		return
	partner_payload = raw_payload
	if not bool(partner_payload.get("working_save_unchanged", false)) or not bool(partner_payload.get("active_v2_unchanged", false)):
		status_label.text = "PARTNER-ASSET SAFETY CHECK FAILED"
		status_label.add_theme_color_override("font_color", BAD)
		return
	if not pending_proposal.is_empty() and str(pending_proposal.get("partner_team", "")) == str(partner_payload.get("team", "")):
		_apply_pending_proposal()
	_render_partner_assets()
	_update_package_summary()


func _render_active_assets() -> void:
	_clear_children(active_assets_rows)
	var players: Array = foundation_payload.get("trade_assets", {}).get("players", [])
	var picks: Array = foundation_payload.get("draft_assets", {}).get("owned", [])
	active_assets_rows.add_child(_small_label("PLAYERS", MUTED))
	for raw_player in players:
		if typeof(raw_player) == TYPE_DICTIONARY:
			active_assets_rows.add_child(_player_checkbox(raw_player, "active_player"))
	active_assets_rows.add_child(_divider())
	active_assets_rows.add_child(_small_label("DRAFT RIGHTS", MUTED))
	for raw_pick in picks:
		if typeof(raw_pick) == TYPE_DICTIONARY:
			active_assets_rows.add_child(_pick_checkbox(raw_pick, "active_pick"))


func _render_partner_assets() -> void:
	_clear_children(partner_assets_rows)
	var players: Array = partner_payload.get("players", [])
	var picks: Array = partner_payload.get("picks", [])
	partner_assets_rows.add_child(_small_label("PLAYERS", MUTED))
	for raw_player in players:
		if typeof(raw_player) == TYPE_DICTIONARY:
			partner_assets_rows.add_child(_player_checkbox(raw_player, "partner_player"))
	partner_assets_rows.add_child(_divider())
	partner_assets_rows.add_child(_small_label("DRAFT RIGHTS", MUTED))
	for raw_pick in picks:
		if typeof(raw_pick) == TYPE_DICTIONARY:
			partner_assets_rows.add_child(_pick_checkbox(raw_pick, "partner_pick"))


func _player_checkbox(player_data: Dictionary, kind: String) -> CheckBox:
	var player_id := str(player_data.get("player_id", ""))
	var box := CheckBox.new()
	box.text = "%s  •  %s  •  OVR %s  •  %s" % [
		str(player_data.get("name", player_id)),
		str(player_data.get("position", "")),
		str(player_data.get("overall", "N/A")),
		_money_text(player_data.get("salary", null))
	]
	box.button_pressed = _selection_dict(kind).has(player_id)
	box.add_theme_color_override("font_color", TEXT)
	box.add_theme_font_size_override("font_size", 10)
	box.toggled.connect(_on_asset_toggled.bind(kind, player_id))
	return box


func _pick_checkbox(pick_data: Dictionary, kind: String) -> CheckBox:
	var asset_id := str(pick_data.get("asset_id", ""))
	var display := str(pick_data.get("display_name", ""))
	if display == "":
		display = "%s R%s • %s" % [str(pick_data.get("draft_year", "")), str(pick_data.get("round", "")), str(pick_data.get("origin_team", ""))]
	var readiness := "READY" if bool(pick_data.get("engine_ready", false)) else "REVIEW"
	var box := CheckBox.new()
	box.text = "%s  •  %s" % [display, readiness]
	box.button_pressed = _selection_dict(kind).has(asset_id)
	box.add_theme_color_override("font_color", TEXT if readiness == "READY" else GOLD)
	box.add_theme_font_size_override("font_size", 10)
	box.toggled.connect(_on_asset_toggled.bind(kind, asset_id))
	return box


func _selection_dict(kind: String) -> Dictionary:
	match kind:
		"active_player":
			return selected_active_players
		"active_pick":
			return selected_active_picks
		"partner_player":
			return selected_partner_players
		"partner_pick":
			return selected_partner_picks
	return {}


func _on_asset_toggled(enabled: bool, kind: String, asset_id: String) -> void:
	var selection := _selection_dict(kind)
	if enabled:
		selection[asset_id] = true
	else:
		selection.erase(asset_id)
	_update_package_summary()


func _selected_ids(selection: Dictionary) -> Array:
	var ids: Array = []
	for key in selection.keys():
		ids.append(str(key))
	ids.sort()
	return ids


func _current_trade_request_payload() -> Dictionary:
	if partner_selector == null or partner_selector.item_count == 0:
		return {}
	return {
		"partner_team": partner_selector.get_item_text(partner_selector.selected),
		"side_a_player_ids": _selected_ids(selected_active_players),
		"side_b_player_ids": _selected_ids(selected_partner_players),
		"side_a_pick_asset_ids": _selected_ids(selected_active_picks),
		"side_b_pick_asset_ids": _selected_ids(selected_partner_picks)
	}


func _invalidate_trade_execution() -> void:
	latest_preview_fingerprint = ""
	latest_preview_working_sha = ""
	latest_preview_request_payload = {}
	execute_button.disabled = true


func _update_package_summary() -> void:
	var partner := partner_selector.get_item_text(partner_selector.selected) if partner_selector.item_count > 0 else "PARTNER"
	var outgoing_count := selected_active_players.size() + selected_active_picks.size()
	var incoming_count := selected_partner_players.size() + selected_partner_picks.size()
	package_label.text = "%s → %s\nSEND  %s player(s) + %s pick right(s)\nGET   %s player(s) + %s pick right(s)" % [
		active_team if active_team != "" else "YOUR TEAM",
		partner,
		str(selected_active_players.size()),
		str(selected_active_picks.size()),
		str(selected_partner_players.size()),
		str(selected_partner_picks.size())
	]
	preview_button.disabled = outgoing_count == 0 or incoming_count == 0 or partner_payload.is_empty()
	preview_label.text = "Package changed. Run a fresh legality preview before execution."
	preview_label.add_theme_color_override("font_color", MUTED)
	_invalidate_trade_execution()


func _clear_package() -> void:
	selected_active_players.clear()
	selected_active_picks.clear()
	selected_partner_players.clear()
	selected_partner_picks.clear()
	pending_proposal = {}
	_render_active_assets()
	if not partner_payload.is_empty():
		_render_partner_assets()
	_update_package_summary()


func _render_proposals() -> void:
	_clear_children(proposal_rows)
	if proposals.is_empty():
		var empty := Label.new()
		empty.text = "No legal production proposals cleared this search window."
		empty.add_theme_color_override("font_color", MUTED)
		proposal_rows.add_child(empty)
		return

	for raw_proposal in proposals:
		if typeof(raw_proposal) != TYPE_DICTIONARY:
			continue
		var proposal: Dictionary = raw_proposal
		var button := Button.new()
		button.custom_minimum_size = Vector2(0, 62)
		button.alignment = HORIZONTAL_ALIGNMENT_LEFT
		button.text = "%s • %s • %s\nGET %s   |   SEND %s" % [
			str(proposal.get("partner_team", "")),
			str(proposal.get("response_label", proposal.get("cpu_response", ""))),
			str(proposal.get("deal_type", "")),
			_join_assets(proposal.get("incoming", [])),
			_join_assets(proposal.get("outgoing", []))
		]
		button.add_theme_color_override("font_color", TEXT)
		button.add_theme_font_size_override("font_size", 10)
		button.add_theme_stylebox_override("normal", _box(PANEL_ALT, 8, BORDER))
		button.add_theme_stylebox_override("hover", _box(PANEL_HOVER, 8, ACCENT))
		button.pressed.connect(_load_proposal.bind(proposal))
		proposal_rows.add_child(button)


func _load_proposal(proposal: Dictionary) -> void:
	var team_code := str(proposal.get("partner_team", ""))
	if team_code == "":
		return
	pending_proposal = proposal.duplicate(true)
	for index in range(partner_selector.item_count):
		if partner_selector.get_item_text(index) == team_code:
			partner_selector.select(index)
			break
	if str(partner_payload.get("team", "")) == team_code:
		_apply_pending_proposal()
		_render_active_assets()
		_render_partner_assets()
		_update_package_summary()
	else:
		_request_partner_assets(team_code)


func _apply_pending_proposal() -> void:
	selected_active_players.clear()
	selected_active_picks.clear()
	selected_partner_players.clear()
	selected_partner_picks.clear()
	for value in pending_proposal.get("side_a_player_ids", []):
		selected_active_players[str(value)] = true
	for value in pending_proposal.get("side_a_pick_asset_ids", []):
		selected_active_picks[str(value)] = true
	for value in pending_proposal.get("side_b_player_ids", []):
		selected_partner_players[str(value)] = true
	for value in pending_proposal.get("side_b_pick_asset_ids", []):
		selected_partner_picks[str(value)] = true
	pending_proposal = {}
	_render_active_assets()


func _request_trade_preview() -> void:
	if preview_request == null or partner_selector.item_count == 0:
		return
	if preview_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	var request_payload := _current_trade_request_payload()
	_invalidate_trade_execution()
	preview_button.disabled = true
	preview_label.text = "Running full embedded trade preview: ownership, salary/CBA, contracts, draft rights, Stepien, and canonical guards..."
	preview_label.add_theme_color_override("font_color", ACCENT)
	var headers := PackedStringArray(["Content-Type: application/json"])
	var error := preview_request.request(TRADE_PREVIEW_URL, headers, HTTPClient.METHOD_POST, JSON.stringify(request_payload))
	if error != OK:
		preview_label.text = "Could not start trade preview."
		preview_label.add_theme_color_override("font_color", BAD)
		preview_button.disabled = false


func _on_preview_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	preview_button.disabled = false
	if result != HTTPRequest.RESULT_SUCCESS:
		preview_label.text = "Trade preview request failed before the Python engine responded."
		preview_label.add_theme_color_override("font_color", BAD)
		return
	var raw_payload = JSON.parse_string(body.get_string_from_utf8())
	if typeof(raw_payload) != TYPE_DICTIONARY:
		preview_label.text = "Trade preview returned invalid data."
		preview_label.add_theme_color_override("font_color", BAD)
		return
	if response_code != 200:
		preview_label.text = str(raw_payload.get("detail", raw_payload.get("error", "Trade preview failed.")))
		preview_label.add_theme_color_override("font_color", BAD)
		return
	if not bool(raw_payload.get("working_save_unchanged", false)) or not bool(raw_payload.get("active_v2_unchanged", false)):
		preview_label.text = "SAFETY FAILURE • preview changed a protected checkpoint"
		preview_label.add_theme_color_override("font_color", BAD)
		return

	var preview: Dictionary = raw_payload.get("preview", {})
	var preview_status := str(preview.get("status", "manual_review"))
	var side_a: Dictionary = preview.get("side_a", {})
	var side_b: Dictionary = preview.get("side_b", {})
	var issue_lines: Array = []
	for raw_check in preview.get("checks", []):
		if typeof(raw_check) != TYPE_DICTIONARY:
			continue
		var check: Dictionary = raw_check
		if str(check.get("status", "")).to_lower() != "pass":
			issue_lines.append("%s • %s" % [str(check.get("code", "")), str(check.get("message", ""))])
		if issue_lines.size() >= 4:
			break

	var detail := "STATUS %s • ENGINE COMMITTABLE %s\n%s sends %s • receives %s\n%s sends %s • receives %s\nFinancial %s • Contracts %s • Draft/Stepien %s" % [
		preview_status.to_upper(),
		"YES" if bool(preview.get("can_commit", false)) else "NO",
		str(side_a.get("team", active_team)),
		_money_text(side_a.get("outgoing_salary", 0.0)),
		_money_text(side_a.get("incoming_salary", 0.0)),
		str(side_b.get("team", "")),
		_money_text(side_b.get("outgoing_salary", 0.0)),
		_money_text(side_b.get("incoming_salary", 0.0)),
		str(preview.get("financial_bridge_status", "")),
		str(preview.get("player_contract_bridge_status", "")),
		str(preview.get("draft_right_bridge_status", ""))
	]
	if not issue_lines.is_empty():
		detail += "\n\nNON-PASS CHECKS\n" + "\n".join(issue_lines)
	else:
		detail += "\n\nAll surfaced preview checks passed."
	var committable := preview_status == "pass" and bool(preview.get("can_commit", false))
	preview_label.text = detail
	preview_label.add_theme_color_override("font_color", GOOD if committable else GOLD)

	var fingerprint := str(preview.get("package_fingerprint", ""))
	var working_sha := str(raw_payload.get("working_save_sha256", ""))
	if committable and fingerprint != "" and working_sha != "":
		latest_preview_fingerprint = fingerprint
		latest_preview_working_sha = working_sha
		latest_preview_request_payload = _current_trade_request_payload().duplicate(true)
		execute_button.disabled = false
		detail += "\n\nEXECUTION READY • Fresh preview token locked to the current V3 working save."
		preview_label.text = detail
	else:
		_invalidate_trade_execution()


func _confirm_execute_trade() -> void:
	if execute_in_flight or latest_preview_fingerprint == "" or latest_preview_working_sha == "":
		return
	var partner := str(latest_preview_request_payload.get("partner_team", ""))
	var outgoing_count: int = int(latest_preview_request_payload.get("side_a_player_ids", []).size()) + int(latest_preview_request_payload.get("side_a_pick_asset_ids", []).size())
	var incoming_count: int = int(latest_preview_request_payload.get("side_b_player_ids", []).size()) + int(latest_preview_request_payload.get("side_b_pick_asset_ids", []).size())
	execute_dialog.dialog_text = "%s ↔ %s\n\nSend %s asset(s) and receive %s asset(s).\n\nThis writes ONLY the isolated V3 working save. A recovery checkpoint is created first, the result is reloaded and verified, and the protected V2 checkpoint must remain unchanged." % [
		active_team,
		partner,
		str(outgoing_count),
		str(incoming_count)
	]
	execute_dialog.popup_centered(Vector2i(540, 300))


func _execute_trade() -> void:
	if execute_request == null or execute_in_flight:
		return
	if execute_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	if latest_preview_fingerprint == "" or latest_preview_working_sha == "":
		preview_label.text = "Execution token is stale. Run PREVIEW LEGALITY again."
		preview_label.add_theme_color_override("font_color", GOLD)
		_invalidate_trade_execution()
		return
	if not _begin_long_action(
		"trade_execution",
		"EXECUTING TRADE",
		"Applying the certified transaction to the isolated V3 franchise...",
		[
			"Rechecking the fresh trade preview and working-save fingerprint...",
			"Applying the production transaction and CBA engines...",
			"Persisting rosters, contracts, and asset ledgers...",
			"Reloading the V3 checkpoint and verifying the trade...",
			"Confirming the protected V2 checkpoint is unchanged...",
		]
	):
		preview_label.text = "Another franchise-changing action is already running."
		preview_label.add_theme_color_override("font_color", GOLD)
		return

	var request_payload: Dictionary = latest_preview_request_payload.duplicate(true)
	request_payload["expected_package_fingerprint"] = latest_preview_fingerprint
	request_payload["expected_working_save_sha256"] = latest_preview_working_sha
	execute_in_flight = true
	execute_button.disabled = true
	preview_button.disabled = true
	preview_label.text = "Executing through the production transaction engine, then verifying the V3 save and protected V2 hash..."
	preview_label.add_theme_color_override("font_color", ACCENT)
	var headers := PackedStringArray(["Content-Type: application/json"])
	var error := execute_request.request(TRADE_EXECUTE_URL, headers, HTTPClient.METHOD_POST, JSON.stringify(request_payload))
	if error != OK:
		_finish_long_action("trade_execution", false, "Trade execution request could not start.")
		execute_in_flight = false
		preview_button.disabled = false
		preview_label.text = "Could not start trade execution."
		preview_label.add_theme_color_override("font_color", BAD)
		_invalidate_trade_execution()


func _on_execute_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	_finish_long_action(
		"trade_execution",
		result == HTTPRequest.RESULT_SUCCESS and response_code == 200,
		"Trade execution completed." if result == HTTPRequest.RESULT_SUCCESS and response_code == 200 else "Trade execution ended with an error."
	)
	execute_in_flight = false
	preview_button.disabled = false
	var raw_payload = JSON.parse_string(body.get_string_from_utf8())
	if result != HTTPRequest.RESULT_SUCCESS or typeof(raw_payload) != TYPE_DICTIONARY:
		preview_label.text = "Trade execution request failed before a valid bridge response was received."
		preview_label.add_theme_color_override("font_color", BAD)
		_invalidate_trade_execution()
		return

	if response_code != 200:
		var detail := str(raw_payload.get("detail", raw_payload.get("error", "Trade execution failed.")))
		if bool(raw_payload.get("rollback_performed", false)):
			detail += "\nRollback: %s" % ("VERIFIED" if bool(raw_payload.get("rollback_verified", false)) else "REQUIRES REVIEW")
		if str(raw_payload.get("error", "")) == "stale_trade_preview":
			detail += "\nRun PREVIEW LEGALITY again before retrying."
		preview_label.text = detail
		preview_label.add_theme_color_override("font_color", GOLD if response_code == 409 else BAD)
		_invalidate_trade_execution()
		return

	if not bool(raw_payload.get("persisted_after_reload", false)) or not bool(raw_payload.get("active_v2_unchanged", false)):
		preview_label.text = "TRADE SAFETY FAILURE • bridge did not confirm reload persistence and V2 protection."
		preview_label.add_theme_color_override("font_color", BAD)
		_invalidate_trade_execution()
		return

	var transaction_id := str(raw_payload.get("transaction_id", ""))
	preview_label.text = "TRADE COMMITTED • %s\nPersisted after reload • V3 working save updated • protected V2 unchanged\nRecovery checkpoint: %s" % [
		transaction_id,
		str(raw_payload.get("recovery_checkpoint_path", ""))
	]
	preview_label.add_theme_color_override("font_color", GOOD)
	status_label.text = "LIVE • %s committed successfully • refreshing transaction foundation..." % transaction_id
	status_label.add_theme_color_override("font_color", GOOD)
	selected_active_players.clear()
	selected_active_picks.clear()
	selected_partner_players.clear()
	selected_partner_picks.clear()
	pending_proposal = {}
	_invalidate_trade_execution()
	_request_foundation()


func _join_assets(values: Array) -> String:
	var names: Array = []
	for value in values:
		names.append(str(value))
	return " + ".join(names) if not names.is_empty() else "None"


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


func _divider() -> HSeparator:
	var line := HSeparator.new()
	line.add_theme_constant_override("separation", 7)
	line.modulate = Color(1, 1, 1, 0.12)
	return line


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
