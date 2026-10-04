extends Control
signal navigate(page: String)
const DS = preload("res://scripts/design_system_v3.gd")
const Portrait = preload("res://scripts/player_portrait_v3.gd")
const Identity = preload("res://scripts/page_identity_v3.gd")
var request: HTTPRequest
var status: Label
var counts: Label
var filter: OptionButton
var rows: VBoxContainer
var identity: Control
var payload: Dictionary = {}
var expected_team := ""
var visible_ids: Array = []

func _ready() -> void:
	var scroll := ScrollContainer.new()
	scroll.name = "DecisionInboxScroll"
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	add_child(scroll)
	scroll.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	var margin := MarginContainer.new()
	margin.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	for side in ["left", "right", "top", "bottom"]:
		margin.add_theme_constant_override("margin_" + side, 28)
	scroll.add_child(margin)
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 16)
	margin.add_child(column)
	var header := HBoxContainer.new()
	header.add_theme_constant_override("separation", 14)
	column.add_child(header)
	var titles := VBoxContainer.new()
	titles.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	header.add_child(titles)
	titles.add_child(_label("YOUR FRANCHISE • NEXT DECISIONS", 12, DS.GOLD))
	titles.add_child(_label("FRANCHISE INBOX", 32))
	titles.add_child(_label("Review the stakes, then open the tool that handles the decision.", 15, DS.MUTED))
	identity = Identity.new()
	header.add_child(identity)
	var refresh_button := Button.new()
	refresh_button.text = "REFRESH INBOX"
	refresh_button.custom_minimum_size = Vector2(155, 52)
	refresh_button.pressed.connect(refresh)
	header.add_child(refresh_button)
	status = _label("Open the inbox to load the current franchise report.", 14, DS.MUTED)
	column.add_child(status)
	counts = _label("", 18, DS.GOLD)
	column.add_child(counts)
	filter = OptionButton.new()
	filter.custom_minimum_size = Vector2(230, 42)
	filter.size_flags_horizontal = Control.SIZE_SHRINK_BEGIN
	for category in ["All decisions", "Offers", "Availability", "Player roles", "Game preparation", "Season decisions"]:
		filter.add_item(category)
	filter.item_selected.connect(func(_index): _render())
	column.add_child(filter)
	rows = VBoxContainer.new()
	rows.add_theme_constant_override("separation", 12)
	column.add_child(rows)
	request = HTTPRequest.new()
	request.timeout = 30
	request.request_completed.connect(_on_completed)
	add_child(request)

func apply_team_brand(team: String, primary: Color, secondary: Color) -> void:
	if expected_team != team:
		payload.clear()
		if rows != null:
			_clear()
			counts.text = ""
	expected_team = team
	if identity != null:
		identity.configure(team, primary, secondary)

func invalidate() -> void:
	request.cancel_request()
	payload.clear()
	_clear()
	counts.text = ""
	status.text = "Refresh to load the active franchise decisions."

func refresh() -> void:
	invalidate()
	status.text = "Loading your current franchise decisions…"
	if request.request("http://127.0.0.1:8765/v3/decision-inbox") != OK:
		status.text = "Inbox unavailable. Refresh to retry."

func _on_completed(result: int, code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	if result != HTTPRequest.RESULT_SUCCESS or code != 200:
		status.text = "Inbox unavailable. Refresh to retry."
		return
	var parsed = JSON.parse_string(body.get_string_from_utf8())
	if not parsed is Dictionary:
		status.text = "Inbox unavailable. Refresh to retry."
		return
	if str(parsed.get("team", "")) != expected_team or not bool(parsed.get("working_save_unchanged", false)) or not bool(parsed.get("active_v2_unchanged", false)):
		status.text = "Inbox snapshot does not match your active franchise. Refresh to retry."
		return
	payload = parsed
	_render()

func _clear() -> void:
	visible_ids.clear()
	for child in rows.get_children():
		rows.remove_child(child)
		child.queue_free()

func _render() -> void:
	_clear()
	var cards: Array = payload.get("cards", [])
	var totals := {"Action": 0, "Watch": 0, "Next": 0}
	for card in cards:
		totals[card.get("priority", "Next")] += 1
	counts.text = "%s ACTION • %s WATCH • %s NEXT" % [totals.Action, totals.Watch, totals.Next]
	status.text = "%s • League day %s • %s\n%s" % [payload.get("team", ""), payload.get("day_index", "?"), payload.get("season", ""), "Saved offer queue loaded. Cards open existing decision tools." if payload.get("offer_queue_status", "") == "loaded" else "Incoming-offer queue is not initialized in this save. Other franchise reports are shown below."]
	for card in cards:
		if filter.selected != 0 and card.get("category", "") != filter.get_item_text(filter.selected):
			continue
		visible_ids.append(card.get("id", ""))
		var panel := PanelContainer.new()
		panel.name = "Decision_" + str(card.get("id", ""))
		var style := StyleBoxFlat.new()
		style.bg_color = DS.PANEL_ALT
		style.border_color = DS.GOLD if card.get("priority", "") == "Action" else DS.BORDER
		style.set_border_width_all(1)
		style.set_corner_radius_all(14)
		style.content_margin_left = 18
		style.content_margin_right = 18
		style.content_margin_top = 18
		style.content_margin_bottom = 18
		panel.add_theme_stylebox_override("panel", style)
		rows.add_child(panel)
		var row := HBoxContainer.new()
		row.add_theme_constant_override("separation", 16)
		panel.add_child(row)
		if str(card.get("player_id", "")) != "":
			var portrait := Portrait.new()
			portrait.custom_minimum_size = Vector2(100, 90)
			row.add_child(portrait)
			portrait.configure({"player_id": card.player_id, "name": card.get("name", "Player")})
		var copy := VBoxContainer.new()
		copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		copy.add_theme_constant_override("separation", 8)
		row.add_child(copy)
		copy.add_child(_label("%s • %s" % [card.get("priority", "Next").to_upper(), card.get("category", "")], 12, DS.GOLD))
		copy.add_child(_label(card.get("title", "Decision"), 22))
		copy.add_child(_label(card.get("detail", ""), 15))
		var action := Button.new()
		action.text = "OPEN " + str(card.get("destination", "FRONT OFFICE"))
		action.custom_minimum_size = Vector2(175, 44)
		action.size_flags_vertical = Control.SIZE_SHRINK_CENTER
		action.pressed.connect(func(): navigate.emit(str(card.get("destination", "FRONT OFFICE"))))
		row.add_child(action)
	if visible_ids.is_empty():
		rows.add_child(_label("No decisions match this view." if not cards.is_empty() else "No actionable items were reported in this snapshot.", 18, DS.MUTED))

func _label(value: String, font_size: int, color: Color = DS.TEXT) -> Label:
	var label := Label.new()
	label.text = value
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.add_theme_font_size_override("font_size", font_size)
	label.add_theme_color_override("font_color", color)
	return label
