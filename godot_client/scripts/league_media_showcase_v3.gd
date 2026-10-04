extends VBoxContainer

const DesignSystemV3 = preload("res://scripts/design_system_v3.gd")
const TeamBrandingV3 = preload("res://scripts/team_branding_v3.gd")
const TeamLogoV3 = preload("res://scripts/team_logo_v3.gd")
const PlayerPortraitV3 = preload("res://scripts/player_portrait_v3.gd")

const PANEL := DesignSystemV3.PANEL
const PANEL_ALT := DesignSystemV3.PANEL_ALT
const TEXT := DesignSystemV3.TEXT
const MUTED := DesignSystemV3.MUTED
const ACCENT := DesignSystemV3.ACCENT
const GOOD := DesignSystemV3.GOOD
const BAD := DesignSystemV3.BAD
const GOLD := DesignSystemV3.GOLD
const BORDER := DesignSystemV3.BORDER

var active_team := ""
var primary := DesignSystemV3.TEAM_PRIMARY
var secondary := DesignSystemV3.GOLD


func _ready() -> void:
	name = "LeagueMediaShowcase"
	size_flags_horizontal = Control.SIZE_EXPAND_FILL
	add_theme_constant_override("separation", 14)


func configure(
	payload: Dictionary,
	team_abbreviation: String,
	primary_color: Color,
	secondary_color: Color
) -> void:
	active_team = team_abbreviation.strip_edges().to_upper()
	primary = primary_color
	secondary = secondary_color
	_clear_children(self)

	_build_pulse(payload)
	_build_schedule(payload)
	_build_leaders_and_awards(payload)
	_build_playoff_and_world(payload)


func _build_pulse(payload: Dictionary) -> void:
	var card := _card(Color(primary, 0.10), Color(TeamBrandingV3.hover_color(primary), 0.62), 18)
	card.name = "LeaguePulseHero"
	card.custom_minimum_size = Vector2(0, 155)
	add_child(card)

	var body := _body(card, 18)
	var top := HBoxContainer.new()
	top.add_theme_constant_override("separation", 14)
	body.add_child(top)

	var identity := HBoxContainer.new()
	identity.custom_minimum_size = Vector2(330, 0)
	identity.add_theme_constant_override("separation", 12)
	top.add_child(identity)

	var logo := TeamLogoV3.new()
	logo.custom_minimum_size = Vector2(104, 90)
	logo.configure(active_team)
	identity.add_child(logo)

	var identity_copy := VBoxContainer.new()
	identity_copy.alignment = BoxContainer.ALIGNMENT_CENTER
	identity_copy.add_theme_constant_override("separation", 3)
	identity.add_child(identity_copy)
	identity_copy.add_child(_label("LEAGUE PULSE", 10, TeamBrandingV3.hover_color(primary)))
	var team_title := _label(active_team if active_team != "" else "FRANCHISE", 28, TEXT)
	identity_copy.add_child(team_title)

	var standing := _dict(payload.get("active_team_standing"))
	var pulse_schedule = _dict(payload.get("schedule"))
	var pulse_completed = _i(pulse_schedule.get("completed_games"))
	var position_text := "POSITION UNAVAILABLE"
	if not standing.is_empty():
		var pulse_record = _s(standing.get("record"), "0-0")
		var pulse_conference = _s(standing.get("conference"), "LEAGUE").to_upper()
		if pulse_completed <= 0 or pulse_record == "0-0":
			position_text = "%s • %s • OPENING WEEK" % [pulse_conference, pulse_record]
		else:
			position_text = "#%d %s • %s" % [
				_i(standing.get("rank")),
				pulse_conference,
				pulse_record,
			]
	identity_copy.add_child(_label(position_text, 12, MUTED))

	var metrics := GridContainer.new()
	metrics.columns = 3
	metrics.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	metrics.add_theme_constant_override("h_separation", 10)
	top.add_child(metrics)

	var season := _dict(payload.get("season"))
	var schedule := _dict(payload.get("schedule"))
	var postseason := _dict(payload.get("postseason"))
	_metric(metrics, "SEASON", "%s • %s" % [
		_s(season.get("label"), "UNKNOWN"),
		_s(season.get("phase"), "unknown").replace("_", " ").to_upper(),
	], GOLD)

	var completed := _i(schedule.get("completed_games"))
	var total := _i(schedule.get("total_games"))
	var progress_value := "UNAVAILABLE"
	if total > 0:
		progress_value = "%d / %d • %.0f%%" % [completed, total, 100.0 * completed / total]
	_metric(metrics, "LEAGUE PROGRESS", progress_value, ACCENT)

	var stage := _s(postseason.get("stage"), "")
	var postseason_value := "REGULAR SEASON"
	if bool(postseason.get("active", false)):
		postseason_value = stage.replace("_", " ").to_upper() if stage != "" else "ACTIVE"
	elif _s(postseason.get("champion"), "") != "":
		postseason_value = "CHAMPION • %s" % _s(postseason.get("champion"))
	_metric(metrics, "POSTSEASON", postseason_value, GOOD)


func _build_schedule(payload: Dictionary) -> void:
	var section := VBoxContainer.new()
	section.add_theme_constant_override("separation", 8)
	add_child(section)
	section.add_child(_section_header("SCHEDULE CENTER", "Recent finals and the next games on the league calendar"))

	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 12)
	section.add_child(row)

	var schedule := _dict(payload.get("schedule"))
	var recent_card := _card(PANEL, Color(GOOD, 0.38), 16)
	recent_card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var recent_body := _body(recent_card, 14)
	recent_body.add_child(_label("RECENT FINALS", 11, GOOD))
	var recent := _array(schedule.get("recent_results"))
	if recent.is_empty():
		recent_body.add_child(_empty("No completed games are available yet."))
	else:
		for raw in recent.slice(0, 4):
			recent_body.add_child(_matchup_row(_dict(raw), true))
	row.add_child(recent_card)

	var upcoming_card := _card(PANEL, Color(ACCENT, 0.40), 16)
	upcoming_card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var upcoming_body := _body(upcoming_card, 14)
	upcoming_body.add_child(_label("UPCOMING", 11, ACCENT))
	var upcoming := _array(schedule.get("upcoming_games"))
	if upcoming.is_empty():
		upcoming_body.add_child(_empty("No remaining regular-season games are exposed."))
	else:
		for raw in upcoming.slice(0, 4):
			upcoming_body.add_child(_matchup_row(_dict(raw), false))
	row.add_child(upcoming_card)


func _build_leaders_and_awards(payload: Dictionary) -> void:
	var section := VBoxContainer.new()
	section.add_theme_constant_override("separation", 8)
	add_child(section)
	section.add_child(_section_header("STAR WATCH", "League leaders and the current awards race"))

	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 12)
	section.add_child(row)

	var leaders_card := _card(PANEL, Color(ACCENT, 0.34), 16)
	leaders_card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var leaders_body := _body(leaders_card, 14)
	leaders_body.add_child(_label("LEAGUE LEADERS", 11, ACCENT))

	var leaders := _dict(payload.get("leaders"))
	var leader_grid := GridContainer.new()
	leader_grid.columns = 3
	leader_grid.add_theme_constant_override("h_separation", 8)
	leader_grid.add_theme_constant_override("v_separation", 8)
	leaders_body.add_child(leader_grid)

	var leader_specs := [
		["SCORING", "scoring", "ppg", "PPG"],
		["REBOUNDING", "rebounds", "rpg", "RPG"],
		["ASSISTS", "assists", "apg", "APG"],
	]
	for spec in leader_specs:
		var rows := _array(leaders.get(str(spec[1])))
		var leader: Dictionary = _dict(rows[0]) if not rows.is_empty() else {}
		leader_grid.add_child(_star_card(str(spec[0]), leader, str(spec[2]), str(spec[3]), ACCENT))
	row.add_child(leaders_card)

	var awards_card := _card(PANEL, Color(GOLD, 0.42), 16)
	awards_card.custom_minimum_size = Vector2(365, 0)
	var awards_body := _body(awards_card, 14)
	awards_body.add_child(_label("AWARDS RACE", 11, GOLD))

	var awards := _dict(payload.get("award_watch"))
	var awards_grid := GridContainer.new()
	awards_grid.columns = 2
	awards_grid.add_theme_constant_override("h_separation", 8)
	awards_body.add_child(awards_grid)
	var mvp_rows := _array(awards.get("mvp_watch"))
	var dpoy_rows := _array(awards.get("dpoy_watch"))
	awards_grid.add_child(_award_card(
		"MVP WATCH",
		_dict(mvp_rows[0]) if not mvp_rows.is_empty() else {},
		GOLD
	))
	awards_grid.add_child(_award_card(
		"DPOY WATCH",
		_dict(dpoy_rows[0]) if not dpoy_rows.is_empty() else {},
		GOOD
	))
	row.add_child(awards_card)


func _build_playoff_and_world(payload: Dictionary) -> void:
	var schedule = _dict(payload.get("schedule"))
	var completed = _i(schedule.get("completed_games"))
	var opening = completed <= 0

	var section = VBoxContainer.new()
	section.add_theme_constant_override("separation", 8)
	add_child(section)
	section.add_child(_section_header(
		"LEAGUE PREVIEW + OPENING WEEK" if opening else "PLAYOFF RACE + LEAGUE WIRE",
		"Opening slate, conference context, and truthful league headlines" if opening else "Seeding pressure, postseason state, and truthful league headlines"
	))

	var row = HBoxContainer.new()
	row.add_theme_constant_override("separation", 12)
	section.add_child(row)

	var picture_card = _card(PANEL, Color(GOLD, 0.34), 16)
	picture_card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var picture_body = _body(picture_card, 14)
	picture_body.add_child(_label("CONFERENCE OUTLOOK" if opening else "PLAYOFF PICTURE", 11, GOLD))

	if opening:
		var opening_copy = _label(
			"All teams are level before the first completed result. Seeding and playoff labels stay neutral until the standings have real separation.",
			11,
			MUTED
		)
		opening_copy.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		picture_body.add_child(opening_copy)
		picture_body.add_child(_divider())
		var upcoming = _array(schedule.get("upcoming_games"))
		if upcoming.is_empty():
			picture_body.add_child(_empty("The opening slate is not exposed yet."))
		else:
			for raw in upcoming.slice(0, 4):
				picture_body.add_child(_matchup_row(_dict(raw), false))
	else:
		var conferences = HBoxContainer.new()
		conferences.add_theme_constant_override("separation", 10)
		picture_body.add_child(conferences)
		var picture = _dict(payload.get("playoff_picture"))
		conferences.add_child(_playoff_column("EAST", _array(picture.get("east"))))
		conferences.add_child(_playoff_column("WEST", _array(picture.get("west"))))
	row.add_child(picture_card)

	var world_card = _card(PANEL, Color(primary, 0.42), 16)
	world_card.custom_minimum_size = Vector2(390, 0)
	var world_body = _body(world_card, 14)
	world_body.add_child(_label("LEAGUE WIRE", 11, TeamBrandingV3.hover_color(primary)))
	var wire_items = _wire_items(payload)
	if wire_items.is_empty():
		world_body.add_child(_empty("League wire has no events to surface yet."))
	else:
		for item in wire_items.slice(0, 6):
			world_body.add_child(_wire_row(str(item)))

	var history = _array(payload.get("season_history"))
	if not history.is_empty():
		world_body.add_child(_divider())
		world_body.add_child(_label("RECENT CHAMPIONS", 10, MUTED))
		for raw in history.slice(0, 3):
			world_body.add_child(_history_row(_dict(raw)))
	row.add_child(world_card)


func _matchup_row(game: Dictionary, completed: bool) -> Control:
	var card := _card(PANEL_ALT, Color(BORDER, 0.85), 11)
	card.custom_minimum_size = Vector2(0, 64)
	var body := _body(card, 8)
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 8)
	body.add_child(row)

	var away := _s(game.get("away_team"), "---").to_upper()
	var home := _s(game.get("home_team"), "---").to_upper()

	var away_logo := TeamLogoV3.new()
	away_logo.custom_minimum_size = Vector2(42, 38)
	away_logo.configure(away)
	row.add_child(away_logo)

	var away_copy := VBoxContainer.new()
	away_copy.custom_minimum_size = Vector2(82, 0)
	away_copy.alignment = BoxContainer.ALIGNMENT_CENTER
	row.add_child(away_copy)
	away_copy.add_child(_label(away, 13, TEXT))
	if completed:
		away_copy.add_child(_label(str(_i(game.get("away_score"))), 17, TEXT))

	var center := VBoxContainer.new()
	center.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	center.alignment = BoxContainer.ALIGNMENT_CENTER
	row.add_child(center)
	center.add_child(_label("FINAL" if completed else "AT", 9, GOOD if completed else MUTED))
	center.add_child(_label("DAY %d" % _i(game.get("day_index")), 10, MUTED))

	var home_copy := VBoxContainer.new()
	home_copy.custom_minimum_size = Vector2(82, 0)
	home_copy.alignment = BoxContainer.ALIGNMENT_CENTER
	home_copy.add_theme_constant_override("separation", 1)
	row.add_child(home_copy)
	var home_title := _label(home, 13, TEXT)
	home_title.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	home_copy.add_child(home_title)
	if completed:
		var home_score := _label(str(_i(game.get("home_score"))), 17, TEXT)
		home_score.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
		home_copy.add_child(home_score)

	var home_logo := TeamLogoV3.new()
	home_logo.custom_minimum_size = Vector2(42, 38)
	home_logo.configure(home)
	row.add_child(home_logo)
	return card


func _star_card(
	title: String,
	player: Dictionary,
	stat_key: String,
	stat_label: String,
	tone: Color
) -> Control:
	var card := _card(PANEL_ALT, Color(tone, 0.30), 12)
	card.custom_minimum_size = Vector2(0, 132)
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var body := _body(card, 9)
	body.add_child(_label(title, 9, tone))

	if player.is_empty():
		body.add_child(_empty("No qualifier"))
		return card

	var top := HBoxContainer.new()
	top.add_theme_constant_override("separation", 8)
	body.add_child(top)

	var portrait := PlayerPortraitV3.new()
	portrait.custom_minimum_size = Vector2(72, 64)
	top.add_child(portrait)
	portrait.configure(_portrait_payload(player))

	var copy := VBoxContainer.new()
	copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	copy.alignment = BoxContainer.ALIGNMENT_CENTER
	top.add_child(copy)
	var player_name := _label(_s(player.get("name"), "Unknown"), 12, TEXT)
	player_name.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	copy.add_child(player_name)
	copy.add_child(_label(_s(player.get("team"), "---"), 9, MUTED))
	copy.add_child(_label("%.1f %s" % [_f(player.get(stat_key)), stat_label], 18, tone))
	return card


func _award_card(title: String, player: Dictionary, tone: Color) -> Control:
	var card := _card(PANEL_ALT, Color(tone, 0.32), 12)
	card.custom_minimum_size = Vector2(0, 155)
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var body := _body(card, 9)
	body.add_child(_label(title, 9, tone))
	if player.is_empty():
		body.add_child(_empty("No candidate"))
		return card

	var portrait := PlayerPortraitV3.new()
	portrait.custom_minimum_size = Vector2(92, 80)
	body.add_child(portrait)
	portrait.configure(_portrait_payload(player))
	var player_name := _label(_s(player.get("name"), "Unknown"), 12, TEXT)
	player_name.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	player_name.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	body.add_child(player_name)
	var stats := _label("%.1f PPG • %.1f RPG • %.1f APG" % [
		_f(player.get("ppg")), _f(player.get("rpg")), _f(player.get("apg"))
	], 9, MUTED)
	stats.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	body.add_child(stats)
	return card


func _playoff_column(title: String, rows: Array) -> Control:
	var card := _card(PANEL_ALT, Color(BORDER, 0.80), 12)
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var body := _body(card, 10)
	body.add_child(_label(title, 10, TEXT))

	if rows.is_empty():
		body.add_child(_empty("Unavailable"))
		return card

	for raw in rows.slice(0, 10):
		var item := _dict(raw)
		var line := HBoxContainer.new()
		line.add_theme_constant_override("separation", 6)
		body.add_child(line)

		var seed := _label("#%d" % _i(item.get("seed")), 10, MUTED)
		seed.custom_minimum_size = Vector2(28, 0)
		line.add_child(seed)

		var team := _s(item.get("team"), "---").to_upper()
		var logo := TeamLogoV3.new()
		logo.custom_minimum_size = Vector2(26, 24)
		logo.configure(team)
		line.add_child(logo)

		var team_label := _label(team, 11, TEXT)
		team_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		line.add_child(team_label)

		var record := _label(_s(item.get("record"), "0-0"), 10, MUTED)
		record.custom_minimum_size = Vector2(54, 0)
		record.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
		line.add_child(record)

		var zone := _s(item.get("zone"), "")
		var zone_text := "PLAYOFF" if zone == "playoff" else "PLAY-IN"
		var zone_color := GOOD if zone == "playoff" else GOLD
		var zone_label := _label(zone_text, 8, zone_color)
		zone_label.custom_minimum_size = Vector2(54, 0)
		zone_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
		line.add_child(zone_label)
	return card


func _history_row(item: Dictionary) -> Control:
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 8)

	var champion := _s(item.get("champion"), "")
	var logo := TeamLogoV3.new()
	logo.custom_minimum_size = Vector2(32, 28)
	logo.configure(champion)
	row.add_child(logo)

	var text := "%s • %s" % [_s(item.get("season"), "Season"), champion if champion != "" else "TBD"]
	var runner_up := _s(item.get("runner_up"), "")
	if runner_up != "":
		text += " over %s" % runner_up
	var label := _label(text, 10, TEXT)
	label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row.add_child(label)
	return row


func _wire_items(payload: Dictionary) -> Array[String]:
	var items: Array[String] = []
	var schedule = _dict(payload.get("schedule"))
	var completed = _i(schedule.get("completed_games"))
	var standing = _dict(payload.get("active_team_standing"))

	if not standing.is_empty():
		var record = _s(standing.get("record"), "0-0")
		var conference = _s(standing.get("conference"), "league").to_upper()
		if completed <= 0 or record == "0-0":
			items.append("%s opens the season at %s in the %s; seeding begins after completed games." % [
				_s(standing.get("team"), active_team),
				record,
				conference,
			])
		else:
			items.append("%s is #%d in the %s at %s." % [
				_s(standing.get("team"), active_team),
				_i(standing.get("rank")),
				conference,
				record,
			])

	for raw in _array(schedule.get("recent_results")).slice(0, 2):
		var result = _dict(raw)
		items.append("FINAL • %s %d at %s %d" % [
			_s(result.get("away_team"), "---"),
			_i(result.get("away_score")),
			_s(result.get("home_team"), "---"),
			_i(result.get("home_score")),
		])

	if completed <= 0:
		for raw in _array(schedule.get("upcoming_games")).slice(0, 2):
			var upcoming = _dict(raw)
			items.append("UPCOMING • %s at %s • Day %d" % [
				_s(upcoming.get("away_team"), "---"),
				_s(upcoming.get("home_team"), "---"),
				_i(upcoming.get("day_index")),
			])

	var awards = _dict(payload.get("award_watch"))
	var mvp_rows = _array(awards.get("mvp_watch"))
	if not mvp_rows.is_empty():
		var leader = _dict(mvp_rows[0])
		items.append("MVP WATCH • %s (%s) leads the current projection." % [
			_s(leader.get("name"), "Unknown"),
			_s(leader.get("team"), "---"),
		])

	var postseason = _dict(payload.get("postseason"))
	if bool(postseason.get("active", false)):
		items.append("POSTSEASON • %s is active." % _s(postseason.get("stage"), "stage").replace("_", " ").to_upper())
	var champion = _s(postseason.get("champion"), "")
	if champion != "":
		items.append("CHAMPION • %s has won the current archived season." % champion)
	return items


func _wire_row(text_value: String) -> Control:
	var panel := PanelContainer.new()
	panel.add_theme_stylebox_override("panel", _box(Color(PANEL_ALT, 0.72), Color(BORDER, 0.68), 10))
	var margin := MarginContainer.new()
	_set_margins(margin, 10, 8, 10, 8)
	panel.add_child(margin)

	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 8)
	margin.add_child(row)

	var dot := Label.new()
	dot.text = "●"
	dot.add_theme_color_override("font_color", TeamBrandingV3.hover_color(primary))
	dot.add_theme_font_size_override("font_size", 9)
	row.add_child(dot)

	var label := _label(text_value, 10, TEXT)
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row.add_child(label)
	return panel


func _metric(parent: GridContainer, title: String, value: String, tone: Color) -> void:
	var card := _card(PANEL_ALT, Color(tone, 0.30), 12)
	card.custom_minimum_size = Vector2(0, 88)
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var body := _body(card, 11)

	var bar := ColorRect.new()
	bar.custom_minimum_size = Vector2(0, 3)
	bar.color = tone
	bar.mouse_filter = Control.MOUSE_FILTER_IGNORE
	body.add_child(bar)
	body.add_child(_label(title, 9, Color(tone, 0.95)))
	var value_label := _label(value, 14, TEXT)
	value_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	body.add_child(value_label)
	parent.add_child(card)


func _section_header(title: String, subtitle: String) -> Control:
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 10)

	var titles := VBoxContainer.new()
	titles.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row.add_child(titles)
	titles.add_child(_label(title, 17, TEXT))
	titles.add_child(_label(subtitle, 10, MUTED))

	var accent := Label.new()
	accent.text = "FRANCHISE NETWORK"
	accent.add_theme_color_override("font_color", TeamBrandingV3.hover_color(primary))
	accent.add_theme_font_size_override("font_size", 9)
	row.add_child(accent)
	return row


func _portrait_payload(player: Dictionary) -> Dictionary:
	return {
		"player_id": _s(player.get("player_id"), ""),
		"name": _s(player.get("name"), "Unknown Player"),
		"generated_prospect": bool(player.get("generated_prospect", false)),
	}


func _card(fill: Color, border: Color, radius: int) -> PanelContainer:
	var card := PanelContainer.new()
	card.add_theme_stylebox_override("panel", _box(fill, border, radius))
	return card


func _body(card: PanelContainer, margin_size: int) -> VBoxContainer:
	var margin := MarginContainer.new()
	_set_margins(margin, margin_size, margin_size, margin_size, margin_size)
	card.add_child(margin)
	var body := VBoxContainer.new()
	body.add_theme_constant_override("separation", 7)
	margin.add_child(body)
	return body


func _divider() -> HSeparator:
	var divider := HSeparator.new()
	divider.modulate = Color(1, 1, 1, 0.10)
	return divider


func _empty(text_value: String) -> Label:
	var label := _label(text_value, 10, MUTED)
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	return label


func _label(text_value: String, size: int, color: Color) -> Label:
	var label := Label.new()
	label.text = text_value
	label.add_theme_font_size_override("font_size", size)
	label.add_theme_color_override("font_color", color)
	return label


func _box(fill: Color, border: Color, radius: int) -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = fill
	style.border_color = border
	style.set_border_width_all(1)
	style.corner_radius_top_left = radius
	style.corner_radius_top_right = radius
	style.corner_radius_bottom_left = radius
	style.corner_radius_bottom_right = radius
	return style


func _set_margins(container: MarginContainer, left: int, top: int, right: int, bottom: int) -> void:
	container.add_theme_constant_override("margin_left", left)
	container.add_theme_constant_override("margin_top", top)
	container.add_theme_constant_override("margin_right", right)
	container.add_theme_constant_override("margin_bottom", bottom)


func _dict(value) -> Dictionary:
	return value if typeof(value) == TYPE_DICTIONARY else {}


func _array(value) -> Array:
	return value if typeof(value) == TYPE_ARRAY else []


func _s(value, fallback: String = "") -> String:
	if value == null:
		return fallback
	var text := str(value).strip_edges()
	return fallback if text == "" else text


func _i(value, fallback: int = 0) -> int:
	if value == null:
		return fallback
	return int(value)


func _f(value, fallback: float = 0.0) -> float:
	if value == null:
		return fallback
	return float(value)


func _clear_children(node: Node) -> void:
	for child in node.get_children():
		node.remove_child(child)
		child.queue_free()
