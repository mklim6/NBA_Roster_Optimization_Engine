extends VBoxContainer
const DS = preload("res://scripts/design_system_v3.gd")
const Logo = preload("res://scripts/team_logo_v3.gd")
var payload: Dictionary = {}
var milestone_cards: Array = []
var result_cards: Array = []
var chart: Control

class MarginChart extends Control:
	var values: Array = []
	var tone := DS.GOOD
	func _draw() -> void:
		if values.is_empty():
			return
		var extent := 1.0
		for value in values:
			extent = maxf(extent, absf(float(value)))
		var left := 18.0
		var right := size.x - 18.0
		var middle := size.y * 0.5
		var height := size.y * 0.38
		draw_line(Vector2(left,middle), Vector2(right,middle), DS.BORDER, 1)
		var points := PackedVector2Array([Vector2(left,middle)])
		for index in range(values.size()):
			points.append(Vector2(lerpf(left,right,float(index+1)/values.size()), middle-float(values[index])/extent*height))
		if points.size() >= 2:
			draw_polyline(points, tone, 3, true)
		for point in points:
			draw_circle(point, 3, tone)
		draw_string(ThemeDB.fallback_font, Vector2(left,14), "+%.0f" % extent, HORIZONTAL_ALIGNMENT_LEFT, -1, 11, DS.MUTED)
		draw_string(ThemeDB.fallback_font, Vector2(left,size.y-3), "-%.0f" % extent, HORIZONTAL_ALIGNMENT_LEFT, -1, 11, DS.MUTED)

func configure(data: Dictionary, accent: Color, unavailable: String = "") -> void:
	payload = data.duplicate(true)
	milestone_cards.clear()
	result_cards.clear()
	chart = null
	for child in get_children():
		remove_child(child)
		child.queue_free()
	add_theme_constant_override("separation", 12)
	add_child(_label("SEASON MOMENTUM", 20, DS.GOLD))
	if data.is_empty():
		add_child(_label(unavailable if not unavailable.is_empty() else "Season progress unavailable. Return to HQ to retry.", 14, DS.MUTED))
		return
	var target = data.get("next_target", null)
	var wins = data.get("wins", null)
	var message := "All four win milestones reached. Keep building your season."
	if wins == null:
		message = "Win record unavailable. Milestone progress is unknown."
	elif target != null:
		var remaining := int(target.target)-int(wins)
		message = "%s %s to %s • %s / %s" % [remaining, "win" if remaining == 1 else "wins", target.title, wins, target.target]
	add_child(_label(message, 16))
	add_child(_label("Your wins build this season’s milestone collection.", 12, DS.MUTED))
	var milestones := HBoxContainer.new()
	milestones.add_theme_constant_override("separation", 10)
	add_child(milestones)
	for milestone in data.get("milestones", []):
		var achieved := bool(milestone.get("achieved", false))
		var tone := DS.GOLD if achieved else accent.lightened(.25)
		var card := _card(milestones, tone)
		milestone_cards.append(card)
		card.add_child(_label("REACHED" if achieved else "IN PROGRESS", 11, tone))
		card.add_child(_label(str(milestone.target) + (" WIN" if int(milestone.target) == 1 else " WINS"), 26, tone))
		card.add_child(_label(str(milestone.title), 14))
		var progress = milestone.get("progress", null)
		if progress != null:
			var bar := ProgressBar.new()
			bar.custom_minimum_size.y = 8
			bar.show_percentage = false
			bar.max_value = float(milestone.target)
			bar.value = float(progress)
			bar.add_theme_stylebox_override("fill", DS.style_box(tone, 4, tone, 0, 0.0))
			card.add_child(bar)
	var recent: Array = data.get("recent", [])
	var body := _card(self, accent)
	if recent.is_empty():
		body.add_child(_label("YOUR STORY STARTS WITH GAME ONE", 18, DS.GOLD))
		body.add_child(_label("Your saved results will build a form ribbon and scoring-margin chart here after your first game.", 14, DS.MUTED))
		return
	body.add_child(_label("RECENT FORM • %s-%s IN LAST %s" % [data.get("recent_wins",0), recent.size()-int(data.get("recent_wins",0)), recent.size()], 16))
	var ribbon := HBoxContainer.new()
	ribbon.add_theme_constant_override("separation", 8)
	body.add_child(ribbon)
	for game in recent:
		var tone := DS.GOOD if game.result == "W" else DS.BAD if game.result == "L" else DS.MUTED
		var result := _card(ribbon, tone)
		result_cards.append(result)
		var identity := HBoxContainer.new()
		result.add_child(identity)
		var logo := Logo.new()
		logo.custom_minimum_size = Vector2(36,32)
		logo.configure(str(game.opponent))
		identity.add_child(logo)
		identity.add_child(_label(str(game.result) + " • " + str(game.opponent), 16, tone))
		result.add_child(_label("%s–%s" % [game.scored,game.allowed], 18))
		result.add_child(_label("%s • DAY %s" % [game.venue,game.day_index], 11, DS.MUTED))
	var margin = data.get("cumulative_margin", 0)
	body.add_child(_label("CUMULATIVE SCORING MARGIN • %+.0f PTS" % float(margin), 16))
	body.add_child(_label("Starts at zero; each saved game adds points scored minus points allowed. Game order runs left to right.", 12, DS.MUTED))
	chart = MarginChart.new()
	chart.custom_minimum_size.y = 140
	chart.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	chart.tone = accent.lightened(.25)
	for game in data.get("trend", []):
		chart.values.append(game.cumulative_margin)
	body.add_child(chart)
	body.add_child(_label("%s saved games tracked • current regular-season schedule" % data.get("games_tracked",0), 12, DS.MUTED))

func _card(parent: Node, tone: Color) -> VBoxContainer:
	var panel := PanelContainer.new()
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var style := DS.style_box(DS.PANEL_ALT, 12, Color(tone,.45), 1, 0.0)
	style.content_margin_left = 14
	style.content_margin_right = 14
	style.content_margin_top = 14
	style.content_margin_bottom = 14
	panel.add_theme_stylebox_override("panel", style)
	parent.add_child(panel)
	var body := VBoxContainer.new()
	body.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	body.add_theme_constant_override("separation", 8)
	panel.add_child(body)
	return body

func _label(text: String, font_size: int, color: Color = DS.TEXT) -> Label:
	var label := Label.new()
	label.text = text
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	label.add_theme_font_size_override("font_size", font_size)
	label.add_theme_color_override("font_color", color)
	return label
