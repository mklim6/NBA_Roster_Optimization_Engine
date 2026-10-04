extends VBoxContainer
const DS = preload("res://scripts/design_system_v3.gd")
const Portrait = preload("res://scripts/player_portrait_v3.gd")
var game: Dictionary = {}
var controlled := ""
var comparisons: Dictionary = {}

func configure(value: Dictionary, active_team: String) -> void:
	game = value.duplicate(true)
	controlled = active_team
	for child in get_children():
		remove_child(child)
		child.queue_free()
	comparisons.clear()
	add_theme_constant_override("separation", 12)
	if game.is_empty():
		add_child(_label("GAME SPOTLIGHT", 18, DS.GOLD))
		add_child(_label("Your completed game's standout players and team comparison will appear here.", 14, DS.MUTED))
		return
	var home := str(game.get("home_team", ""))
	var away := str(game.get("away_team", ""))
	var opponent := away if controlled == home else home
	add_child(_label("GAME SPOTLIGHT • SAVED BOX SCORE", 14, DS.GOLD))
	var stars := HBoxContainer.new()
	stars.add_theme_constant_override("separation", 12)
	add_child(stars)
	for team in [controlled, opponent]:
		var rows := _rows(team)
		rows.sort_custom(func(a, b):
			if float(a.get("points", 0)) != float(b.get("points", 0)):
				return float(a.get("points", 0)) > float(b.get("points", 0))
			return str(a.get("name", "")) < str(b.get("name", "")))
		var body := _card(stars)
		body.add_child(_label(team + " • SCORING LEADER", 12, DS.GOLD))
		if rows.is_empty():
			body.add_child(_label("Player data unavailable", 16, DS.MUTED))
			continue
		var player: Dictionary = rows[0]
		var row := HBoxContainer.new()
		row.add_theme_constant_override("separation", 12)
		body.add_child(row)
		var portrait := Portrait.new()
		portrait.name = "PostgameStar_" + team
		portrait.custom_minimum_size = Vector2(128, 112)
		portrait.configure(player)
		row.add_child(portrait)
		var copy := VBoxContainer.new()
		copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		copy.alignment = BoxContainer.ALIGNMENT_CENTER
		row.add_child(copy)
		copy.add_child(_label(str(player.get("name", "Unknown")), 22))
		copy.add_child(_label("%s PTS • %s REB • %s AST" % [player.get("points", "—"), player.get("rebounds", "—"), player.get("assists", "—")], 15))
	var body := _card(self)
	body.add_child(_label("TEAM COMPARISON • " + controlled + " / " + opponent, 18))
	body.add_child(_label("Totals from recorded player lines. Bars compare volume; they do not measure efficiency.", 13, DS.MUTED))
	for stat in [["rebounds", "REBOUNDS"], ["assists", "ASSISTS"], ["turnovers", "TURNOVERS"], ["three_pointers_made", "THREES MADE"]]:
		var first = _total(_rows(controlled), stat[0])
		var second = _total(_rows(opponent), stat[0])
		comparisons[stat[0]] = [first, second]
		body.add_child(_label("%s    %s %s  /  %s %s" % [stat[1], controlled, "—" if first == null else str(first), opponent, "—" if second == null else str(second)], 14))
		if first != null and second != null:
			var bars := HBoxContainer.new()
			bars.add_theme_constant_override("separation", 10)
			body.add_child(bars)
			for index in range(2):
				var bar := ProgressBar.new()
				bar.custom_minimum_size.y = 10
				bar.size_flags_horizontal = Control.SIZE_EXPAND_FILL
				bar.show_percentage = false
				bar.max_value = maxf(1.0, maxf(float(first), float(second)))
				bar.value = float(first if index == 0 else second)
				var fill := StyleBoxFlat.new()
				fill.bg_color = DS.GOOD if index == 0 else DS.ACCENT
				fill.set_corner_radius_all(4)
				bar.add_theme_stylebox_override("fill", fill)
				bars.add_child(bar)

func _rows(team: String) -> Array:
	var rows: Array = []
	for player in game.get("player_box_scores", []):
		if str(player.get("team", "")) == team:
			rows.append(player)
	return rows

func _total(rows: Array, key: String):
	if rows.is_empty():
		return null
	var total := 0.0
	for row in rows:
		if row.get(key, null) == null:
			return null
		total += float(row[key])
	return total

func _label(value: String, font_size: int, color: Color = DS.TEXT) -> Label:
	var label := Label.new()
	label.text = value
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.add_theme_font_size_override("font_size", font_size)
	label.add_theme_color_override("font_color", color)
	return label

func _card(parent: Node) -> VBoxContainer:
	var panel := PanelContainer.new()
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var style := StyleBoxFlat.new()
	style.bg_color = DS.PANEL_ALT
	style.border_color = DS.BORDER
	style.set_border_width_all(1)
	style.set_corner_radius_all(14)
	style.content_margin_left = 18
	style.content_margin_right = 18
	style.content_margin_top = 16
	style.content_margin_bottom = 16
	panel.add_theme_stylebox_override("panel", style)
	parent.add_child(panel)
	var body := VBoxContainer.new()
	body.add_theme_constant_override("separation", 10)
	panel.add_child(body)
	return body
