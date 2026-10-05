extends VBoxContainer
const DS = preload("res://scripts/design_system_v3.gd")
const Portrait = preload("res://scripts/player_portrait_v3.gd")
const CareerHistory = preload("res://scripts/player_career_history_v3.gd")
var rows: Array = []
var selected_id := ""
var sort_selector: OptionButton
var direction_selector: OptionButton
var cards: GridContainer
var selected_detail: VBoxContainer
var count_label: Label
var visible_ids: Array = []

func _ready() -> void:
	add_theme_constant_override("separation", 12)
	add_child(_label("PLAYER DEVELOPMENT LAB", 24, DS.GOLD))
	add_child(_label("Explore your roster's current ability and projected outlook. Projections describe the model; they are not guaranteed growth.", 14, DS.MUTED))
	var controls := HBoxContainer.new()
	controls.add_theme_constant_override("separation", 12)
	add_child(controls)
	sort_selector = OptionButton.new()
	for title in ["Future outlook", "Potential gap", "Youngest first"]:
		sort_selector.add_item(title)
	sort_selector.custom_minimum_size = Vector2(200, 42)
	sort_selector.item_selected.connect(func(_index): _render())
	controls.add_child(sort_selector)
	direction_selector = OptionButton.new()
	for title in ["All directions", "Rising", "Stable", "Declining"]:
		direction_selector.add_item(title)
	direction_selector.custom_minimum_size = Vector2(175, 42)
	direction_selector.item_selected.connect(func(_index): _render())
	controls.add_child(direction_selector)
	count_label = _label("Loading roster outlook…", 14, DS.MUTED)
	count_label.custom_minimum_size.x = 180
	count_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	count_label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	controls.add_child(count_label)
	selected_detail = VBoxContainer.new()
	add_child(selected_detail)
	cards = GridContainer.new()
	cards.columns = 3
	cards.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	cards.add_theme_constant_override("h_separation", 12)
	cards.add_theme_constant_override("v_separation", 12)
	add_child(cards)

func configure(development: Dictionary) -> void:
	rows = development.get("full_roster", development.get("core", [])).duplicate(true)
	if not rows.any(func(player): return str(player.get("player_id", "")) == selected_id):
		selected_id = ""
	_render()

func clear_report() -> void:
	rows.clear()
	selected_id = ""
	_render()
	count_label.text = "Awaiting current team report"

func _clear(parent: Node) -> void:
	for child in parent.get_children():
		parent.remove_child(child)
		child.queue_free()

func _sort_value(player: Dictionary):
	match sort_selector.selected:
		1:
			if player.get("potential", null) == null or player.get("overall", null) == null:
				return null
			return float(player.potential) - float(player.overall)
		2:
			return player.get("age", null)
	return player.get("future_outlook", null)

func _render() -> void:
	_clear(cards)
	_clear(selected_detail)
	visible_ids.clear()
	var visible_rows: Array = []
	for player in rows:
		if direction_selector.selected == 0 or str(player.get("direction", "")) == direction_selector.get_item_text(direction_selector.selected):
			visible_rows.append(player)
	visible_rows.sort_custom(func(a, b):
		var first = _sort_value(a)
		var second = _sort_value(b)
		if first == null or second == null:
			if first != second:
				return first != null
		elif float(first) != float(second):
			return float(first) < float(second) if sort_selector.selected == 2 else float(first) > float(second)
		return str(a.get("name", "")) + str(a.get("player_id", "")) < str(b.get("name", "")) + str(b.get("player_id", "")))
	if not visible_rows.any(func(player): return str(player.get("player_id", "")) == selected_id):
		selected_id = str(visible_rows[0].get("player_id", "")) if not visible_rows.is_empty() else ""
	count_label.text = "%s / %s players" % [visible_rows.size(), rows.size()]
	if visible_rows.is_empty():
		selected_detail.add_child(_label("No players match this development view.", 16, DS.MUTED))
		return
	for player in visible_rows:
		var id := str(player.get("player_id", ""))
		visible_ids.append(id)
		if id == selected_id:
			_render_selected(player)
		var body := _card(cards, id == selected_id)
		var portrait := Portrait.new()
		portrait.name = "DevelopmentPortrait_" + id
		portrait.custom_minimum_size = Vector2(140, 110)
		body.add_child(portrait)
		portrait.configure(player)
		body.add_child(_label(str(player.get("name", "Unknown")), 19))
		body.add_child(_label("%s • AGE %s • %s" % [player.get("position", "—"), _number(player.get("age", null)), player.get("direction", "Unknown")], 12, DS.MUTED))
		body.add_child(_label("OVR %s    POT %s    FUT %s" % [_number(player.get("overall", null)), _number(player.get("potential", null)), _number(player.get("future_outlook", null))], 14))
		var button := Button.new()
		button.name = "DevelopmentSelect_" + id
		button.text = "SELECTED" if id == selected_id else "EXPLORE OUTLOOK"
		button.custom_minimum_size.y = 40
		button.pressed.connect(_select_player.bind(id))
		body.add_child(button)

func _select_player(id: String) -> void:
	selected_id = id
	_render()
	await get_tree().process_frame
	var ancestor = get_parent()
	while ancestor != null and not ancestor is ScrollContainer:
		ancestor = ancestor.get_parent()
	if ancestor is ScrollContainer:
		ancestor.ensure_control_visible(selected_detail)

func _render_selected(player: Dictionary) -> void:
	var body := _card(selected_detail, true)
	body.add_child(_label(str(player.get("name", "Unknown")) + " • DEVELOPMENT OUTLOOK", 22, DS.GOLD))
	var history = player.get("history_entries", null)
	body.add_child(_label("Direction: %s • Recorded history entries: %s" % [player.get("direction", "Unknown"), "Unavailable" if history == null else str(history)], 14))
	for metric in [["overall", "CURRENT ABILITY"], ["potential", "MODEL POTENTIAL"], ["future_outlook", "FUTURE OUTLOOK"]]:
		var value = player.get(metric[0], null)
		body.add_child(_label(metric[1] + " • " + _number(value), 13, DS.MUTED))
		if value != null:
			var bar := ProgressBar.new()
			bar.show_percentage = false
			bar.max_value = 100
			bar.value = float(value)
			bar.custom_minimum_size.y = 10
			body.add_child(bar)
	var reliability = player.get("profile_reliability", null)
	body.add_child(_label("Profile reliability: %s. Potential and outlook are projections, not recorded changes." % ("Unavailable" if reliability == null else "%.0f%%" % (float(reliability) * 100.0)), 13, DS.MUTED))
	if player.has("career_history"):
		var career = CareerHistory.new()
		career.name = "PlayerCareerHistory"
		body.add_child(career)
		career.configure(player.get("career_history", {}))

func _number(value) -> String:
	return "—" if value == null else "%.1f" % float(value)

func _label(value: String, font_size: int, color: Color = DS.TEXT) -> Label:
	var label := Label.new()
	label.text = value
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.add_theme_font_size_override("font_size", font_size)
	label.add_theme_color_override("font_color", color)
	return label

func _card(parent: Node, selected: bool) -> VBoxContainer:
	var panel := PanelContainer.new()
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var style := StyleBoxFlat.new()
	style.bg_color = DS.PANEL_ALT
	style.border_color = DS.GOLD if selected else DS.BORDER
	style.set_border_width_all(1)
	style.set_corner_radius_all(14)
	style.content_margin_left = 16
	style.content_margin_right = 16
	style.content_margin_top = 16
	style.content_margin_bottom = 16
	panel.add_theme_stylebox_override("panel", style)
	parent.add_child(panel)
	var body := VBoxContainer.new()
	body.add_theme_constant_override("separation", 8)
	panel.add_child(body)
	return body
