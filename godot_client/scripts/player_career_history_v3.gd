extends VBoxContainer
const DS = preload("res://scripts/design_system_v3.gd")
var history: Dictionary = {}
var expanded_event = -1
var timeline: VBoxContainer

class ChangeChart extends Control:
	var events: Array = []
	func _ready() -> void:
		custom_minimum_size = Vector2(0, 150)
		resized.connect(queue_redraw)
	func _draw() -> void:
		var font = ThemeDB.fallback_font
		var baseline = 70.0
		var width = max(1.0, size.x - 24.0)
		draw_line(Vector2(12, baseline), Vector2(size.x - 12, baseline), Color("68778b"), 1)
		var scale = 0.5
		for event in events:
			if event.get("delta", null) != null:
				scale = max(scale, abs(float(event.delta)))
		var step = width / max(1, events.size())
		for i in range(events.size()):
			var event = events[i]
			var x = 12 + step * i
			var value = event.get("delta", null)
			var color = Color("72c7f5") if str(event.get("kind", "")) == "season" else Color("f0c866")
			if value == null:
				draw_string(font, Vector2(x+4,baseline-10), "?", HORIZONTAL_ALIGNMENT_LEFT, step, 13, Color("9ba8bb"))
			else:
				var height = abs(float(value)) / scale * 42
				var top = baseline - height if float(value) >= 0 else baseline
				draw_rect(Rect2(x + 3, top, max(3.0, step-10), max(2.0,height)), color)
				draw_string(font, Vector2(x+3, 16), "%+.2f" % float(value), HORIZONTAL_ALIGNMENT_LEFT, step-5, 11, color)
			draw_string(font, Vector2(x+3, 126), str(event.get("season", "")).left(4), HORIZONTAL_ALIGNMENT_LEFT, step-5, 11, Color("9ba8bb"))
			var kind = str(event.get("kind", ""))
			draw_string(font, Vector2(x+3, 142), "YEAR" if kind == "season" else "MENTOR" if kind == "mentor" else "CAMP", HORIZONTAL_ALIGNMENT_LEFT, step-5, 9, color)

func configure(data: Dictionary) -> void:
	history = data.duplicate(true)
	for child in get_children():
		remove_child(child)
		child.queue_free()
	add_theme_constant_override("separation", 10)
	add_child(_label("YOUR DEVELOPMENT STORY", 20, DS.GOLD))
	var total = int(history.get("total_events", 0))
	if total == 0:
		add_child(_label("Your story starts here. Complete a season or training camp to record the first chapter of this player's development.", 14, DS.MUTED))
		return
	var change = history.get("recorded_change", null)
	add_child(_label("%s ANNUAL CHAPTERS • %s CAMPS • %s MENTORSHIPS • RECORDED OVR CHANGE %s" % [history.get("annual_events", 0), history.get("camp_events", 0), history.get("mentor_events",0), "Unavailable" if change == null else "%+.2f" % float(change)], 13))
	add_child(_label(str(history.get("coverage", "")), 12, DS.MUTED))
	var events: Array = history.get("events", [])
	var chart = ChangeChart.new()
	chart.name = "CareerChangeChart"
	chart.events = events.slice(max(0,events.size()-12))
	add_child(chart)
	add_child(_label("LAST %s RECORDED EVENTS • ANNUAL DEVELOPMENT IN BLUE • CAMP & MENTORSHIPS IN GOLD" % chart.events.size(), 11, DS.MUTED))
	timeline = VBoxContainer.new()
	timeline.name = "CareerTimeline"
	timeline.add_theme_constant_override("separation", 8)
	add_child(timeline)
	for i in range(events.size()-1,max(-1,events.size()-9),-1):
		var event = events[i]
		var panel = PanelContainer.new()
		var style = StyleBoxFlat.new()
		style.bg_color = DS.PANEL
		style.border_color = DS.BORDER if event.get("kind", "") == "season" else Color(DS.GOLD,.4)
		style.set_border_width_all(1)
		style.set_corner_radius_all(10)
		style.content_margin_left = 12
		style.content_margin_right = 12
		style.content_margin_top = 10
		style.content_margin_bottom = 10
		panel.add_theme_stylebox_override("panel",style)
		timeline.add_child(panel)
		var body = VBoxContainer.new()
		panel.add_child(body)
		var destination = str(event.get("target_season", ""))
		var title = str(event.get("season", "")) + (" → " + destination if destination != "" else "")
		body.add_child(_label(title + " • " + str(event.get("headline", "")), 15, DS.ACCENT if event.get("kind", "") == "season" else DS.GOLD))
		var before = event.get("before", null)
		var after = event.get("after", null)
		body.add_child(_label("OVR %s → %s" % [_number(before), _number(after)], 18))
		var mentor = str(event.get("mentor_name", ""))
		if mentor != "":
			body.add_child(_label("MENTORED BY " + mentor.to_upper(), 12, DS.GOLD))
		var detail = _label(_skills(event.get("skills", {})), 12, DS.MUTED)
		detail.visible = false
		var button = Button.new()
		button.text = "REVIEW SKILL CHANGES"
		button.custom_minimum_size.y = 36
		button.pressed.connect(func():
			detail.visible = not detail.visible
			button.text = "HIDE SKILL CHANGES" if detail.visible else "REVIEW SKILL CHANGES")
		body.add_child(button)
		body.add_child(detail)
	if total > timeline.get_child_count():
		add_child(_label("Showing the latest %s of %s saved career events." % [timeline.get_child_count(), total], 12, DS.MUTED))

func _skills(skills: Dictionary) -> String:
	var parts: Array[String] = []
	for skill in skills:
		var value = skills[skill]
		parts.append(str(skill).capitalize() + " " + ("Unavailable" if value == null else "%+.2f" % float(value)))
	return " • ".join(parts) if not parts.is_empty() else "No skill breakdown was saved for this event."

func _number(value) -> String:
	return "Unavailable" if value == null else "%.2f" % float(value)

func _label(text: String, font_size: int, color: Color = DS.TEXT) -> Label:
	var label = Label.new()
	label.text = text
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.add_theme_font_size_override("font_size",font_size)
	label.add_theme_color_override("font_color",color)
	return label
