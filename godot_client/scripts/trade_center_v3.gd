extends Control

# Batch 22 franchise presentation macro
# 50B-R2E premium Trade Negotiation Room visual pass
# 50B-R2E.0.4 lazy visual dependency hotfix
# 50B-R2E.0.6 stable asset-panel compiler hotfix
# 50B-R2E.1 visual density + empty-state polish

const DesignSystemV3 = preload("res://scripts/design_system_v3.gd")
const TeamBrandingV3 = preload("res://scripts/team_branding_v3.gd")
const PageIdentityV3 = preload("res://scripts/page_identity_v3.gd")
const TradeAssetCardV3 = preload("res://scripts/trade_asset_card_v3.gd")
const TradePackageStageV3 = preload("res://scripts/trade_package_stage_v3.gd")
const TeamLogoV3 = preload("res://scripts/team_logo_v3.gd")

const FOUNDATION_URL := "http://127.0.0.1:8765/v3/transaction-foundation?trade_finder=1"
const TEAM_ASSETS_URL := "http://127.0.0.1:8765/v3/trade/team-assets"
const TRADE_PREVIEW_URL := "http://127.0.0.1:8765/v3/trade/preview"
const TRADE_EXECUTE_URL := "http://127.0.0.1:8765/v3/trade/execute"

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
var package_stage: Control
var active_asset_logo: Control
var partner_asset_logo: Control
var active_color = TEAM_PRIMARY
var active_secondary = DesignSystemV3.TEXT
var negotiation_hero: Control
var active_assets_panel: PanelContainer
var partner_assets_panel: PanelContainer
var trade_finder_surface: PanelContainer
var trade_finder_scroll: ScrollContainer

var foundation_request: HTTPRequest
var partner_assets_request: HTTPRequest
var preview_request: HTTPRequest
var execute_request: HTTPRequest

var brand_heading: Label
var active_assets_heading: Label
var primary_buttons: Array = []
var package_state: Label
var outgoing_assets_label: Label
var incoming_assets_label: Label
var pending_preview_request_payload := {}

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


func apply_team_brand(_team: String, primary: Color, _secondary: Color) -> void:
	active_color = primary
	active_secondary = _secondary
	if page_identity != null:
		page_identity.configure(_team, primary, _secondary)
	if page_brand_bar != null:
		page_brand_bar.color = primary
	if brand_heading != null:
		brand_heading.add_theme_color_override("font_color", TeamBrandingV3.hover_color(primary))
	if active_assets_heading != null:
		active_assets_heading.add_theme_color_override("font_color", TeamBrandingV3.hover_color(primary))
	if active_assets_panel != null and active_assets_panel.has_method("configure"):
		active_assets_panel.configure(primary, 16)
	for button in primary_buttons:
		TeamBrandingV3.apply_primary_button(button, primary)
	if package_stage != null:
		_refresh_package_stage()
		_render_active_assets()
	_refresh_negotiation_hero()


func _update_package_state() -> void:
	if package_state == null:
		return
	if execute_in_flight:
		package_state.text = "TRADE IN PROGRESS"
	elif not execute_button.disabled and latest_preview_fingerprint != "" and latest_preview_working_sha != "":
		package_state.text = "READY TO CONFIRM"
	elif preview_label.get_theme_color("font_color") in [BAD, GOLD]:
		package_state.text = "PREVIEW REJECTED"
	else:
		package_state.text = "PACKAGE NEEDS PREVIEW"
	if package_stage != null:
		package_stage.set_preview_state(package_state.text, GOOD if package_state.text == "READY TO CONFIRM" else GOLD)
	_refresh_negotiation_hero()


func _display(value: Variant, fallback: String = "N/A") -> String:
	return fallback if value == null or str(value).strip_edges() == "" else str(value)


func _dict(value: Variant) -> Dictionary:
	return value if typeof(value) == TYPE_DICTIONARY else {}


func _array(value: Variant) -> Array:
	return value if typeof(value) == TYPE_ARRAY else []


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


func _new_premium_surface() -> PanelContainer:
	var script: Variant = load("res://scripts/premium_surface_v3.gd")
	return script.new()


func _new_trade_negotiation_hero() -> PanelContainer:
	var script: Variant = load("res://scripts/trade_negotiation_hero_v3.gd")
	return script.new()


func _premium_chip(text_value: String, tone: Color, font_size: int = 9) -> Label:
	var script: Variant = load("res://scripts/premium_ui_v3.gd")
	return script.chip(text_value, tone, font_size)


func _build_ui() -> void:
	var page_scroll := ScrollContainer.new()
	page_scroll.name = "TradeCenterPageScroll"
	page_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	page_scroll.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	page_scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	page_scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	add_child(page_scroll)

	var outer := MarginContainer.new()
	outer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_set_margins(outer, 28, 24, 28, 120)
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
	brand_heading = _small_label("FRONT OFFICE • NEGOTIATION ROOM", TEAM_PRIMARY_HOVER)
	titles.add_child(brand_heading)

	var title := Label.new()
	title.text = "TRADE CENTER"
	title.add_theme_color_override("font_color", TEXT)
	title.add_theme_font_size_override("font_size", 36)
	titles.add_child(title)

	var subtitle := Label.new()
	subtitle.text = "Build leverage, compare value, and take a legal package from conversation to commitment."
	subtitle.add_theme_color_override("font_color", MUTED)
	subtitle.add_theme_font_size_override("font_size", 12)
	titles.add_child(subtitle)

	page_identity = PageIdentityV3.new()
	header.add_child(page_identity)

	var refresh_button := _action_button("REFRESH MARKET", false)
	refresh_button.pressed.connect(_request_foundation)
	header.add_child(refresh_button)

	var safety := _new_premium_surface()
	safety.name = "TradeMarketStatusSurface"
	safety.custom_minimum_size = Vector2(0, 58)
	safety.configure(ACCENT, 14)
	var safety_body := _card_body(safety, 12)
	status_label = Label.new()
	status_label.text = "Loading live trade market and asset ownership..."
	status_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	status_label.add_theme_color_override("font_color", MUTED)
	status_label.add_theme_font_size_override("font_size", 11)
	safety_body.add_child(status_label)
	column.add_child(safety)

	negotiation_hero = _new_trade_negotiation_hero()
	negotiation_hero.name = "TradeNegotiationHero"
	column.add_child(negotiation_hero)
	negotiation_hero.configure("", "", [], [], [], [], "BUILD YOUR PACKAGE")

	package_stage = TradePackageStageV3.new()
	column.add_child(package_stage)
	package_stage.configure("", "", [], [], [], [])
	package_stage.visible = false

	trade_finder_surface = _new_premium_surface()
	trade_finder_surface.name = "TradeFinderPremiumSurface"
	trade_finder_surface.custom_minimum_size = Vector2(0, 128)
	var finder_card := trade_finder_surface
	finder_card.configure(GOLD, 18)
	var finder_body := _card_body(finder_card, 16)
	var finder_header := HBoxContainer.new()
	finder_header.add_child(_section_title("TRADE FINDER • LIVE PROPOSALS"))
	var finder_spacer := Control.new()
	finder_spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	finder_header.add_child(finder_spacer)
	finder_header.add_child(_premium_chip("FRONT OFFICE AI", GOOD, 10))
	finder_body.add_child(finder_header)

	var finder_hint := Label.new()
	finder_hint.text = "Open a front-office proposal below or build your own package. Every deal still passes the same legality and CBA preview before execution."
	finder_hint.add_theme_color_override("font_color", MUTED)
	finder_hint.add_theme_font_size_override("font_size", 10)
	finder_body.add_child(finder_hint)

	trade_finder_scroll = ScrollContainer.new()
	trade_finder_scroll.name = "TradeFinderScroll"
	trade_finder_scroll.custom_minimum_size = Vector2(0, 46)
	trade_finder_scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	finder_body.add_child(trade_finder_scroll)
	var proposal_scroll := trade_finder_scroll

	proposal_rows = VBoxContainer.new()
	proposal_rows.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	proposal_rows.add_theme_constant_override("separation", 5)
	proposal_scroll.add_child(proposal_rows)

	var builder_row := HBoxContainer.new()
	builder_row.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	builder_row.add_theme_constant_override("separation", 12)
	column.add_child(builder_row)

	active_assets_panel = _asset_panel("YOUR ASSETS", true)
	active_assets_panel.custom_minimum_size = Vector2(345, 560)
	active_assets_panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	builder_row.add_child(active_assets_panel)

	var command_card := _new_premium_surface()
	command_card.name = "TradePackageControlSurface"
	command_card.custom_minimum_size = Vector2(280, 560)
	command_card.configure(ACCENT, 18)
	var command_body := _card_body(command_card, 16)
	command_body.add_child(_premium_chip("DEAL DESK", GOLD, 10))
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
	outgoing_assets_label = _small_label("SEND • None selected", MUTED)
	outgoing_assets_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	command_body.add_child(outgoing_assets_label)
	incoming_assets_label = _small_label("GET • None selected", MUTED)
	incoming_assets_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	command_body.add_child(incoming_assets_label)
	package_state = _small_label("PACKAGE NEEDS PREVIEW", GOLD)
	command_body.add_child(package_state)

	var control_spacer := Control.new()
	control_spacer.size_flags_vertical = Control.SIZE_EXPAND_FILL
	command_body.add_child(control_spacer)

	preview_button = _action_button("PREVIEW LEGALITY", true)
	preview_button.disabled = true
	preview_button.pressed.connect(_request_trade_preview)
	command_body.add_child(preview_button)

	execute_button = _action_button("EXECUTE TRADE", true)
	execute_button.disabled = true
	execute_button.pressed.connect(_confirm_execute_trade)
	command_body.add_child(execute_button)

	var locked := Label.new()
	locked.text = "Preview checks contract, salary, and draft-right rules. Execution requires a valid preview and your confirmation."
	locked.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	locked.add_theme_color_override("font_color", MUTED)
	locked.add_theme_font_size_override("font_size", 9)
	command_body.add_child(locked)
	builder_row.add_child(command_card)

	partner_assets_panel = _asset_panel("PARTNER ASSETS", false)
	partner_assets_panel.custom_minimum_size = Vector2(345, 560)
	partner_assets_panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	builder_row.add_child(partner_assets_panel)

	var preview_card := _new_premium_surface()
	preview_card.name = "TradeLegalityDeskSurface"
	preview_card.custom_minimum_size = Vector2(0, 145)
	preview_card.configure(GOOD, 18)
	var preview_body := _card_body(preview_card, 16)
	var preview_header := HBoxContainer.new()
	preview_header.add_child(_section_title("DEAL DESK • LEGALITY + FINANCIAL PREVIEW"))
	var preview_spacer := Control.new()
	preview_spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	preview_header.add_child(preview_spacer)
	preview_header.add_child(_premium_chip("VERIFY BEFORE COMMIT", ACCENT, 10))
	preview_body.add_child(preview_header)

	preview_label = Label.new()
	preview_label.text = "Build a package and select PREVIEW LEGALITY."
	preview_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	preview_label.add_theme_color_override("font_color", MUTED)
	preview_label.add_theme_font_size_override("font_size", 11)
	preview_body.add_child(preview_label)
	var rule_rail := HBoxContainer.new()
	rule_rail.add_theme_constant_override("separation", 7)
	preview_body.add_child(rule_rail)
	for rule_name in ["SALARY MATCH", "DRAFT RIGHTS", "CONTRACTS", "CBA RULES"]:
		rule_rail.add_child(_premium_chip(rule_name, ACCENT, 8))
	column.add_child(preview_card)
	column.add_child(finder_card)

	execute_dialog = ConfirmationDialog.new()
	execute_dialog.title = "Confirm franchise trade"
	execute_dialog.dialog_text = "Commit this trade to your franchise?"
	execute_dialog.confirmed.connect(_execute_trade)
	add_child(execute_dialog)
	execute_dialog.get_ok_button().text = "EXECUTE TRADE"


func _asset_panel(title_text: String, active_side: bool) -> PanelContainer:
	var card := _card(Vector2(0, 0))
	var body := _card_body(card, 14)
	var side_color := TEAM_PRIMARY_HOVER if active_side else ACCENT
	var side_heading := _small_label("ACTIVE FRANCHISE" if active_side else "TRADE PARTNER", side_color)
	if active_side:
		active_assets_heading = side_heading
	var identity = HBoxContainer.new()
	identity.add_theme_constant_override("separation", 8)
	body.add_child(identity)
	var logo = TeamLogoV3.new()
	logo.custom_minimum_size = Vector2(58, 58)
	identity.add_child(logo)
	if active_side:
		active_asset_logo = logo
	else:
		partner_asset_logo = logo
	var titles = VBoxContainer.new()
	titles.alignment = BoxContainer.ALIGNMENT_CENTER
	titles.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	identity.add_child(titles)
	titles.add_child(side_heading)
	titles.add_child(_section_title(title_text))

	var hint := Label.new()
	hint.text = "Select players and exact draft-right assets to include."
	hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	hint.add_theme_color_override("font_color", MUTED)
	hint.add_theme_font_size_override("font_size", 9)
	body.add_child(hint)

	var scroll := ScrollContainer.new()
	scroll.name = "OutgoingAssetsScroll" if active_side else "IncomingAssetsScroll"
	scroll.custom_minimum_size = Vector2(0, 400)
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
	_invalidate_trade_execution()
	if foundation_request == null:
		return
	if foundation_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	status_label.text = "Scanning live front offices, roster assets, and draft capital..."
	status_label.add_theme_color_override("font_color", ACCENT)
	preview_button.disabled = true
	var error := foundation_request.request(FOUNDATION_URL)
	if error != OK:
		status_label.text = "Could not start the transaction-foundation request."
		status_label.add_theme_color_override("font_color", BAD)


func _on_foundation_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	_invalidate_trade_execution()
	preview_button.disabled = true
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
	partner_codes = _array(foundation_payload.get("teams"))
	proposals = _array(_dict(foundation_payload.get("trade_finder")).get("proposals"))
	_render_active_assets()
	_render_proposals()
	_populate_partner_selector()

	var finder := _dict(foundation_payload.get("trade_finder"))
	status_label.text = "LIVE MARKET • %s • %s legal packages • %s proposal(s) • %.2fs search" % [
		active_team,
		str(finder.get("legal_packages", 0)),
		str(proposals.size()),
		float(finder.get("search_elapsed_seconds", 0.0))
	]
	status_label.add_theme_color_override("font_color", GOOD)
	_refresh_package_stage()


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
	partner_payload = {}
	_refresh_package_stage()
	_invalidate_trade_execution()
	preview_button.disabled = true
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
	_invalidate_trade_execution()
	preview_button.disabled = true
	if result != HTTPRequest.RESULT_SUCCESS or response_code != 200:
		status_label.text = "Partner asset request failed • HTTP %s" % response_code
		status_label.add_theme_color_override("font_color", BAD)
		return
	var raw_payload = JSON.parse_string(body.get_string_from_utf8())
	if typeof(raw_payload) != TYPE_DICTIONARY:
		return
	partner_payload = raw_payload
	if partner_assets_panel != null and partner_assets_panel.has_method("configure"):
		var partner_tone: Color = TeamBrandingV3.palette(str(partner_payload.get("team", ""))).get("primary", ACCENT)
		partner_assets_panel.configure(partner_tone, 16)
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
	var players: Array = _array(_dict(foundation_payload.get("trade_assets")).get("players"))
	var picks: Array = _array(_dict(foundation_payload.get("draft_assets")).get("owned"))
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
	var players: Array = _array(partner_payload.get("players"))
	var picks: Array = _array(partner_payload.get("picks"))
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
	var box = TradeAssetCardV3.new()
	var partner_color: Color = TeamBrandingV3.palette(str(partner_payload.get("team", ""))).get("primary", ACCENT)
	box.configure(player_data, _selection_dict(kind).has(player_id), active_color if kind == "active_player" else partner_color)
	box.toggled.connect(_on_asset_toggled.bind(kind, player_id))
	return box


func _pick_checkbox(pick_data: Dictionary, kind: String) -> CheckBox:
	var asset_id := str(pick_data.get("asset_id", ""))
	var display := str(pick_data.get("display_name", ""))
	if display == "":
		display = "%s R%s • %s" % [str(pick_data.get("draft_year", "")), str(pick_data.get("round", "")), str(pick_data.get("origin_team", ""))]
	var readiness := "READY" if bool(pick_data.get("engine_ready", false)) else "REVIEW"
	var box := CheckBox.new()
	box.name = "TradePick_" + asset_id
	box.set_meta("asset_id", asset_id)
	box.flat = false
	box.custom_minimum_size = Vector2(0, 66)
	box.add_theme_stylebox_override("normal", _box(Color(GOLD, 0.07), 10, Color(GOLD, 0.34)))
	box.add_theme_stylebox_override("hover", _box(Color(GOLD, 0.12), 10, Color(GOLD, 0.62)))
	box.add_theme_stylebox_override("pressed", _box(Color(GOLD, 0.16), 10, GOLD))
	box.text = "DRAFT CAPITAL  •  %s  •  %s" % [display, readiness]
	box.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	box.tooltip_text = box.text
	box.button_pressed = _selection_dict(kind).has(asset_id)
	box.add_theme_color_override("font_color", TEXT if readiness == "READY" else GOLD)
	box.add_theme_font_size_override("font_size", 11)
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
	pending_preview_request_payload = {}
	latest_preview_fingerprint = ""
	latest_preview_working_sha = ""
	latest_preview_request_payload = {}
	execute_button.disabled = true
	_update_package_state()


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
	outgoing_assets_label.text = "SEND • " + _selected_asset_names(selected_active_players, selected_active_picks, _array(_dict(foundation_payload.get("trade_assets")).get("players")), _array(_dict(foundation_payload.get("draft_assets")).get("owned")))
	incoming_assets_label.text = "GET • " + _selected_asset_names(selected_partner_players, selected_partner_picks, _array(partner_payload.get("players")), _array(partner_payload.get("picks")))
	preview_button.disabled = execute_in_flight or outgoing_count == 0 or incoming_count == 0 or partner_payload.is_empty()
	preview_label.text = "Package changed. Run a fresh legality preview before execution."
	preview_label.add_theme_color_override("font_color", MUTED)
	_refresh_package_stage()
	_invalidate_trade_execution()


func _refresh_package_stage() -> void:
	if package_stage == null:
		return
	var has_assets := (
		not selected_active_players.is_empty()
		or not selected_partner_players.is_empty()
		or not selected_active_picks.is_empty()
		or not selected_partner_picks.is_empty()
	)
	package_stage.visible = has_assets
	var partner = partner_selector.get_item_text(partner_selector.selected) if partner_selector != null and partner_selector.item_count > 0 else ""
	package_stage.configure(
		active_team, partner,
		_selected_asset_rows(selected_active_players, _array(_dict(foundation_payload.get("trade_assets")).get("players")), "player_id"),
		_selected_asset_rows(selected_partner_players, _array(partner_payload.get("players")), "player_id"),
		_selected_asset_rows(selected_active_picks, _array(_dict(foundation_payload.get("draft_assets")).get("owned")), "asset_id"),
		_selected_asset_rows(selected_partner_picks, _array(partner_payload.get("picks")), "asset_id")
	)
	if active_asset_logo != null:
		active_asset_logo.configure(active_team)
	if partner_asset_logo != null:
		partner_asset_logo.configure(partner)
	if package_state != null:
		package_stage.set_preview_state(package_state.text, GOOD if package_state.text == "READY TO CONFIRM" else GOLD)
	_refresh_negotiation_hero()


func _refresh_negotiation_hero() -> void:
	if negotiation_hero == null:
		return
	var partner := ""
	if partner_selector != null and partner_selector.item_count > 0:
		partner = partner_selector.get_item_text(partner_selector.selected)
	var state_text := "BUILD YOUR PACKAGE"
	if package_state != null:
		state_text = package_state.text
	negotiation_hero.configure(
		active_team,
		partner,
		_selected_asset_rows(selected_active_players, _array(_dict(foundation_payload.get("trade_assets")).get("players")), "player_id"),
		_selected_asset_rows(selected_partner_players, _array(partner_payload.get("players")), "player_id"),
		_selected_asset_rows(selected_active_picks, _array(_dict(foundation_payload.get("draft_assets")).get("owned")), "asset_id"),
		_selected_asset_rows(selected_partner_picks, _array(partner_payload.get("picks")), "asset_id"),
		state_text
	)


func _selected_asset_rows(selection: Dictionary, rows: Array, id_key: String) -> Array:
	var result: Array = []
	for id in _selected_ids(selection):
		var found = false
		for raw in rows:
			if raw is Dictionary and str(raw.get(id_key, "")) == id:
				result.append(raw)
				found = true
				break
		if not found:
			result.append({id_key: id, "name": id, "display_name": id})
	return result


func _selected_asset_names(players: Dictionary, picks: Dictionary, player_rows: Array, pick_rows: Array) -> String:
	var names: Array = []
	for id in _selected_ids(players):
		var name := str(id)
		for raw in player_rows:
			var row := _dict(raw)
			if _display(row.get("player_id"), "") == id:
				name = _display(row.get("name"), id)
				break
		names.append(name)
	for id in _selected_ids(picks):
		var name := str(id)
		for raw in pick_rows:
			var row := _dict(raw)
			if _display(row.get("asset_id"), "") == id:
				name = _display(row.get("display_name"), id)
				break
		names.append(name)
	return " + ".join(names) if not names.is_empty() else "None selected"


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
		if trade_finder_surface != null:
			trade_finder_surface.custom_minimum_size = Vector2(0, 128)
		if trade_finder_scroll != null:
			trade_finder_scroll.custom_minimum_size = Vector2(0, 46)
		var empty := Label.new()
		empty.text = "No legal front-office proposals cleared this search window. Refresh Market to scan again."
		empty.add_theme_color_override("font_color", MUTED)
		empty.add_theme_font_size_override("font_size", 11)
		proposal_rows.add_child(empty)
		return

	if trade_finder_surface != null:
		trade_finder_surface.custom_minimum_size = Vector2(0, 225)
	if trade_finder_scroll != null:
		trade_finder_scroll.custom_minimum_size = Vector2(0, 180)

	for raw_proposal in proposals:
		if typeof(raw_proposal) != TYPE_DICTIONARY:
			continue
		var proposal: Dictionary = raw_proposal
		var partner := str(proposal.get("partner_team", ""))
		var response := str(proposal.get("response_label", proposal.get("cpu_response", "OPEN")))
		var deal_type := str(proposal.get("deal_type", "proposal")).replace("_", " ").to_upper()
		var team_color: Color = TeamBrandingV3.palette(partner).get("primary", ACCENT)
		var response_tone := _proposal_response_tone(response)

		var button := Button.new()
		button.custom_minimum_size = Vector2(0, 104)
		button.name = "TradeFinderProposal_" + partner
		button.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
		button.alignment = HORIZONTAL_ALIGNMENT_LEFT
		button.text = "%s  •  %s  •  %s\nRECEIVE  %s\nSEND       %s" % [
			partner,
			response.to_upper(),
			deal_type,
			_join_assets(proposal.get("incoming", [])),
			_join_assets(proposal.get("outgoing", []))
		]
		button.tooltip_text = button.text
		button.add_theme_color_override("font_color", TEXT)
		button.add_theme_color_override("font_hover_color", Color.WHITE)
		button.add_theme_font_size_override("font_size", 12)
		var normal = _box(Color(team_color, 0.075), 14, Color(team_color, 0.42))
		normal.content_margin_left = 92
		normal.content_margin_right = 118
		var hover = _box(Color(team_color, 0.14), 14, Color(team_color, 0.82))
		hover.content_margin_left = 92
		hover.content_margin_right = 118
		button.add_theme_stylebox_override("normal", normal)
		button.add_theme_stylebox_override("hover", hover)
		button.add_theme_stylebox_override("pressed", hover)

		var logo = TeamLogoV3.new()
		logo.position = Vector2(14, 14)
		logo.size = Vector2(64, 76)
		button.add_child(logo)
		logo.configure(partner)

		var response_chip := _premium_chip(response.to_upper(), response_tone, 9)
		response_chip.mouse_filter = Control.MOUSE_FILTER_IGNORE
		response_chip.set_anchors_preset(Control.PRESET_TOP_RIGHT)
		response_chip.offset_left = -112.0
		response_chip.offset_top = 14.0
		response_chip.offset_right = -14.0
		response_chip.offset_bottom = 42.0
		button.add_child(response_chip)

		button.pressed.connect(_load_proposal.bind(proposal))
		proposal_rows.add_child(button)


func _proposal_response_tone(response: String) -> Color:
	var normalized := response.to_lower()
	if "accept" in normalized or "interest" in normalized or "ready" in normalized:
		return GOOD
	if "reject" in normalized or "declin" in normalized or "block" in normalized:
		return BAD
	return GOLD


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
	pending_preview_request_payload = request_payload.duplicate(true)
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
	preview_button.disabled = execute_in_flight or selected_active_players.size() + selected_active_picks.size() == 0 or selected_partner_players.size() + selected_partner_picks.size() == 0 or partner_payload.is_empty()
	if pending_preview_request_payload.is_empty() or pending_preview_request_payload != _current_trade_request_payload():
		preview_label.text = "Package changed while preview was running. Run a fresh legality preview."
		preview_label.add_theme_color_override("font_color", MUTED)
		_invalidate_trade_execution()
		return
	latest_preview_fingerprint = ""
	latest_preview_working_sha = ""
	latest_preview_request_payload = {}
	execute_button.disabled = true
	if result != HTTPRequest.RESULT_SUCCESS:
		preview_label.text = "Trade preview request failed before the Python engine responded."
		preview_label.add_theme_color_override("font_color", BAD)
		_invalidate_trade_execution()
		return
	var raw_payload = JSON.parse_string(body.get_string_from_utf8())
	if typeof(raw_payload) != TYPE_DICTIONARY:
		preview_label.text = "Trade preview returned invalid data."
		preview_label.add_theme_color_override("font_color", BAD)
		_invalidate_trade_execution()
		return
	if response_code != 200:
		preview_label.text = str(raw_payload.get("detail", raw_payload.get("error", "Trade preview failed.")))
		preview_label.add_theme_color_override("font_color", BAD)
		_invalidate_trade_execution()
		return
	if not bool(raw_payload.get("working_save_unchanged", false)) or not bool(raw_payload.get("active_v2_unchanged", false)):
		preview_label.text = "SAFETY FAILURE • preview changed a protected checkpoint"
		preview_label.add_theme_color_override("font_color", BAD)
		_invalidate_trade_execution()
		return

	var preview: Dictionary = _dict(raw_payload.get("preview"))
	var preview_status := str(preview.get("status", "manual_review"))
	var side_a: Dictionary = _dict(preview.get("side_a"))
	var side_b: Dictionary = _dict(preview.get("side_b"))
	var issue_lines: Array = []
	for raw_check in _array(preview.get("checks")):
		if typeof(raw_check) != TYPE_DICTIONARY:
			continue
		var check: Dictionary = raw_check
		if str(check.get("status", "")).to_lower() != "pass":
			issue_lines.append("%s • %s" % [str(check.get("code", "")), str(check.get("message", ""))])
		if issue_lines.size() >= 4:
			break

	var detail := "STATUS %s • READY TO COMMIT %s\n%s sends %s • receives %s\n%s sends %s • receives %s\nFinancial %s • Contracts %s • Draft/Stepien %s" % [
		preview_status.to_upper(),
		"YES" if bool(preview.get("can_commit", false)) else "NO",
		str(side_a.get("team", active_team)),
		_money_text(side_a.get("outgoing_salary")),
		_money_text(side_a.get("incoming_salary")),
		str(side_b.get("team", "")),
		_money_text(side_b.get("outgoing_salary")),
		_money_text(side_b.get("incoming_salary")),
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

	var fingerprint := _display(preview.get("package_fingerprint"), "")
	var working_sha := _display(raw_payload.get("working_save_sha256"), "")
	if committable and fingerprint != "" and working_sha != "":
		latest_preview_fingerprint = fingerprint
		latest_preview_working_sha = working_sha
		latest_preview_request_payload = _current_trade_request_payload().duplicate(true)
		execute_button.disabled = false
		detail += "\n\nEXECUTION READY • This preview is locked to the current package."
		preview_label.text = detail
	else:
		_invalidate_trade_execution()

	_update_package_state()

func _confirm_execute_trade() -> void:
	if execute_in_flight or latest_preview_fingerprint == "" or latest_preview_working_sha == "":
		return
	var partner := str(latest_preview_request_payload.get("partner_team", ""))
	var outgoing_count: int = int(latest_preview_request_payload.get("side_a_player_ids", []).size()) + int(latest_preview_request_payload.get("side_a_pick_asset_ids", []).size())
	var incoming_count: int = int(latest_preview_request_payload.get("side_b_player_ids", []).size()) + int(latest_preview_request_payload.get("side_b_pick_asset_ids", []).size())
	execute_dialog.dialog_text = "%s ↔ %s\n\nSend %s asset(s) and receive %s asset(s).\n\nThis will commit the trade after a fresh legality check. A recovery checkpoint is created first, then the result is reloaded and verified." % [
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
		"Applying the certified transaction to your franchise...",
		[
			"Rechecking the fresh trade preview and package fingerprint...",
			"Applying the production transaction and CBA engines...",
			"Persisting rosters, contracts, and asset ledgers...",
			"Reloading the franchise and verifying the trade...",
			"Finalizing transaction safety checks...",
		]
	):
		preview_label.text = "Another franchise-changing action is already running."
		preview_label.add_theme_color_override("font_color", GOLD)
		return

	var request_payload: Dictionary = latest_preview_request_payload.duplicate(true)
	request_payload["expected_package_fingerprint"] = latest_preview_fingerprint
	request_payload["expected_working_save_sha256"] = latest_preview_working_sha
	execute_in_flight = true
	_update_package_state()
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
	preview_label.text = "TRADE COMMITTED • %s\nSaved and verified after reload. Your franchise is ready to continue." % transaction_id
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
	if typeof(value) != TYPE_INT and typeof(value) != TYPE_FLOAT:
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
