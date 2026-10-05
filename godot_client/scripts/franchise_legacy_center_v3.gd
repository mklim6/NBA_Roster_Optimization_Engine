extends Control

const DS = preload("res://scripts/design_system_v3.gd")
const TeamLogoV3 = preload("res://scripts/team_logo_v3.gd")
const Portrait = preload("res://scripts/player_portrait_v3.gd")

const LEGACY_URL = "http://127.0.0.1:8765/v3/franchise-legacy"

var http_request: HTTPRequest
var root_scroll: ScrollContainer
var content: VBoxContainer
var status_label: Label
var payload: Dictionary = {}

var active_team = ""
var active_primary = DS.TEAM_PRIMARY
var active_secondary = Color("000000")
var active_foreground = DS.TEXT


func _ready() -> void:
	name = "FranchiseLegacyCenter"
	_ensure_ui()
	_build_http()
	refresh()


func _ensure_ui() -> void:
	if root_scroll != null:
		return

	root_scroll = ScrollContainer.new()
	root_scroll.name = "LegacyScroll"
	root_scroll.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	root_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	add_child(root_scroll)

	var outer = MarginContainer.new()
	outer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_set_margins(outer, 30, 24, 30, 34)
	root_scroll.add_child(outer)

	content = VBoxContainer.new()
	content.name = "LegacyContent"
	content.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	content.add_theme_constant_override("separation", 16)
	outer.add_child(content)

	status_label = _label(
		"Connecting to the V3 franchise history archive...",
		10,
		DS.MUTED
	)
	content.add_child(status_label)


func _build_http() -> void:
	if http_request != null:
		return
	http_request = HTTPRequest.new()
	http_request.name = "LegacyHTTPRequest"
	add_child(http_request)
	http_request.request_completed.connect(_on_request_completed)


func refresh() -> void:
	_ensure_ui()
	if http_request == null:
		_build_http()
	if http_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		http_request.cancel_request()

	status_label.text = "LOADING LEGACY ARCHIVE • Read-only V3 history aggregation"
	status_label.add_theme_color_override("font_color", DS.MUTED)

	var error = http_request.request(LEGACY_URL)
	if error != OK:
		status_label.text = "Legacy archive request could not be started."
		status_label.add_theme_color_override("font_color", DS.BAD)


func apply_team_brand(
	team_abbreviation: String,
	primary: Color,
	secondary: Color
) -> void:
	active_team = team_abbreviation.strip_edges().to_upper()
	active_primary = primary
	active_secondary = secondary
	active_foreground = _readable(primary)
	if not payload.is_empty():
		configure(payload)


func configure(data: Dictionary) -> void:
	_ensure_ui()
	payload = data.duplicate(true)

	_clear_content_below_status()

	active_team = str(data.get("team", active_team)).strip_edges().to_upper()
	status_label.text = "LIVE V3 HISTORY • READ-ONLY • %s" % str(
		data.get("foundation_version", "Legacy Foundation")
	)
	status_label.add_theme_color_override("font_color", DS.GOOD)

	_build_hero(data)
	_build_trophy_room(data)
	_build_season_timeline(data)
	_build_record_book(data)
	_build_legends(data)
	_build_greatest_games(data)
	_build_rivalries(data)
	_build_draft_history(data)
	_build_transaction_history(data)
	_build_event_ledger(data)
	_build_league_history(data)


func _on_request_completed(
	result: int,
	response_code: int,
	_headers: PackedStringArray,
	body: PackedByteArray
) -> void:
	if result != HTTPRequest.RESULT_SUCCESS:
		_show_error("Legacy endpoint did not respond.")
		return

	var parsed = JSON.parse_string(body.get_string_from_utf8())
	if typeof(parsed) != TYPE_DICTIONARY:
		_show_error("Legacy endpoint returned invalid JSON.")
		return

	if response_code != 200:
		_show_error(
			str(parsed.get("detail", parsed.get("error", "Legacy archive unavailable.")))
		)
		return

	configure(parsed)


func _show_error(message: String) -> void:
	_clear_content_below_status()
	status_label.text = "LEGACY ARCHIVE UNAVAILABLE"
	status_label.add_theme_color_override("font_color", DS.BAD)
	var card = _card(Color("16131a"), Color(DS.BAD, 0.30), 14)
	var body = _body(card, 16)
	body.add_child(_label(message, 12, DS.TEXT))
	body.add_child(_label(
		"The rest of the franchise remains available. This page is read-only and does not alter either save.",
		10,
		DS.MUTED
	))
	content.add_child(card)


func _build_hero(data: Dictionary) -> void:
	var tenure = _dict(data.get("tenure"))
	var era = _dict(tenure.get("era"))
	var gm = _dict(tenure.get("gm_resume"))
	var trophy = _dict(data.get("trophy_room"))
	var empty = _dict(data.get("empty_state"))

	var hero = _card(
		Color("0b1219").lerp(active_primary, 0.08),
		Color(active_primary, 0.66),
		20
	)
	hero.name = "LegacyHero"
	hero.custom_minimum_size = Vector2(0, 310)
	var body = _body(hero, 22)

	var top = HBoxContainer.new()
	top.add_theme_constant_override("separation", 18)
	body.add_child(top)

	var logo_shell = PanelContainer.new()
	logo_shell.custom_minimum_size = Vector2(150, 150)
	logo_shell.add_theme_stylebox_override(
		"panel",
		_box(
			Color(active_primary, 0.13),
			20,
			Color(active_primary, 0.58)
		)
	)
	top.add_child(logo_shell)

	var logo = TeamLogoV3.new()
	logo.name = "LegacyTeamLogo"
	logo.configure(str(data.get("team", active_team)))
	logo_shell.add_child(logo)

	var title_box = VBoxContainer.new()
	title_box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	title_box.alignment = BoxContainer.ALIGNMENT_CENTER
	title_box.add_theme_constant_override("separation", 4)
	top.add_child(title_box)

	title_box.add_child(_label("FRANCHISE UNIVERSE • HISTORY ARCHIVE", 10, DS.GOOD))
	title_box.add_child(_label(
		str(data.get("team_name", data.get("team", "FRANCHISE"))).to_upper(),
		34,
		DS.TEXT
	))
	title_box.add_child(_label("FRANCHISE LEGACY", 24, active_primary.lightened(0.42)))
	var completed_seasons = int(gm.get("completed_seasons", 0))
	var tenure_line = "%s • FIRST SEASON • GM record %s" % [
		str(data.get("current_season", "")),
		str(gm.get("career_record", "0-0"))
	]
	if completed_seasons > 0:
		tenure_line = "%s • %s completed season(s) • GM record %s" % [
			str(data.get("current_season", "")),
			str(completed_seasons),
			str(gm.get("career_record", "0-0"))
		]
	title_box.add_child(_label(tenure_line, 11, DS.MUTED))

	var era_card = _card(
		Color(active_primary, 0.08),
		Color(active_primary, 0.44),
		14
	)
	era_card.custom_minimum_size = Vector2(270, 150)
	var era_body = _body(era_card, 14)
	era_body.add_child(_label("CURRENT ERA", 9, active_primary.lightened(0.40)))
	era_body.add_child(_label(str(era.get("label", "THE NEXT CHAPTER")), 20, DS.TEXT))
	var era_text = _label(str(era.get("description", "")), 10, DS.MUTED)
	era_text.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	era_body.add_child(era_text)
	top.add_child(era_card)

	var metrics = GridContainer.new()
	metrics.columns = 5
	metrics.add_theme_constant_override("h_separation", 10)
	metrics.add_theme_constant_override("v_separation", 10)
	body.add_child(metrics)

	_metric_card(metrics, "CHAMPIONSHIPS", str(trophy.get("championships", 0)), DS.GOLD)
	_metric_card(metrics, "FINALS", str(trophy.get("finals_appearances", 0)), DS.ACCENT)
	_metric_card(metrics, "PLAYOFF BERTHS", str(trophy.get("playoff_appearances", 0)), DS.GOOD)
	_metric_card(metrics, "CAREER WINS", str(gm.get("career_wins", 0)), active_primary.lightened(0.38))
	_metric_card(metrics, "DRAFT PICKS", str(gm.get("draft_selections", 0)), DS.TEXT)

	if not bool(empty.get("has_completed_history", false)):
		var empty_card = _card(
			Color("111922"),
			Color(active_primary, 0.30),
			13
		)
		empty_card.name = "LegacyEmptyState"
		var empty_body = _body(empty_card, 14)
		empty_body.add_child(_label(str(empty.get("headline", "THE NEXT CHAPTER STARTS HERE")), 16, DS.GOLD))
		var detail = _label(str(empty.get("detail", "")), 10, DS.MUTED)
		detail.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		empty_body.add_child(detail)
		body.add_child(empty_card)

	content.add_child(hero)


func _build_trophy_room(data: Dictionary) -> void:
	var trophy = _dict(data.get("trophy_room"))
	var card = _section_card("THE TROPHY ROOM", "Championships and postseason milestones earned during this V3 franchise.")
	card.name = "LegacyTrophyRoom"
	var body = card.get_meta("body") as VBoxContainer

	var row = HBoxContainer.new()
	row.add_theme_constant_override("separation", 10)
	body.add_child(row)

	_trophy_card(
		row,
		"NBA TITLES",
		int(trophy.get("championships", 0)),
		_array(trophy.get("championship_seasons")),
		DS.GOLD
	)
	_trophy_card(
		row,
		"FINALS",
		int(trophy.get("finals_appearances", 0)),
		_array(trophy.get("finals_seasons")),
		DS.ACCENT
	)
	_trophy_card(
		row,
		"CONFERENCE TITLES",
		int(trophy.get("conference_titles", 0)),
		_array(trophy.get("conference_title_seasons")),
		active_primary.lightened(0.36)
	)
	_trophy_card(
		row,
		"PLAYOFF BERTHS",
		int(trophy.get("playoff_appearances", 0)),
		_array(trophy.get("playoff_seasons")),
		DS.GOOD
	)

	var title_seasons = _array(trophy.get("championship_seasons"))
	if title_seasons.is_empty():
		var waiting = _empty_line(
			"CHAMPIONSHIP BANNER RAIL • The first V3 title will be permanently raised here."
		)
		waiting.name = "LegacyBannerEmptyState"
		body.add_child(waiting)
	else:
		var banners = HBoxContainer.new()
		banners.name = "LegacyBannerRail"
		banners.add_theme_constant_override("separation", 8)
		body.add_child(banners)
		for season in title_seasons:
			var banner = _card(
				Color(DS.GOLD, 0.08),
				Color(DS.GOLD, 0.50),
				9
			)
			banner.custom_minimum_size = Vector2(128, 58)
			var banner_body = _body(banner, 9)
			banner_body.add_child(_label("CHAMPION", 8, DS.GOLD))
			banner_body.add_child(_label(str(season), 13, DS.TEXT))
			banners.add_child(banner)

	content.add_child(card)


func _build_season_timeline(data: Dictionary) -> void:
	var card = _section_card(
		"YOUR FRANCHISE THROUGH THE YEARS",
		"Every archived season becomes a permanent chapter in the front-office tenure."
	)
	card.name = "LegacySeasonTimeline"
	var body = card.get_meta("body") as VBoxContainer
	var rows = _array(data.get("season_timeline"))

	if rows.is_empty():
		body.add_child(_empty_line("No season timeline is available yet."))
		content.add_child(card)
		return

	for raw in rows.slice(0, 12):
		var row_data = _dict(raw)
		var row = HBoxContainer.new()
		row.add_theme_constant_override("separation", 10)

		var season = _label(str(row_data.get("season", "SEASON")), 15, DS.TEXT)
		season.custom_minimum_size = Vector2(120, 0)
		season.size_flags_horizontal = Control.SIZE_SHRINK_BEGIN
		row.add_child(season)

		var record = _pill(str(row_data.get("record", "0-0")), active_primary.lightened(0.38))
		record.custom_minimum_size = Vector2(82, 28)
		row.add_child(record)

		var result = _label(str(row_data.get("result", "")), 11, _result_color(str(row_data.get("result", ""))))
		result.custom_minimum_size = Vector2(180, 0)
		result.size_flags_horizontal = Control.SIZE_SHRINK_BEGIN
		row.add_child(result)

		var detail = _label(
			"Point diff %+d%s" % [
				int(row_data.get("point_diff", 0)),
				" • CURRENT" if bool(row_data.get("is_current", false)) else ""
			],
			10,
			DS.MUTED
		)
		row.add_child(detail)

		body.add_child(row)

	content.add_child(card)


func _build_record_book(data: Dictionary) -> void:
	var records = _dict(data.get("records"))
	var card = _section_card(
		"FRANCHISE RECORD BOOK",
		"Records are reconstructed from archived V3 game results and franchise player lines."
	)
	card.name = "LegacyRecordBook"
	var body = card.get_meta("body") as VBoxContainer

	var grid = GridContainer.new()
	grid.columns = 4
	grid.add_theme_constant_override("h_separation", 10)
	grid.add_theme_constant_override("v_separation", 10)
	body.add_child(grid)

	var best = _dict(records.get("best_season"))
	_record_tile(
		grid,
		"BEST SEASON",
		"%s • %s" % [str(best.get("season", "—")), str(best.get("record", "—"))],
		str(best.get("result", "History still building"))
	)

	var largest = _dict(records.get("largest_win"))
	_record_tile(
		grid,
		"LARGEST WIN",
		"+%s vs %s" % [
			str(largest.get("margin", "—")),
			str(largest.get("opponent", "—"))
		] if not largest.is_empty() else "—",
		str(largest.get("season", "No completed win indexed"))
	)

	var high = _dict(records.get("highest_team_score"))
	_record_tile(
		grid,
		"HIGHEST TEAM SCORE",
		"%s vs %s" % [
			str(high.get("team_score", "—")),
			str(high.get("opponent", "—"))
		] if not high.is_empty() else "—",
		str(high.get("season", "No completed game indexed"))
	)

	var career_points = _dict(records.get("career_points"))
	_record_tile(
		grid,
		"FRANCHISE POINTS",
		"%s • %s" % [
			str(career_points.get("name", "—")),
			str(career_points.get("value", "—"))
		] if not career_points.is_empty() else "—",
		"Box-score era leader"
	)

	for key_title in [
		["career_rebounds", "FRANCHISE REBOUNDS"],
		["career_assists", "FRANCHISE ASSISTS"],
		["career_threes", "FRANCHISE THREES"]
	]:
		var item = _dict(records.get(key_title[0]))
		_record_tile(
			grid,
			key_title[1],
			"%s • %s" % [
				str(item.get("name", "—")),
				str(item.get("value", "—"))
			] if not item.is_empty() else "—",
			"Box-score era leader"
		)

	var single = _dict(records.get("single_game"))
	var points = _dict(single.get("points"))
	_record_tile(
		grid,
		"SINGLE-GAME POINTS",
		"%s • %s" % [
			str(points.get("name", "—")),
			str(points.get("value", "—"))
		] if not points.is_empty() else "—",
		"%s vs %s" % [
			str(points.get("season", "")),
			str(points.get("opponent", ""))
		] if not points.is_empty() else "No completed game indexed"
	)

	content.add_child(card)


func _build_legends(data: Dictionary) -> void:
	var card = _section_card(
		"FRANCHISE LEGENDS",
		"Legacy score rewards production, games with the franchise, and championships captured while on the roster."
	)
	card.name = "LegacyLegends"
	var body = card.get_meta("body") as VBoxContainer
	var legends = _array(data.get("legends"))

	if legends.is_empty():
		body.add_child(_empty_line("No franchise player history has accumulated yet."))
		content.add_child(card)
		return

	var grid = GridContainer.new()
	grid.columns = 4
	grid.add_theme_constant_override("h_separation", 10)
	grid.add_theme_constant_override("v_separation", 10)
	body.add_child(grid)

	for raw in legends.slice(0, 8):
		var row = _dict(raw)
		var legend = _card(Color("101922"), Color(active_primary, 0.27), 12)
		legend.custom_minimum_size = Vector2(0, 184)
		legend.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		var legend_body = _body(legend, 12)

		var top = HBoxContainer.new()
		top.add_theme_constant_override("separation", 9)
		legend_body.add_child(top)

		var portrait = Portrait.new()
		portrait.custom_minimum_size = Vector2(84, 82)
		portrait.configure({
			"player_id": row.get("player_id", ""),
			"name": row.get("name", "")
		})
		top.add_child(portrait)

		var copy = VBoxContainer.new()
		copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		top.add_child(copy)
		copy.add_child(_label(str(row.get("name", "")), 14, DS.TEXT))
		copy.add_child(_label(
			"LEGACY %.1f" % float(row.get("legacy_score", 0.0)),
			9,
			DS.GOLD
		))
		copy.add_child(_label(
			"%s season(s) • %s title(s)" % [
				str(row.get("seasons_count", 0)),
				str(row.get("championships", 0))
			],
			9,
			DS.MUTED
		))

		legend_body.add_child(_label(
			"%s PTS  •  %s REB  •  %s AST" % [
				str(row.get("points", 0)),
				str(row.get("rebounds", 0)),
				str(row.get("assists", 0))
			],
			10,
			DS.TEXT
		))
		legend_body.add_child(_label(
			"%s games • best scoring game %s" % [
				str(row.get("games", 0)),
				str(row.get("best_game_points", 0))
			],
			9,
			DS.MUTED
		))
		grid.add_child(legend)

	content.add_child(card)


func _build_greatest_games(data: Dictionary) -> void:
	var card = _section_card(
		"GREATEST GAMES",
		"Notable franchise games ranked from actual V3 scores, playoff context, overtime, margin, and player performance."
	)
	card.name = "LegacyGreatestGames"
	var body = card.get_meta("body") as VBoxContainer
	var games = _array(data.get("greatest_games"))

	if games.is_empty():
		body.add_child(_empty_line("No completed franchise games are available yet."))
		content.add_child(card)
		return

	for raw in games.slice(0, 8):
		var game = _dict(raw)
		var row = HBoxContainer.new()
		row.add_theme_constant_override("separation", 10)

		var result = _pill(
			str(game.get("result", "FINAL")),
			DS.GOOD if str(game.get("result", "")) == "W" else DS.BAD
		)
		result.custom_minimum_size = Vector2(52, 28)
		row.add_child(result)

		var score = _label(
			"%s  %s-%s  %s" % [
				str(game.get("season", "")),
				str(game.get("team_score", 0)),
				str(game.get("opponent_score", 0)),
				str(game.get("opponent", ""))
			],
			12,
			DS.TEXT
		)
		score.custom_minimum_size = Vector2(300, 0)
		score.size_flags_horizontal = Control.SIZE_SHRINK_BEGIN
		row.add_child(score)

		var context_bits: Array[String] = []
		if bool(game.get("is_playoff", false)):
			context_bits.append("PLAYOFF")
		if int(game.get("overtime_periods", 0)) > 0:
			context_bits.append("%sOT" % str(game.get("overtime_periods", 0)))
		if str(game.get("top_player", "")) != "":
			context_bits.append(
				"%s %s PTS" % [
					str(game.get("top_player", "")),
					str(game.get("top_points", 0))
				]
			)

		row.add_child(_label(
			" • ".join(context_bits) if not context_bits.is_empty() else "REGULAR SEASON",
			9,
			DS.MUTED
		))
		body.add_child(row)

	content.add_child(card)


func _build_rivalries(data: Dictionary) -> void:
	var card = _section_card(
		"RIVALRY HISTORY",
		"Rivalry strength is a simulator model based on meetings, playoff games, close finishes, overtime, and Finals history."
	)
	card.name = "LegacyRivalries"
	var body = card.get_meta("body") as VBoxContainer
	var rows = _array(data.get("rivalries"))

	if rows.is_empty():
		body.add_child(_empty_line("Rivalries will emerge as the franchise accumulates meaningful matchups."))
		content.add_child(card)
		return

	var grid = GridContainer.new()
	grid.columns = 4
	grid.add_theme_constant_override("h_separation", 10)
	grid.add_theme_constant_override("v_separation", 10)
	body.add_child(grid)

	for raw in rows.slice(0, 8):
		var rivalry = _dict(raw)
		var tile = _card(Color("111821"), Color(DS.BAD, 0.22), 12)
		tile.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		var tile_body = _body(tile, 12)
		tile_body.add_child(_label(str(rivalry.get("opponent", "")), 18, DS.TEXT))
		tile_body.add_child(_label(str(rivalry.get("tier", "HISTORY BUILDING")), 9, DS.BAD.lightened(0.25)))
		tile_body.add_child(_label(
			"%s-%s • %s games" % [
				str(rivalry.get("wins", 0)),
				str(rivalry.get("losses", 0)),
				str(rivalry.get("games", 0))
			],
			10,
			DS.MUTED
		))
		tile_body.add_child(_label(
			"%s playoff • %s Finals meeting(s)" % [
				str(rivalry.get("playoff_games", 0)),
				str(rivalry.get("finals_meetings", 0))
			],
			9,
			DS.MUTED
		))
		grid.add_child(tile)

	content.add_child(card)


func _build_draft_history(data: Dictionary) -> void:
	var card = _section_card(
		"DRAFT HISTORY",
		"Every archived selection made by this franchise through the production Draft engine."
	)
	card.name = "LegacyDraftHistory"
	var body = card.get_meta("body") as VBoxContainer
	var rows = _array(data.get("draft_history"))

	if rows.is_empty():
		body.add_child(_empty_line("No completed V3 Draft selection has been archived for this franchise yet."))
		content.add_child(card)
		return

	for raw in rows.slice(0, 16):
		var pick = _dict(raw)
		var row = HBoxContainer.new()
		row.add_theme_constant_override("separation", 10)
		row.add_child(_pill(
			"%s • #%s" % [
				str(pick.get("draft_year", "")),
				str(pick.get("overall_pick", ""))
			],
			DS.GOLD
		))

		var name = _label(str(pick.get("name", "")), 12, DS.TEXT)
		name.custom_minimum_size = Vector2(210, 0)
		name.size_flags_horizontal = Control.SIZE_SHRINK_BEGIN
		row.add_child(name)

		row.add_child(_label(
			"%s • %s • %s" % [
				str(pick.get("position", "")),
				str(pick.get("school", "")),
				str(pick.get("archetype", ""))
			],
			9,
			DS.MUTED
		))

		var status = (
			"%s • OVR %s" % [
				str(pick.get("current_team", "")),
				str(pick.get("current_overall", "—"))
			]
			if bool(pick.get("still_in_league", false))
			else "NO CURRENT PLAYER STATE"
		)
		row.add_child(_label(status, 9, DS.GOOD if bool(pick.get("still_in_league", false)) else DS.MUTED))
		body.add_child(row)

	content.add_child(card)


func _build_transaction_history(data: Dictionary) -> void:
	var card = _section_card(
		"FRONT OFFICE TRANSACTION ARCHIVE",
		"Durable trade history involving the active franchise. Other transaction types will join the ledger only when authoritative history exists."
	)
	card.name = "LegacyTransactionHistory"
	var body = card.get_meta("body") as VBoxContainer
	var rows = _array(data.get("trade_history"))

	if rows.is_empty():
		body.add_child(_empty_line("No durable V3 trade record exists for this franchise yet."))
		content.add_child(card)
		return

	for raw in rows.slice(0, 12):
		var trade = _dict(raw)
		var item = _card(Color("0f171f"), Color(active_primary, 0.22), 10)
		var item_body = _body(item, 11)

		var header = HBoxContainer.new()
		header.add_theme_constant_override("separation", 8)
		item_body.add_child(header)
		header.add_child(_label(
			"TRADE WITH %s" % str(trade.get("partner", "")).to_upper(),
			11,
			DS.TEXT
		))
		header.add_child(_label(
			str(trade.get("transaction_id", "")),
			8,
			DS.MUTED
		))

		item_body.add_child(_label(
			"ACQUIRED • %s" % _asset_line(
				_array(trade.get("incoming_players")),
				_array(trade.get("incoming_picks"))
			),
			9,
			DS.GOOD
		))
		item_body.add_child(_label(
			"SENT • %s" % _asset_line(
				_array(trade.get("outgoing_players")),
				_array(trade.get("outgoing_picks"))
			),
			9,
			DS.MUTED
		))
		body.add_child(item)

	content.add_child(card)


func _build_event_ledger(data: Dictionary) -> void:
	var card = _section_card(
		"FRANCHISE STORY ARCHIVE",
		"One normalized historical ledger powers the franchise timeline, news memory, and future era systems."
	)
	card.name = "LegacyEventLedger"
	var body = card.get_meta("body") as VBoxContainer
	var rows = _array(data.get("event_ledger"))

	if rows.is_empty():
		body.add_child(_empty_line("Major events will appear here as the franchise creates history."))
		content.add_child(card)
		return

	for raw in rows.slice(0, 18):
		var event = _dict(raw)
		var row = HBoxContainer.new()
		row.add_theme_constant_override("separation", 10)

		var season = _pill(str(event.get("season", "")), active_primary.lightened(0.35))
		season.custom_minimum_size = Vector2(108, 28)
		row.add_child(season)

		var type_label = _label(str(event.get("event_type", "")), 9, _event_color(str(event.get("event_type", ""))))
		type_label.custom_minimum_size = Vector2(135, 0)
		type_label.size_flags_horizontal = Control.SIZE_SHRINK_BEGIN
		row.add_child(type_label)

		var copy = VBoxContainer.new()
		copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		copy.add_child(_label(str(event.get("title", "")), 11, DS.TEXT))
		copy.add_child(_label(str(event.get("detail", "")), 9, DS.MUTED))
		row.add_child(copy)
		body.add_child(row)

	content.add_child(card)


func _build_league_history(data: Dictionary) -> void:
	var card = _section_card(
		"LEAGUE HISTORY",
		"Your franchise exists inside a league that remembers its champions and Finals matchups."
	)
	card.name = "LegacyLeagueHistory"
	var body = card.get_meta("body") as VBoxContainer
	var rows = _array(data.get("league_history"))

	if rows.is_empty():
		body.add_child(_empty_line("League champions will populate after the first completed V3 season."))
		content.add_child(card)
		return

	for raw in rows.slice(0, 12):
		var season = _dict(raw)
		var row = HBoxContainer.new()
		row.add_theme_constant_override("separation", 10)

		var season_label = _label(str(season.get("season", "")), 13, DS.TEXT)
		season_label.custom_minimum_size = Vector2(115, 0)
		season_label.size_flags_horizontal = Control.SIZE_SHRINK_BEGIN
		row.add_child(season_label)

		row.add_child(_pill(
			"CHAMPION • %s" % str(season.get("champion", "—")),
			DS.GOLD
		))
		row.add_child(_label(
			"def. %s" % str(season.get("runner_up", "—")),
			10,
			DS.MUTED
		))
		body.add_child(row)

	content.add_child(card)


func _section_card(title_text: String, detail_text: String) -> PanelContainer:
	var card = _card(DS.PANEL, Color(DS.BORDER, 0.86), 16)
	var body = _body(card, 17)
	card.set_meta("body", body)
	body.add_child(_label(title_text, 19, DS.TEXT))
	body.add_child(_label(detail_text, 9, DS.MUTED))
	body.add_child(_divider())
	return card


func _trophy_card(
	parent: HBoxContainer,
	title_text: String,
	count: int,
	seasons: Array,
	tone: Color
) -> void:
	var card = _card(Color(tone, 0.06), Color(tone, 0.30), 12)
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	card.custom_minimum_size = Vector2(0, 100)
	var body = _body(card, 12)
	body.add_child(_label(title_text, 8, tone))
	body.add_child(_label(str(count), 28, DS.TEXT))
	body.add_child(_label(
		" • ".join(_string_array(seasons.slice(max(0, seasons.size() - 3), seasons.size())))
		if not seasons.is_empty()
		else "History waiting",
		8,
		DS.MUTED
	))
	parent.add_child(card)


func _record_tile(
	parent: GridContainer,
	title_text: String,
	value_text: String,
	detail_text: String
) -> void:
	var card = _card(Color("101821"), Color(active_primary, 0.20), 11)
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	card.custom_minimum_size = Vector2(0, 88)
	var body = _body(card, 10)
	body.add_child(_label(title_text, 8, active_primary.lightened(0.40)))
	body.add_child(_label(value_text, 13, DS.TEXT))
	body.add_child(_label(detail_text, 8, DS.MUTED))
	parent.add_child(card)


func _metric_card(parent: GridContainer, title_text: String, value_text: String, tone: Color) -> void:
	var card = _card(Color(tone, 0.055), Color(tone, 0.28), 11)
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	card.custom_minimum_size = Vector2(0, 72)
	var body = _body(card, 9)
	body.add_child(_label(title_text, 8, tone))
	body.add_child(_label(value_text, 18, DS.TEXT))
	parent.add_child(card)


func _empty_line(text_value: String) -> Control:
	var card = _card(Color("101820"), Color(DS.BORDER, 0.65), 10)
	var body = _body(card, 12)
	var label = _label(text_value, 10, DS.MUTED)
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	body.add_child(label)
	return card


func _asset_line(players: Array, picks: Array) -> String:
	var values: Array[String] = []
	for value in players:
		values.append(str(value))
	for value in picks:
		values.append(str(value))
	return ", ".join(values) if not values.is_empty() else "No listed assets"


func _result_color(result: String) -> Color:
	if result == "NBA CHAMPION":
		return DS.GOLD
	if result in ["NBA FINALS", "CONFERENCE CHAMPION"]:
		return DS.ACCENT
	if result == "PLAYOFFS":
		return DS.GOOD
	return DS.MUTED


func _event_color(event_type: String) -> Color:
	if event_type == "CHAMPIONSHIP":
		return DS.GOLD
	if event_type in ["FINALS", "CONFERENCE_TITLE"]:
		return DS.ACCENT
	if event_type == "TRADE":
		return DS.GOOD
	if event_type == "DRAFT":
		return active_primary.lightened(0.42)
	return DS.MUTED


func _card(fill: Color, border: Color, radius: int) -> PanelContainer:
	var card = PanelContainer.new()
	card.add_theme_stylebox_override("panel", _box(fill, radius, border))
	return card


func _body(card: PanelContainer, padding: int) -> VBoxContainer:
	var margin = MarginContainer.new()
	_set_margins(margin, padding, padding, padding, padding)
	card.add_child(margin)

	var body = VBoxContainer.new()
	body.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	body.add_theme_constant_override("separation", 7)
	margin.add_child(body)
	return body


func _box(fill: Color, radius: int, border: Color) -> StyleBoxFlat:
	var box = StyleBoxFlat.new()
	box.bg_color = fill
	box.border_color = border
	box.border_width_left = 1
	box.border_width_top = 1
	box.border_width_right = 1
	box.border_width_bottom = 1
	box.corner_radius_top_left = radius
	box.corner_radius_top_right = radius
	box.corner_radius_bottom_left = radius
	box.corner_radius_bottom_right = radius
	return box


func _pill(text_value: String, tone: Color) -> Label:
	var label = _label("  %s  " % text_value, 9, tone)
	label.autowrap_mode = TextServer.AUTOWRAP_OFF
	label.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	label.size_flags_horizontal = Control.SIZE_SHRINK_BEGIN
	label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	label.add_theme_stylebox_override(
		"normal",
		_box(Color(tone, 0.08), 7, Color(tone, 0.30))
	)
	return label


func _label(text_value: String, font_size: int, color: Color = DS.TEXT) -> Label:
	var label = Label.new()
	label.text = text_value
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	label.add_theme_font_size_override("font_size", font_size)
	label.add_theme_color_override("font_color", color)
	return label


func _divider() -> HSeparator:
	var line = HSeparator.new()
	line.modulate = Color(1, 1, 1, 0.10)
	return line


func _set_margins(container: MarginContainer, left: int, top: int, right: int, bottom: int) -> void:
	container.add_theme_constant_override("margin_left", left)
	container.add_theme_constant_override("margin_top", top)
	container.add_theme_constant_override("margin_right", right)
	container.add_theme_constant_override("margin_bottom", bottom)


func _clear_content_below_status() -> void:
	if content == null:
		return
	var children = content.get_children()
	for index in range(children.size() - 1, 0, -1):
		var child = children[index]
		content.remove_child(child)
		child.queue_free()


func _dict(value) -> Dictionary:
	return value if typeof(value) == TYPE_DICTIONARY else {}


func _array(value) -> Array:
	return value if typeof(value) == TYPE_ARRAY else []


func _string_array(values: Array) -> Array[String]:
	var output: Array[String] = []
	for value in values:
		output.append(str(value))
	return output


func _readable(color: Color) -> Color:
	var luminance = (
		0.2126 * color.r
		+ 0.7152 * color.g
		+ 0.0722 * color.b
	)
	return Color("071014") if luminance > 0.57 else Color("f5f7fa")
