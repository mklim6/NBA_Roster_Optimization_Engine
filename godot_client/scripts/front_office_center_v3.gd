extends Control

const DesignSystemV3 = preload("res://scripts/design_system_v3.gd")
const TeamBrandingV3 = preload("res://scripts/team_branding_v3.gd")

const FRONT_OFFICE_URL := "http://127.0.0.1:8765/v3/front-office"

const BG := DesignSystemV3.BG
const PANEL := DesignSystemV3.PANEL
const PANEL_ALT := DesignSystemV3.PANEL_ALT
const TEXT := DesignSystemV3.TEXT
const MUTED := DesignSystemV3.MUTED
const GOOD := DesignSystemV3.GOOD
const BAD := DesignSystemV3.BAD
const BORDER := DesignSystemV3.BORDER
const GOLD := DesignSystemV3.GOLD
const ACCENT := DesignSystemV3.ACCENT
const TEAM_PRIMARY := DesignSystemV3.TEAM_PRIMARY
const TEAM_PRIMARY_HOVER := DesignSystemV3.TEAM_PRIMARY_HOVER

var brand_heading: Label
var refresh_button: Button

var request: HTTPRequest
var status_label: Label
var season_value: Label
var position_value: Label
var chemistry_value: Label
var roster_value: Label
var health_text: Label
var morale_text: Label
var development_text: Label
var workload_text: Label
var financial_text: Label
var staff_text: Label
var payload := {}


func _ready() -> void:
	_build_page()
	_build_http()


func apply_team_brand(_team: String, primary: Color, _secondary: Color) -> void:
	if brand_heading != null:
		brand_heading.add_theme_color_override("font_color", TeamBrandingV3.hover_color(primary))
	if refresh_button != null:
		TeamBrandingV3.apply_primary_button(refresh_button, primary)


func refresh() -> void:
	_refresh()


func _build_page() -> void:
	var background := ColorRect.new()
	background.color = BG
	add_child(background)
	background.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)

	var outer := MarginContainer.new()
	_set_margins(outer, 34, 28, 34, 30)
	add_child(outer)
	outer.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)

	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 16)
	outer.add_child(column)

	var header := HBoxContainer.new()
	header.add_theme_constant_override("separation", 14)
	column.add_child(header)

	var titles := VBoxContainer.new()
	titles.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	titles.add_theme_constant_override("separation", 4)
	header.add_child(titles)

	var eyebrow := _label("FRANCHISE OPERATIONS • FRONT OFFICE", 10, TEAM_PRIMARY_HOVER)
	brand_heading = eyebrow
	titles.add_child(eyebrow)
	var title := _label("FRONT OFFICE COMMAND CENTER", 31, TEXT)
	titles.add_child(title)
	var subtitle := _label(
		"Team health, morale, workload, development, financial context, and staff visibility from the isolated V3 franchise.",
		12,
		MUTED
	)
	subtitle.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	titles.add_child(subtitle)

	var refresh := Button.new()
	refresh_button = refresh
	refresh.text = "REFRESH FRONT OFFICE"
	refresh.custom_minimum_size = Vector2(165, 62)
	refresh.pressed.connect(_refresh)
	header.add_child(refresh)

	status_label = _label("LOADING V3 FRONT OFFICE...", 11, GOOD)
	column.add_child(status_label)

	var metrics := GridContainer.new()
	metrics.columns = 4
	metrics.add_theme_constant_override("h_separation", 12)
	metrics.add_theme_constant_override("v_separation", 12)
	column.add_child(metrics)

	season_value = _metric_card(metrics, "SEASON", "LOADING...")
	position_value = _metric_card(metrics, "COMPETITIVE POSITION", "LOADING...")
	chemistry_value = _metric_card(metrics, "CHEMISTRY", "LOADING...")
	roster_value = _metric_card(metrics, "ROSTER / ROTATION", "LOADING...")

	var scroll := ScrollContainer.new()
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	column.add_child(scroll)

	var grid := GridContainer.new()
	grid.columns = 2
	grid.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	grid.add_theme_constant_override("h_separation", 14)
	grid.add_theme_constant_override("v_separation", 14)
	scroll.add_child(grid)

	health_text = _section(grid, "TEAM HEALTH", "Injury availability and return timetable.")
	morale_text = _section(grid, "MORALE + ROLE HEALTH", "Role satisfaction and trade-request pressure.")
	development_text = _section(grid, "DEVELOPMENT CORE", "Highest future-outlook players and development direction.")
	workload_text = _section(grid, "ROTATION + WORKLOAD", "Minutes, fatigue, durability, and health-risk context.")
	financial_text = _section(grid, "FINANCIAL / ROSTER HEALTH", "Production payroll and cap context from the active franchise.")
	staff_text = _section(grid, "STAFF ROOM", "Production staff/scouting authority visibility. No invented staff writes.")


func _build_http() -> void:
	request = HTTPRequest.new()
	add_child(request)
	request.request_completed.connect(_on_request_completed)


func _refresh() -> void:
	if request == null:
		return
	status_label.text = "REFRESHING FRONT OFFICE..."
	status_label.add_theme_color_override("font_color", MUTED)
	var error := request.request(FRONT_OFFICE_URL)
	if error != OK:
		status_label.text = "FRONT OFFICE REQUEST COULD NOT START"
		status_label.add_theme_color_override("font_color", BAD)


func _on_request_completed(
	_result: int,
	response_code: int,
	_headers: PackedStringArray,
	body: PackedByteArray
) -> void:
	var parsed = JSON.parse_string(body.get_string_from_utf8())
	if response_code != 200 or typeof(parsed) != TYPE_DICTIONARY:
		status_label.text = "FRONT OFFICE DATA UNAVAILABLE"
		status_label.add_theme_color_override("font_color", BAD)
		return

	payload = parsed
	if _text(payload.get("error"), "") != "":
		status_label.text = "FRONT OFFICE DATA ERROR • %s" % _text(payload.get("error"), "unknown")
		status_label.add_theme_color_override("font_color", BAD)
		return

	_render_payload()


func _render_payload() -> void:
	var season := _dict(payload.get("season"))
	var competitive := _dict(payload.get("competitive"))
	var chemistry := _dict(payload.get("chemistry"))
	var team := _dict(payload.get("team"))
	var rotation := _dict(payload.get("rotation"))
	var health := _dict(payload.get("team_health"))
	var morale := _dict(payload.get("morale"))
	var development := _dict(payload.get("development"))
	var financial := _dict(payload.get("financial"))
	var staff := _dict(payload.get("staff"))

	var season_label := _text(season.get("label"), "UNKNOWN")
	var phase := _text(season.get("phase"), "UNKNOWN").replace("_", " ").to_upper()
	season_value.text = "%s • %s" % [season_label, phase]

	var rank := _int_value(competitive.get("conference_rank"), 0)
	var conference := _text(competitive.get("conference"), "")
	var record := _text(competitive.get("record"), "")
	if rank > 0 and conference != "":
		position_value.text = "#%d %s • %s" % [rank, conference.to_upper(), record]
	else:
		position_value.text = record if record != "" else "UNAVAILABLE"

	var chemistry_score := _float_value(chemistry.get("score"), -1.0)
	var morale_avg := _float_value(chemistry.get("morale_average"), -1.0)
	if chemistry_score >= 0.0:
		chemistry_value.text = "%.1f" % chemistry_score
		if morale_avg >= 0.0:
			chemistry_value.text += " • MORALE %.1f" % morale_avg
	else:
		chemistry_value.text = "UNAVAILABLE"

	roster_value.text = "%s PLAYERS • %s ROTATION" % [
		_count_text(team.get("roster_size")), _count_text(rotation.get("rotation_players"))]

	health_text.text = _render_health(health)
	morale_text.text = _render_morale(morale, chemistry)
	development_text.text = _render_development(development)
	workload_text.text = _render_workload(health, rotation)
	financial_text.text = _render_financial(financial, team)
	staff_text.text = _render_staff(staff)

	var team_abbr := _text(team.get("abbreviation"), "")
	status_label.text = "LIVE V3 CHECKPOINT • READ ONLY • V2 PROTECTED"
	if team_abbr != "":
		status_label.text += " • %s" % team_abbr
	status_label.add_theme_color_override("font_color", GOOD)


func _render_health(health: Dictionary) -> String:
	var lines: Array[String] = []
	lines.append("Injured / limited: %s" % _count_text(health.get("injured_count")))
	if typeof(health.get("injuries")) != TYPE_ARRAY:
		lines.append("Injury availability has not been evaluated for this snapshot.")
		return "\n".join(lines)
	var injuries := _array(health.get("injuries"))
	if injuries.is_empty():
		lines.append("No active injuries in the current roster snapshot.")
	else:
		for raw in injuries.slice(0, 7):
			var row := _dict(raw)
			var name := _text(row.get("name"), "Unknown")
			var status := _text(row.get("status"), "Unavailable")
			var games := _int_value(row.get("games_remaining"), 0)
			var injury_type := _text(row.get("injury_type"), "")
			var detail := "%s • %s" % [name, status]
			if injury_type != "":
				detail += " • %s" % injury_type
			if games > 0:
				detail += " • %d games" % games
			lines.append(detail)
	return "\n".join(lines)


func _render_morale(morale: Dictionary, chemistry: Dictionary) -> String:
	var roster := _array(morale.get("full_roster"))
	if not roster.is_empty():
		var evaluated := false
		for raw in roster:
			var row := _dict(raw)
			if row.get("score") != null or row.get("trade_request_risk") != null or _text(row.get("status"), "") != "":
				evaluated = true
		if not evaluated:
			return "Morale and trade-request risk have not been evaluated for this snapshot."
	var lines: Array[String] = []
	var alignment := _float_value(chemistry.get("role_alignment"), -1.0)
	var frustrated := _count_text(chemistry.get("frustrated_players"))
	var pressure := _count_text(chemistry.get("trade_pressure_players"))
	if alignment >= 0.0:
		lines.append("Role alignment: %.1f" % alignment)
	lines.append("Frustrated: %s • Trade pressure: %s" % [frustrated, pressure])

	if typeof(morale.get("attention")) != TYPE_ARRAY:
		lines.append("Morale alerts have not been evaluated for this snapshot.")
		return "\n".join(lines)
	var attention := _array(morale.get("attention"))
	if attention.is_empty():
		lines.append("No major morale alerts in the current snapshot.")
	else:
		lines.append("")
		for raw in attention.slice(0, 7):
			var row := _dict(raw)
			var name := _text(row.get("name"), "Unknown")
			var status := _text(row.get("status"), "")
			var risk := _float_value(row.get("trade_request_risk"), -1.0)
			var line := "%s • %s" % [name, status if status != "" else "WATCH"]
			if risk >= 0.0:
				line += " • trade risk %.0f%%" % risk
			lines.append(line)
	return "\n".join(lines)


func _render_development(development: Dictionary) -> String:
	var rows := _array(development.get("core"))
	if rows.is_empty():
		return "No development-core rows available."
	var lines: Array[String] = []
	for raw in rows.slice(0, 8):
		var row := _dict(raw)
		var name := _text(row.get("name"), "Unknown")
		var age := _float_value(row.get("age"), -1.0)
		var overall := _float_value(row.get("overall"), -1.0)
		var potential := _float_value(row.get("potential"), -1.0)
		var future := _float_value(row.get("future_outlook"), -1.0)
		var direction := _text(row.get("direction"), "Stable")
		var line := name
		if age >= 0.0:
			line += " • age %.0f" % age
		if overall >= 0.0:
			line += " • OVR %.0f" % overall
		if potential >= 0.0:
			line += " • POT %.0f" % potential
		if future >= 0.0:
			line += " • FUT %.0f" % future
		line += " • %s" % direction
		lines.append(line)
	return "\n".join(lines)


func _render_workload(health: Dictionary, rotation: Dictionary) -> String:
	var lines: Array[String] = []
	lines.append("Rotation: %s players • %s target minutes" % [
		_count_text(rotation.get("rotation_players")), _count_text(rotation.get("total_target_minutes"))])
	if typeof(health.get("workload_watch")) != TYPE_ARRAY:
		lines.append("Workload watch is unavailable for this snapshot.")
	var rows := _array(health.get("workload_watch"))
	for raw in rows.slice(0, 8):
		var row := _dict(raw)
		var name := _text(row.get("name"), "Unknown")
		var minutes := _float_value(row.get("target_minutes"), 0.0)
		var fatigue := _float_value(row.get("fatigue"), -1.0)
		var durability := _float_value(row.get("durability"), -1.0)
		var line := "%s • %.0f min" % [name, minutes]
		if fatigue >= 0.0:
			line += " • fatigue %.1f" % fatigue
		if durability >= 0.0:
			line += " • durability %.1f" % durability
		var risk := _text(row.get("risk_tier"), "")
		if risk != "":
			line += " • %s" % risk
		lines.append(line)
	return "\n".join(lines)


func _render_financial(financial: Dictionary, team: Dictionary) -> String:
	var lines: Array[String] = []
	lines.append("Roster size: %s • Active: %s • Inactive: %s" % [
		_count_text(team.get("roster_size")),
		_count_text(team.get("active_players")),
		_count_text(team.get("inactive_players"))
	])

	var preferred_keys := [
		["payroll", "Payroll"],
		["team_salary", "Team salary"],
		["salary_cap", "Salary cap"],
		["cap_space", "Cap space"],
		["tax_line", "Tax line"],
		["first_apron", "First apron"],
		["second_apron", "Second apron"]
	]
	var emitted := 0
	for pair in preferred_keys:
		var key: String = pair[0]
		if not financial.has(key):
			continue
		var value = financial.get(key)
		if value == null:
			continue
		lines.append("%s: %s" % [pair[1], _money_or_text(value)])
		emitted += 1

	if emitted == 0:
		for key in financial.keys():
			if emitted >= 7:
				break
			var value = financial.get(key)
			if typeof(value) in [TYPE_INT, TYPE_FLOAT, TYPE_STRING, TYPE_BOOL]:
				lines.append("%s: %s" % [_text(key, "").replace("_", " ").capitalize(), _money_or_text(value)])
				emitted += 1
	if emitted == 0:
		lines.append("No standalone financial snapshot is exposed for this checkpoint.")
	return "\n".join(lines)


func _render_staff(staff: Dictionary) -> String:
	var lines: Array[String] = []
	var lead = staff.get("lead_scout")
	if lead != null and _text(lead, "") != "":
		lines.append("Lead scout: %s" % _text(lead, ""))
	lines.append(_text(staff.get("status"), "Staff authority status unavailable."))
	lines.append("")
	lines.append("Staff writes: DISABLED")
	lines.append("A real production staff-hiring authority will be wired before this page is allowed to mutate the franchise.")
	return "\n".join(lines)


func _count_text(value: Variant) -> String:
	if typeof(value) != TYPE_INT and typeof(value) != TYPE_FLOAT:
		return "N/A"
	return "%.0f" % float(value)


func _metric_card(parent: GridContainer, title: String, value: String) -> Label:
	var card := PanelContainer.new()
	card.custom_minimum_size = Vector2(0, 92)
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	card.add_theme_stylebox_override("panel", _box(PANEL_ALT, 14, BORDER))
	parent.add_child(card)
	var margin := MarginContainer.new()
	_set_margins(margin, 16, 12, 16, 12)
	card.add_child(margin)
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 6)
	margin.add_child(column)
	column.add_child(_label(title, 10, MUTED))
	var label := _label(value, 19, TEXT)
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	column.add_child(label)
	return label


func _section(parent: GridContainer, title: String, subtitle: String) -> Label:
	var card := PanelContainer.new()
	card.custom_minimum_size = Vector2(0, 285)
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	card.add_theme_stylebox_override("panel", _box(PANEL, 14, BORDER))
	parent.add_child(card)
	var margin := MarginContainer.new()
	_set_margins(margin, 18, 16, 18, 18)
	card.add_child(margin)
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 8)
	margin.add_child(column)
	column.add_child(_label(title, 13, GOLD))
	var helper := _label(subtitle, 11, MUTED)
	helper.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	column.add_child(helper)
	var text := _label("Loading...", 12, TEXT)
	text.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	column.add_child(text)
	return text


func _label(text_value: String, size: int, color: Color) -> Label:
	var label := Label.new()
	label.text = text_value
	label.add_theme_font_size_override("font_size", size)
	label.add_theme_color_override("font_color", color)
	return label


func _box(color: Color, radius: int, border: Color) -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = color
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


func _text(value, fallback: String) -> String:
	if value == null:
		return fallback
	var result := str(value).strip_edges()
	return fallback if result == "" else result


func _int_value(value, fallback: int) -> int:
	if value == null:
		return fallback
	if typeof(value) == TYPE_INT:
		return int(value)
	if typeof(value) == TYPE_FLOAT:
		return int(value)
	var raw := str(value).strip_edges()
	return fallback if raw == "" or not raw.is_valid_int() else raw.to_int()


func _float_value(value, fallback: float) -> float:
	if value == null:
		return fallback
	if typeof(value) == TYPE_INT or typeof(value) == TYPE_FLOAT:
		return float(value)
	var raw := str(value).strip_edges()
	return fallback if raw == "" or not raw.is_valid_float() else raw.to_float()


func _money_or_text(value) -> String:
	if typeof(value) == TYPE_INT or typeof(value) == TYPE_FLOAT:
		var number := float(value)
		if abs(number) >= 1000000.0:
			return "$%.1fM" % (number / 1000000.0)
		if abs(number) >= 1000.0:
			return "$%.1fK" % (number / 1000.0)
		return "%.1f" % number
	return _text(value, "—")
