extends VBoxContainer
const DS = preload("res://scripts/design_system_v3.gd")
const Logo = preload("res://scripts/team_logo_v3.gd")
var selected: Dictionary = {}
var reference: Dictionary = {}
var stage_text: Label
var primary := DS.TEAM_PRIMARY

func configure(prospect: Dictionary, comparison: Dictionary, draft: Dictionary, team: String, color: Color) -> void:
	selected = prospect.duplicate(true)
	reference = comparison.duplicate(true)
	primary = color
	for child in get_children():
		remove_child(child)
		child.queue_free()
	add_theme_constant_override("separation", 12)
	var stage := _panel(self)
	var stage_row := HBoxContainer.new()
	stage_row.add_theme_constant_override("separation", 16)
	stage.add_child(stage_row)
	var owner := str(draft.get("current_pick", {}).get("owner_team", team)) if draft.get("current_pick", null) is Dictionary else team
	var logo := Logo.new()
	logo.custom_minimum_size = Vector2(80, 70)
	stage_row.add_child(logo)
	logo.configure(owner)
	var copy := VBoxContainer.new()
	copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	stage_row.add_child(copy)
	var phase := str(draft.get("phase", ""))
	stage_text = _label("BUILD YOUR NEXT CORE", 24, primary.lightened(0.4))
	if phase == "draft_in_progress":
		stage_text.text = "%s ON THE CLOCK • PICK %s" % [owner, draft.get("current_pick", {}).get("overall_pick", "—")]
	elif phase == "draft_complete":
		stage_text.text = "THE CLASS IS SELECTED"
	copy.add_child(stage_text)
	copy.add_child(_label("%s Draft • %s" % [draft.get("draft_year", "Upcoming"), phase.replace("_", " ").capitalize()], 14, DS.MUTED))
	if selected.is_empty():
		stage.add_child(_label("Select a prospect to open the dossier. Pin a report, then select another prospect to compare their scouting estimates.", 15))
		return
	var dossiers := HBoxContainer.new()
	dossiers.add_theme_constant_override("separation", 14)
	add_child(dossiers)
	_dossier(dossiers, selected, "SELECTED PROSPECT")
	if not reference.is_empty() and reference.get("prospect_id", "") != selected.get("prospect_id", ""):
		_dossier(dossiers, reference, "PINNED COMPARISON")

func _dossier(parent: Node, row: Dictionary, heading: String) -> void:
	var body := _panel(parent)
	body.add_child(_label(heading, 12, DS.GOLD))
	var identity := HBoxContainer.new()
	identity.add_theme_constant_override("separation", 14)
	body.add_child(identity)
	var badge := _label("#%s\n%s" % [row.get("Rank", "—"), row.get("Pos", "—")], 30, primary.lightened(0.5))
	badge.custom_minimum_size = Vector2(82, 90)
	badge.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	badge.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	identity.add_child(badge)
	var copy := VBoxContainer.new()
	copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	identity.add_child(copy)
	copy.add_child(_label(str(row.get("Prospect", "Unknown prospect")), 25))
	copy.add_child(_label("%s • AGE %s" % [_text(row.get("School / Club", null)), _text(row.get("Age", null))], 14, DS.MUTED))
	copy.add_child(_label(_text(row.get("Archetype", null)), 15))
	body.add_child(_label("SCOUTED OVR %s    SCOUTED POT %s" % [_rating(row.get("Scouted OVR", null)), _rating(row.get("Scouted POT", null))], 19))
	var confidence = row.get("Confidence", null)
	body.add_child(_label("REPORT CONFIDENCE • " + ("Unavailable" if confidence == null else "%.0f%%" % float(confidence)), 14, DS.GOLD))
	if confidence != null:
		var bar := ProgressBar.new()
		bar.name = "Confidence_" + str(row.get("prospect_id", ""))
		bar.custom_minimum_size.y = 12
		bar.show_percentage = false
		bar.value = float(confidence)
		var fill := StyleBoxFlat.new()
		fill.bg_color = DS.GOLD
		fill.set_corner_radius_all(5)
		bar.add_theme_stylebox_override("fill", fill)
		body.add_child(bar)
	body.add_child(_label("%s report • Projected: %s" % [_text(row.get("Report", null)), _text(row.get("Projected", null))], 14, DS.MUTED))
	body.add_child(_label("Scouting estimates may change as reports improve. Confidence is report certainty, not a probability of becoming a star.", 13, DS.MUTED))

func _rating(value) -> String:
	return "—" if value == null else "%.1f" % float(value)

func _text(value) -> String:
	return "Unavailable" if value == null else str(value)

func _label(value: String, font_size: int, color: Color = DS.TEXT) -> Label:
	var label := Label.new()
	label.text = value
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.add_theme_font_size_override("font_size", font_size)
	label.add_theme_color_override("font_color", color)
	return label

func _panel(parent: Node) -> VBoxContainer:
	var panel := PanelContainer.new()
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var style := StyleBoxFlat.new()
	style.bg_color = DS.PANEL_ALT
	style.border_color = Color(primary, 0.55)
	style.set_border_width_all(1)
	style.set_corner_radius_all(16)
	style.content_margin_left = 18
	style.content_margin_right = 18
	style.content_margin_top = 18
	style.content_margin_bottom = 18
	panel.add_theme_stylebox_override("panel", style)
	parent.add_child(panel)
	var body := VBoxContainer.new()
	body.add_theme_constant_override("separation", 10)
	panel.add_child(body)
	return body
