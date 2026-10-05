extends Control

# Batch 22 franchise presentation macro

const DesignSystemV3 = preload("res://scripts/design_system_v3.gd")
const TeamBrandingV3 = preload("res://scripts/team_branding_v3.gd")
const PageIdentityV3 = preload("res://scripts/page_identity_v3.gd")
const MarketPlayerCardV3 = preload("res://scripts/market_player_card_v3.gd")
const PlayerPortraitV3 = preload("res://scripts/player_portrait_v3.gd")

const MARKET_URL := "http://127.0.0.1:8765/v3/free-agency/market"
const PREVIEW_URL := "http://127.0.0.1:8765/v3/free-agency/preview"
const EXECUTE_URL := "http://127.0.0.1:8765/v3/free-agency/execute"

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

var market_request: HTTPRequest
var preview_request: HTTPRequest
var execute_request: HTTPRequest

var brand_heading: Label
var market_count: Label
var offer_state: Label
var primary_buttons: Array = []
var brand_color := TEAM_PRIMARY
var market_available := false
var pending_preview_request_payload := {}

var status_label: Label
var search_box: LineEdit
var position_filter: OptionButton
var salary_filter: OptionButton
var sort_selector: OptionButton
var load_more_button: Button
var selected_portrait: Control
var market_summary: Label
var market_snapshot_panel: PanelContainer
var visible_limit = 80
var market_rows: VBoxContainer
var market_list_scroll: ScrollContainer
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


var long_action_manager = null


func apply_team_brand(_team: String, primary: Color, _secondary: Color) -> void:
	if page_identity != null:
		page_identity.configure(_team, primary, _secondary)
	if page_brand_bar != null:
		page_brand_bar.color = primary
	brand_color = primary
	if market_snapshot_panel != null:
		market_snapshot_panel.add_theme_stylebox_override("panel", _box(Color(primary, 0.09), 14, Color(primary, 0.42)))
	if brand_heading != null:
		brand_heading.add_theme_color_override("font_color", TeamBrandingV3.hover_color(primary))
	for button in primary_buttons:
		TeamBrandingV3.apply_primary_button(button, primary)
	if market_rows != null:
		_render_market_rows()


func _update_offer_state() -> void:
	if offer_state == null:
		return
	if execute_in_flight:
		offer_state.text = "SIGNING IN PROGRESS"
	elif selected_player.is_empty():
		offer_state.text = "SELECT A PLAYER"
	elif not sign_button.disabled and latest_preview_fingerprint != "" and latest_preview_working_sha != "":
		offer_state.text = "READY TO CONFIRM"
	elif preview_label.get_theme_color("font_color") in [BAD, GOLD]:
		offer_state.text = "PREVIEW REJECTED"
	else:
		offer_state.text = "OFFER NEEDS PREVIEW"


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
	page_scroll.name = "FreeAgencyPageScroll"
	page_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	page_scroll.vertical_scroll_mode = ScrollContainer.SCROLL_MODE_AUTO
	page_scroll.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	page_scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	page_scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	add_child(page_scroll)

	var outer := MarginContainer.new()
	outer.name = "FreeAgencyOuterMargin"
	outer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	outer.size_flags_vertical = Control.SIZE_SHRINK_BEGIN
	_set_margins(outer, 28, 24, 28, 120)
	page_scroll.add_child(outer)

	var column := VBoxContainer.new()
	column.name = "FreeAgencyPageColumn"
	column.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	column.size_flags_vertical = Control.SIZE_SHRINK_BEGIN
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
	brand_heading = _small_label("FRANCHISE OPERATIONS • PLAYER MARKET", TEAM_PRIMARY_HOVER)
	titles.add_child(brand_heading)

	var title := Label.new()
	title.text = "FREE AGENCY"
	title.add_theme_color_override("font_color", TEXT)
	title.add_theme_font_size_override("font_size", 36)
	titles.add_child(title)

	var subtitle := Label.new()
	subtitle.text = "Discover your next addition. Compare players and build an offer."
	subtitle.add_theme_color_override("font_color", MUTED)
	subtitle.add_theme_font_size_override("font_size", 12)
	titles.add_child(subtitle)

	page_identity = PageIdentityV3.new()
	header.add_child(page_identity)

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

	var overview = _card(Vector2(0, 64))
	market_snapshot_panel = overview
	overview.add_theme_stylebox_override("panel", _box(Color(brand_color, 0.09), 14, Color(brand_color, 0.42)))
	var overview_body = _card_body(overview, 12)
	overview_body.add_child(_small_label("MARKET SNAPSHOT", ACCENT))
	market_summary = _small_label("Load the market to explore available talent.", TEXT)
	market_summary.name = "FreeAgencyMarketSnapshot"
	market_summary.add_theme_font_size_override("font_size", 15)
	market_summary.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	overview_body.add_child(market_summary)
	column.add_child(overview)

	var content_row := HBoxContainer.new()
	content_row.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	content_row.add_theme_constant_override("separation", 14)
	column.add_child(content_row)

	var market_card := _card(Vector2(540, 690))
	market_card.add_theme_stylebox_override("panel", _box(PANEL, 16, Color(ACCENT, 0.46)))
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

	var discovery_filters = HBoxContainer.new()
	discovery_filters.add_theme_constant_override("separation", 8)
	market_body.add_child(discovery_filters)
	sort_selector = OptionButton.new()
	sort_selector.name = "MarketSort"
	sort_selector.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	for value in ["Market order", "Highest overall", "Lowest salary", "Youngest first"]:
		sort_selector.add_item(value)
	sort_selector.item_selected.connect(_on_position_filter_changed)
	discovery_filters.add_child(sort_selector)
	salary_filter = OptionButton.new()
	salary_filter.name = "MarketSalaryFilter"
	for value in ["Any reference salary", "Up to $5M", "Up to $10M", "Up to $20M", "Salary unavailable"]:
		salary_filter.add_item(value)
	salary_filter.item_selected.connect(_on_position_filter_changed)
	discovery_filters.add_child(salary_filter)

	market_count = _small_label("Market data unavailable", MUTED)
	market_body.add_child(market_count)

	var market_scroll := ScrollContainer.new()
	market_list_scroll = market_scroll
	market_scroll.name = "FreeAgencyMarketScroll"
	market_scroll.custom_minimum_size = Vector2(0, 400)
	market_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	market_scroll.vertical_scroll_mode = ScrollContainer.SCROLL_MODE_AUTO
	market_scroll.mouse_force_pass_scroll_events = true
	market_scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	market_scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	market_body.add_child(market_scroll)

	market_rows = VBoxContainer.new()
	market_rows.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	market_rows.add_theme_constant_override("separation", 4)
	market_scroll.add_child(market_rows)
	load_more_button = _action_button("LOAD 80 MORE PLAYERS")
	load_more_button.name = "LoadMoreMarketPlayers"
	load_more_button.visible = false
	load_more_button.pressed.connect(_load_more_players)
	market_body.add_child(load_more_button)

	var negotiation_card := _card(Vector2(340, 690))
	negotiation_card.add_theme_stylebox_override("panel", _box(PANEL, 16, Color(GOLD, 0.52)))
	var negotiation_body := _card_body(negotiation_card, 16)
	negotiation_body.add_child(_small_label("CONTRACT DESK", GOLD))
	negotiation_body.add_child(_section_title("NEGOTIATION PREVIEW"))

	offer_state = _small_label("SELECT A PLAYER", GOLD)
	negotiation_body.add_child(offer_state)

	var selected_hero = HBoxContainer.new()
	selected_hero.add_theme_constant_override("separation", 10)
	negotiation_body.add_child(selected_hero)
	selected_portrait = PlayerPortraitV3.new()
	selected_portrait.name = "NegotiationPlayerPortrait"
	selected_portrait.custom_minimum_size = Vector2(112, 86)
	selected_hero.add_child(selected_portrait)
	selected_portrait.configure({"name": "Free Agent"})
	selection_label = Label.new()
	selection_label.text = "Select a player from the market board."
	selection_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	selection_label.add_theme_color_override("font_color", TEXT)
	selection_label.add_theme_font_size_override("font_size", 13)
	selection_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	selected_hero.add_child(selection_label)

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

	sign_button = _action_button("SIGN PLAYER", true)
	sign_button.disabled = true
	sign_button.pressed.connect(_confirm_sign_player)
	negotiation_body.add_child(sign_button)

	var lock_note := Label.new()
	lock_note.text = "Reference salary is a comparison value, not an asking price or a guarantee of eligibility. Preview your offer to check contract rules. Signing requires a valid preview and confirmation."
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

	var page_bottom_spacer := Control.new()
	page_bottom_spacer.name = "FreeAgencyBottomSafeArea"
	page_bottom_spacer.custom_minimum_size = Vector2(0, 180)
	page_bottom_spacer.mouse_filter = Control.MOUSE_FILTER_IGNORE
	column.add_child(page_bottom_spacer)

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
	_invalidate_signing_execution()
	market_available = false
	visible_limit = 80
	_update_preview_button()
	free_agents = []
	_render_market_rows()
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

	if typeof(market_payload.get("players")) != TYPE_ARRAY:
		status_label.text = "Free-agency player list is unavailable. Refresh the market."
		return
	market_available = true
	free_agents = market_payload.get("players")
	var selection_found = false
	for player in free_agents:
		if player is Dictionary and not selected_player.is_empty() and str(player.get("player_id", "")) == str(selected_player.get("player_id", "")):
			selected_player = player.duplicate(true)
			selection_found = true
			break
	if not selection_found:
		selected_player = {}
		selection_label.text = "Select a player from the market board."
		selected_portrait.configure({"name": "Free Agent"})
	else:
		_update_selected_hero()
	_update_preview_button()
	var season := _dict(market_payload.get("season"))
	status_label.text = "LIVE • %s free agents • %s • Day %s • %s • working save unchanged • V2 protected" % [
		str(free_agents.size()),
		_display(season.get("label")),
		_display(season.get("day_index")),
		_display(season.get("phase")).replace("_", " ").capitalize()
	]
	status_label.add_theme_color_override("font_color", GOOD)
	_render_market_rows()


func _on_filter_changed(_value: String) -> void:
	visible_limit = 80
	_render_market_rows()
	market_list_scroll.scroll_vertical = 0


func _on_position_filter_changed(_index: int) -> void:
	visible_limit = 80
	_render_market_rows()
	market_list_scroll.scroll_vertical = 0


func _render_market_rows() -> void:
	_clear_children(market_rows)
	load_more_button.visible = false
	_update_market_snapshot()
	if not market_available:
		market_count.text = "Market data unavailable"
		market_rows.add_child(_small_label("Refresh to load the free-agent market.", MUTED))
		return
	var query := search_box.text.strip_edges().to_lower()
	var position_value := position_filter.get_item_text(position_filter.selected) if position_filter.item_count > 0 else "ALL"
	var matches: Array = []
	var total := 0
	for raw in free_agents:
		if typeof(raw) != TYPE_DICTIONARY:
			continue
		total += 1
		var name := _display(raw.get("name"))
		var position := _display(raw.get("position"))
		if query != "" and query not in name.to_lower():
			continue
		if position_value != "ALL" and position_value not in position.split("/"):
			continue
		var known_salary = typeof(raw.get("salary")) in [TYPE_INT, TYPE_FLOAT] and float(raw.get("salary")) >= 0
		if salary_filter.selected == 4 and known_salary:
			continue
		var ceiling = [0, 5000000, 10000000, 20000000, 0][salary_filter.selected]
		if ceiling > 0:
			if not known_salary or float(raw.get("salary")) > ceiling:
				continue
		matches.append(raw)
	if sort_selector.selected != 0:
		matches.sort_custom(_market_sort_before)
	var shown := mini(visible_limit, matches.size())
	load_more_button.visible = shown < matches.size()
	market_count.text = "Showing %d of %d matches" % [shown, matches.size()] if matches.size() > visible_limit or query != "" or position_value != "ALL" or salary_filter.selected != 0 else "Showing %d of %d free agents" % [shown, total]
	for player_data in matches.slice(0, shown):
		var button = MarketPlayerCardV3.new()
		var selected: bool = not selected_player.is_empty() and player_data.get("player_id") != null and player_data.get("player_id") == selected_player.get("player_id")
		market_rows.add_child(button)
		button.configure(player_data, selected, brand_color)
		button.pressed.connect(_select_player.bind(player_data))
	if shown == 0:
		market_rows.add_child(_small_label("No free agents in this market." if total == 0 else "No players match the current search/filter.", MUTED))


func _update_selected_hero() -> void:
	selected_portrait.configure(selected_player)
	selection_label.text = "%s\n%s • Age %s\nOVR %s • POT %s" % [
		_display(selected_player.get("name")),
		_display(selected_player.get("position")),
		_display(selected_player.get("age")),
		_display(selected_player.get("overall")),
		_display(selected_player.get("potential"))
	]


func _load_more_players() -> void:
	visible_limit += 80
	_render_market_rows()


func _market_sort_before(left: Dictionary, right: Dictionary) -> bool:
	var field = ["", "overall", "salary", "age"][sort_selector.selected]
	var left_value = left.get(field)
	var right_value = right.get(field)
	var left_known = typeof(left_value) in [TYPE_INT, TYPE_FLOAT]
	var right_known = typeof(right_value) in [TYPE_INT, TYPE_FLOAT]
	if left_known != right_known:
		return left_known
	if left_known and float(left_value) != float(right_value):
		return float(left_value) > float(right_value) if field == "overall" else float(left_value) < float(right_value)
	var left_name = str(left.get("name", "")).to_lower()
	var right_name = str(right.get("name", "")).to_lower()
	if left_name != right_name:
		return left_name < right_name
	return str(left.get("player_id", "")) < str(right.get("player_id", ""))


func _update_market_snapshot() -> void:
	if not market_available:
		market_summary.text = "Load the market to explore available talent."
		return
	var total = 0
	var best = null
	var lowest = null
	for player in free_agents:
		if not player is Dictionary:
			continue
		total += 1
		var rating = player.get("overall")
		if typeof(rating) in [TYPE_INT, TYPE_FLOAT] and (best == null or float(rating) > float(best)):
			best = rating
		var salary = player.get("salary")
		if typeof(salary) in [TYPE_INT, TYPE_FLOAT] and float(salary) >= 0 and (lowest == null or float(salary) < float(lowest)):
			lowest = salary
	var salary_summary = "SALARY REFERENCES UNAVAILABLE" if lowest == null else "LOWEST REFERENCE %s" % _money_text(lowest)
	market_summary.text = "%s AVAILABLE   •   TOP OVR %s   •   %s" % [total, _display(best, "--"), salary_summary]


func _display(value: Variant, fallback: String = "N/A") -> String:
	return fallback if value == null or str(value).strip_edges() == "" else str(value)


func _dict(value: Variant) -> Dictionary:
	return value if typeof(value) == TYPE_DICTIONARY else {}


func _select_player(player_data: Dictionary) -> void:
	selected_player = player_data.duplicate(true)
	var salary_value := float(selected_player.get("salary")) if typeof(selected_player.get("salary")) in [TYPE_INT, TYPE_FLOAT] else 0.0
	if salary_value <= 0.0:
		salary_value = 5000000.0
	offer_salary.text = str(int(round(salary_value)))
	offer_years.select(1)
	offer_option.select(0)
	_update_selected_hero()
	preview_label.text = "Offer changed. Run a fresh contract/CBA preview."
	preview_label.add_theme_color_override("font_color", MUTED)
	_invalidate_signing_execution()
	_update_preview_button()
	_render_market_rows()


func _invalidate_signing_execution() -> void:
	pending_preview_request_payload = {}
	latest_preview_fingerprint = ""
	latest_preview_working_sha = ""
	latest_preview_request_payload = {}
	if sign_button != null:
		sign_button.disabled = true
	_update_offer_state()


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
	preview_button.disabled = execute_in_flight or selected_player.is_empty() or not salary_valid
	_update_offer_state()


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
	pending_preview_request_payload = request_payload.duplicate(true)
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
	if pending_preview_request_payload != _current_offer_request_payload():
		preview_label.text = "Offer changed while preview was running. Run a fresh preview."
		preview_label.add_theme_color_override("font_color", MUTED)
		_invalidate_signing_execution()
		return
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

	var gate: Dictionary = _dict(raw_payload.get("contract_cba_gate"))
	var transaction: Dictionary = _dict(raw_payload.get("transaction_preview"))
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

	var fingerprint: String = _display(transaction.get("candidate_fingerprint"), "")
	var working_sha: String = _display(raw_payload.get("working_save_sha256"), "")
	if committable and fingerprint != "" and working_sha != "":
		latest_preview_fingerprint = fingerprint
		latest_preview_working_sha = working_sha
		latest_preview_request_payload = _current_offer_request_payload().duplicate(true)
		sign_button.disabled = false
		detail += "\n\nEXECUTION READY • Fresh signing token locked to the current V3 working save."
		preview_label.text = detail
		_update_offer_state()
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
	if not _begin_long_action(
		"free_agency_signing",
		"SIGNING FREE AGENT",
		"Committing the certified contract to the isolated V3 franchise...",
		[
			"Rechecking the offer preview and working-save fingerprint...",
			"Applying contract, salary-cap, and roster legality...",
			"Persisting the signing and updated market state...",
			"Reloading the V3 checkpoint and verifying the contract...",
			"Confirming protected V2 remains byte-identical...",
		]
	):
		preview_label.text = "Another franchise-changing action is already running."
		preview_label.add_theme_color_override("font_color", GOLD)
		return

	var request_payload: Dictionary = latest_preview_request_payload.duplicate(true)
	request_payload["expected_candidate_fingerprint"] = latest_preview_fingerprint
	request_payload["expected_working_save_sha256"] = latest_preview_working_sha
	execute_in_flight = true
	_update_offer_state()
	sign_button.disabled = true
	preview_button.disabled = true
	preview_label.text = "Signing through the production free-agency engine, then verifying the V3 save and protected V2 hash..."
	preview_label.add_theme_color_override("font_color", ACCENT)
	var headers := PackedStringArray(["Content-Type: application/json"])
	var error: int = execute_request.request(EXECUTE_URL, headers, HTTPClient.METHOD_POST, JSON.stringify(request_payload))
	if error != OK:
		_finish_long_action("free_agency_signing", false, "Free-agency execution request could not start.")
		execute_in_flight = false
		_update_preview_button()
		preview_label.text = "Could not start free-agency execution."
		preview_label.add_theme_color_override("font_color", BAD)
		_invalidate_signing_execution()


func _on_execute_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	_finish_long_action(
		"free_agency_signing",
		result == HTTPRequest.RESULT_SUCCESS and response_code == 200,
		"Free-agent signing completed." if result == HTTPRequest.RESULT_SUCCESS and response_code == 200 else "Free-agent signing ended with an error."
	)
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
	selected_portrait.configure({"name": "Free Agent"})
	selection_label.text = "Select a player from the market board."
	offer_salary.text = ""
	_invalidate_signing_execution()
	_request_market()


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
