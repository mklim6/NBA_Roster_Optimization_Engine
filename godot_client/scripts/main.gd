extends Control

const TradeCenterV3 = preload("res://scripts/trade_center_v3.gd")
const FreeAgencyCenterV3 = preload("res://scripts/free_agency_center_v3.gd")
const ScoutingDraftCenterV3 = preload("res://scripts/scouting_draft_center_v3.gd")
const SeasonLifecycleCenterV3 = preload("res://scripts/season_lifecycle_center_v3.gd")
const LeagueIntelligenceCenterV3 = preload("res://scripts/league_intelligence_center_v3.gd")
const FrontOfficeCenterV3 = preload("res://scripts/front_office_center_v3.gd")
const GameDayCenterV3 = preload("res://scripts/game_day_center_v3.gd")
const SaveManagerV3 = preload("res://scripts/save_manager_v3.gd")
const SettingsTutorialV3 = preload("res://scripts/settings_tutorial_v3.gd")
const RequestCoordinatorV3 = preload("res://scripts/request_coordinator_v3.gd")
const LongActionManagerV3 = preload("res://scripts/long_action_manager_v3.gd")
const DesignSystemV3 = preload("res://scripts/design_system_v3.gd")
const UiComponentsV3 = preload("res://scripts/ui_components_v3.gd")
const TeamBrandingV3 = preload("res://scripts/team_branding_v3.gd")
const FranchiseHeroArtV3 = preload("res://scripts/franchise_hero_art_v3.gd")
const UxPolishV3 = preload("res://scripts/ux_polish_v3.gd")

const BRIDGE_URL := "http://127.0.0.1:8765/health"
const SUMMARY_URL := "http://127.0.0.1:8765/v3/franchise-summary"
const ROSTER_URL := "http://127.0.0.1:8765/v3/roster"
const ROTATION_PREVIEW_URL := "http://127.0.0.1:8765/v3/rotation/preview"
const ROTATION_APPLY_URL := "http://127.0.0.1:8765/v3/rotation/apply"
const GAME_DAY_URL := "http://127.0.0.1:8765/v3/game-day"
const GAME_DAY_SIMULATE_URL := "http://127.0.0.1:8765/v3/game-day/simulate"
const INTELLIGENCE_URL := "http://127.0.0.1:8765/v3/franchise-intelligence"
const MARKET_INTELLIGENCE_URL := "http://127.0.0.1:8765/v3/market-intelligence"
const TRANSACTION_FOUNDATION_URL := "http://127.0.0.1:8765/v3/transaction-foundation"

const BG := DesignSystemV3.BG
const SIDEBAR := DesignSystemV3.SIDEBAR
const PANEL := DesignSystemV3.PANEL
const PANEL_ALT := DesignSystemV3.PANEL_ALT
const PANEL_HOVER := DesignSystemV3.PANEL_HOVER
const TEXT := DesignSystemV3.TEXT
const MUTED := DesignSystemV3.MUTED
const ACCENT := DesignSystemV3.ACCENT
const GOOD := DesignSystemV3.GOOD
const BAD := DesignSystemV3.BAD
const BORDER := DesignSystemV3.BORDER
const SOFT_BORDER := DesignSystemV3.SOFT_BORDER
const TEAM_PRIMARY := DesignSystemV3.TEAM_PRIMARY
const TEAM_PRIMARY_HOVER := DesignSystemV3.TEAM_PRIMARY_HOVER
const GOLD := DesignSystemV3.GOLD

var bridge_status: Label
var bridge_detail: Label
var retry_button: Button
var http_request: HTTPRequest
var summary_request: HTTPRequest
var roster_request: HTTPRequest
var rotation_request: HTTPRequest
var game_day_request: HTTPRequest
var game_day_simulate_request: HTTPRequest
var intelligence_request: HTTPRequest
var market_intelligence_request: HTTPRequest
var transaction_foundation_request: HTTPRequest

var home_page: Control
var roster_page: Control
var trades_page: Control
var free_agency_page: Control
var scouting_page: Control
var season_page: Control
var league_page: Control
var front_office_page: Control
var game_day_page: Control
var save_manager_page: Control
var settings_page: Control
var desktop_preferences: Dictionary = {
	"show_tutorial_on_startup": true,
	"tutorial_completed": false,
	"confirm_load": true,
	"confirm_delete": true,
	"confirm_new_franchise": true,
	"return_home_after_save_switch": true,
}
var startup_tutorial_checked := false
var current_page := "HOME"
var page_navigation_initialized := false
var request_coordinator = null
var long_action_manager = null
var long_action_overlay: Control
var long_action_title_label: Label
var long_action_detail_label: Label
var long_action_elapsed_label: Label
var long_action_spinner_label: Label
var nav_buttons := {}
var active_team_abbreviation := "CHI"
var active_team_primary := DesignSystemV3.TEAM_PRIMARY
var active_team_secondary := Color("000000")
var active_team_hover := DesignSystemV3.TEAM_PRIMARY_HOVER
var active_team_foreground := DesignSystemV3.TEXT
var branded_primary_buttons: Array = []
var background_top_band: ColorRect
var background_accent_line: ColorRect
var header_eyebrow_label: Label
var franchise_hero_art: Control
var team_card_panel: PanelContainer
var team_badge_panel: PanelContainer
var team_card_eyebrow_label: Label
var roster_payload := {}
var feature_status_labels := {}
var feature_module_labels := {}

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
	theme = DesignSystemV3.build_theme()
	request_coordinator = RequestCoordinatorV3.new()
	long_action_manager = LongActionManagerV3.new()
	long_action_manager.action_started.connect(_on_long_action_started)
	long_action_manager.action_finished.connect(_on_long_action_finished)
	_build_background()
	_build_interface()
	_build_long_action_overlay()
	_build_http_client()
	_check_bridge()


func _build_long_action_overlay() -> void:
	long_action_overlay = Control.new()
	long_action_overlay.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	long_action_overlay.mouse_filter = Control.MOUSE_FILTER_STOP
	long_action_overlay.visible = false
	add_child(long_action_overlay)
	long_action_overlay.move_to_front()

	var dim := ColorRect.new()
	dim.color = Color(0, 0, 0, 0.78)
	dim.mouse_filter = Control.MOUSE_FILTER_STOP
	long_action_overlay.add_child(dim)
	dim.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)

	var center := CenterContainer.new()
	long_action_overlay.add_child(center)
	center.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)

	var card := _card(Vector2(650, 315))
	card.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	card.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	center.add_child(card)

	var body := _card_body(card, 26)
	body.add_theme_constant_override("separation", 14)
	body.add_child(_small_label("FRANCHISE ENGINE • DURABLE ACTION", TEAM_PRIMARY_HOVER))

	long_action_title_label = Label.new()
	long_action_title_label.text = "WORKING..."
	long_action_title_label.add_theme_color_override("font_color", TEXT)
	long_action_title_label.add_theme_font_size_override("font_size", 28)
	body.add_child(long_action_title_label)

	long_action_spinner_label = Label.new()
	long_action_spinner_label.text = "●  ○  ○"
	long_action_spinner_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	long_action_spinner_label.add_theme_color_override("font_color", ACCENT)
	long_action_spinner_label.add_theme_font_size_override("font_size", 22)
	body.add_child(long_action_spinner_label)

	long_action_detail_label = Label.new()
	long_action_detail_label.text = "The production engine is working..."
	long_action_detail_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	long_action_detail_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	long_action_detail_label.add_theme_color_override("font_color", TEXT)
	long_action_detail_label.add_theme_font_size_override("font_size", 13)
	body.add_child(long_action_detail_label)

	long_action_elapsed_label = Label.new()
	long_action_elapsed_label.text = "Elapsed 0.0s"
	long_action_elapsed_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	long_action_elapsed_label.add_theme_color_override("font_color", MUTED)
	long_action_elapsed_label.add_theme_font_size_override("font_size", 11)
	body.add_child(long_action_elapsed_label)

	var safety := Label.new()
	safety.text = "The desktop stays responsive while this write runs. A second franchise-changing action is blocked until persistence and V2-protection checks finish. Do not close the app during this operation."
	safety.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	safety.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	safety.add_theme_color_override("font_color", GOLD)
	safety.add_theme_font_size_override("font_size", 10)
	body.add_child(safety)


func _on_long_action_started(snapshot: Dictionary) -> void:
	if long_action_overlay == null:
		return
	long_action_title_label.text = str(snapshot.get("title", "FRANCHISE ACTION")).to_upper()
	long_action_detail_label.text = str(snapshot.get("detail", snapshot.get("status", "Working...")))
	long_action_elapsed_label.text = "Elapsed 0.0s"
	long_action_overlay.visible = true
	long_action_overlay.move_to_front()
	UxPolishV3.animate_overlay_in(long_action_overlay)


func _on_long_action_finished(_snapshot: Dictionary) -> void:
	if long_action_overlay != null:
		long_action_overlay.visible = false


func _process(_delta: float) -> void:
	if long_action_manager == null or long_action_overlay == null or not long_action_manager.is_busy():
		return
	var elapsed := float(long_action_manager.elapsed_seconds())
	var frames := ["●  ○  ○", "○  ●  ○", "○  ○  ●"]
	long_action_spinner_label.text = frames[int(elapsed * 3.0) % frames.size()]
	long_action_detail_label.text = str(long_action_manager.status_text())
	long_action_elapsed_label.text = "Elapsed %.1fs • Safe write lock active" % elapsed


func _build_background() -> void:
	var background := ColorRect.new()
	background.color = BG
	add_child(background)
	background.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)

	background_top_band = ColorRect.new()
	background_top_band.color = Color(active_team_primary, 0.075)
	background_top_band.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(background_top_band)
	background_top_band.anchor_right = 1.0
	background_top_band.offset_bottom = 185.0

	background_accent_line = ColorRect.new()
	background_accent_line.color = active_team_primary
	background_accent_line.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(background_accent_line)
	background_accent_line.anchor_right = 1.0
	background_accent_line.offset_bottom = 3.0

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

	save_manager_page = SaveManagerV3.new()
	content_stack.add_child(save_manager_page)
	save_manager_page.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	if save_manager_page.has_signal("active_save_changed"):
		save_manager_page.connect("active_save_changed", _on_active_save_changed)

	settings_page = SettingsTutorialV3.new()
	content_stack.add_child(settings_page)
	settings_page.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	if settings_page.has_signal("preferences_changed"):
		settings_page.connect("preferences_changed", _on_desktop_preferences_changed)
	if settings_page.has_signal("tutorial_finished"):
		settings_page.connect("tutorial_finished", _on_tutorial_finished)

	roster_page = _build_roster_area()
	content_stack.add_child(roster_page)
	roster_page.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)

	game_day_page = GameDayCenterV3.new()
	content_stack.add_child(game_day_page)
	game_day_page.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)

	trades_page = TradeCenterV3.new()
	content_stack.add_child(trades_page)
	trades_page.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)

	free_agency_page = FreeAgencyCenterV3.new()
	content_stack.add_child(free_agency_page)
	free_agency_page.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)

	scouting_page = ScoutingDraftCenterV3.new()
	content_stack.add_child(scouting_page)
	scouting_page.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)

	season_page = SeasonLifecycleCenterV3.new()
	content_stack.add_child(season_page)
	season_page.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)

	league_page = LeagueIntelligenceCenterV3.new()
	content_stack.add_child(league_page)
	league_page.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)

	front_office_page = FrontOfficeCenterV3.new()
	content_stack.add_child(front_office_page)
	front_office_page.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)

	for page in [game_day_page, trades_page, free_agency_page, scouting_page, season_page]:
		if page != null and page.has_method("set_long_action_manager"):
			page.call("set_long_action_manager", long_action_manager)

	_show_page("HOME")

func _build_sidebar() -> Control:
	var sidebar_panel := PanelContainer.new()
	sidebar_panel.custom_minimum_size = Vector2(244, 0)
	sidebar_panel.add_theme_stylebox_override(
		"panel",
		DesignSystemV3.style_box(SIDEBAR, 0, SOFT_BORDER, 1, 0.12)
	)

	var margin := MarginContainer.new()
	_set_margins(margin, 18, 20, 18, 18)
	sidebar_panel.add_child(margin)

	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 6)
	margin.add_child(column)

	var brand_row := HBoxContainer.new()
	brand_row.add_theme_constant_override("separation", 12)
	column.add_child(brand_row)

	var mark := PanelContainer.new()
	mark.custom_minimum_size = Vector2(48, 48)
	mark.add_theme_stylebox_override(
		"panel",
		DesignSystemV3.style_box(
			TEAM_PRIMARY,
			DesignSystemV3.RADIUS_MD,
			TEAM_PRIMARY_HOVER,
			1,
			0.22
		)
	)
	brand_row.add_child(mark)

	var mark_label := Label.new()
	mark_label.text = "FS"
	mark_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	mark_label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	mark_label.add_theme_color_override("font_color", TEXT)
	mark_label.add_theme_font_size_override("font_size", 16)
	mark.add_child(mark_label)

	var brand_box := VBoxContainer.new()
	brand_box.add_theme_constant_override("separation", 1)
	brand_row.add_child(brand_box)

	var brand := Label.new()
	brand.text = "FRANCHISE SIMULATOR"
	brand.add_theme_color_override("font_color", TEXT)
	brand.add_theme_font_size_override("font_size", 17)
	brand_box.add_child(brand)

	var brand_detail := Label.new()
	brand_detail.text = "DESKTOP FRONT OFFICE"
	brand_detail.add_theme_color_override("font_color", MUTED)
	brand_detail.add_theme_font_size_override("font_size", 9)
	brand_box.add_child(brand_detail)

	var version := Label.new()
	version.text = "V3 • PRODUCTION ENGINE"
	version.add_theme_color_override("font_color", DesignSystemV3.ACCENT)
	version.add_theme_font_size_override("font_size", 9)
	column.add_child(version)

	var brand_spacer := Control.new()
	brand_spacer.custom_minimum_size = Vector2(0, 10)
	column.add_child(brand_spacer)

	column.add_child(UiComponentsV3.sidebar_group_label("COMMAND"))
	column.add_child(_nav_button("HOME", true))
	column.add_child(_nav_button("FRANCHISES"))

	column.add_child(UiComponentsV3.sidebar_group_label("TEAM"))
	column.add_child(_nav_button("ROSTER"))
	column.add_child(_nav_button("GAME DAY"))

	column.add_child(UiComponentsV3.sidebar_group_label("ROSTER BUILDING"))
	column.add_child(_nav_button("TRADES"))
	column.add_child(_nav_button("FREE AGENCY"))
	column.add_child(_nav_button("SCOUTING"))

	column.add_child(UiComponentsV3.sidebar_group_label("LEAGUE"))
	column.add_child(_nav_button("SEASON"))
	column.add_child(_nav_button("LEAGUE"))

	column.add_child(UiComponentsV3.sidebar_group_label("ORGANIZATION"))
	column.add_child(_nav_button("FRONT OFFICE"))
	column.add_child(_nav_button("SETTINGS"))

	var expanding_spacer := Control.new()
	expanding_spacer.size_flags_vertical = Control.SIZE_EXPAND_FILL
	column.add_child(expanding_spacer)

	var eras := _nav_button("ERAS  •  COMING IN V3")
	eras.disabled = true
	column.add_child(eras)

	var footer := Label.new()
	footer.text = "V3 working universe\nV2 release protected"
	footer.add_theme_color_override("font_color", MUTED)
	footer.add_theme_font_size_override("font_size", 10)
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

	header_eyebrow_label = Label.new()
	var eyebrow := header_eyebrow_label
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
	team_card_panel = _card(Vector2(330, 220))
	team_card_panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var card := team_card_panel
	card.add_theme_stylebox_override("panel", _box(PANEL, 16, Color(active_team_primary, 0.72)))
	franchise_hero_art = FranchiseHeroArtV3.new()
	franchise_hero_art.mouse_filter = Control.MOUSE_FILTER_IGNORE
	card.add_child(franchise_hero_art)
	var body := _card_body(card, 20)
	body.add_theme_constant_override("separation", 12)

	var top := HBoxContainer.new()
	top.add_theme_constant_override("separation", 10)
	team_card_eyebrow_label = _small_label("YOUR FRANCHISE", active_team_hover)
	top.add_child(team_card_eyebrow_label)
	var top_spacer := Control.new()
	top_spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	top.add_child(top_spacer)
	top.add_child(_pill("V3 WORKING SAVE", GOOD))
	body.add_child(top)

	var identity := HBoxContainer.new()
	identity.add_theme_constant_override("separation", 15)
	body.add_child(identity)

	team_badge_panel = PanelContainer.new()
	var badge := team_badge_panel
	badge.custom_minimum_size = Vector2(72, 72)
	badge.add_theme_stylebox_override("panel", _box(active_team_primary, 16, active_team_hover))
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
	open_game_day.pressed.connect(_show_page.bind("GAME DAY"))
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

func _build_feature_area(
	title_text: String,
	subtitle_text: String,
	section_tag: String,
	modules: Array
) -> Control:
	var outer := MarginContainer.new()
	outer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	outer.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_set_margins(outer, 34, 28, 34, 30)

	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 20)
	outer.add_child(column)

	var header := HBoxContainer.new()
	header.add_theme_constant_override("separation", 14)
	column.add_child(header)

	var titles := VBoxContainer.new()
	titles.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	titles.add_theme_constant_override("separation", 4)
	header.add_child(titles)

	var eyebrow := Label.new()
	eyebrow.text = "FRANCHISE OPERATIONS • %s" % section_tag
	eyebrow.add_theme_color_override("font_color", TEAM_PRIMARY_HOVER)
	eyebrow.add_theme_font_size_override("font_size", 10)
	titles.add_child(eyebrow)

	var title := Label.new()
	title.text = title_text
	title.add_theme_color_override("font_color", TEXT)
	title.add_theme_font_size_override("font_size", 32)
	titles.add_child(title)

	var subtitle := Label.new()
	subtitle.text = subtitle_text
	subtitle.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	subtitle.add_theme_color_override("font_color", MUTED)
	subtitle.add_theme_font_size_override("font_size", 12)
	titles.add_child(subtitle)

	header.add_child(_pill("V3 DESKTOP", TEAM_PRIMARY_HOVER))

	var hero := PanelContainer.new()
	hero.custom_minimum_size = Vector2(0, 132)
	hero.add_theme_stylebox_override("panel", _box(Color("151923"), 16, Color(TEAM_PRIMARY, 0.45)))
	column.add_child(hero)

	var hero_margin := MarginContainer.new()
	_set_margins(hero_margin, 22, 18, 22, 18)
	hero.add_child(hero_margin)

	var hero_row := HBoxContainer.new()
	hero_row.add_theme_constant_override("separation", 16)
	hero_margin.add_child(hero_row)

	var hero_text := VBoxContainer.new()
	hero_text.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	hero_text.add_theme_constant_override("separation", 6)
	hero_row.add_child(hero_text)

	hero_text.add_child(_small_label("DESKTOP MODULE", GOLD))

	var hero_title := Label.new()
	hero_title.text = "%s COMMAND CENTER" % section_tag
	hero_title.add_theme_color_override("font_color", TEXT)
	hero_title.add_theme_font_size_override("font_size", 22)
	hero_text.add_child(hero_title)

	var hero_detail := Label.new()
	hero_detail.text = "Loading live V3 franchise intelligence..."
	hero_detail.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	hero_detail.add_theme_color_override("font_color", MUTED)
	hero_detail.add_theme_font_size_override("font_size", 11)
	hero_text.add_child(hero_detail)
	feature_status_labels[section_tag] = hero_detail

	hero_row.add_child(_pill("ENGINE READY", GOOD))

	var grid := GridContainer.new()
	grid.columns = 3
	grid.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	grid.add_theme_constant_override("h_separation", 14)
	grid.add_theme_constant_override("v_separation", 14)
	column.add_child(grid)

	for raw_module in modules:
		if typeof(raw_module) != TYPE_ARRAY or raw_module.size() < 2:
			continue
		var module_title := str(raw_module[0])
		var module_detail := str(raw_module[1])

		var module_card := _card(Vector2(0, 190))
		module_card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		module_card.add_theme_stylebox_override("panel", _box(PANEL_ALT, 14, SOFT_BORDER))
		grid.add_child(module_card)

		var module_body := _card_body(module_card, 18)
		module_body.add_theme_constant_override("separation", 9)
		module_body.add_child(_small_label(section_tag, MUTED))

		var module_name := Label.new()
		module_name.text = module_title
		module_name.add_theme_color_override("font_color", TEXT)
		module_name.add_theme_font_size_override("font_size", 18)
		module_body.add_child(module_name)

		var module_description := Label.new()
		module_description.text = module_detail
		module_description.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		module_description.add_theme_color_override("font_color", MUTED)
		module_description.add_theme_font_size_override("font_size", 11)
		module_body.add_child(module_description)
		feature_module_labels["%s:%s" % [section_tag, module_title]] = module_description

		var module_spacer := Control.new()
		module_spacer.size_flags_vertical = Control.SIZE_EXPAND_FILL
		module_body.add_child(module_spacer)

		var live_section := section_tag in ["TRADES", "MARKET", "SCOUTING", "LEAGUE", "OPERATIONS"]
		module_body.add_child(
			_pill(
				"LIVE DATA" if live_section else "V3 WIRING NEXT",
				GOOD if live_section else ACCENT
			)
		)

	var workflow := PanelContainer.new()
	workflow.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	workflow.size_flags_vertical = Control.SIZE_EXPAND_FILL
	workflow.add_theme_stylebox_override("panel", _box(Color("0f151f"), 14, SOFT_BORDER))
	column.add_child(workflow)

	var workflow_margin := MarginContainer.new()
	_set_margins(workflow_margin, 20, 16, 20, 16)
	workflow.add_child(workflow_margin)

	var workflow_box := VBoxContainer.new()
	workflow_box.add_theme_constant_override("separation", 8)
	workflow_margin.add_child(workflow_box)

	workflow_box.add_child(_section_title("V3 DESKTOP ROADMAP"))

	var workflow_text := Label.new()
	workflow_text.text = "1  Visual shell\n2  Read-only live data\n3  Safe working-save actions\n4  Full feature parity validation"
	workflow_text.add_theme_color_override("font_color", MUTED)
	workflow_text.add_theme_font_size_override("font_size", 12)
	workflow_box.add_child(workflow_text)

	return outer


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

	roster_rows.add_child(
		UiComponentsV3.loading_skeleton(
			5,
			"Loading players from the V3 working checkpoint..."
		)
	)

	column.add_child(roster_card)

	var note := Label.new()
	note.text = "V3 WORKING SAVE • Rotation edits are isolated from the protected V2 release checkpoint. Cap room remains an active-roster contract estimate."
	note.add_theme_color_override("font_color", MUTED)
	note.add_theme_font_size_override("font_size", 10)
	column.add_child(note)

	return outer


func _roster_summary_card(label_text: String, value_text: String) -> Control:
	var card := _card(Vector2(0, 108))
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	card.add_theme_stylebox_override("panel", _box(PANEL_ALT, 14, SOFT_BORDER))
	var body := _card_body(card, 14)
	body.add_theme_constant_override("separation", 6)

	var accent := ColorRect.new()
	accent.custom_minimum_size = Vector2(0, 3)
	accent.color = TEAM_PRIMARY if label_text == "ROSTER" else Color(TEAM_PRIMARY, 0.34)
	accent.mouse_filter = Control.MOUSE_FILTER_IGNORE
	body.add_child(accent)

	body.add_child(
		_small_label(
			label_text,
			TEAM_PRIMARY_HOVER if label_text == "ROSTER" else MUTED
		)
	)

	var value := Label.new()
	value.text = value_text
	value.add_theme_color_override("font_color", TEXT)
	value.add_theme_font_size_override("font_size", 24)
	body.add_child(value)

	var context := Label.new()
	context.add_theme_color_override("font_color", MUTED)
	context.add_theme_font_size_override("font_size", 9)
	match label_text:
		"ROSTER":
			context.text = "ACTIVE STANDARD CONTRACTS"
		"PAYROLL":
			context.text = "ACTIVE ROSTER COMMITMENT"
		"CAP ROOM EST.":
			context.text = "LIVE FRANCHISE ESTIMATE"
		"CHEMISTRY":
			context.text = "LOCKER ROOM PULSE"
		_:
			context.text = "FRANCHISE SNAPSHOT"
	body.add_child(context)

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
	row.add_child(_roster_cell("PLAYER", 220, MUTED))
	row.add_child(_roster_cell("POS", 62, MUTED))
	row.add_child(_roster_cell("OVR", 48, MUTED, HORIZONTAL_ALIGNMENT_CENTER))
	row.add_child(_roster_cell("AGE", 44, MUTED, HORIZONTAL_ALIGNMENT_CENTER))
	row.add_child(_roster_cell("ROLE", 140, MUTED))
	row.add_child(_roster_cell("MIN", 48, MUTED, HORIZONTAL_ALIGNMENT_CENTER))
	row.add_child(_roster_cell("SALARY", 78, MUTED))
	row.add_child(_roster_cell("MORALE", 82, MUTED))
	row.add_child(_roster_cell("HEALTH", 128, MUTED))
	row.add_child(_roster_cell("PPG", 50, MUTED, HORIZONTAL_ALIGNMENT_RIGHT))
	return row


func _roster_row(player: Dictionary) -> Control:
	var panel := PanelContainer.new()
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	panel.custom_minimum_size = Vector2(0, 60)
	panel.add_theme_stylebox_override("panel", _box(PANEL_ALT, 10, SOFT_BORDER))
	panel.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	panel.mouse_filter = Control.MOUSE_FILTER_STOP
	panel.tooltip_text = "Open %s player profile" % str(player.get("name", "player"))
	panel.gui_input.connect(_on_roster_row_input.bind(player))

	var margin := MarginContainer.new()
	margin.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_set_margins(margin, 12, 8, 12, 8)
	panel.add_child(margin)

	var row := HBoxContainer.new()
	row.mouse_filter = Control.MOUSE_FILTER_IGNORE
	row.add_theme_constant_override("separation", 8)
	margin.add_child(row)

	var player_name := str(player.get("name", "Unknown"))
	var starter := bool(player.get("is_starter", false))
	var in_rotation := bool(player.get("in_rotation", false))
	var depth_state := "STARTER" if starter else ("ROTATION" if in_rotation else "RESERVE")
	var name_color := TEAM_PRIMARY_HOVER if starter else TEXT
	if starter:
		panel.add_theme_stylebox_override(
			"panel",
			_box(Color("171b23"), 10, Color(TEAM_PRIMARY, 0.60))
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

	var player_identity := HBoxContainer.new()
	player_identity.custom_minimum_size = Vector2(220, 44)
	player_identity.mouse_filter = Control.MOUSE_FILTER_IGNORE
	player_identity.add_theme_constant_override("separation", 9)

	var portrait_script = load("res://scripts/player_portrait_v3.gd")
	if portrait_script != null:
		var portrait = portrait_script.new()
		portrait.custom_minimum_size = Vector2(48, 42)
		player_identity.add_child(portrait)
		portrait.configure(player)

	var identity_copy := VBoxContainer.new()
	identity_copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	identity_copy.add_theme_constant_override("separation", 1)
	player_identity.add_child(identity_copy)

	var player_name_label := Label.new()
	player_name_label.text = player_name
	player_name_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	player_name_label.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	player_name_label.add_theme_color_override("font_color", name_color)
	player_name_label.add_theme_font_size_override("font_size", 12)
	identity_copy.add_child(player_name_label)

	var identity_meta := Label.new()
	identity_meta.text = "%s  •  %s" % [depth_state, str(player.get("development_direction", "")).to_upper()]
	identity_meta.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	identity_meta.add_theme_color_override("font_color", TEAM_PRIMARY_HOVER if starter else MUTED)
	identity_meta.add_theme_font_size_override("font_size", 9)
	identity_copy.add_child(identity_meta)

	row.add_child(player_identity)
	row.add_child(_roster_cell(str(player.get("position", "")), 62, TEXT))
	row.add_child(_roster_rating_badge(player.get("overall", null)))
	row.add_child(_roster_cell(_number_text(player.get("age", null), 1), 44, MUTED, HORIZONTAL_ALIGNMENT_CENTER))
	row.add_child(_roster_cell(str(player.get("role", "")), 140, TEXT))
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
	player_detail_overlay.name = "PlayerProfileOverlay"
	player_detail_overlay.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	player_detail_overlay.mouse_filter = Control.MOUSE_FILTER_STOP
	add_child(player_detail_overlay)
	player_detail_overlay.move_to_front()

	var dim := ColorRect.new()
	dim.color = Color(0, 0, 0, 0.78)
	dim.mouse_filter = Control.MOUSE_FILTER_STOP
	player_detail_overlay.add_child(dim)
	dim.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)

	var center := CenterContainer.new()
	center.mouse_filter = Control.MOUSE_FILTER_PASS
	player_detail_overlay.add_child(center)
	center.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)

	var card := _card(Vector2(980, 690))
	card.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	card.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	card.add_theme_stylebox_override("panel", _box(PANEL, 18, Color(TEAM_PRIMARY, 0.58)))
	center.add_child(card)

	var body := _card_body(card, 20)
	body.add_theme_constant_override("separation", 14)

	var header := HBoxContainer.new()
	header.add_theme_constant_override("separation", 14)
	body.add_child(header)

	var profile_portrait_script = load("res://scripts/player_portrait_v3.gd")
	if profile_portrait_script != null:
		var profile_portrait = profile_portrait_script.new()
		profile_portrait.custom_minimum_size = Vector2(164, 120)
		header.add_child(profile_portrait)
		profile_portrait.configure(player)

	var title_box := VBoxContainer.new()
	title_box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	title_box.add_theme_constant_override("separation", 6)
	header.add_child(title_box)

	var player_name := Label.new()
	player_name.text = str(player.get("name", "Unknown Player"))
	player_name.add_theme_color_override("font_color", TEXT)
	player_name.add_theme_font_size_override("font_size", 30)
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

	var rating_strip := HBoxContainer.new()
	rating_strip.add_theme_constant_override("separation", 8)
	rating_strip.add_child(_profile_rating_tile("OVR", player.get("overall", null)))
	rating_strip.add_child(_profile_rating_tile("POT", player.get("potential", null)))
	title_box.add_child(rating_strip)

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
	var morale_status := _display_text(morale.get("status", null), "Not evaluated")
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
	grid.add_child(_profile_stats_card(stats))

	var contract = player.get("contract", {})
	var contract_lines := [
		"Role   %s" % str(player.get("role", "")),
		"Target minutes   %s" % _number_text(player.get("target_minutes", 0), 0),
		"Salary   %s" % _display_text(contract.get("salary_display", null)),
		"Years remaining   %s" % str(contract.get("years_remaining", 0)),
		"Contract status   %s" % _pretty_phase(_display_text(contract.get("status", null))),
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
		morale_reasons = "Morale has not been evaluated for this player." if morale_status == "Not evaluated" else "No active morale concerns."

	grid.add_child(
		_detail_card(
			"MORALE",
			[
				"Status   %s" % morale_status,
				"Score   %s" % _number_text(morale.get("score", null), 1),
				"Role satisfaction   %s" % _number_text(morale.get("role_satisfaction", null), 1),
				"Expected role   %s" % _friendly_value(str(morale.get("expected_role", ""))),
				"Recent minutes   %s" % _number_text(morale.get("recent_minutes", null), 1),
				"Trade request risk   %s" % _pct_text(morale.get("trade_request_risk", null)),
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
	grid.add_child(_profile_skill_card(skills))

	var footer := Label.new()
	footer.text = "ACTIVE V3 PLAYER PROFILE • Data comes from the isolated V3 working franchise; protected V2 remains unchanged."
	footer.add_theme_color_override("font_color", MUTED)
	footer.add_theme_font_size_override("font_size", 10)
	content.add_child(footer)


# Batch 20C player profile presentation
func _profile_stats_card(stats: Dictionary) -> Control:
	var card := _card(Vector2(0, 0))
	card.name = "ProfileSeasonProduction"
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	card.add_theme_stylebox_override("panel", _box(PANEL_ALT, 12, SOFT_BORDER))
	var body := _card_body(card, 15)
	body.add_theme_constant_override("separation", 12)
	body.add_child(_small_label("SEASON PRODUCTION", TEAM_PRIMARY_HOVER))
	var metrics := HBoxContainer.new()
	metrics.add_theme_constant_override("separation", 8)
	body.add_child(metrics)
	for metric in [["PPG", "ppg"], ["RPG", "rpg"], ["APG", "apg"]]:
		metrics.add_child(_profile_stat_tile(metric[0], stats.get(metric[1], null)))
	for entry in [
		["Games / starts", "%s / %s" % [_display_text(stats.get("games_played", null)), _display_text(stats.get("games_started", null))]],
		["Minutes per game", _number_text(stats.get("mpg", null), 1)],
		["Steals / blocks", "%s / %s" % [_number_text(stats.get("spg", null), 1), _number_text(stats.get("bpg", null), 1)]],
		["Field goal", _pct_text(stats.get("fg_pct", null))],
		["Three point", _pct_text(stats.get("three_pct", null))],
		["Free throw", _pct_text(stats.get("ft_pct", null))]
	]:
		body.add_child(_profile_value_row(entry[0], entry[1]))
	return card


func _profile_stat_tile(label_text: String, value) -> Control:
	var tile := PanelContainer.new()
	tile.name = "ProfileStat" + label_text
	tile.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	tile.add_theme_stylebox_override("panel", _box(PANEL, 9, SOFT_BORDER))
	var body := _card_body(tile, 10)
	body.add_theme_constant_override("separation", 4)
	body.add_child(_small_label(label_text, MUTED))
	var number := Label.new()
	number.text = _number_text(value, 1)
	number.add_theme_font_size_override("font_size", 24)
	number.add_theme_color_override("font_color", TEXT)
	body.add_child(number)
	return tile


func _profile_value_row(label_text: String, value_text: String) -> Control:
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 12)
	var label := Label.new()
	label.text = label_text
	label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	label.add_theme_font_size_override("font_size", 11)
	label.add_theme_color_override("font_color", MUTED)
	row.add_child(label)
	var value := Label.new()
	value.text = value_text
	value.add_theme_font_size_override("font_size", 12)
	value.add_theme_color_override("font_color", TEXT)
	row.add_child(value)
	return row


func _profile_skill_card(skills: Dictionary) -> Control:
	var card := _card(Vector2(0, 0))
	card.name = "ProfileSkillRatings"
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	card.add_theme_stylebox_override("panel", _box(PANEL_ALT, 12, SOFT_BORDER))
	var body := _card_body(card, 15)
	body.add_theme_constant_override("separation", 8)
	body.add_child(_small_label("SKILL RATINGS", TEAM_PRIMARY_HOVER))
	for entry in [
		["Scoring", "scoring_rating"], ["Shooting", "shooting_rating"],
		["Playmaking", "playmaking_rating"], ["Rebounding", "rebounding_rating"],
		["Defense", "defense_rating"], ["Efficiency", "efficiency_rating"],
		["Availability", "availability_rating"]
	]:
		var rating = skills.get(entry[1], null)
		body.add_child(_profile_value_row(entry[0], _number_text(rating, 1)))
		if rating != null:
			var bar := ProgressBar.new()
			bar.name = "ProfileSkill" + entry[0]
			bar.custom_minimum_size = Vector2(0, 5)
			bar.mouse_filter = Control.MOUSE_FILTER_IGNORE
			bar.min_value = 0
			bar.max_value = 100
			bar.value = clampf(float(rating), 0, 100)
			bar.show_percentage = false
			bar.add_theme_stylebox_override("background", _box(PANEL, 3, PANEL))
			bar.add_theme_stylebox_override("fill", _box(_rating_tone(rating), 3, _rating_tone(rating)))
			body.add_child(bar)
	return card


func _unhandled_key_input(event: InputEvent) -> void:
	if event.is_action_pressed("ui_cancel") and not event.is_echo():
		if player_detail_overlay != null and is_instance_valid(player_detail_overlay):
			_close_player_detail()
			get_viewport().set_input_as_handled()


func _detail_card(title_text: String, lines: Array) -> Control:
	var card := _card(Vector2(0, 0))
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	card.add_theme_stylebox_override("panel", _box(PANEL_ALT, 12, SOFT_BORDER))
	var body := _card_body(card, 15)
	body.add_theme_constant_override("separation", 7)

	var heading_row := HBoxContainer.new()
	heading_row.add_theme_constant_override("separation", 8)
	body.add_child(heading_row)

	var accent := ColorRect.new()
	accent.custom_minimum_size = Vector2(3, 16)
	accent.color = TEAM_PRIMARY
	accent.mouse_filter = Control.MOUSE_FILTER_IGNORE
	heading_row.add_child(accent)
	heading_row.add_child(_small_label(title_text, TEAM_PRIMARY_HOVER))

	for line in lines:
		var label := Label.new()
		label.text = str(line)
		label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		label.add_theme_color_override("font_color", TEXT)
		label.add_theme_font_size_override("font_size", 11)
		body.add_child(label)

	return card


# Batch 20B roster presentation upgrade
func _rating_tone(value) -> Color:
	if value == null:
		return MUTED
	var rating := float(value)
	if rating >= 90.0:
		return GOLD
	if rating >= 85.0:
		return GOOD
	if rating >= 80.0:
		return ACCENT
	if rating >= 75.0:
		return TEAM_PRIMARY_HOVER
	return MUTED


func _roster_rating_badge(value) -> Control:
	var tone := _rating_tone(value)
	var badge := PanelContainer.new()
	badge.name = "RosterOverallBadge"
	badge.custom_minimum_size = Vector2(48, 34)
	badge.mouse_filter = Control.MOUSE_FILTER_IGNORE
	badge.add_theme_stylebox_override(
		"panel",
		_box(Color(tone, 0.14), 9, Color(tone, 0.65))
	)

	var label := Label.new()
	label.text = _number_text(value, 1)
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	label.add_theme_color_override("font_color", tone)
	label.add_theme_font_size_override("font_size", 12)
	badge.add_child(label)
	return badge


func _profile_rating_tile(label_text: String, value) -> Control:
	var tone := _rating_tone(value)
	var tile := PanelContainer.new()
	if label_text == "OVR":
		tile.name = "ProfileOverallTile"
	elif label_text == "POT":
		tile.name = "ProfilePotentialTile"
	tile.custom_minimum_size = Vector2(92, 54)
	tile.mouse_filter = Control.MOUSE_FILTER_IGNORE
	tile.add_theme_stylebox_override(
		"panel",
		_box(Color(tone, 0.11), 10, Color(tone, 0.52))
	)

	var margin := MarginContainer.new()
	_set_margins(margin, 10, 7, 10, 7)
	tile.add_child(margin)

	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 1)
	margin.add_child(column)

	var label := Label.new()
	label.text = label_text
	label.add_theme_color_override("font_color", MUTED)
	label.add_theme_font_size_override("font_size", 8)
	column.add_child(label)

	var number := Label.new()
	number.text = _number_text(value, 1)
	number.add_theme_color_override("font_color", tone)
	number.add_theme_font_size_override("font_size", 18)
	column.add_child(number)

	return tile


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


func _feature_label(key: String) -> Label:
	var value = feature_module_labels.get(key)
	return value as Label if value is Label else null


func _set_feature_text(key: String, text_value: String) -> void:
	var label := _feature_label(key)
	if label != null:
		label.text = text_value


func _market_player_lines(rows: Array, limit: int = 5) -> String:
	var lines: Array = []
	var count: int = 0
	for raw_row in rows:
		if typeof(raw_row) != TYPE_DICTIONARY:
			continue
		var row: Dictionary = raw_row
		lines.append(
			"%s • %s • OVR %s • Age %s" % [
				str(row.get("name", "")),
				str(row.get("position", "")),
				str(row.get("overall", "N/A")),
				str(row.get("age", "N/A"))
			]
		)
		count += 1
		if count >= limit:
			break
	return "\n".join(lines)


func _trade_asset_lines(rows: Array, limit: int = 5) -> String:
	var lines: Array = []
	var count: int = 0
	for raw_row in rows:
		if typeof(raw_row) != TYPE_DICTIONARY:
			continue
		var row: Dictionary = raw_row
		lines.append(
			"%s • OVR %s • %s • %s PPG" % [
				str(row.get("name", "")),
				str(row.get("overall", "N/A")),
				str(row.get("salary_display", "N/A")),
				str(row.get("ppg", 0.0))
			]
		)
		count += 1
		if count >= limit:
			break
	return "\n".join(lines)


func _asset_name_list(values: Array) -> String:
	var names: Array = []
	for value in values:
		names.append(str(value))
	return " + ".join(names) if not names.is_empty() else "None"


func _trade_proposal_lines(rows: Array, limit: int = 5) -> String:
	var lines: Array = []
	var count: int = 0
	for raw_row in rows:
		if typeof(raw_row) != TYPE_DICTIONARY:
			continue
		var row: Dictionary = raw_row
		var incoming: Array = row.get("incoming", [])
		var outgoing: Array = row.get("outgoing", [])
		lines.append(
			"%s • %s • %s\nGET  %s\nSEND %s" % [
				str(row.get("partner_team", "")),
				str(row.get("response_label", row.get("cpu_response", ""))).replace("_", " ").capitalize(),
				str(row.get("deal_type", "")),
				_asset_name_list(incoming),
				_asset_name_list(outgoing)
			]
		)
		count += 1
		if count >= limit:
			break
	return "\n\n".join(lines)


func _draft_asset_lines(rows: Array, limit: int = 7) -> String:
	var lines: Array = []
	var count: int = 0
	for raw_row in rows:
		if typeof(raw_row) != TYPE_DICTIONARY:
			continue
		var row: Dictionary = raw_row
		var readiness := "ENGINE READY" if bool(row.get("engine_ready", false)) else "REVIEW"
		lines.append(
			"%s R%s • %s • %s" % [
				str(row.get("draft_year", "")),
				str(row.get("round", "")),
				str(row.get("origin_team", "")),
				readiness
			]
		)
		count += 1
		if count >= limit:
			break
	return "\n".join(lines)


func _request_transaction_foundation(include_trade_finder: bool = true) -> void:
	if transaction_foundation_request == null:
		return
	if transaction_foundation_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		transaction_foundation_request.cancel_request()

	var url: String = TRANSACTION_FOUNDATION_URL
	url += "?trade_finder=1" if include_trade_finder else "?trade_finder=0"
	var error: int = transaction_foundation_request.request(url)
	if error != OK:
		var label = feature_status_labels.get("TRADES")
		if label is Label:
			label.text = "Transaction foundation request could not be started."


func _on_transaction_foundation_completed(
	result: int,
	response_code: int,
	_headers: PackedStringArray,
	body: PackedByteArray
) -> void:
	if result != HTTPRequest.RESULT_SUCCESS or response_code != 200:
		var failure_label = feature_status_labels.get("TRADES")
		if failure_label is Label:
			failure_label.text = "Transaction foundation unavailable • HTTP %s" % str(response_code)
		return

	var payload = JSON.parse_string(body.get_string_from_utf8())
	if typeof(payload) != TYPE_DICTIONARY:
		return

	var working_safe: bool = bool(payload.get("working_save_unchanged", false))
	var v2_safe: bool = bool(payload.get("active_v2_unchanged", false))
	if not working_safe or not v2_safe:
		var unsafe_label = feature_status_labels.get("TRADES")
		if unsafe_label is Label:
			unsafe_label.text = "TRANSACTION SAFETY CHECK FAILED"
		return

	var status_label = feature_status_labels.get("TRADES")
	if status_label is Label:
		status_label.text = "LIVE TRANSACTION FOUNDATION • READ-ONLY PREVIEWS • V2 PROTECTED"

	var finder: Dictionary = payload.get("trade_finder", {})
	var proposals: Array = finder.get("proposals", [])
	if str(finder.get("status", "")) == "ok":
		var proposal_text := _trade_proposal_lines(proposals, 5)
		if proposal_text == "":
			proposal_text = "No production Trade Finder proposals cleared this search window."
		_set_feature_text(
			"TRADES:TRADE FINDER",
			"PRODUCTION TRADE FINDER • %s TEAMS SCANNED • %s LEGAL PACKAGES\n%s" % [
				str(finder.get("teams_scanned", 0)),
				str(finder.get("legal_packages", 0)),
				proposal_text
			]
		)
	else:
		_set_feature_text(
			"TRADES:TRADE FINDER",
			"Production Trade Finder unavailable for this refresh.\n%s" % str(finder.get("detail", "No detail returned."))
		)

	var draft_assets: Dictionary = payload.get("draft_assets", {})
	var owned: Array = draft_assets.get("owned", [])
	_set_feature_text(
		"TRADES:DRAFT CAPITAL",
		"EXACT LIVE OWNERSHIP • %s ASSETS • %s ENGINE READY\n%s" % [
			str(draft_assets.get("owned_count", owned.size())),
			str(draft_assets.get("engine_ready_count", 0)),
			_draft_asset_lines(owned, 7)
		]
	)


func _request_market_intelligence() -> void:
	if market_intelligence_request == null:
		return
	if market_intelligence_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		market_intelligence_request.cancel_request()

	var error := market_intelligence_request.request(MARKET_INTELLIGENCE_URL)
	if error != OK:
		for section in ["TRADES", "MARKET"]:
			var label = feature_status_labels.get(section)
			if label is Label:
				label.text = "Live market intelligence request could not be started."


func _on_market_intelligence_completed(
	result: int,
	response_code: int,
	_headers: PackedStringArray,
	body: PackedByteArray
) -> void:
	if result != HTTPRequest.RESULT_SUCCESS or response_code != 200:
		var body_text: String = body.get_string_from_utf8()
		var failure_detail: String = "HTTP %s • request result %s" % [
			str(response_code),
			str(result)
		]
		if body_text != "":
			failure_detail += " • " + body_text.left(180).replace("\n", " ")
		print("MARKET INTELLIGENCE FAILURE: ", failure_detail)
		for section in ["TRADES", "MARKET"]:
			var failed_label = feature_status_labels.get(section)
			if failed_label is Label:
				failed_label.text = "Market intelligence unavailable • %s" % failure_detail
		return

	var payload = JSON.parse_string(body.get_string_from_utf8())
	if typeof(payload) != TYPE_DICTIONARY:
		return

	var season = payload.get("season", {})
	var context_text := "%s • League Day %s • %s" % [
		str(season.get("label", "")),
		str(season.get("day_index", "?")),
		str(season.get("phase", "")).replace("_", " ").capitalize()
	]

	for section in ["TRADES", "MARKET"]:
		var status_label = feature_status_labels.get(section)
		if status_label is Label:
			status_label.text = "LIVE V3 DATA • %s" % context_text

	var trade = payload.get("trade", {})
	var assets: Array = trade.get("assets", [])
	var financial = trade.get("financial", {})
	var draft = trade.get("draft", {})

	_set_feature_text(
		"TRADES:TRADE FINDER",
		"ACTIVE ROSTER ASSET SNAPSHOT\n%s" % _trade_asset_lines(assets, 5)
	)

	_set_feature_text(
		"TRADES:INCOMING OFFERS",
		"Incoming-offer queue is not exposed in V3 yet.\n\nPayroll %s • Cap room %s\nTax room %s • 1st apron room %s" % [
			_display_text(financial.get("payroll_display", null)),
			_display_text(financial.get("cap_room_estimate_display", null)),
			str(financial.get("tax_room_display", "N/A")),
			str(financial.get("first_apron_room_display", "N/A"))
		]
	)

	if typeof(draft) == TYPE_DICTIONARY and not draft.is_empty():
		_set_feature_text(
			"TRADES:DRAFT CAPITAL",
			"%s Draft • %s\nTarget season %s\nExact owned-pick / rights inventory will use the dedicated trade-state endpoint next." % [
				str(draft.get("draft_year", "Next")),
				str(draft.get("phase", "")).replace("_", " ").capitalize(),
				str(draft.get("target_season", ""))
			]
		)

	var free_agency = payload.get("free_agency", {})
	var free_agents: Array = free_agency.get("top_available", [])
	_set_feature_text(
		"MARKET:MARKET BOARD",
		"%s FREE AGENTS AVAILABLE\n%s" % [
			str(free_agency.get("total_available", 0)),
			_market_player_lines(free_agents, 5)
		]
	)

	_set_feature_text(
		"MARKET:NEGOTIATIONS",
		"READ-ONLY CAP + CONTRACT PREVIEW\nPayroll %s\nCap room %s\nTax room %s\n2nd apron room %s\nContract/CBA preview API online • transaction writes disabled" % [
			_display_text(financial.get("payroll_display", null)),
			_display_text(financial.get("cap_room_estimate_display", null)),
			str(financial.get("tax_room_display", "N/A")),
			str(financial.get("second_apron_room_display", "N/A"))
		]
	)

	var depth = payload.get("roster_depth", {})
	var counts = depth.get("position_counts", {})
	var thin: Array = depth.get("thinnest_positions", [])
	_set_feature_text(
		"MARKET:ROSTER PLAN",
		"POSITION DEPTH\nPG %s • SG %s • SF %s • PF %s • C %s\nThinnest current groups: %s" % [
			str(counts.get("PG", 0)),
			str(counts.get("SG", 0)),
			str(counts.get("SF", 0)),
			str(counts.get("PF", 0)),
			str(counts.get("C", 0)),
			" / ".join(thin)
		]
	)


func _request_franchise_intelligence() -> void:
	if intelligence_request == null:
		return
	if intelligence_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		intelligence_request.cancel_request()

	var error := intelligence_request.request(INTELLIGENCE_URL)
	if error != OK:
		for section in ["SCOUTING", "LEAGUE", "OPERATIONS"]:
			var label = feature_status_labels.get(section)
			if label is Label:
				label.text = "Live franchise intelligence request could not be started."


func _standings_lines(rows: Array) -> String:
	var lines: Array = []
	for row in rows:
		if typeof(row) != TYPE_DICTIONARY:
			continue
		lines.append(
			"%s  %s  %s  %s" % [
				str(row.get("rank", "")),
				str(row.get("team", "")),
				str(row.get("record", "")),
				str(row.get("streak", ""))
			]
		)
	return "\n".join(lines)


func _leader_lines(rows: Array, metric: String) -> String:
	var lines: Array = []
	for row in rows:
		if typeof(row) != TYPE_DICTIONARY:
			continue
		lines.append(
			"%s  %s  %s" % [
				str(row.get("name", "")),
				str(row.get("team", "")),
				str(row.get(metric, 0.0))
			]
		)
	return "\n".join(lines)


func _on_intelligence_completed(
	result: int,
	response_code: int,
	_headers: PackedStringArray,
	body: PackedByteArray
) -> void:
	if result != HTTPRequest.RESULT_SUCCESS or response_code != 200:
		for section in ["SCOUTING", "LEAGUE", "OPERATIONS"]:
			var failed_label = feature_status_labels.get(section)
			if failed_label is Label:
				failed_label.text = "Live franchise intelligence unavailable. Bridge restart may be required."
		return

	var payload = JSON.parse_string(body.get_string_from_utf8())
	if typeof(payload) != TYPE_DICTIONARY:
		return

	var season = payload.get("season", {})
	var season_text := "%s • League Day %s • %s" % [
		str(season.get("label", "")),
		str(season.get("day_index", "?")),
		str(season.get("phase", "")).replace("_", " ").capitalize()
	]

	for section in ["SCOUTING", "LEAGUE", "OPERATIONS"]:
		var status_label = feature_status_labels.get(section)
		if status_label is Label:
			status_label.text = "LIVE V3 DATA • %s" % season_text

	var league = payload.get("league", {})
	var east: Array = league.get("east", [])
	var west: Array = league.get("west", [])
	_set_feature_text(
		"LEAGUE:STANDINGS",
		"EAST\n%s\n\nWEST\n%s" % [
			_standings_lines(east.slice(0, 3)),
			_standings_lines(west.slice(0, 3))
		]
	)

	var leaders = league.get("leaders", {})
	_set_feature_text(
		"LEAGUE:AWARDS",
		"SCORING\n%s\n\nASSISTS\n%s" % [
			_leader_lines(leaders.get("scoring", []), "ppg"),
			_leader_lines(leaders.get("assists", []), "apg")
		]
	)

	var result_lines: Array = []
	for recent in league.get("recent_results", []):
		if typeof(recent) == TYPE_DICTIONARY:
			result_lines.append(
				"Day %s • %s" % [
					str(recent.get("day_index", "")),
					str(recent.get("display", ""))
				]
			)
	_set_feature_text(
		"LEAGUE:TRANSACTIONS",
		"RECENT LEAGUE RESULTS\n%s" % "\n".join(result_lines)
	)

	var scouting = payload.get("scouting", {})
	var draft = scouting.get("draft", {})
	if typeof(draft) == TYPE_DICTIONARY and not draft.is_empty():
		_set_feature_text(
			"SCOUTING:DRAFT BOARD",
			"%s Draft • %s\nTarget season %s\nCurrent pick index %s" % [
				str(draft.get("draft_year", "Next")),
				str(draft.get("phase", "scouting")).replace("_", " ").capitalize(),
				str(draft.get("target_season", "")),
				str(draft.get("current_pick_index", 0))
			]
		)
		var counts = scouting.get("collection_counts", {})
		var count_bits: Array = []
		if typeof(counts) == TYPE_DICTIONARY:
			for key in counts.keys():
				count_bits.append("%s %s" % [str(counts[key]), str(key).replace("_", " ")])
		_set_feature_text(
			"SCOUTING:REPORTS",
			"Live draft metadata loaded.\n%s" % (
				" • ".join(count_bits)
				if count_bits.size() > 0
				else "Detailed prospect-report collection wiring is next."
			)
		)
		_set_feature_text(
			"SCOUTING:STAFF",
			"Scouting phase: %s\nDesktop scout assignments remain protected until a dedicated write-safe endpoint is added." % str(
				draft.get("phase", "")
			).replace("_", " ").capitalize()
		)

	var front = payload.get("front_office", {})
	var chemistry = front.get("chemistry", {})
	var financial = front.get("financial", {})
	var competitive = front.get("competitive", {})
	var injured: Array = front.get("injured_players", [])
	var morale_watch: Array = front.get("morale_watch", [])
	var rotation = front.get("rotation", {})

	var health_lines: Array = [
		"Chemistry %s • %s rotation players • %.0f minutes" % [
			str(chemistry.get("score", "N/A")),
			str(rotation.get("rotation_players", "?")),
			float(rotation.get("total_minutes", 0.0))
		],
		"%s injured • %s morale watch" % [
			str(injured.size()),
			str(morale_watch.size())
		]
	]
	for player in injured.slice(0, 2):
		if typeof(player) == TYPE_DICTIONARY:
			health_lines.append(
				"%s • %s" % [
					str(player.get("name", "")),
					str(player.get("status", ""))
				]
			)
	_set_feature_text("OPERATIONS:TEAM HEALTH", "\n".join(health_lines))

	_set_feature_text(
		"OPERATIONS:FRANCHISE PLAN",
		"Record %s • %s in %s\nPayroll %s • Cap room %s\nWorking save stays isolated from V2." % [
			str(competitive.get("record", "")),
			str(competitive.get("conference_rank", "?")),
			str(competitive.get("conference", "")),
			_display_text(financial.get("payroll_display", null)),
			_display_text(financial.get("cap_room_estimate_display", null))
		]
	)

	_set_feature_text(
		"OPERATIONS:STAFF ROOM",
		"Live team state loaded for %s.\nStaff personnel controls will use a dedicated write-safe endpoint before edits are enabled." % str(
			payload.get("team_name", "Active Franchise")
		)
	)


func _page_control(page_name: String):
	match page_name:
		"HOME":
			return home_page
		"FRANCHISES":
			return save_manager_page
		"ROSTER":
			return roster_page
		"GAME DAY":
			return game_day_page
		"TRADES":
			return trades_page
		"FREE AGENCY":
			return free_agency_page
		"SCOUTING":
			return scouting_page
		"SEASON":
			return season_page
		"LEAGUE":
			return league_page
		"FRONT OFFICE":
			return front_office_page
		"SETTINGS":
			return settings_page
	return null


func _all_page_controls() -> Array:
	return [
		home_page,
		save_manager_page,
		roster_page,
		game_day_page,
		trades_page,
		free_agency_page,
		scouting_page,
		season_page,
		league_page,
		front_office_page,
		settings_page,
	]


func _show_page(page_name: String, force_refresh: bool = false) -> void:
	if page_navigation_initialized and page_name == current_page and not force_refresh:
		return

	var previous_page := current_page
	page_navigation_initialized = true
	current_page = page_name

	var target_page = _page_control(page_name)
	for page in _all_page_controls():
		if page == null:
			continue
		page.visible = page == target_page
		if page != target_page:
			page.modulate = Color(1.0, 1.0, 1.0, 1.0)

	if target_page != null and page_name != previous_page:
		UxPolishV3.animate_page_in(target_page, active_team_primary)

	for key in nav_buttons.keys():
		var button: Button = nav_buttons[key]
		_apply_nav_button_style(button, str(key) == page_name)

	if page_name == "ROSTER":
		_request_roster(force_refresh)
	elif page_name == "GAME DAY":
		if game_day_page != null and game_day_page.has_method("refresh"):
			game_day_page.call("refresh")
	elif page_name == "HOME":
		_request_franchise_summary(force_refresh)
	elif page_name == "FRANCHISES":
		if save_manager_page != null and save_manager_page.has_method("refresh"):
			save_manager_page.call("refresh")
	elif page_name == "SETTINGS":
		if settings_page != null and settings_page.has_method("refresh"):
			settings_page.call("refresh")
	elif page_name == "LEAGUE":
		if league_page != null and league_page.has_method("refresh"):
			league_page.call("refresh")
	elif page_name == "FRONT OFFICE":
		if front_office_page != null and front_office_page.has_method("refresh"):
			front_office_page.call("refresh")
	elif page_name == "SCOUTING":
		if scouting_page != null and scouting_page.has_method("refresh"):
			scouting_page.call("refresh")
	elif page_name == "SEASON":
		if season_page != null and season_page.has_method("refresh"):
			season_page.call("refresh")
	elif page_name == "TRADES":
		if trades_page != null and trades_page.has_method("refresh"):
			trades_page.call("refresh")
	elif page_name == "FREE AGENCY":
		if free_agency_page != null and free_agency_page.has_method("refresh"):
			free_agency_page.call("refresh")

func _on_active_save_changed() -> void:
	# A save switch changes the authoritative V3 working universe. Clear client
	# request reuse state before loading the destination franchise.
	if request_coordinator != null:
		request_coordinator.invalidate_all()
	if bool(desktop_preferences.get("return_home_after_save_switch", true)):
		_show_page("HOME", true)
	else:
		_show_page("FRANCHISES", true)


func _on_desktop_preferences_changed(next_preferences: Dictionary) -> void:
	desktop_preferences = next_preferences.duplicate(true)
	if save_manager_page != null and save_manager_page.has_method("apply_preferences"):
		save_manager_page.call("apply_preferences", desktop_preferences)

	if startup_tutorial_checked:
		return
	startup_tutorial_checked = true
	if bool(desktop_preferences.get("show_tutorial_on_startup", true)):
		_show_page("SETTINGS")
		if settings_page != null and settings_page.has_method("start_tutorial"):
			settings_page.call_deferred("start_tutorial", true)


func _on_tutorial_finished(started_from_startup: bool) -> void:
	if started_from_startup:
		_show_page("HOME")


func _apply_nav_button_style(button: Button, active: bool) -> void:
	UiComponentsV3.apply_nav_state(button, active, active_team_primary)


func _apply_active_team_brand(team_abbreviation: String) -> void:
	var team_key := team_abbreviation.strip_edges().to_upper()
	if team_key == "":
		return

	var palette: Dictionary = DesignSystemV3.team_palette(team_key)
	active_team_abbreviation = team_key
	active_team_primary = palette.get("primary", DesignSystemV3.TEAM_PRIMARY)
	active_team_secondary = palette.get("secondary", DesignSystemV3.TEXT)
	active_team_hover = TeamBrandingV3.hover_color(active_team_primary)
	active_team_foreground = TeamBrandingV3.readable_foreground(active_team_primary)

	if background_top_band != null:
		background_top_band.color = Color(active_team_primary, 0.075)
	if background_accent_line != null:
		background_accent_line.color = active_team_primary

	if header_eyebrow_label != null:
		header_eyebrow_label.add_theme_color_override("font_color", active_team_hover)
	if team_card_eyebrow_label != null:
		team_card_eyebrow_label.add_theme_color_override("font_color", active_team_hover)
	if long_action_spinner_label != null:
		long_action_spinner_label.add_theme_color_override("font_color", active_team_hover)

	if franchise_hero_art != null:
		franchise_hero_art.apply_team_brand(team_key, active_team_primary, active_team_secondary)
	if team_card_panel != null:
		team_card_panel.add_theme_stylebox_override(
			"panel",
			DesignSystemV3.style_box(
				PANEL,
				DesignSystemV3.RADIUS_LG,
				Color(active_team_primary, 0.76),
				1,
				0.16
			)
		)

	if team_badge_panel != null:
		team_badge_panel.add_theme_stylebox_override(
			"panel",
			DesignSystemV3.style_box(
				active_team_primary,
				DesignSystemV3.RADIUS_LG,
				active_team_hover,
				1,
				0.22
			)
		)

	if team_abbr_badge != null:
		team_abbr_badge.add_theme_color_override("font_color", active_team_foreground)

	for key in nav_buttons.keys():
		var button: Button = nav_buttons[key]
		UiComponentsV3.apply_nav_state(
			button,
			str(key) == current_page,
			active_team_primary
		)

	for button in branded_primary_buttons:
		if button is Button and is_instance_valid(button):
			TeamBrandingV3.apply_primary_button(button, active_team_primary)

	_broadcast_team_brand()


func _broadcast_team_brand() -> void:
	for page in [
		home_page,
		roster_page,
		game_day_page,
		trades_page,
		free_agency_page,
		scouting_page,
		season_page,
		league_page,
		front_office_page,
		save_manager_page,
		settings_page
	]:
		if page != null and page.has_method("apply_team_brand"):
			page.call(
				"apply_team_brand",
				active_team_abbreviation,
				active_team_primary,
				active_team_secondary
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
	var button := UiComponentsV3.wide_action(title_text, subtitle_text)

	match title_text:
		"OPEN ROSTER":
			button.pressed.connect(_show_page.bind("ROSTER"))
		"TRADE CENTER":
			button.pressed.connect(_show_page.bind("TRADES"))
		"SCOUTING BOARD":
			button.pressed.connect(_show_page.bind("SCOUTING"))
		"LEAGUE HUB":
			button.pressed.connect(_show_page.bind("LEAGUE"))

	return button

func _nav_button(text_value: String, active: bool = false) -> Button:
	var button := UiComponentsV3.nav_button(
		text_value,
		active,
		active_team_primary
	)

	if text_value in [
		"HOME",
		"FRANCHISES",
		"ROSTER",
		"GAME DAY",
		"TRADES",
		"FREE AGENCY",
		"SCOUTING",
		"SEASON",
		"LEAGUE",
		"FRONT OFFICE",
		"SETTINGS"
	]:
		nav_buttons[text_value] = button
		button.pressed.connect(_show_page.bind(text_value))

	return button

func _action_button(text_value: String, primary: bool = false) -> Button:
	var button := UiComponentsV3.action_button(text_value, primary)
	if primary:
		branded_primary_buttons.append(button)
		TeamBrandingV3.apply_primary_button(button, active_team_primary)
	return button

func _pill(text_value: String, color: Color) -> Label:
	return UiComponentsV3.pill(text_value, color)

func _section_title(text_value: String) -> Label:
	return UiComponentsV3.section_title(text_value)

func _small_label(text_value: String, color: Color) -> Label:
	return UiComponentsV3.small_label(text_value, color)

func _divider() -> HSeparator:
	return UiComponentsV3.divider()

func _card(minimum: Vector2) -> PanelContainer:
	return UiComponentsV3.card(minimum)

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

	intelligence_request = HTTPRequest.new()
	intelligence_request.timeout = 6.0
	intelligence_request.request_completed.connect(_on_intelligence_completed)
	add_child(intelligence_request)

	market_intelligence_request = HTTPRequest.new()
	market_intelligence_request.timeout = 30.0
	market_intelligence_request.request_completed.connect(_on_market_intelligence_completed)
	add_child(market_intelligence_request)

	transaction_foundation_request = HTTPRequest.new()
	transaction_foundation_request.timeout = 60.0
	transaction_foundation_request.request_completed.connect(_on_transaction_foundation_completed)
	add_child(transaction_foundation_request)

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
	# Batch 18B: Roster is lazy-loaded on first navigation. The launcher already
	# prewarms its server response cache, so hidden UI work is unnecessary.
	if settings_page != null and settings_page.has_method("refresh"):
		settings_page.call("refresh")


func _request_roster(force_refresh: bool = false) -> void:
	if roster_request == null:
		return

	if roster_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return

	if request_coordinator != null and not request_coordinator.begin_request("roster", force_refresh):
		return

	if roster_status != null:
		roster_status.text = "Refreshing V3 working roster..."

	var error := roster_request.request(ROSTER_URL)
	if error != OK:
		if request_coordinator != null:
			request_coordinator.finish_request("roster", false)
		_set_roster_error("Could not request the active roster.")


func _on_roster_completed(
	result: int,
	response_code: int,
	_headers: PackedStringArray,
	body: PackedByteArray
) -> void:
	if request_coordinator != null:
		request_coordinator.finish_request("roster", result == HTTPRequest.RESULT_SUCCESS and response_code == 200)
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
	roster_payroll_value.text = _display_text(financial.get("payroll_display", null))
	roster_cap_value.text = _display_text(financial.get("cap_room_estimate_display", null))
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
			if request_coordinator != null:
				request_coordinator.invalidate_all()
			_request_roster(true)
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


func _request_franchise_summary(force_refresh: bool = false) -> void:
	if summary_request == null:
		return

	if summary_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return

	if request_coordinator != null and not request_coordinator.begin_request("franchise_summary", force_refresh):
		return

	var error := summary_request.request(SUMMARY_URL)
	if error != OK:
		if request_coordinator != null:
			request_coordinator.finish_request("franchise_summary", false)
		_set_live_data_error("Could not request active franchise summary.")


func _on_summary_completed(
	result: int,
	response_code: int,
	_headers: PackedStringArray,
	body: PackedByteArray
) -> void:
	if request_coordinator != null:
		request_coordinator.finish_request("franchise_summary", result == HTTPRequest.RESULT_SUCCESS and response_code == 200)
	if result != HTTPRequest.RESULT_SUCCESS or response_code != 200:
		_set_live_data_error("Active V3 franchise data could not be loaded.")
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
	_apply_active_team_brand(str(team.get("abbreviation", "")))
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
	header_subtitle.text = "V3 FRANCHISE DATA UNAVAILABLE"

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


func _display_text(value, fallback: String = "N/A") -> String:
	if value == null:
		return fallback
	var text := str(value).strip_edges()
	return fallback if text.is_empty() else text
