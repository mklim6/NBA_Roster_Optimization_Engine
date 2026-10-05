extends VBoxContainer
const DS = preload("res://scripts/design_system_v3.gd")
signal navigate_requested(page: String)
var board: Dictionary
var donor: OptionButton
var recipient: OptionButton
var amount: SpinBox
var result: Label
var baseline: Label

func configure(data: Dictionary) -> void:
	board = data.duplicate(true)
	name = "RebuildOpportunityLab"
	add_theme_constant_override("separation", 12)
	add_child(_label("OPPORTUNITY LAB • MAKE ROOM FOR YOUR CORE", 22, DS.GOLD))
	add_child(_label("Try a minutes tradeoff before changing your rotation. Pick who gives up time, who receives it, and how much.", 14))
	baseline = _label("", 14)
	add_child(baseline)
	var grid = GridContainer.new()
	grid.columns = 2
	grid.add_theme_constant_override("h_separation", 12)
	grid.add_theme_constant_override("v_separation", 8)
	add_child(grid)
	grid.add_child(_label("TAKE MINUTES FROM", 12))
	grid.add_child(_label("GIVE MINUTES TO", 12))
	donor = OptionButton.new()
	recipient = OptionButton.new()
	for picker in [donor, recipient]:
		picker.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		picker.clip_text = true
		picker.custom_minimum_size = Vector2(0, 42)
		picker.add_item("Choose a player")
		for row in board.get("players", []):
			picker.add_item(str(row.name))
		picker.item_selected.connect(func(_index): _update())
		grid.add_child(picker)
	var controls = HBoxContainer.new()
	add_child(controls)
	var transfer_label = _label("MINUTES TO TRANSFER", 12)
	transfer_label.autowrap_mode = TextServer.AUTOWRAP_OFF
	transfer_label.custom_minimum_size = Vector2(180, 40)
	controls.add_child(transfer_label)
	amount = SpinBox.new()
	amount.name = "OpportunityTransferMinutes"
	amount.custom_minimum_size = Vector2(100, 40)
	amount.min_value = 0
	amount.max_value = 48
	amount.step = 1
	amount.value_changed.connect(func(_value): _update())
	controls.add_child(amount)
	var reset = Button.new()
	reset.text = "RESET WORKSHEET"
	reset.custom_minimum_size.y = 40
	reset.pressed.connect(func(): amount.value = 0; donor.select(0); recipient.select(0); _update())
	controls.add_child(reset)
	result = _label("", 15)
	result.name = "OpportunityScenarioResult"
	add_child(result)
	add_child(_label(str(board.get("scope", "")), 12, DS.MUTED))
	var review = Button.new()
	review.text = "OPEN ROSTER • REVIEW THE REAL ROTATION"
	review.custom_minimum_size.y = 44
	review.pressed.connect(func(): navigate_requested.emit("ROSTER"))
	add_child(review)
	var toggle = CheckButton.new()
	toggle.text = "COMPARE PLANNED MINUTES WITH ACTUAL USAGE"
	add_child(toggle)
	var evidence = VBoxContainer.new()
	evidence.visible = false
	add_child(evidence)
	toggle.toggled.connect(func(value): evidence.visible = value)
	for row in board.get("players", []):
		evidence.add_child(_label("%s%s • plan %.1f min • actual %.1f MPG • %s appearances" % [row.name, " • YOUNG CORE" if row.young_core else "", row.planned_minutes, row.minutes_per_game, row.games], 13, DS.ACCENT if row.young_core else DS.MUTED))
	_update()

func _update() -> void:
	if result == null:
		return
	baseline.text = "SAVED ROTATION • %.1f / 240 min • %.1f min allocated to age-25-or-younger players" % [float(board.get("planned_total", 0)), float(board.get("young_core_minutes", 0))]
	result.add_theme_color_override("font_color", DS.MUTED)
	if donor.selected < 1 or recipient.selected < 1:
		result.text = "Choose two players to compare a scenario. Your saved rotation stays unchanged."
		return
	if donor.selected == recipient.selected:
		result.text = "Choose different players for the transfer."
		return
	var source: Dictionary = board.players[donor.selected - 1]
	var target: Dictionary = board.players[recipient.selected - 1]
	var transfer = float(amount.value)
	if transfer > float(source.planned_minutes) or float(target.planned_minutes) + transfer > 48:
		result.text = "This transfer exceeds the donor's available minutes or the recipient's 48-minute limit. Reduce the amount."
		result.add_theme_color_override("font_color", DS.WARNING)
		return
	var core_minutes = float(board.get("young_core_minutes", 0)) + (transfer if target.young_core else 0.0) - (transfer if source.young_core else 0.0)
	result.text = "WORKSHEET ONLY\n%s: %.1f → %.1f planned min\n%s: %.1f → %.1f planned min\nYoung core allocation: %.1f → %.1f min\nTotal stays %.1f / 240 min. Review lineup, health and role promises in Roster and Locker Room before applying your own changes." % [source.name, source.planned_minutes, float(source.planned_minutes) - transfer, target.name, target.planned_minutes, float(target.planned_minutes) + transfer, float(board.get("young_core_minutes", 0)), core_minutes, float(board.get("planned_total", 0))]
	result.add_theme_color_override("font_color", DS.ACCENT)

func _label(text: String, font_size: int, color: Color = DS.TEXT) -> Label:
	var label = Label.new()
	label.text = text
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.add_theme_font_size_override("font_size", font_size)
	label.add_theme_color_override("font_color", color)
	return label
