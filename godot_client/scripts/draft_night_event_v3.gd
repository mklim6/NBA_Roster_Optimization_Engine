extends VBoxContainer

# Batch 37 Draft Night event presentation.
# Read-only visual layer driven by the existing Scouting & Draft payload.

const DesignSystemV3 = preload("res://scripts/design_system_v3.gd")
const TeamBrandingV3 = preload("res://scripts/team_branding_v3.gd")
const TeamLogoV3 = preload("res://scripts/team_logo_v3.gd")

const PANEL = DesignSystemV3.PANEL
const PANEL_ALT = DesignSystemV3.PANEL_ALT
const TEXT = DesignSystemV3.TEXT
const MUTED = DesignSystemV3.MUTED
const ACCENT = DesignSystemV3.ACCENT
const GOOD = DesignSystemV3.GOOD
const BAD = DesignSystemV3.BAD
const GOLD = DesignSystemV3.GOLD
const BORDER = DesignSystemV3.BORDER

var active_team = ""
var primary = DesignSystemV3.TEAM_PRIMARY


func _ready() -> void:
	name = "DraftNightEvent"
	size_flags_horizontal = Control.SIZE_EXPAND_FILL
	add_theme_constant_override("separation", 10)


func configure(
	payload: Dictionary,
	prospects: Array,
	selected_prospect: Dictionary,
	team_abbreviation: String,
	brand_color: Color
) -> void:
	active_team = team_abbreviation.strip_edges().to_upper()
	primary = brand_color
	_clear_children(self)

	var draft = _dict(payload.get("draft"))
	var summary = _dict(payload.get("summary"))
	var phase = _s(draft.get("phase"), "unavailable").to_lower()
	var current_pick = _dict(draft.get("current_pick"))

	if phase == "draft_in_progress" and not current_pick.is_empty():
		_build_live_draft(draft, summary, prospects, selected_prospect, current_pick)
	elif phase.find("draft") >= 0 and current_pick.is_empty() and phase != "season_scouting":
		_build_complete_state(draft, prospects, selected_prospect)
	else:
		_build_scouting_runway(draft, summary, prospects, selected_prospect)


func _build_scouting_runway(
	draft: Dictionary,
	summary: Dictionary,
	prospects: Array,
	selected: Dictionary
) -> void:
	var hero = _hero_card(Color(primary, 0.10), Color(primary, 0.56))
	hero.name = "DraftRunwayHero"
	var body = _body(hero, 18)

	var top = HBoxContainer.new()
	top.add_theme_constant_override("separation", 14)
	body.add_child(top)

	var logo = TeamLogoV3.new()
	logo.name = "DraftRunwayTeamLogo"
	logo.custom_minimum_size = Vector2(104, 92)
	logo.configure(active_team)
	top.add_child(logo)

	var copy = VBoxContainer.new()
	copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	copy.alignment = BoxContainer.ALIGNMENT_CENTER
	copy.add_theme_constant_override("separation", 3)
	top.add_child(copy)
	copy.add_child(_label("FRANCHISE DRAFT ROOM • TALENT PIPELINE", 10, TeamBrandingV3.hover_color(primary)))
	copy.add_child(_label("ROAD TO DRAFT NIGHT", 30, TEXT))
	copy.add_child(_label(
		"Build your board now. The same scouting estimates will follow you into the live draft room.",
		10,
		MUTED
	))

	var year_panel = _card(Color(GOLD, 0.08), Color(GOLD, 0.40), 12)
	year_panel.custom_minimum_size = Vector2(190, 82)
	var year_body = _body(year_panel, 10)
	year_body.add_child(_label("UPCOMING DRAFT", 8, GOLD))
	year_body.add_child(_label(str(_i(draft.get("draft_year"), 0)), 21, TEXT))
	top.add_child(year_panel)

	var metrics = GridContainer.new()
	metrics.columns = 4
	metrics.add_theme_constant_override("h_separation", 10)
	body.add_child(metrics)
	var weeks_done = _i(summary.get("weeks_completed"), 0)
	var weeks_left = _i(summary.get("weeks_remaining"), 0)
	_metric(metrics, "SCOUTING WEEK", "%d / %d" % [weeks_done, weeks_done + weeks_left], ACCENT)
	_metric(metrics, "BOARD", "%d PROSPECTS" % prospects.size(), GOOD)
	_metric(metrics, "AVG CONFIDENCE", _confidence(_f(summary.get("average_confidence"), 0.0)), GOLD)
	_metric(metrics, "PHASE", "SEASON SCOUTING", TeamBrandingV3.hover_color(primary))

	add_child(hero)
	_build_selected_and_best_available(selected, prospects, "SCOUTING SPOTLIGHT")


func _build_live_draft(
	draft: Dictionary,
	summary: Dictionary,
	prospects: Array,
	selected: Dictionary,
	current_pick: Dictionary
) -> void:
	var owner = _s(current_pick.get("owner_team"), "---").to_upper()
	var user_pick = owner == active_team and active_team != ""
	var tone = primary if user_pick else ACCENT

	var hero = _hero_card(Color(tone, 0.10), Color(tone, 0.62))
	hero.name = "DraftOnClockHero"
	var body = _body(hero, 18)

	var eyebrow = _label(
		"YOUR FRANCHISE IS ON THE CLOCK" if user_pick else "LIVE DRAFT • CPU PICK",
		10,
		TeamBrandingV3.hover_color(tone)
	)
	body.add_child(eyebrow)

	var row = HBoxContainer.new()
	row.add_theme_constant_override("separation", 16)
	body.add_child(row)

	var owner_panel = VBoxContainer.new()
	owner_panel.custom_minimum_size = Vector2(180, 0)
	owner_panel.alignment = BoxContainer.ALIGNMENT_CENTER
	row.add_child(owner_panel)

	var owner_logo = TeamLogoV3.new()
	owner_logo.name = "DraftOnClockOwnerLogo"
	owner_logo.custom_minimum_size = Vector2(120, 106)
	owner_logo.configure(owner)
	owner_panel.add_child(owner_logo)

	var owner_label = _label(owner, 23, TEXT)
	owner_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	owner_panel.add_child(owner_label)

	var clock = VBoxContainer.new()
	clock.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	clock.alignment = BoxContainer.ALIGNMENT_CENTER
	clock.add_theme_constant_override("separation", 2)
	row.add_child(clock)

	var pick_number = _i(current_pick.get("overall_pick"), 0)
	var round_number = _i(current_pick.get("round"), 0)
	var round_pick = _i(current_pick.get("round_pick"), 0)

	var on_clock = _label("ON THE CLOCK", 34, TEXT)
	on_clock.name = "DraftOnClockTitle"
	on_clock.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	clock.add_child(on_clock)

	var pick_line = _label(
		"PICK #%d • ROUND %d, PICK %d" % [pick_number, round_number, round_pick],
		15,
		GOLD
	)
	pick_line.name = "DraftPickNumber"
	pick_line.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	clock.add_child(pick_line)

	var message = _label(
		"Select a prospect below, then use the existing preview-gated Draft Night Desk to confirm the pick."
		if user_pick
		else "The CPU selection remains controlled by the existing preview-gated Draft Night Desk.",
		10,
		MUTED
	)
	message.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	message.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	clock.add_child(message)

	var status_panel = _card(Color(GOLD, 0.07), Color(GOLD, 0.36), 12)
	status_panel.custom_minimum_size = Vector2(210, 102)
	var status_body = _body(status_panel, 10)
	status_body.add_child(_label("DRAFT YEAR", 8, MUTED))
	status_body.add_child(_label(str(_i(draft.get("draft_year"), 0)), 18, TEXT))
	status_body.add_child(_label("BOARD • %d AVAILABLE" % prospects.size(), 9, GOOD))
	row.add_child(status_panel)

	add_child(hero)
	_build_selected_and_best_available(selected, prospects, "PICK SPOTLIGHT")


func _build_complete_state(draft: Dictionary, prospects: Array, selected: Dictionary) -> void:
	var hero = _hero_card(Color(GOOD, 0.08), Color(GOOD, 0.48))
	hero.name = "DraftCompleteHero"
	var body = _body(hero, 18)
	body.add_child(_label("FRANCHISE DRAFT ROOM", 10, GOOD))
	body.add_child(_label("DRAFT COMPLETE", 30, TEXT))
	body.add_child(_label(
		"The live selection window has closed. Review the board and continue into post-Draft roster construction.",
		10,
		MUTED
	))
	add_child(hero)
	_build_selected_and_best_available(selected, prospects, "DRAFT BOARD REVIEW")


func _build_selected_and_best_available(
	selected: Dictionary,
	prospects: Array,
	section_title: String
) -> void:
	var row = HBoxContainer.new()
	row.name = "DraftEventDecisionRow"
	row.add_theme_constant_override("separation", 12)
	add_child(row)

	var selected_card = _card(PANEL, Color(primary, 0.44), 16)
	selected_card.name = "DraftSelectedProspectCard"
	selected_card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	selected_card.custom_minimum_size = Vector2(0, 230)
	var selected_body = _body(selected_card, 14)
	selected_body.add_child(_label(section_title, 10, TeamBrandingV3.hover_color(primary)))

	if selected.is_empty():
		selected_body.add_child(_label("NO PROSPECT SELECTED", 24, TEXT))
		var hint = _label("Select a prospect from the Draft Board to turn this into your live decision card.", 10, MUTED)
		hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		selected_body.add_child(hint)
	else:
		_build_selected_prospect(selected_body, selected)
	row.add_child(selected_card)

	var best_card = _card(PANEL, Color(GOLD, 0.38), 16)
	best_card.name = "DraftBestAvailableCard"
	best_card.custom_minimum_size = Vector2(430, 230)
	var best_body = _body(best_card, 14)
	best_body.add_child(_label("BEST AVAILABLE", 10, GOLD))
	best_body.add_child(_label("TOP OF YOUR CURRENT BOARD", 17, TEXT))

	var top = _sorted_board(prospects)
	if top.is_empty():
		best_body.add_child(_label("Board data unavailable.", 10, MUTED))
	else:
		for index in range(min(3, top.size())):
			best_body.add_child(_best_available_row(_dict(top[index]), index + 1))
	row.add_child(best_card)


func _build_selected_prospect(parent: VBoxContainer, prospect: Dictionary) -> void:
	var header = HBoxContainer.new()
	header.add_theme_constant_override("separation", 12)
	parent.add_child(header)

	var rank = _rank_badge(_i(prospect.get("Rank"), 0))
	header.add_child(rank)

	var identity = VBoxContainer.new()
	identity.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	identity.add_theme_constant_override("separation", 2)
	header.add_child(identity)
	identity.add_child(_label(_s(prospect.get("Prospect"), "Unknown Prospect"), 24, TEXT))
	identity.add_child(_label(
		"%s • %s • %s" % [
			_s(prospect.get("Pos"), "--"),
			_s(prospect.get("School / Club"), "Unknown"),
			_s(prospect.get("Archetype"), "Unclassified"),
		],
		10,
		MUTED
	))

	var position = _card(Color(ACCENT, 0.08), Color(ACCENT, 0.34), 10)
	position.custom_minimum_size = Vector2(72, 58)
	var pos_body = _body(position, 8)
	var pos = _label(_s(prospect.get("Pos"), "--").to_upper(), 17, ACCENT)
	pos.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	pos_body.add_child(pos)
	header.add_child(position)

	var metrics = GridContainer.new()
	metrics.columns = 4
	metrics.add_theme_constant_override("h_separation", 8)
	parent.add_child(metrics)
	_metric(metrics, "SCOUTED OVR", _rating(prospect.get("Scouted OVR")), TEXT)
	_metric(metrics, "SCOUTED POT", _rating(prospect.get("Scouted POT")), GOOD)
	_metric(metrics, "CONFIDENCE", _confidence(_f(prospect.get("Confidence"), 0.0)), GOLD)
	_metric(metrics, "PROJECTED", _s(prospect.get("Projected"), "N/A"), ACCENT)


func _best_available_row(prospect: Dictionary, slot: int) -> Control:
	var row = PanelContainer.new()
	row.add_theme_stylebox_override("panel", _box(PANEL_ALT, 10, Color(BORDER, 0.86)))
	row.custom_minimum_size = Vector2(0, 50)

	var margin = MarginContainer.new()
	_set_margins(margin, 9, 7, 9, 7)
	row.add_child(margin)

	var line = HBoxContainer.new()
	line.add_theme_constant_override("separation", 8)
	margin.add_child(line)

	var rank = _label("#%d" % _i(prospect.get("Rank"), slot), 13, GOLD)
	rank.custom_minimum_size = Vector2(36, 0)
	line.add_child(rank)

	var identity = VBoxContainer.new()
	identity.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	line.add_child(identity)
	identity.add_child(_label(_s(prospect.get("Prospect"), "Unknown"), 11, TEXT))
	identity.add_child(_label(
		"%s • %s" % [_s(prospect.get("Pos"), "--"), _s(prospect.get("School / Club"), "Unknown")],
		8,
		MUTED
	))

	var ovr = _label(_rating(prospect.get("Scouted OVR")), 14, TEXT)
	ovr.custom_minimum_size = Vector2(42, 0)
	ovr.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	line.add_child(ovr)

	var pot = _label(_rating(prospect.get("Scouted POT")), 14, GOOD)
	pot.custom_minimum_size = Vector2(42, 0)
	pot.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	line.add_child(pot)
	return row


func _sorted_board(prospects: Array) -> Array:
	var rows: Array = []
	for raw in prospects:
		if typeof(raw) == TYPE_DICTIONARY:
			rows.append(_dict(raw))
	rows.sort_custom(func(a, b):
		return _i(_dict(a).get("Rank"), 9999) < _i(_dict(b).get("Rank"), 9999)
	)
	return rows


func _rank_badge(rank_value: int) -> Control:
	var panel = _card(Color(GOLD, 0.09), Color(GOLD, 0.46), 12)
	panel.custom_minimum_size = Vector2(72, 72)
	var body = _body(panel, 8)
	var top = _label("RANK", 8, MUTED)
	top.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	body.add_child(top)
	var value = _label("#%d" % rank_value if rank_value > 0 else "—", 21, GOLD)
	value.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	body.add_child(value)
	return panel


func _metric(parent: GridContainer, title: String, value: String, tone: Color) -> void:
	var panel = _card(Color(tone, 0.06), Color(tone, 0.28), 10)
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	panel.custom_minimum_size = Vector2(0, 66)
	var body = _body(panel, 8)
	body.add_child(_label(title, 8, tone))
	body.add_child(_label(value, 14, TEXT))
	parent.add_child(panel)


func _hero_card(fill: Color, border: Color) -> PanelContainer:
	var card = PanelContainer.new()
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	card.add_theme_stylebox_override("panel", _box(fill, 18, border))
	return card


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


func _label(text_value: String, size: int, color: Color) -> Label:
	var label = Label.new()
	label.text = text_value
	label.add_theme_color_override("font_color", color)
	label.add_theme_font_size_override("font_size", size)
	return label


func _set_margins(container: MarginContainer, left: int, top: int, right: int, bottom: int) -> void:
	container.add_theme_constant_override("margin_left", left)
	container.add_theme_constant_override("margin_top", top)
	container.add_theme_constant_override("margin_right", right)
	container.add_theme_constant_override("margin_bottom", bottom)


func _clear_children(node: Node) -> void:
	for child in node.get_children():
		node.remove_child(child)
		child.queue_free()


func _dict(value) -> Dictionary:
	return value if typeof(value) == TYPE_DICTIONARY else {}


func _s(value, fallback: String = "") -> String:
	return str(value) if value != null and str(value).strip_edges() != "" else fallback


func _i(value, fallback: int = 0) -> int:
	if typeof(value) in [TYPE_INT, TYPE_FLOAT]:
		return int(value)
	return fallback


func _f(value, fallback: float = 0.0) -> float:
	if typeof(value) in [TYPE_INT, TYPE_FLOAT]:
		return float(value)
	return fallback


func _rating(value) -> String:
	if typeof(value) in [TYPE_INT, TYPE_FLOAT]:
		return "%.1f" % float(value)
	return "N/A"


func _confidence(value: float) -> String:
	return "%.0f%%" % value
