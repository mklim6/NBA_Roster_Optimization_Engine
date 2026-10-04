extends PanelContainer

const Design = preload("res://scripts/design_system_v3.gd")
const Branding = preload("res://scripts/team_branding_v3.gd")
const Logo = preload("res://scripts/team_logo_v3.gd")
const Portrait = preload("res://scripts/player_portrait_v3.gd")
var salary_difference: Label
var preview_state: Label

func configure(active_team: String, partner_team: String, outgoing: Array, incoming: Array, outgoing_picks: Array, incoming_picks: Array) -> void:
	name = "TradePackageStage"
	size_flags_horizontal = Control.SIZE_EXPAND_FILL
	for child in get_children():
		remove_child(child)
		child.queue_free()
	add_theme_stylebox_override("panel", _box(Design.PANEL, Design.BORDER, 16))
	var margin = MarginContainer.new()
	for edge in ["left", "right", "top", "bottom"]:
		margin.add_theme_constant_override("margin_" + edge, 16)
	add_child(margin)
	var body = VBoxContainer.new()
	body.add_theme_constant_override("separation", 12)
	margin.add_child(body)
	var heading = HBoxContainer.new()
	body.add_child(heading)
	var title = _label("THE DEAL • LIVE PACKAGE", 11, Design.ACCENT)
	title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	heading.add_child(title)
	preview_state = _label("BUILD PACKAGE", 10, Design.GOLD)
	preview_state.name = "TradeStagePreviewState"
	heading.add_child(preview_state)
	var sides = HBoxContainer.new()
	sides.add_theme_constant_override("separation", 12)
	body.add_child(sides)
	sides.add_child(_side("Outgoing", active_team, outgoing, outgoing_picks))
	var exchange = _label("⇄", 30, Design.GOLD)
	exchange.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	exchange.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	exchange.custom_minimum_size = Vector2(40, 0)
	sides.add_child(exchange)
	sides.add_child(_side("Incoming", partner_team, incoming, incoming_picks))
	var sent = _salary(outgoing)
	var received = _salary(incoming)
	salary_difference = _label("", 12, Design.TEXT)
	salary_difference.name = "TradeSalaryDifference"
	if sent.known and received.known:
		var delta: float = received.total - sent.total
		salary_difference.text = "CURRENT PLAYER SALARY CHANGE  %s%s" % ["+" if delta > 0 else "", _money(delta)]
	else:
		salary_difference.text = "CURRENT PLAYER SALARY CHANGE  Unavailable until all selected salaries are known"
	salary_difference.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	body.add_child(salary_difference)
	body.add_child(_label("Current salary comparison • Preview determines trade legality", 10, Design.MUTED))

func set_preview_state(value: String, color: Color) -> void:
	preview_state.text = value
	preview_state.add_theme_color_override("font_color", color)

func _side(direction: String, team: String, players: Array, picks: Array) -> Control:
	var color: Color = Branding.palette(team).get("primary", Design.ACCENT)
	var panel = PanelContainer.new()
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	panel.size_flags_stretch_ratio = 1.0
	panel.add_theme_stylebox_override("panel", _box(Color(color, 0.075), Color(color, 0.50), 12))
	var margin = MarginContainer.new()
	for edge in ["left", "right", "top", "bottom"]:
		margin.add_theme_constant_override("margin_" + edge, 12)
	panel.add_child(margin)
	var body = VBoxContainer.new()
	body.add_theme_constant_override("separation", 8)
	margin.add_child(body)
	var heading = HBoxContainer.new()
	heading.add_theme_constant_override("separation", 10)
	body.add_child(heading)
	var logo = Logo.new()
	logo.name = direction + "TeamLogo"
	logo.custom_minimum_size = Vector2(72, 64)
	heading.add_child(logo)
	logo.configure(team)
	var identity = VBoxContainer.new()
	identity.alignment = BoxContainer.ALIGNMENT_CENTER
	identity.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	heading.add_child(identity)
	identity.add_child(_label(direction.to_upper(), 10, Design.ACCENT))
	identity.add_child(_label(team if team != "" else "CHOOSE TEAM", 26, Design.TEXT))
	identity.add_child(_label("%s PLAYERS • %s DRAFT RIGHTS" % [players.size(), picks.size()], 9, Design.MUTED))
	var portraits = HBoxContainer.new()
	portraits.name = direction + "SelectedPlayers"
	portraits.add_theme_constant_override("separation", 8)
	body.add_child(portraits)
	if players.is_empty():
		var empty = _label("Select players from the asset board below.", 12, Design.MUTED)
		empty.custom_minimum_size = Vector2(0, 96)
		empty.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		empty.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
		empty.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		portraits.add_child(empty)
	for player in players.slice(0, 3):
		var tile = VBoxContainer.new()
		tile.custom_minimum_size = Vector2(128, 0)
		tile.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		portraits.add_child(tile)
		var portrait = Portrait.new()
		portrait.name = direction + "PackagePortrait_" + str(player.get("player_id", ""))
		portrait.custom_minimum_size = Vector2(128, 176 if players.size() == 1 else 144)
		tile.add_child(portrait)
		portrait.configure(player)
		var player_name = _label(str(player.get("name", "Unknown")), 15, Design.TEXT)
		player_name.tooltip_text = player_name.text
		player_name.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
		tile.add_child(player_name)
		tile.add_child(_label("%s • OVR %s" % [player.get("position", "--"), "--" if player.get("overall") == null else str(player.get("overall"))], 11, Design.MUTED))
	if players.size() > 3:
		body.add_child(_label("+ %s additional players in this package" % (players.size() - 3), 10, Design.ACCENT))
	var pick_names: Array = []
	for pick in picks:
		pick_names.append(str(pick.get("display_name", pick.get("asset_id", "Draft right"))))
	var pick_label = _label("NO DRAFT RIGHTS SELECTED" if picks.is_empty() else "DRAFT RIGHTS • " + " + ".join(pick_names.slice(0, 2)), 10, Design.GOLD if not picks.is_empty() else Design.MUTED)
	pick_label.name = direction + "PackagePicks"
	pick_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	pick_label.tooltip_text = "\n".join(pick_names)
	body.add_child(pick_label)
	if picks.size() > 2:
		body.add_child(_label("+ %s additional draft rights" % (picks.size() - 2), 10, Design.GOLD))
	var salary = _salary(players)
	var salary_label = _label("PLAYER SALARY  " + (_money(salary.total) if salary.known else "Unavailable"), 12, Design.TEXT)
	salary_label.name = direction + "SalaryTotal"
	body.add_child(salary_label)
	return panel

func _salary(players: Array) -> Dictionary:
	var total = 0.0
	var known = true
	for player in players:
		if typeof(player.get("salary")) in [TYPE_INT, TYPE_FLOAT]:
			total += float(player.get("salary"))
		else:
			known = false
	return {"total": total, "known": known}

func _money(value: float) -> String:
	return "-$%.1fM" % (abs(value) / 1000000) if value < 0 else "$%.1fM" % (value / 1000000)

func _label(value: String, font_size: int, color: Color) -> Label:
	var label = Label.new()
	label.text = value
	label.add_theme_font_size_override("font_size", font_size)
	label.add_theme_color_override("font_color", color)
	return label

func _box(fill: Color, border: Color, radius: int) -> StyleBoxFlat:
	var style = StyleBoxFlat.new()
	style.bg_color = fill
	style.border_color = border
	style.set_border_width_all(1)
	style.set_corner_radius_all(radius)
	return style
