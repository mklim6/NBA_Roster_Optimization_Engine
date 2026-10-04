extends Control

# Batch 22 franchise presentation macro

const DesignSystemV3 = preload("res://scripts/design_system_v3.gd")
const TeamBrandingV3 = preload("res://scripts/team_branding_v3.gd")
const PageIdentityV3 = preload("res://scripts/page_identity_v3.gd")

const LEAGUE_URL := "http://127.0.0.1:8765/v3/league-intelligence"

const BG := DesignSystemV3.BG
const PANEL := DesignSystemV3.PANEL
const PANEL_ALT := DesignSystemV3.PANEL_ALT
const TEXT := DesignSystemV3.TEXT
const MUTED := DesignSystemV3.MUTED
const ACCENT := DesignSystemV3.ACCENT
const GOOD := DesignSystemV3.GOOD
const GOLD := DesignSystemV3.GOLD
const TEAM_PRIMARY := DesignSystemV3.TEAM_PRIMARY
const BORDER := DesignSystemV3.BORDER

var page_identity: Control
var page_brand_bar: ColorRect

var brand_heading: Label
var standings_tables: Array = []
var standings_team := ""
var standings_highlight := GOOD
var last_standings := {}

var league_request: HTTPRequest
var status_label: Label
var season_label: Label
var progress_label: Label
var active_seed_label: Label
var standings_east: Label
var standings_west: Label
var leaders_label: Label
var playoff_label: Label
var schedule_label: Label
var awards_label: Label
var postseason_label: Label
var history_label: Label
var refresh_button: Button


func apply_team_brand(_team: String, primary: Color, _secondary: Color) -> void:
	if page_identity != null:
		page_identity.configure(_team, primary, _secondary)
	if page_brand_bar != null:
		page_brand_bar.color = primary
	standings_team = _team
	standings_highlight = primary.lerp(Color.WHITE, 0.45)
	if brand_heading != null:
		brand_heading.add_theme_color_override("font_color", standings_highlight)
	if refresh_button != null:
		TeamBrandingV3.apply_primary_button(refresh_button, primary)
	if standings_tables.size() == 2:
		_render_standings_table(standings_tables[0], _array(last_standings.get("east")))
		_render_standings_table(standings_tables[1], _array(last_standings.get("west")))


func _ready() -> void:
	_build_interface()
	_build_http()


func _build_http() -> void:
	league_request = HTTPRequest.new()
	add_child(league_request)
	league_request.request_completed.connect(_on_request_completed)


func _build_interface() -> void:
	var background := ColorRect.new()
	background.color = BG
	background.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(background)
	background.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)

	var outer := MarginContainer.new()
	_set_margins(outer, 34, 28, 34, 30)
	add_child(outer)
	outer.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)

	var root := VBoxContainer.new()
	root.add_theme_constant_override("separation", 16)
	outer.add_child(root)

	var header := HBoxContainer.new()
	header.add_theme_constant_override("separation", 14)
	root.add_child(header)

	page_brand_bar = ColorRect.new()
	page_brand_bar.custom_minimum_size = Vector2(0, 4)
	page_brand_bar.color = TEAM_PRIMARY
	page_brand_bar.mouse_filter = Control.MOUSE_FILTER_IGNORE
	root.add_child(page_brand_bar)

	var titles := VBoxContainer.new()
	titles.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	titles.add_theme_constant_override("separation", 3)
	header.add_child(titles)

	var eyebrow := _label("FRANCHISE OPERATIONS • LEAGUE", 10, TEAM_PRIMARY)
	brand_heading = eyebrow
	titles.add_child(eyebrow)
	var title := _label("LEAGUE INTELLIGENCE CENTER", 36, TEXT)
	titles.add_child(title)
	var subtitle := _label(
		"Full standings, playoff positioning, statistical leaders, award watch, schedule/results, and postseason history from the isolated V3 franchise.",
		12,
		MUTED
	)
	subtitle.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	titles.add_child(subtitle)

	page_identity = PageIdentityV3.new()
	header.add_child(page_identity)

	refresh_button = Button.new()
	refresh_button.text = "REFRESH LEAGUE"
	refresh_button.custom_minimum_size = Vector2(160, 52)
	refresh_button.pressed.connect(refresh)
	header.add_child(refresh_button)

	status_label = _label("LOADING V3 LEAGUE STATE...", 11, MUTED)
	root.add_child(status_label)

	var metrics := HBoxContainer.new()
	metrics.add_theme_constant_override("separation", 12)
	root.add_child(metrics)
	season_label = _metric(metrics, "SEASON", "LOADING...")
	progress_label = _metric(metrics, "LEAGUE PROGRESS", "LOADING...")
	active_seed_label = _metric(metrics, "YOUR POSITION", "LOADING...")

	var scroll := ScrollContainer.new()
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	root.add_child(scroll)

	var content := VBoxContainer.new()
	content.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	content.add_theme_constant_override("separation", 14)
	scroll.add_child(content)

	var standings_row := HBoxContainer.new()
	standings_row.add_theme_constant_override("separation", 14)
	content.add_child(standings_row)
	standings_east = _section(standings_row, "EASTERN CONFERENCE", "Loading standings...", Vector2(470, 485))
	standings_west = _section(standings_row, "WESTERN CONFERENCE", "Loading standings...", Vector2(470, 485))

	var middle_row := HBoxContainer.new()
	middle_row.add_theme_constant_override("separation", 14)
	content.add_child(middle_row)
	leaders_label = _section(middle_row, "STATISTICAL LEADERS", "Loading leaders...", Vector2(470, 420))
	playoff_label = _section(middle_row, "PLAYOFF PICTURE", "Loading playoff race...", Vector2(470, 420))

	var schedule_row := HBoxContainer.new()
	schedule_row.add_theme_constant_override("separation", 14)
	content.add_child(schedule_row)
	schedule_label = _section(schedule_row, "SCHEDULE + RESULTS", "Loading league calendar...", Vector2(470, 420))
	awards_label = _section(schedule_row, "AWARD WATCH", "Loading award context...", Vector2(470, 420))

	var history_row := HBoxContainer.new()
	history_row.add_theme_constant_override("separation", 14)
	content.add_child(history_row)
	postseason_label = _section(history_row, "POSTSEASON / BRACKET", "Loading postseason context...", Vector2(470, 260))
	history_label = _section(history_row, "LEAGUE HISTORY", "Loading champions...", Vector2(470, 260))


func refresh() -> void:
	if league_request == null:
		return
	if league_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	status_label.text = "REFRESHING LIVE V3 LEAGUE INTELLIGENCE..."
	status_label.add_theme_color_override("font_color", MUTED)
	refresh_button.disabled = true
	var error := league_request.request(LEAGUE_URL)
	if error != OK:
		refresh_button.disabled = false
		status_label.text = "REQUEST FAILED TO START • %s" % str(error)
		status_label.add_theme_color_override("font_color", TEAM_PRIMARY)


func _on_request_completed(_result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	refresh_button.disabled = false
	var parsed = JSON.parse_string(body.get_string_from_utf8())
	if response_code < 200 or response_code >= 300 or typeof(parsed) != TYPE_DICTIONARY:
		status_label.text = "LEAGUE INTELLIGENCE UNAVAILABLE • bridge response %d" % response_code
		status_label.add_theme_color_override("font_color", TEAM_PRIMARY)
		return
	var payload: Dictionary = parsed
	if payload.has("error"):
		status_label.text = "LEAGUE INTELLIGENCE ERROR • %s" % _s(payload.get("detail"), _s(payload.get("error"), "unknown error"))
		status_label.add_theme_color_override("font_color", TEAM_PRIMARY)
		return
	_render(payload)


func _render(payload: Dictionary) -> void:
	var season := _dict(payload.get("season"))
	var schedule := _dict(payload.get("schedule"))
	var standing := _dict(payload.get("active_team_standing"))
	var phase := _s(season.get("phase"), "unknown").replace("_", " ").to_upper()
	season_label.text = "%s • %s" % [_s(season.get("label"), "UNKNOWN"), phase]
	var schedule_known := typeof(schedule.get("completed_games")) in [TYPE_INT, TYPE_FLOAT] and typeof(schedule.get("total_games")) in [TYPE_INT, TYPE_FLOAT] and typeof(schedule.get("remaining_games")) in [TYPE_INT, TYPE_FLOAT]
	var completed := _i(schedule.get("completed_games"))
	var total := _i(schedule.get("total_games"))
	var remaining := _i(schedule.get("remaining_games"))
	progress_label.text = "%d / %d • %d LEFT" % [completed, total, remaining] if schedule_known else "UNAVAILABLE"
	if standing.is_empty():
		active_seed_label.text = "UNAVAILABLE"
	else:
		active_seed_label.text = "#%d %s • %s" % [
			_i(standing.get("rank")),
			_s(standing.get("conference"), "LEAGUE").to_upper(),
			_s(standing.get("record"), "0-0")
		]

	var standings := _dict(payload.get("standings"))
	standings_east.text = _standings_text(_array(standings.get("east")))
	standings_west.text = _standings_text(_array(standings.get("west")))
	last_standings = standings
	standings_team = _s(standing.get("team"), standings_team)
	_render_standings_table(standings_tables[0], _array(standings.get("east")))
	_render_standings_table(standings_tables[1], _array(standings.get("west")))
	leaders_label.text = _leaders_text(_dict(payload.get("leaders")), _i(payload.get("leader_minimum_games")))
	playoff_label.text = _playoff_text(_dict(payload.get("playoff_picture")))
	schedule_label.text = _schedule_text(schedule)
	awards_label.text = _awards_text(_dict(payload.get("award_watch")))
	postseason_label.text = _postseason_text(_dict(payload.get("postseason")))
	history_label.text = _history_text(_array(payload.get("season_history")))

	status_label.text = "LIVE V3 CHECKPOINT • READ ONLY • V2 PROTECTED"
	status_label.add_theme_color_override("font_color", GOOD)


func _render_standings_table(table: GridContainer, rows: Array) -> void:
	for child in table.get_children():
		table.remove_child(child)
		child.queue_free()
	for heading in ["#", "TEAM", "W-L", "DIFF", "STREAK"]:
		table.add_child(_label(heading, 10, MUTED))
	if rows.is_empty():
		table.add_child(_label("—", 12, MUTED))
		table.add_child(_label("Unavailable", 12, MUTED))
		return
	for raw in rows:
		if typeof(raw) != TYPE_DICTIONARY:
			continue
		var row: Dictionary = raw
		var team := _s(row.get("team"), "N/A")
		var is_active := team == standings_team and standings_team != ""
		var diff := _s(row.get("point_diff"), "N/A")
		if typeof(row.get("point_diff")) in [TYPE_INT, TYPE_FLOAT]:
			diff = "%+d" % int(row.get("point_diff"))
		var cells := [_s(row.get("rank"), "N/A"), team + (" • YOU" if is_active else ""), _s(row.get("record"), "N/A"), diff, _s(row.get("streak"), "N/A")]
		for i in range(cells.size()):
			var cell := _label(cells[i], 12, standings_highlight if is_active else TEXT)
			cell.tooltip_text = _s(row.get("team_name"), team) if i == 1 else cells[i]
			if i == 1:
				cell.size_flags_horizontal = Control.SIZE_EXPAND_FILL
			elif i > 1:
				cell.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
			table.add_child(cell)


func _standings_text(rows: Array) -> String:
	if rows.is_empty():
		return "No conference standings are available."
	var lines: Array[String] = []
	lines.append("    TEAM       W-L      DIFF   STRK")
	for raw in rows:
		var row := _dict(raw)
		lines.append("%2d  %-4s  %8s  %+5d   %s" % [
			_i(row.get("rank")),
			_s(row.get("team"), "---"),
			_s(row.get("record"), "0-0"),
			_i(row.get("point_diff")),
			_s(row.get("streak"), "-")
		])
	return "\n".join(lines)


func _leaders_text(leaders: Dictionary, minimum_games: int) -> String:
	var lines: Array[String] = ["Minimum games: %d" % minimum_games]
	var categories := [
		["SCORING", "scoring", "ppg", "PPG"],
		["REBOUNDS", "rebounds", "rpg", "RPG"],
		["ASSISTS", "assists", "apg", "APG"],
		["STEALS", "steals", "spg", "SPG"],
		["BLOCKS", "blocks", "bpg", "BPG"]
	]
	for category in categories:
		lines.append("")
		lines.append(str(category[0]))
		var rows := _array(leaders.get(str(category[1])))
		if rows.is_empty():
			lines.append("No qualifying players yet." if typeof(leaders.get(str(category[1]))) == TYPE_ARRAY else "Leaderboard unavailable.")
		for raw in rows:
			var row := _dict(raw)
			lines.append("%d. %s (%s)  %.1f %s" % [
				_i(row.get("rank")),
				_s(row.get("name"), "Unknown"),
				_s(row.get("team"), ""),
				_f(row.get(str(category[2]))),
				str(category[3])
			])
	return "\n".join(lines)


func _playoff_text(picture: Dictionary) -> String:
	var lines: Array[String] = []
	for conference_key in ["east", "west"]:
		lines.append(str(conference_key).to_upper())
		for raw in _array(picture.get(conference_key)):
			var row := _dict(raw)
			var marker := "P" if _s(row.get("zone")) == "playoff" else "PI"
			lines.append("%2d. %-4s %-7s  %s" % [
				_i(row.get("seed")),
				_s(row.get("team"), "---"),
				_s(row.get("record"), "0-0"),
				marker
			])
		lines.append("")
	lines.append("P = playoff position • PI = play-in position")
	return "\n".join(lines)


func _schedule_text(schedule: Dictionary) -> String:
	var lines: Array[String] = ["RECENT RESULTS"]
	var recent := _array(schedule.get("recent_results"))
	if recent.is_empty():
		lines.append("No completed games yet." if typeof(schedule.get("recent_results")) == TYPE_ARRAY else "Recent results unavailable.")
	for raw in recent.slice(0, 6):
		var row := _dict(raw)
		lines.append("Day %d • %s %d at %s %d" % [
			_i(row.get("day_index")),
			_s(row.get("away_team")),
			_i(row.get("away_score")),
			_s(row.get("home_team")),
			_i(row.get("home_score"))
		])
	lines.append("")
	lines.append("UPCOMING")
	var upcoming := _array(schedule.get("upcoming_games"))
	if upcoming.is_empty():
		lines.append("No regular-season games remain." if typeof(schedule.get("upcoming_games")) == TYPE_ARRAY else "Upcoming schedule unavailable.")
	for raw in upcoming.slice(0, 6):
		var row := _dict(raw)
		lines.append("Day %d • %s at %s" % [
			_i(row.get("day_index")),
			_s(row.get("away_team")),
			_s(row.get("home_team"))
		])
	return "\n".join(lines)


func _awards_text(award_watch: Dictionary) -> String:
	var lines: Array[String] = []
	lines.append(_s(award_watch.get("projection_note"), "Award context unavailable."))
	for pair in [["MVP WATCH", "mvp_watch"], ["DPOY WATCH", "dpoy_watch"]]:
		lines.append("")
		lines.append(str(pair[0]))
		for raw in _array(award_watch.get(str(pair[1]))):
			var row := _dict(raw)
			lines.append("%d. %s (%s) • %.1f PPG • %.1f RPG • %.1f APG" % [
				_i(row.get("rank")),
				_s(row.get("name"), "Unknown"),
				_s(row.get("team"), ""),
				_f(row.get("ppg")),
				_f(row.get("rpg")),
				_f(row.get("apg"))
			])
	return "\n".join(lines)


func _postseason_text(postseason: Dictionary) -> String:
	if not bool(postseason.get("active", false)):
		return "Postseason bracket is not active in the current checkpoint.\nThe bracket will populate here once postseason state exists."
	var lines: Array[String] = []
	lines.append("Stage: %s" % _s(postseason.get("stage"), "unknown").replace("_", " ").to_upper())
	var champion := _s(postseason.get("champion"))
	if champion != "":
		lines.append("Champion: %s" % champion)
	var runner_up := _s(postseason.get("runner_up"))
	if runner_up != "":
		lines.append("Runner-up: %s" % runner_up)
	lines.append("Full postseason state is exposed by the bridge for later bracket graphics.")
	return "\n".join(lines)


func _history_text(history: Array) -> String:
	if history.is_empty():
		return "No completed seasons are archived yet in this franchise."
	var lines: Array[String] = []
	for raw in history:
		var row := _dict(raw)
		var champion := _s(row.get("champion"), "TBD")
		var runner_up := _s(row.get("runner_up"), "")
		var display := "%s • %s champion" % [_s(row.get("season"), "Season"), champion]
		if runner_up != "":
			display += " over %s" % runner_up
		lines.append(display)
	return "\n".join(lines)


func _metric(parent: HBoxContainer, title: String, value_text: String) -> Label:
	var card := PanelContainer.new()
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	card.custom_minimum_size = Vector2(0, 92)
	card.add_theme_stylebox_override("panel", _box(PANEL_ALT, 12, BORDER))
	parent.add_child(card)
	var margin := MarginContainer.new()
	_set_margins(margin, 14, 12, 14, 12)
	card.add_child(margin)
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 5)
	margin.add_child(column)
	column.add_child(_label(title, 10, MUTED))
	var value := _label(value_text, 19, TEXT)
	column.add_child(value)
	return value


func _section(parent: HBoxContainer, title: String, initial: String, minimum: Vector2) -> Label:
	var card := PanelContainer.new()
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	card.custom_minimum_size = minimum
	card.add_theme_stylebox_override("panel", _box(PANEL, 14, BORDER))
	parent.add_child(card)
	var margin := MarginContainer.new()
	_set_margins(margin, 16, 14, 16, 14)
	card.add_child(margin)
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 10)
	margin.add_child(column)
	column.add_child(_label(title, 12, GOLD))
	var body := _label(initial, 12, TEXT)
	body.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	column.add_child(body)
	if title in ["EASTERN CONFERENCE", "WESTERN CONFERENCE"]:
		body.hide()
		var table := GridContainer.new()
		table.columns = 5
		table.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		table.add_theme_constant_override("h_separation", 10)
		table.add_theme_constant_override("v_separation", 8)
		column.add_child(table)
		standings_tables.append(table)
	return body


func _label(text_value: String, size: int, color: Color) -> Label:
	var label := Label.new()
	label.text = text_value
	label.add_theme_font_size_override("font_size", size)
	label.add_theme_color_override("font_color", color)
	return label


func _box(color: Color, radius: int, border_color: Color) -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = color
	style.border_color = border_color
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
	if typeof(value) == TYPE_DICTIONARY:
		return value
	return {}


func _array(value) -> Array:
	if typeof(value) == TYPE_ARRAY:
		return value
	return []


func _s(value, fallback: String = "") -> String:
	if value == null:
		return fallback
	var text := str(value).strip_edges()
	if text == "":
		return fallback
	return text


func _i(value, fallback: int = 0) -> int:
	if value == null:
		return fallback
	return int(value)


func _f(value, fallback: float = 0.0) -> float:
	if value == null:
		return fallback
	return float(value)
