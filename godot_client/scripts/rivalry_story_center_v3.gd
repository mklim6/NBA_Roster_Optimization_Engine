extends Control

# EXP48_1_NODE_LIFECYCLE: request-backed visual components are added before configure().

const DS = preload("res://scripts/design_system_v3.gd")
const Logo = preload("res://scripts/team_logo_v3.gd")
const Portrait = preload("res://scripts/player_portrait_v3.gd")

signal navigate_requested(page: String)

const STORIES_URL = "http://127.0.0.1:8765/v3/rivalry-stories"

var content: VBoxContainer
var status: Label
var request: HTTPRequest
var primary = DS.TEAM_PRIMARY
var secondary = Color("000000")
var payload: Dictionary = {}
var rivalry_picker: OptionButton
var rivalry_body: VBoxContainer
var selected_rival = 0


func _ready() -> void:
	name = "RivalryStoryCenter"
	var background = ColorRect.new()
	background.color = DS.BG
	background.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(background)

	var scroll = ScrollContainer.new()
	scroll.name = "RivalryStoryScroll"
	scroll.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	scroll.vertical_scroll_mode = ScrollContainer.SCROLL_MODE_AUTO
	add_child(scroll)

	var margin = MarginContainer.new()
	margin.name = "RivalryStoryMargin"
	margin.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	margin.size_flags_vertical = Control.SIZE_SHRINK_BEGIN
	_set_margins(margin, 24, 24, 24, 180)
	scroll.add_child(margin)

	content = VBoxContainer.new()
	content.name = "RivalryStoryContent"
	content.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	content.size_flags_vertical = Control.SIZE_SHRINK_BEGIN
	content.add_theme_constant_override("separation", 16)
	margin.add_child(content)

	status = _label("Connecting to the league story desk…", 12, DS.MUTED)
	content.add_child(status)

	request = HTTPRequest.new()
	request.timeout = 45.0
	request.request_completed.connect(_completed)
	add_child(request)


func apply_team_brand(_team: String, color: Color, team_secondary: Color) -> void:
	primary = color
	secondary = team_secondary


func refresh() -> void:
	if request == null:
		return
	if request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		request.cancel_request()
	payload.clear()
	_clear(content, status)
	status.text = "Reconstructing rivalries and league stories from the saved V3 universe…"
	var error = request.request(STORIES_URL)
	if error != OK:
		_error("Could not start Rivalries + Stories request.")


func _completed(
	result: int,
	code: int,
	_headers: PackedStringArray,
	bytes: PackedByteArray
) -> void:
	var data = JSON.parse_string(bytes.get_string_from_utf8())
	if result != HTTPRequest.RESULT_SUCCESS or code != 200 or typeof(data) != TYPE_DICTIONARY:
		var detail = (
			str(data.get("detail", "Rivalries + Stories unavailable."))
			if typeof(data) == TYPE_DICTIONARY
			else "Rivalries + Stories unavailable."
		)
		_error(detail)
		return
	configure(data)


func _error(message: String) -> void:
	_clear(content, status)
	status.text = "STORY DESK UNAVAILABLE"
	status.add_theme_color_override("font_color", DS.BAD)
	var card = _card(content, DS.BAD)
	card.add_child(_label(message, 15))
	card.add_child(_label(
		"No franchise result was changed. Reload the current working save and retry.",
		11,
		DS.MUTED
	))
	card.add_child(_button("RETRY STORY DESK", refresh))


func configure(data: Dictionary) -> void:
	payload = data.duplicate(true)
	_clear(content, status)
	status.text = "%s • LEAGUE DAY %s • %s • READ-ONLY STORY ENGINE" % [
		str(data.get("season", "")),
		str(data.get("day", 0)),
		str(data.get("phase", "")).replace("_", " ").to_upper()
	]
	status.add_theme_color_override("font_color", DS.GOOD)

	_build_hero(data)
	_build_featured_matchup(data)
	_build_rivalry_heat_board(data)
	_build_rivalry_dossier(data)
	_build_story_feed(data)
	_build_return_games(data)
	_build_league_wire(data)
	_build_scope(data)

	var spacer = Control.new()
	spacer.name = "RivalryStoryBottomSafeArea"
	spacer.custom_minimum_size = Vector2(0, 120)
	spacer.mouse_filter = Control.MOUSE_FILTER_IGNORE
	content.add_child(spacer)


func _build_hero(data: Dictionary) -> void:
	var hero = _card(content, primary)
	hero.get_parent().name = "RivalryStoryHeroCard"

	var row = HBoxContainer.new()
	row.add_theme_constant_override("separation", 18)
	hero.add_child(row)

	var logo_shell = PanelContainer.new()
	logo_shell.custom_minimum_size = Vector2(118, 118)
	logo_shell.add_theme_stylebox_override(
		"panel",
		_box(Color(primary, 0.09), 18, Color(primary, 0.50))
	)
	row.add_child(logo_shell)

	var logo = Logo.new()
	logo.custom_minimum_size = Vector2(104, 104)
	logo_shell.add_child(logo)
	logo.configure(str(data.get("team", "")))

	var copy = VBoxContainer.new()
	copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	copy.add_theme_constant_override("separation", 4)
	row.add_child(copy)
	copy.add_child(_label("EXPANSION 48 • LIVING LEAGUE", 9, DS.ACCENT))
	copy.add_child(_label("RIVALRIES + LEAGUE STORIES", 32, DS.GOLD))
	copy.add_child(_label(
		"%s • Every matchup leaves a mark." % str(data.get("team_name", data.get("team", ""))),
		16
	))
	copy.add_child(_label(
		"Persistent head-to-head history, playoff chapters, rematches, former-player returns, star matchups and league-wide story games.",
		12,
		DS.MUTED
	))

	var archive = _dict(data.get("archive"))
	var metric_row = GridContainer.new()
	metric_row.columns = 4
	metric_row.add_theme_constant_override("h_separation", 8)
	metric_row.add_theme_constant_override("v_separation", 8)
	hero.add_child(metric_row)
	_metric(metric_row, "RIVALRY FILES", str(_array(data.get("rivalries")).size()), primary)
	_metric(metric_row, "SAVED GAMES", str(archive.get("completed_game_count", 0)), DS.TEXT)
	_metric(metric_row, "ACTIVE STORIES", str(_array(data.get("active_stories")).size()), DS.GOLD)
	_metric(metric_row, "LEAGUE WIRE", str(_array(data.get("league_story_wire")).size()), DS.ACCENT)

	var actions = HBoxContainer.new()
	actions.add_theme_constant_override("separation", 8)
	hero.add_child(actions)
	actions.add_child(_nav_button("OPEN FRANCHISE PULSE", "PULSE"))
	actions.add_child(_nav_button("OPEN GAME DAY", "GAME DAY"))
	actions.add_child(_nav_button("OPEN LEGACY", "LEGACY"))


func _build_featured_matchup(data: Dictionary) -> void:
	var featured = data.get("featured_matchup")
	var section = _section(
		"MATCHUP POSTER",
		"The next franchise game is framed only by storylines that exist in the saved universe.",
		DS.GOLD
	)
	section.get_parent().name = "RivalryFeaturedMatchup"

	if typeof(featured) != TYPE_DICTIONARY:
		section.add_child(_empty(
			"No franchise game is currently scheduled. The story desk will spotlight the next matchup when the calendar provides one."
		))
		return

	var game: Dictionary = featured
	var poster = PanelContainer.new()
	poster.name = "RivalryMatchupPoster"
	poster.add_theme_stylebox_override(
		"panel",
		_box(Color(primary, 0.065), 18, Color(primary, 0.42))
	)
	section.add_child(poster)

	var margin = MarginContainer.new()
	_set_margins(margin, 18, 16, 18, 16)
	poster.add_child(margin)

	var body = VBoxContainer.new()
	body.add_theme_constant_override("separation", 12)
	margin.add_child(body)

	body.add_child(_label(str(game.get("category", "MATCHUP WATCH")), 10, DS.GOLD))
	body.add_child(_label(str(game.get("headline", "NEXT MATCHUP")), 27))

	var matchup = HBoxContainer.new()
	matchup.add_theme_constant_override("separation", 18)
	body.add_child(matchup)

	var left_team = (
		str(game.get("home_team", ""))
		if bool(game.get("is_home", false))
		else str(game.get("away_team", ""))
	)
	var right_team = str(game.get("opponent", ""))
	matchup.add_child(_team_poster(left_team, str(data.get("team_name", left_team)), primary))

	var center = VBoxContainer.new()
	center.custom_minimum_size = Vector2(160, 0)
	center.alignment = BoxContainer.ALIGNMENT_CENTER
	matchup.add_child(center)
	var location = "VS" if bool(game.get("is_home", false)) else "@"
	var vs = _label(location, 28, DS.GOLD)
	vs.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	center.add_child(vs)
	var day = _label("LEAGUE DAY %s" % str(game.get("day", "?")), 11, DS.MUTED)
	day.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	center.add_child(day)
	var countdown = _label(
		"%s DAY(S) AWAY" % str(game.get("days_away", 0)),
		10,
		DS.ACCENT
	)
	countdown.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	center.add_child(countdown)

	matchup.add_child(_team_poster(
		right_team,
		str(game.get("opponent_name", right_team)),
		Color("78869b")
	))

	var reasons = _array(game.get("reasons"))
	if reasons.is_empty():
		body.add_child(_label(
			"FIRST CHAPTER • No recorded rivalry marker exists yet in this V3 universe.",
			12,
			DS.MUTED
		))
	else:
		for reason in reasons:
			body.add_child(_label("• " + str(reason), 12, DS.MUTED))

	var star = _dict(game.get("star_matchup"))
	if bool(star.get("available", false)):
		body.add_child(_star_matchup_card(star))

	var actions = HBoxContainer.new()
	actions.add_theme_constant_override("separation", 8)
	body.add_child(actions)
	actions.add_child(_nav_button("OPEN GAME DAY", "GAME DAY"))
	actions.add_child(_nav_button("OPEN GAME NIGHT THEATER", "THEATER"))
	actions.add_child(_nav_button("OPEN LEGACY HISTORY", "LEGACY"))


func _build_rivalry_heat_board(data: Dictionary) -> void:
	var section = _section(
		"RIVALRY HEAT BOARD",
		"Heat grows only from saved meetings, playoff games, close finishes, overtime, Finals history and completed playoff series.",
		primary
	)
	section.get_parent().name = "RivalryHeatBoard"

	var rows = _array(data.get("rivalries"))
	if rows.is_empty():
		section.add_child(_empty(
			"No completed V3 matchup history exists yet. Scheduled opponents will begin at HISTORY BUILDING until games create evidence."
		))
		return

	var grid = GridContainer.new()
	grid.columns = 2
	grid.add_theme_constant_override("h_separation", 10)
	grid.add_theme_constant_override("v_separation", 10)
	section.add_child(grid)

	for index in range(min(rows.size(), 8)):
		var rivalry: Dictionary = rows[index]
		grid.add_child(_rivalry_summary_card(rivalry, index))


func _rivalry_summary_card(rivalry: Dictionary, index: int) -> Control:
	var tone = _tier_color(str(rivalry.get("tier", "HISTORY BUILDING")))
	var panel = PanelContainer.new()
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	panel.add_theme_stylebox_override(
		"panel",
		_box(Color(tone, 0.045), 13, Color(tone, 0.32))
	)

	var margin = MarginContainer.new()
	_set_margins(margin, 13, 11, 13, 11)
	panel.add_child(margin)

	var body = VBoxContainer.new()
	body.add_theme_constant_override("separation", 6)
	margin.add_child(body)

	var header = HBoxContainer.new()
	header.add_theme_constant_override("separation", 10)
	body.add_child(header)

	var logo = Logo.new()
	logo.custom_minimum_size = Vector2(62, 62)
	header.add_child(logo)
	logo.configure(str(rivalry.get("opponent", "")))

	var copy = VBoxContainer.new()
	copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	header.add_child(copy)
	copy.add_child(_label(str(rivalry.get("opponent_name", "")), 17))
	copy.add_child(_label(
		"%s • HEAT %.1f" % [
			str(rivalry.get("tier", "")),
			float(rivalry.get("heat_score", 0.0))
		],
		10,
		tone
	))
	copy.add_child(_label(
		"ALL-TIME %s • %s PLAYOFF GAMES • %s FINALS" % [
			str(rivalry.get("record", "0-0")),
			str(rivalry.get("playoff_games", 0)),
			str(rivalry.get("finals_meetings", 0))
		],
		9,
		DS.MUTED
	))

	var detail = _label(str(rivalry.get("narrative", "")), 10, DS.MUTED)
	detail.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	body.add_child(detail)

	var button = _button("OPEN RIVALRY DOSSIER", _select_rivalry.bind(index))
	body.add_child(button)
	return panel


func _build_rivalry_dossier(data: Dictionary) -> void:
	var section = _section(
		"RIVALRY DOSSIER",
		"Select an opponent to inspect the saved series, postseason chapters and game-by-game timeline.",
		DS.ACCENT
	)
	section.get_parent().name = "RivalryDossier"

	var rows = _array(data.get("rivalries"))
	if rows.is_empty():
		section.add_child(_empty(
			"The dossier opens after the schedule or completed-game archive creates an opponent history."
		))
		return

	rivalry_picker = OptionButton.new()
	rivalry_picker.name = "RivalryDossierPicker"
	rivalry_picker.custom_minimum_size.y = 42
	for rivalry in rows:
		rivalry_picker.add_item(
			"%s • %s • HEAT %.1f" % [
				str(rivalry.get("opponent_name", rivalry.get("opponent", ""))),
				str(rivalry.get("tier", "")),
				float(rivalry.get("heat_score", 0.0))
			]
		)
	rivalry_picker.item_selected.connect(_select_rivalry)
	section.add_child(rivalry_picker)

	rivalry_body = VBoxContainer.new()
	rivalry_body.name = "RivalryDossierBody"
	rivalry_body.add_theme_constant_override("separation", 12)
	section.add_child(rivalry_body)

	selected_rival = clampi(selected_rival, 0, rows.size() - 1)
	rivalry_picker.select(selected_rival)
	_render_rivalry_dossier(rows[selected_rival])


func _select_rivalry(index: int) -> void:
	var rows = _array(payload.get("rivalries"))
	if rows.is_empty() or index < 0 or index >= rows.size():
		return
	selected_rival = index
	if is_instance_valid(rivalry_picker):
		rivalry_picker.select(index)
	if is_instance_valid(rivalry_body):
		_clear(rivalry_body)
		_render_rivalry_dossier(rows[index])


func _render_rivalry_dossier(rivalry: Dictionary) -> void:
	var tone = _tier_color(str(rivalry.get("tier", "HISTORY BUILDING")))
	var top = PanelContainer.new()
	top.add_theme_stylebox_override("panel", _box(Color(tone, 0.04), 13, Color(tone, 0.30)))
	rivalry_body.add_child(top)

	var margin = MarginContainer.new()
	_set_margins(margin, 14, 12, 14, 12)
	top.add_child(margin)

	var body = VBoxContainer.new()
	body.add_theme_constant_override("separation", 8)
	margin.add_child(body)

	var header = HBoxContainer.new()
	header.add_theme_constant_override("separation", 12)
	body.add_child(header)

	var logo = Logo.new()
	logo.custom_minimum_size = Vector2(82, 82)
	header.add_child(logo)
	logo.configure(str(rivalry.get("opponent", "")))

	var copy = VBoxContainer.new()
	copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	header.add_child(copy)
	copy.add_child(_label(str(rivalry.get("opponent_name", "")), 24))
	copy.add_child(_label(
		"%s • HEAT %.1f" % [
			str(rivalry.get("tier", "")),
			float(rivalry.get("heat_score", 0.0))
		],
		11,
		tone
	))
	copy.add_child(_label(str(rivalry.get("narrative", "")), 11, DS.MUTED))

	var metrics = GridContainer.new()
	metrics.columns = 4
	metrics.add_theme_constant_override("h_separation", 7)
	metrics.add_theme_constant_override("v_separation", 7)
	body.add_child(metrics)
	_metric(metrics, "HEAD TO HEAD", str(rivalry.get("record", "0-0")), tone)
	_metric(metrics, "PLAYOFF MEETINGS", str(rivalry.get("playoff_meetings", 0)), DS.GOLD)
	_metric(metrics, "FINALS", str(rivalry.get("finals_meetings", 0)), DS.ACCENT)
	_metric(metrics, "CLOSE GAMES", str(rivalry.get("close_games", 0)), DS.TEXT)
	_metric(metrics, "OVERTIME", str(rivalry.get("overtime_games", 0)), DS.TEXT)
	_metric(metrics, "ELIMINATIONS FOR", str(rivalry.get("eliminations_for", 0)), DS.GOOD)
	_metric(metrics, "ELIMINATIONS AGAINST", str(rivalry.get("eliminations_against", 0)), DS.BAD)
	var streak = _dict(rivalry.get("head_to_head_streak"))
	_metric(metrics, "CURRENT H2H STREAK", "%s%s" % [str(streak.get("result", "")), str(streak.get("count", 0))], DS.MUTED)

	var series = _array(rivalry.get("series_history"))
	var series_card = _mini_section("POSTSEASON CHAPTERS", DS.GOLD)
	rivalry_body.add_child(series_card.get_parent())
	if series.is_empty():
		series_card.add_child(_label("No saved V3 playoff series against this opponent.", 11, DS.MUTED))
	else:
		for row in series:
			var verdict = "SERIES INCOMPLETE / RESULT NOT PROVEN"
			var winner = str(row.get("winner", ""))
			if winner != "":
				verdict = (
					"YOUR FRANCHISE ADVANCED"
					if winner == str(payload.get("team", ""))
					else "%s ADVANCED" % str(rivalry.get("opponent_name", winner)).to_upper()
				)
			series_card.add_child(_label(
				"%s • %s • %s" % [
					str(row.get("season", "")),
					str(row.get("record", "0-0")),
					verdict
				],
				11,
				DS.MUTED
			))

	var timeline = _array(rivalry.get("timeline"))
	var timeline_card = _mini_section("RIVALRY TIMELINE", tone)
	rivalry_body.add_child(timeline_card.get_parent())
	if timeline.is_empty():
		timeline_card.add_child(_label(
			"No completed V3 meeting has been recorded yet.",
			11,
			DS.MUTED
		))
	else:
		for event in timeline:
			var result = str(event.get("result", ""))
			var result_color = DS.GOOD if result == "W" else DS.BAD if result == "L" else DS.MUTED
			var context = "PLAYOFF" if bool(event.get("is_playoff", false)) else "REGULAR SEASON"
			var overtime = (
				" • %sOT" % str(event.get("overtime_periods", 0))
				if int(event.get("overtime_periods", 0)) > 0
				else ""
			)
			var day_text = (
				" • DAY %s" % str(event.get("day"))
				if event.get("day") != null
				else ""
			)
			var line = _label(
				"%s • %s %s-%s • %s%s%s" % [
					str(event.get("season", "")),
					result,
					str(event.get("team_score", 0)),
					str(event.get("opponent_score", 0)),
					context,
					overtime,
					day_text
				],
				11,
				result_color
			)
			timeline_card.add_child(line)

	var action_row = HBoxContainer.new()
	action_row.add_theme_constant_override("separation", 8)
	rivalry_body.add_child(action_row)
	action_row.add_child(_nav_button("OPEN GAME DAY", "GAME DAY"))
	action_row.add_child(_nav_button("OPEN THEATER", "THEATER"))
	action_row.add_child(_nav_button("OPEN LEGACY", "LEGACY"))


func _build_story_feed(data: Dictionary) -> void:
	var section = _section(
		"ACTIVE STORY FEED",
		"Story cards appear only when current schedule and saved evidence support them.",
		DS.GOLD
	)
	section.get_parent().name = "RivalryActiveStoryFeed"

	var stories = _array(data.get("active_stories"))
	if stories.is_empty():
		section.add_child(_empty(
			"No elevated rivalry, revenge, return-game or contender storyline is active right now. Advance the franchise and the story feed will evolve."
		))
		return

	for story in stories:
		var priority = int(story.get("priority", 2))
		var tone = DS.GOLD if priority == 0 else primary if priority == 1 else DS.ACCENT
		var card = PanelContainer.new()
		card.add_theme_stylebox_override("panel", _box(Color(tone, 0.035), 11, Color(tone, 0.24)))
		section.add_child(card)
		var margin = MarginContainer.new()
		_set_margins(margin, 12, 10, 12, 10)
		card.add_child(margin)
		var body = VBoxContainer.new()
		body.add_theme_constant_override("separation", 5)
		margin.add_child(body)
		body.add_child(_label(str(story.get("category", "")).to_upper(), 9, tone))
		body.add_child(_label(str(story.get("title", "")), 17))
		body.add_child(_label(str(story.get("detail", "")), 11, DS.MUTED))
		body.add_child(_label("SOURCE • " + str(story.get("evidence", "")), 9, DS.MUTED))
		var destination = str(story.get("destination", "STORIES"))
		if destination != "STORIES":
			body.add_child(_nav_button("OPEN " + destination, destination))


func _build_return_games(data: Dictionary) -> void:
	var section = _section(
		"FORMER PLAYER RETURN WATCH",
		"Return games require a committed franchise trade record plus the player's current opponent roster assignment.",
		Color("d7a759")
	)
	section.get_parent().name = "RivalryReturnGames"

	var rows = _array(data.get("former_player_returns"))
	if rows.is_empty():
		section.add_child(_empty(
			"No traded-away franchise player is currently scheduled to return against your team."
		))
		return

	var grid = GridContainer.new()
	grid.columns = 2
	grid.add_theme_constant_override("h_separation", 10)
	grid.add_theme_constant_override("v_separation", 10)
	section.add_child(grid)

	for row in rows:
		var panel = PanelContainer.new()
		panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		panel.add_theme_stylebox_override(
			"panel",
			_box(Color("171615"), 11, Color(Color("d7a759"), 0.30))
		)
		grid.add_child(panel)

		var margin = MarginContainer.new()
		_set_margins(margin, 11, 9, 11, 9)
		panel.add_child(margin)
		var body = HBoxContainer.new()
		body.add_theme_constant_override("separation", 9)
		margin.add_child(body)

		var portrait = Portrait.new()
		portrait.custom_minimum_size = Vector2(76, 72)
		body.add_child(portrait)
		portrait.configure({
			"player_id": str(row.get("player_id", "")),
			"name": str(row.get("name", ""))
		})

		var copy = VBoxContainer.new()
		copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		body.add_child(copy)
		copy.add_child(_label(str(row.get("name", "")), 15))
		copy.add_child(_label(
			"%s • %s OVR" % [
				str(row.get("position", "")),
				_display(row.get("overall"))
			],
			9,
			DS.MUTED
		))
		copy.add_child(_label(
			"RETURNS WITH %s • DAY %s" % [
				str(row.get("opponent_name", row.get("opponent", ""))).to_upper(),
				str(row.get("day", "?"))
			],
			10,
			Color("d7a759")
		))


func _build_league_wire(data: Dictionary) -> void:
	var section = _section(
		"LEAGUE STORY WIRE",
		"Finals rematches, .600+ contender clashes and five-game-or-longer streaks are surfaced from the current schedule.",
		DS.ACCENT
	)
	section.get_parent().name = "RivalryLeagueStoryWire"

	var rows = _array(data.get("league_story_wire"))
	if rows.is_empty():
		section.add_child(_empty(
			"No league-wide story game currently meets the evidence thresholds. This is expected early in a season."
		))
		return

	for row in rows:
		var card = PanelContainer.new()
		card.add_theme_stylebox_override(
			"panel",
			_box(Color(DS.ACCENT, 0.03), 11, Color(DS.ACCENT, 0.22))
		)
		section.add_child(card)

		var margin = MarginContainer.new()
		_set_margins(margin, 11, 9, 11, 9)
		card.add_child(margin)

		var body = HBoxContainer.new()
		body.add_theme_constant_override("separation", 10)
		margin.add_child(body)

		var away_logo = Logo.new()
		away_logo.custom_minimum_size = Vector2(48, 48)
		body.add_child(away_logo)
		away_logo.configure(str(row.get("away_team", "")))

		var copy = VBoxContainer.new()
		copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		body.add_child(copy)
		copy.add_child(_label(str(row.get("title", "")), 15))
		copy.add_child(_label(str(row.get("detail", "")), 10, DS.MUTED))
		copy.add_child(_label(
			"LEAGUE DAY %s • %s DAY(S) AWAY" % [
				str(row.get("day", "?")),
				str(row.get("days_away", "?"))
			],
			9,
			DS.ACCENT
		))

		var home_logo = Logo.new()
		home_logo.custom_minimum_size = Vector2(48, 48)
		body.add_child(home_logo)
		home_logo.configure(str(row.get("home_team", "")))


func _build_scope(data: Dictionary) -> void:
	var scope = _dict(data.get("scope"))
	var section = _section(
		"STORY ENGINE SCOPE",
		"Expansion 48 is descriptive, persistent through saved history, and intentionally read-only.",
		DS.MUTED
	)
	section.get_parent().name = "RivalryStoryScope"
	section.add_child(_label(str(scope.get("note", "")), 11, DS.MUTED))
	section.add_child(_label(str(scope.get("series_note", "")), 11, DS.MUTED))
	var row = GridContainer.new()
	row.columns = 3
	row.add_theme_constant_override("h_separation", 8)
	row.add_theme_constant_override("v_separation", 8)
	section.add_child(row)
	row.add_child(_scope_pill("NO FABRICATED HISTORY", DS.GOOD))
	row.add_child(_scope_pill("NO SAVE WRITES", DS.GOOD))
	row.add_child(_scope_pill("V2 PROTECTED", DS.GOOD))


func _star_matchup_card(star: Dictionary) -> Control:
	var panel = PanelContainer.new()
	panel.add_theme_stylebox_override(
		"panel",
		_box(Color(DS.GOLD, 0.035), 12, Color(DS.GOLD, 0.22))
	)
	var margin = MarginContainer.new()
	_set_margins(margin, 12, 10, 12, 10)
	panel.add_child(margin)

	var body = VBoxContainer.new()
	body.add_theme_constant_override("separation", 8)
	margin.add_child(body)
	body.add_child(_label("STAR MATCHUP", 10, DS.GOLD))

	var row = HBoxContainer.new()
	row.add_theme_constant_override("separation", 12)
	body.add_child(row)
	row.add_child(_star_player(_dict(star.get("active")), primary))

	var versus = _label("VS", 20, DS.GOLD)
	versus.custom_minimum_size = Vector2(70, 0)
	versus.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	versus.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	row.add_child(versus)

	row.add_child(_star_player(_dict(star.get("opponent")), Color("78869b")))
	return panel


func _star_player(player: Dictionary, tone: Color) -> Control:
	var body = VBoxContainer.new()
	body.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	body.add_theme_constant_override("separation", 4)

	var portrait = Portrait.new()
	portrait.custom_minimum_size = Vector2(0, 96)
	body.add_child(portrait)
	portrait.configure({
		"player_id": str(player.get("player_id", "")),
		"name": str(player.get("name", ""))
	})

	var name = _label(str(player.get("name", "")), 16)
	name.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	body.add_child(name)

	var meta = _label(
		"%s • %.1f OVR" % [
			str(player.get("position", "")),
			float(player.get("overall", 0.0))
		],
		10,
		tone
	)
	meta.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	body.add_child(meta)

	if player.get("ppg") != null:
		var stats = _label(
			"%.1f PPG • %.1f RPG • %.1f APG" % [
				float(player.get("ppg", 0.0)),
				float(player.get("rpg", 0.0)),
				float(player.get("apg", 0.0))
			],
			9,
			DS.MUTED
		)
		stats.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		body.add_child(stats)
	else:
		var waiting = _label("Season production not recorded yet", 9, DS.MUTED)
		waiting.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		body.add_child(waiting)
	return body


func _team_poster(team: String, display_name: String, tone: Color) -> Control:
	var panel = PanelContainer.new()
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	panel.add_theme_stylebox_override(
		"panel",
		_box(Color(tone, 0.04), 13, Color(tone, 0.24))
	)
	var margin = MarginContainer.new()
	_set_margins(margin, 11, 10, 11, 10)
	panel.add_child(margin)
	var body = VBoxContainer.new()
	body.add_theme_constant_override("separation", 5)
	margin.add_child(body)

	var logo = Logo.new()
	logo.custom_minimum_size = Vector2(0, 90)
	body.add_child(logo)
	logo.configure(team)

	var name = _label(display_name.to_upper(), 17)
	name.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	body.add_child(name)
	var abbr = _label(team, 10, tone)
	abbr.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	body.add_child(abbr)
	return panel


func _section(title_text: String, detail_text: String, tone: Color) -> VBoxContainer:
	var body = _card(content, tone)
	body.add_child(_label(title_text, 21))
	body.add_child(_label(detail_text, 10, DS.MUTED))
	return body


func _mini_section(title_text: String, tone: Color) -> VBoxContainer:
	var panel = PanelContainer.new()
	var style = _box(Color(tone, 0.025), 11, Color(tone, 0.20))
	style.set("content_margin_left", 12)
	style.set("content_margin_top", 10)
	style.set("content_margin_right", 12)
	style.set("content_margin_bottom", 10)
	panel.add_theme_stylebox_override("panel", style)
	var body = VBoxContainer.new()
	body.add_theme_constant_override("separation", 6)
	panel.add_child(body)
	body.add_child(_label(title_text, 14, tone))
	return body


func _metric(parent: GridContainer, title_text: String, value_text: String, tone: Color) -> void:
	var panel = PanelContainer.new()
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	panel.add_theme_stylebox_override(
		"panel",
		_box(Color(tone, 0.035), 9, Color(tone, 0.20))
	)
	parent.add_child(panel)
	var margin = MarginContainer.new()
	_set_margins(margin, 9, 8, 9, 8)
	panel.add_child(margin)
	var body = VBoxContainer.new()
	margin.add_child(body)
	body.add_child(_label(title_text, 8, tone))
	body.add_child(_label(value_text, 15))


func _scope_pill(text_value: String, tone: Color) -> Control:
	var panel = PanelContainer.new()
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	panel.add_theme_stylebox_override(
		"panel",
		_box(Color(tone, 0.035), 8, Color(tone, 0.20))
	)
	var label = _label(text_value, 9, tone)
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	panel.add_child(label)
	return panel


func _empty(text_value: String) -> Control:
	var panel = PanelContainer.new()
	panel.add_theme_stylebox_override(
		"panel",
		_box(Color("101821"), 10, Color(DS.BORDER, 0.72))
	)
	var margin = MarginContainer.new()
	_set_margins(margin, 11, 10, 11, 10)
	panel.add_child(margin)
	var label = _label(text_value, 11, DS.MUTED)
	margin.add_child(label)
	return panel


func _nav_button(text_value: String, destination: String) -> Button:
	return _button(text_value, func(): navigate_requested.emit(destination))


func _button(text_value: String, callback: Callable) -> Button:
	var button = Button.new()
	button.text = text_value
	button.custom_minimum_size.y = 40
	button.add_theme_font_size_override("font_size", 9)
	button.pressed.connect(callback)
	return button


func _card(parent: Node, border: Color) -> VBoxContainer:
	var panel = PanelContainer.new()
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var style = _box(DS.PANEL_ALT, 16, Color(border, 0.50))
	for side in ["left", "right", "top", "bottom"]:
		style.set("content_margin_" + side, 16)
	panel.add_theme_stylebox_override("panel", style)
	parent.add_child(panel)
	var body = VBoxContainer.new()
	body.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	body.add_theme_constant_override("separation", 9)
	panel.add_child(body)
	return body


func _label(text_value: String, font_size: int, color: Color = DS.TEXT) -> Label:
	var label = Label.new()
	label.text = text_value
	label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.add_theme_font_size_override("font_size", font_size)
	label.add_theme_color_override("font_color", color)
	return label


func _tier_color(tier: String) -> Color:
	match tier:
		"HISTORIC":
			return DS.GOLD
		"MAJOR":
			return Color("e28a72")
		"HEATED":
			return Color("e5a85c")
		"EMERGING":
			return DS.ACCENT
		_:
			return DS.MUTED


func _box(fill: Color, radius: int, border: Color) -> StyleBoxFlat:
	var style = StyleBoxFlat.new()
	style.bg_color = fill
	style.border_color = border
	style.set_border_width_all(1)
	style.set_corner_radius_all(radius)
	return style


func _set_margins(
	container: MarginContainer,
	left: int,
	top: int,
	right: int,
	bottom: int
) -> void:
	container.add_theme_constant_override("margin_left", left)
	container.add_theme_constant_override("margin_top", top)
	container.add_theme_constant_override("margin_right", right)
	container.add_theme_constant_override("margin_bottom", bottom)


func _clear(parent: Node, keep: Node = null) -> void:
	for child in parent.get_children():
		if child != keep:
			parent.remove_child(child)
			child.queue_free()


func _dict(value) -> Dictionary:
	return value if typeof(value) == TYPE_DICTIONARY else {}


func _array(value) -> Array:
	return value if typeof(value) == TYPE_ARRAY else []


func _display(value) -> String:
	return "—" if value == null or str(value).strip_edges() == "" else str(value)
