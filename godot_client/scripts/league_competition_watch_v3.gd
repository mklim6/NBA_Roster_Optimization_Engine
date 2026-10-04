extends VBoxContainer

# Batch 35 living league + competition watch
# Read-only presentation component. It consumes the existing league-intelligence payload.

const DesignSystemV3 = preload("res://scripts/design_system_v3.gd")
const TeamBrandingV3 = preload("res://scripts/team_branding_v3.gd")
const TeamLogoV3 = preload("res://scripts/team_logo_v3.gd")

const PANEL = DesignSystemV3.PANEL
const PANEL_ALT = DesignSystemV3.PANEL_ALT
const TEXT = DesignSystemV3.TEXT
const MUTED = DesignSystemV3.MUTED
const ACCENT = DesignSystemV3.ACCENT
const GOOD = DesignSystemV3.GOOD
const GOLD = DesignSystemV3.GOLD
const BORDER = DesignSystemV3.BORDER

var active_team = ""
var primary = DesignSystemV3.TEAM_PRIMARY
var secondary = DesignSystemV3.GOLD


func _ready() -> void:
	name = "LeagueCompetitionWatch"
	size_flags_horizontal = Control.SIZE_EXPAND_FILL
	add_theme_constant_override("separation", 10)


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

	var schedule = _dict(payload.get("schedule"))
	var completed = _i(schedule.get("completed_games"))
	var total = _i(schedule.get("total_games"))
	var season = _dict(payload.get("season"))

	var phase_title = "OPENING WEEK"
	var phase_detail = "The race is about to begin. Standings become meaningful after completed games."
	if completed > 0:
		var pct = float(completed) / float(max(total, 1))
		if pct >= 0.82:
			phase_title = "PLAYOFF PUSH"
			phase_detail = "Every result now carries seeding pressure. Track the teams immediately around your franchise."
		elif pct >= 0.55:
			phase_title = "STRETCH RUN"
			phase_detail = "The conference picture is taking shape. Your closest competitors matter more with every game."
		else:
			phase_title = "CONFERENCE PRESSURE"
			phase_detail = "The standings race is live. See who you are chasing, who is chasing you, and what comes next."

	var section_header = HBoxContainer.new()
	section_header.add_theme_constant_override("separation", 12)
	add_child(section_header)

	var header_copy = VBoxContainer.new()
	header_copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	header_copy.add_theme_constant_override("separation", 2)
	section_header.add_child(header_copy)
	header_copy.add_child(_label("LIVING LEAGUE • COMPETITION WATCH", 10, TeamBrandingV3.hover_color(primary)))
	header_copy.add_child(_label(phase_title, 25, TEXT))
	var detail = _label(phase_detail, 11, MUTED)
	detail.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	header_copy.add_child(detail)

	var season_badge = _card(Color(primary, 0.08), Color(primary, 0.48), 12)
	season_badge.custom_minimum_size = Vector2(220, 72)
	var season_body = _body(season_badge, 10)
	season_body.add_child(_label(_s(season.get("label"), "SEASON"), 10, MUTED))
	season_body.add_child(_label(
		"%d / %d GAMES" % [completed, total] if total > 0 else "SCHEDULE READY",
		15,
		GOOD if completed > 0 else GOLD
	))
	section_header.add_child(season_badge)

	var grid = GridContainer.new()
	grid.columns = 3
	grid.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	grid.add_theme_constant_override("h_separation", 12)
	grid.add_theme_constant_override("v_separation", 12)
	add_child(grid)

	grid.add_child(_build_franchise_race_card(payload, completed))
	grid.add_child(_build_next_test_card(payload))
	grid.add_child(_build_pressure_card(payload, completed))


func _build_franchise_race_card(payload: Dictionary, completed: int) -> Control:
	var card = _card(PANEL, Color(primary, 0.46), 16)
	card.custom_minimum_size = Vector2(0, 205)
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var body = _body(card, 14)
	body.add_child(_label("YOUR FRANCHISE", 10, TeamBrandingV3.hover_color(primary)))

	var identity = HBoxContainer.new()
	identity.add_theme_constant_override("separation", 12)
	body.add_child(identity)

	var logo = TeamLogoV3.new()
	logo.custom_minimum_size = Vector2(82, 72)
	logo.configure(active_team)
	identity.add_child(logo)

	var standing = _dict(payload.get("active_team_standing"))
	var copy = VBoxContainer.new()
	copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	copy.alignment = BoxContainer.ALIGNMENT_CENTER
	identity.add_child(copy)
	copy.add_child(_label(active_team if active_team != "" else "FRANCHISE", 23, TEXT))

	var conference = _s(standing.get("conference"), "league").to_upper()
	var record = _s(standing.get("record"), "0-0")
	if completed <= 0 or record == "0-0":
		copy.add_child(_label("%s • %s" % [conference, record], 12, MUTED))
		copy.add_child(_label("SEEDING OPENS AFTER RESULTS", 10, GOLD))
	else:
		copy.add_child(_label("#%d %s • %s" % [
			_i(standing.get("rank")),
			conference,
			record
		], 12, GOOD))

	var note = _label(
		"Opening-week position is intentionally unranked." if completed <= 0 else "Current position comes directly from the live conference table.",
		10,
		MUTED
	)
	note.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	body.add_child(note)
	return card


func _build_next_test_card(payload: Dictionary) -> Control:
	var card = _card(PANEL, Color(ACCENT, 0.40), 16)
	card.custom_minimum_size = Vector2(0, 205)
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var body = _body(card, 14)
	body.add_child(_label("NEXT LEAGUE TEST", 10, ACCENT))

	var schedule = _dict(payload.get("schedule"))
	var next_game = _next_active_game(_array(schedule.get("upcoming_games")))
	if next_game.is_empty():
		body.add_child(_empty("No upcoming game involving your franchise is exposed yet."))
		return card

	var away = _s(next_game.get("away_team"), "---").to_upper()
	var home = _s(next_game.get("home_team"), "---").to_upper()

	var matchup = HBoxContainer.new()
	matchup.add_theme_constant_override("separation", 8)
	body.add_child(matchup)

	var away_logo = TeamLogoV3.new()
	away_logo.custom_minimum_size = Vector2(64, 58)
	away_logo.configure(away)
	matchup.add_child(away_logo)

	var center = VBoxContainer.new()
	center.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	center.alignment = BoxContainer.ALIGNMENT_CENTER
	matchup.add_child(center)
	var matchup_title = _label("%s  AT  %s" % [away, home], 16, TEXT)
	matchup_title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	center.add_child(matchup_title)
	var day = _i(next_game.get("day_index"))
	var day_label = _label("DAY %d" % day, 10, MUTED)
	day_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	center.add_child(day_label)

	var home_logo = TeamLogoV3.new()
	home_logo.custom_minimum_size = Vector2(64, 58)
	home_logo.configure(home)
	matchup.add_child(home_logo)

	var venue_text = "HOME" if home == active_team else "ROAD"
	body.add_child(_label("%s • %s" % [
		"YOUR MATCHUP",
		venue_text
	], 10, TeamBrandingV3.hover_color(primary)))
	return card


func _build_pressure_card(payload: Dictionary, completed: int) -> Control:
	var card = _card(PANEL, Color(GOLD, 0.38), 16)
	card.custom_minimum_size = Vector2(0, 205)
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var body = _body(card, 14)

	if completed <= 0:
		body.add_child(_label("OPENING SLATE", 10, GOLD))
		var schedule = _dict(payload.get("schedule"))
		var upcoming = _array(schedule.get("upcoming_games"))
		if upcoming.is_empty():
			body.add_child(_empty("Opening-week schedule is not available yet."))
			return card
		for raw in upcoming.slice(0, 3):
			body.add_child(_compact_game(_dict(raw)))
		return card

	body.add_child(_label("AROUND YOU", 10, GOLD))
	var standing = _dict(payload.get("active_team_standing"))
	var conference = _s(standing.get("conference"), "").to_lower()
	var standings = _dict(payload.get("standings"))
	var rows = _array(standings.get("east" if conference.begins_with("e") else "west"))
	var active_index = -1
	for index in range(rows.size()):
		var row = _dict(rows[index])
		if _s(row.get("team"), "").to_upper() == active_team:
			active_index = index
			break

	if active_index < 0:
		body.add_child(_empty("Conference neighbors are unavailable for this snapshot."))
		return card

	var start = max(active_index - 1, 0)
	var finish = min(active_index + 2, rows.size())
	for index in range(start, finish):
		body.add_child(_standing_row(_dict(rows[index])))
	return card


func _compact_game(game: Dictionary) -> Control:
	var row = HBoxContainer.new()
	row.add_theme_constant_override("separation", 7)

	var away = _s(game.get("away_team"), "---").to_upper()
	var home = _s(game.get("home_team"), "---").to_upper()

	var away_logo = TeamLogoV3.new()
	away_logo.custom_minimum_size = Vector2(28, 25)
	away_logo.configure(away)
	row.add_child(away_logo)

	var text = _label("%s at %s" % [away, home], 11, TEXT)
	text.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row.add_child(text)

	var day = _label("DAY %d" % _i(game.get("day_index")), 9, MUTED)
	day.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	row.add_child(day)

	var home_logo = TeamLogoV3.new()
	home_logo.custom_minimum_size = Vector2(28, 25)
	home_logo.configure(home)
	row.add_child(home_logo)
	return row


func _standing_row(row_data: Dictionary) -> Control:
	var row = HBoxContainer.new()
	row.add_theme_constant_override("separation", 8)

	var team = _s(row_data.get("team"), "---").to_upper()
	var is_active = team == active_team

	var logo = TeamLogoV3.new()
	logo.custom_minimum_size = Vector2(31, 28)
	logo.configure(team)
	row.add_child(logo)

	var name = _label(
		"#%d  %s%s" % [
			_i(row_data.get("rank")),
			team,
			" • YOU" if is_active else ""
		],
		11,
		TeamBrandingV3.hover_color(primary) if is_active else TEXT
	)
	name.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row.add_child(name)

	var record = _label(_s(row_data.get("record"), "0-0"), 11, MUTED)
	record.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	row.add_child(record)
	return row


func _next_active_game(upcoming: Array) -> Dictionary:
	for raw in upcoming:
		var game = _dict(raw)
		var away = _s(game.get("away_team"), "").to_upper()
		var home = _s(game.get("home_team"), "").to_upper()
		if active_team != "" and (away == active_team or home == active_team):
			return game
	return _dict(upcoming[0]) if not upcoming.is_empty() else {}


func _card(fill: Color, border: Color, radius: int) -> PanelContainer:
	var card = PanelContainer.new()
	card.add_theme_stylebox_override("panel", _box(fill, radius, border))
	return card


func _body(card: PanelContainer, padding: int) -> VBoxContainer:
	var margin = MarginContainer.new()
	margin.add_theme_constant_override("margin_left", padding)
	margin.add_theme_constant_override("margin_top", padding)
	margin.add_theme_constant_override("margin_right", padding)
	margin.add_theme_constant_override("margin_bottom", padding)
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


func _label(text_value: String, size: int, color: Color) -> Label:
	var label = Label.new()
	label.text = text_value
	label.add_theme_color_override("font_color", color)
	label.add_theme_font_size_override("font_size", size)
	return label


func _empty(text_value: String) -> Label:
	var label = _label(text_value, 10, MUTED)
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	return label


func _clear_children(node: Node) -> void:
	for child in node.get_children():
		node.remove_child(child)
		child.queue_free()


func _dict(value) -> Dictionary:
	return value if typeof(value) == TYPE_DICTIONARY else {}


func _array(value) -> Array:
	return value if typeof(value) == TYPE_ARRAY else []


func _s(value, fallback: String = "") -> String:
	return str(value) if value != null and str(value) != "" else fallback


func _i(value, fallback: int = 0) -> int:
	if typeof(value) in [TYPE_INT, TYPE_FLOAT]:
		return int(value)
	return fallback
