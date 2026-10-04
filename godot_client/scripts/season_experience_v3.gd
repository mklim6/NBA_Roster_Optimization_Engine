extends VBoxContainer

const DesignSystemV3 = preload("res://scripts/design_system_v3.gd")
const TeamBrandingV3 = preload("res://scripts/team_branding_v3.gd")
const TeamLogoV3 = preload("res://scripts/team_logo_v3.gd")

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
	name = "SeasonExperienceShowcase"
	size_flags_horizontal = Control.SIZE_EXPAND_FILL
	add_theme_constant_override("separation", 12)


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

	_build_season_hero(payload)
	_build_timeline(payload)
	_build_boundary_context(payload)


func _build_season_hero(payload: Dictionary) -> void:
	var season := _dict(payload.get("season"))
	var schedule := _dict(payload.get("schedule"))
	var postseason := _dict(payload.get("postseason"))

	var card := _card(Color(primary, 0.11), Color(TeamBrandingV3.hover_color(primary), 0.62), 18)
	card.name = "SeasonBroadcastHero"
	card.custom_minimum_size = Vector2(0, 172)
	add_child(card)

	var body := _body(card, 18)
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 16)
	body.add_child(row)

	var logo := TeamLogoV3.new()
	logo.custom_minimum_size = Vector2(132, 114)
	logo.configure(active_team)
	row.add_child(logo)

	var center := VBoxContainer.new()
	center.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	center.alignment = BoxContainer.ALIGNMENT_CENTER
	center.add_theme_constant_override("separation", 4)
	row.add_child(center)
	center.add_child(_label("FRANCHISE SEASON CENTER", 10, TeamBrandingV3.hover_color(primary)))
	center.add_child(_label(_s(season.get("label"), "SEASON"), 32, TEXT))
	center.add_child(_label(
		_s(season.get("phase"), "unknown").replace("_", " ").to_upper(),
		12,
		MUTED
	))

	var total := _i(schedule.get("total"))
	var completed := _i(schedule.get("completed"))
	var progress := ProgressBar.new()
	progress.custom_minimum_size = Vector2(0, 12)
	progress.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	progress.show_percentage = false
	progress.add_theme_stylebox_override("background", _box(PANEL_ALT, BORDER, 5))
	progress.add_theme_stylebox_override("fill", _box(primary, TeamBrandingV3.hover_color(primary), 5))
	progress.value = clampf(100.0 * completed / total, 0.0, 100.0) if total > 0 else 0.0
	center.add_child(progress)

	var progress_text := "SCHEDULE DATA UNAVAILABLE"
	if total > 0:
		progress_text = "%d / %d GAMES • %d REMAINING" % [completed, total, maxi(0, total - completed)]
	center.add_child(_label(progress_text, 10, MUTED))

	var gate := _card(PANEL_ALT, Color(GOLD, 0.46), 14)
	gate.custom_minimum_size = Vector2(330, 0)
	var gate_body := _body(gate, 14)
	gate_body.add_child(_label("NEXT CERTIFIED GATE", 9, GOLD))
	var next_label := _s(payload.get("next_action_label"), "NO ACTION AVAILABLE")
	var next_title := _label(next_label, 18, TEXT)
	next_title.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	gate_body.add_child(next_title)
	gate_body.add_child(_label("CURRENT STAGE • %s" % _s(payload.get("stage"), "unknown").replace("_", " ").to_upper(), 10, MUTED))

	var champion := _s(postseason.get("champion"), "")
	if champion != "":
		var champ_line := HBoxContainer.new()
		champ_line.add_theme_constant_override("separation", 8)
		gate_body.add_child(champ_line)
		var champion_logo := TeamLogoV3.new()
		champion_logo.custom_minimum_size = Vector2(42, 38)
		champion_logo.configure(champion)
		champ_line.add_child(champion_logo)
		var champion_label := _label("CHAMPION • %s" % champion, 11, GOLD)
		champion_label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
		champ_line.add_child(champion_label)
	row.add_child(gate)


func _build_timeline(payload: Dictionary) -> void:
	var section := VBoxContainer.new()
	section.add_theme_constant_override("separation", 8)
	add_child(section)

	var header := HBoxContainer.new()
	header.add_child(_label("SEASON MILESTONES", 17, TEXT))
	var spacer := Control.new()
	spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	header.add_child(spacer)
	header.add_child(_label("CERTIFIED LIFECYCLE", 9, ACCENT))
	section.add_child(header)

	var grid := GridContainer.new()
	grid.columns = 4
	grid.add_theme_constant_override("h_separation", 8)
	grid.add_theme_constant_override("v_separation", 8)
	section.add_child(grid)

	var timeline := _array(payload.get("timeline"))
	if timeline.is_empty():
		var empty := _card(PANEL, Color(BORDER, 0.70), 12)
		empty.custom_minimum_size = Vector2(0, 80)
		empty.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		var empty_body := _body(empty, 12)
		empty_body.add_child(_label("Lifecycle timeline unavailable.", 11, MUTED))
		grid.add_child(empty)
		return

	for raw in timeline:
		grid.add_child(_milestone_card(_dict(raw)))


func _build_boundary_context(payload: Dictionary) -> void:
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 10)
	add_child(row)

	var postseason := _dict(payload.get("postseason"))
	var postseason_card := _context_card("POSTSEASON", GOLD)
	var postseason_body := postseason_card.get_meta("body") as VBoxContainer
	if bool(postseason.get("initialized", false)):
		var champion := _s(postseason.get("champion"), "")
		if champion != "":
			postseason_body.add_child(_label("CHAMPION • %s" % champion, 15, TEXT))
			var runner_up := _s(postseason.get("runner_up"), "")
			if runner_up != "":
				postseason_body.add_child(_label("Runner-up • %s" % runner_up, 10, MUTED))
		else:
			postseason_body.add_child(_label(
				_s(postseason.get("stage"), "active").replace("_", " ").to_upper(),
				15,
				TEXT
			))
			postseason_body.add_child(_label("Bracket initialized and awaiting certified progression.", 10, MUTED))
	else:
		postseason_body.add_child(_label("NOT INITIALIZED", 15, MUTED))
		postseason_body.add_child(_label("Postseason state will appear at the certified boundary.", 10, MUTED))
	row.add_child(postseason_card)

	var draft := _dict(payload.get("draft"))
	var draft_card := _context_card("DRAFT PIPELINE", ACCENT)
	var draft_body := draft_card.get_meta("body") as VBoxContainer
	if bool(draft.get("initialized", false)):
		draft_body.add_child(_label(_s(draft.get("phase"), "active").replace("_", " ").to_upper(), 15, TEXT))
		draft_body.add_child(_label("%d PICKS TRACKED" % _i(draft.get("pick_count")), 10, MUTED))
	else:
		draft_body.add_child(_label("WAITING FOR DRAFT GATE", 15, MUTED))
		draft_body.add_child(_label("Lottery and class activation remain lifecycle-controlled.", 10, MUTED))
	row.add_child(draft_card)

	var fa := _dict(payload.get("cpu_free_agency"))
	var fa_card := _context_card("CPU ROSTER MARKET", GOOD)
	var fa_body := fa_card.get_meta("body") as VBoxContainer
	var deficit_teams := _i(fa.get("deficit_team_count"))
	var total_deficit := _i(fa.get("total_deficit"))
	fa_body.add_child(_label("%d TEAMS NEED SPOTS" % deficit_teams, 15, TEXT if deficit_teams > 0 else GOOD))
	fa_body.add_child(_label("%d TOTAL ROSTER SPOTS" % total_deficit, 10, MUTED))
	row.add_child(fa_card)


func _milestone_card(item: Dictionary) -> Control:
	var status := _s(item.get("status"), "locked").to_lower()
	var tone := MUTED
	var status_text := "LOCKED"
	if status == "complete":
		tone = GOOD
		status_text = "COMPLETE"
	elif status == "current":
		tone = GOLD
		status_text = "CURRENT"

	var card := _card(PANEL_ALT, Color(tone, 0.38), 12)
	card.custom_minimum_size = Vector2(0, 88)
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var body := _body(card, 10)

	var bar := ColorRect.new()
	bar.custom_minimum_size = Vector2(0, 3)
	bar.color = tone
	bar.mouse_filter = Control.MOUSE_FILTER_IGNORE
	body.add_child(bar)
	body.add_child(_label(status_text, 8, tone))

	var title := _label(_s(item.get("label"), _s(item.get("key"), "Milestone")), 11, TEXT if status != "locked" else MUTED)
	title.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	body.add_child(title)
	return card


func _context_card(title: String, tone: Color) -> PanelContainer:
	var card := _card(PANEL, Color(tone, 0.38), 14)
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	card.custom_minimum_size = Vector2(0, 120)
	var body := _body(card, 12)
	body.add_child(_label(title, 9, tone))
	card.set_meta("body", body)
	return card


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


func _clear_children(node: Node) -> void:
	for child in node.get_children():
		node.remove_child(child)
		child.queue_free()
