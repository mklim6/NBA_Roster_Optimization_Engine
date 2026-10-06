extends PanelContainer

# 50B-R2E premium Trade Negotiation Room hero.
# Presentation only: consumes the already-selected package and never sends requests.

const DS = preload("res://scripts/design_system_v3.gd")
const Branding = preload("res://scripts/team_branding_v3.gd")
const Logo = preload("res://scripts/team_logo_v3.gd")
const UI = preload("res://scripts/premium_ui_v3.gd")

var active_tone := DS.TEAM_PRIMARY
var partner_tone := DS.ACCENT
var _render_key: Dictionary = {}


func _ready() -> void:
	name = "TradeNegotiationHero"
	custom_minimum_size = Vector2(0, 242)
	size_flags_horizontal = Control.SIZE_EXPAND_FILL
	clip_contents = true
	resized.connect(queue_redraw)
	add_theme_stylebox_override(
		"panel",
		DS.style_box(Color("090e17"), 20, Color(DS.GOLD, 0.32), 1, 0.12)
	)


func configure(
	active_team: String,
	partner_team: String,
	outgoing_players: Array,
	incoming_players: Array,
	outgoing_picks: Array,
	incoming_picks: Array,
	state_text: String
) -> void:
	var next_key := {
		"active_team": active_team,
		"partner_team": partner_team,
		"outgoing_players": outgoing_players,
		"incoming_players": incoming_players,
		"outgoing_picks": outgoing_picks,
		"incoming_picks": incoming_picks,
		"state_text": state_text,
	}
	if next_key == _render_key:
		return
	_render_key = next_key.duplicate(true)

	active_tone = Branding.palette(active_team).get("primary", DS.TEAM_PRIMARY)
	partner_tone = Branding.palette(partner_team).get("primary", DS.ACCENT)

	for child in get_children():
		remove_child(child)
		child.queue_free()

	var margin := MarginContainer.new()
	for side in ["left", "right", "top", "bottom"]:
		margin.add_theme_constant_override("margin_" + side, 20)
	add_child(margin)

	var body := VBoxContainer.new()
	body.add_theme_constant_override("separation", 14)
	margin.add_child(body)

	var top := HBoxContainer.new()
	top.add_theme_constant_override("separation", 10)
	body.add_child(top)

	var title := _label("FRONT OFFICE NEGOTIATION ROOM", 11, DS.GOLD)
	title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	top.add_child(title)
	var state_chip := UI.chip(_state_label(state_text), _state_tone(state_text), 10)
	state_chip.name = "NegotiationStateChip"
	top.add_child(state_chip)

	var stage := HBoxContainer.new()
	stage.name = "TradeNegotiationMatchup"
	stage.add_theme_constant_override("separation", 18)
	body.add_child(stage)

	stage.add_child(
		_team_block(
			"YOU SEND",
			active_team,
			outgoing_players,
			outgoing_picks,
			active_tone,
			"NegotiationActiveTeamLogo"
		)
	)

	var center := VBoxContainer.new()
	center.name = "NegotiationCenter"
	center.custom_minimum_size = Vector2(180, 0)
	center.alignment = BoxContainer.ALIGNMENT_CENTER
	center.add_theme_constant_override("separation", 5)
	stage.add_child(center)

	var exchange := _label("⇄", 42, DS.GOLD)
	exchange.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	center.add_child(exchange)

	var matchup := "%s  /  %s" % [
		active_team if active_team != "" else "YOUR TEAM",
		partner_team if partner_team != "" else "PARTNER",
	]
	var matchup_label := _label(matchup, 13, DS.TEXT)
	matchup_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	center.add_child(matchup_label)

	var out_count := outgoing_players.size() + outgoing_picks.size()
	var in_count := incoming_players.size() + incoming_picks.size()
	var counts := _label("%d OUT  •  %d IN" % [out_count, in_count], 10, DS.MUTED)
	counts.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	center.add_child(counts)

	var desk_chip := UI.chip("CBA + DRAFT RIGHTS + CONTRACTS", DS.ACCENT, 9)
	desk_chip.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	center.add_child(desk_chip)

	stage.add_child(
		_team_block(
			"YOU RECEIVE",
			partner_team,
			incoming_players,
			incoming_picks,
			partner_tone,
			"NegotiationPartnerTeamLogo"
		)
	)

	var footer := HBoxContainer.new()
	footer.add_theme_constant_override("separation", 8)
	body.add_child(footer)
	footer.add_child(UI.chip(_asset_summary(outgoing_players, outgoing_picks), active_tone, 9))
	var spacer := Control.new()
	spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	footer.add_child(spacer)
	footer.add_child(UI.chip(_asset_summary(incoming_players, incoming_picks), partner_tone, 9))

	queue_redraw()


func _team_block(
	heading: String,
	team: String,
	players: Array,
	picks: Array,
	tone: Color,
	logo_name: String
) -> PanelContainer:
	var panel := PanelContainer.new()
	panel.name = "NegotiationActiveSide" if "Active" in logo_name else "NegotiationPartnerSide"
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	panel.size_flags_stretch_ratio = 1.0
	panel.add_theme_stylebox_override(
		"panel",
		DS.style_box(Color(tone, 0.075), 16, Color(tone, 0.48), 1, 0.0)
	)

	var margin := MarginContainer.new()
	for side in ["left", "right", "top", "bottom"]:
		margin.add_theme_constant_override("margin_" + side, 14)
	panel.add_child(margin)

	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 14)
	margin.add_child(row)

	var logo := Logo.new()
	logo.name = logo_name
	logo.custom_minimum_size = Vector2(88, 88)
	row.add_child(logo)
	logo.configure(team)

	var copy := VBoxContainer.new()
	copy.alignment = BoxContainer.ALIGNMENT_CENTER
	copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	copy.add_theme_constant_override("separation", 4)
	row.add_child(copy)

	copy.add_child(_label(heading, 9, tone.lightened(0.22)))
	copy.add_child(_label(team if team != "" else "CHOOSE PARTNER", 30, DS.TEXT))
	copy.add_child(
		_label(
			"%d PLAYER%s  •  %d RIGHT%s" % [
				players.size(),
				"" if players.size() == 1 else "S",
				picks.size(),
				"" if picks.size() == 1 else "S",
			],
			10,
			DS.MUTED
		)
	)
	copy.add_child(_label(_featured_asset(players, picks), 12, tone.lightened(0.30)))
	return panel


func _featured_asset(players: Array, picks: Array) -> String:
	if not players.is_empty():
		var first = players[0]
		if typeof(first) == TYPE_DICTIONARY:
			var player_name := str(first.get("name", first.get("player_name", "Selected player")))
			if players.size() > 1:
				return "%s + %d more" % [player_name, players.size() - 1]
			return player_name
	if not picks.is_empty():
		var first_pick = picks[0]
		if typeof(first_pick) == TYPE_DICTIONARY:
			var pick_name := str(first_pick.get("display_name", first_pick.get("asset_id", "Draft right")))
			if picks.size() > 1:
				return "%s + %d more" % [pick_name, picks.size() - 1]
			return pick_name
	return "No assets selected"


func _asset_summary(players: Array, picks: Array) -> String:
	return "%d PLAYERS • %d DRAFT RIGHTS" % [players.size(), picks.size()]


func _state_label(state_text: String) -> String:
	var normalized := state_text.strip_edges()
	if normalized == "":
		return "BUILD YOUR PACKAGE"
	return normalized


func _state_tone(state_text: String) -> Color:
	var normalized := state_text.to_upper()
	if "READY" in normalized:
		return DS.GOOD
	if "REJECTED" in normalized or "FAILED" in normalized:
		return DS.BAD
	if "PROGRESS" in normalized:
		return DS.ACCENT
	return DS.GOLD


func _draw() -> void:
	if size.x <= 0.0 or size.y <= 0.0:
		return

	var left_center := Vector2(size.x * 0.12, size.y * 0.50)
	var right_center := Vector2(size.x * 0.88, size.y * 0.50)
	var reach := minf(size.x * 0.30, size.y * 1.10)
	for i in range(12, 0, -1):
		var radius := reach * float(i) / 12.0
		draw_circle(left_center, radius, Color(active_tone, 0.0045))
		draw_circle(right_center, radius, Color(partner_tone, 0.0045))
	draw_line(Vector2(size.x * 0.5, 48), Vector2(size.x * 0.5, size.y - 34), Color(DS.GOLD, 0.15), 1.0, true)
	draw_line(Vector2(22, 2), Vector2(128, 2), Color(active_tone, 0.92), 3.0, true)
	draw_line(Vector2(size.x - 128, 2), Vector2(size.x - 22, 2), Color(partner_tone, 0.92), 3.0, true)


func _label(text_value: String, font_size: int, color: Color) -> Label:
	var label := Label.new()
	label.text = text_value
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.add_theme_font_size_override("font_size", font_size)
	label.add_theme_color_override("font_color", color)
	return label
