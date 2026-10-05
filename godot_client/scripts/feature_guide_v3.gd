extends VBoxContainer
const DS = preload("res://scripts/design_system_v3.gd")
const PREFS = "user://feature_guides_v1.cfg"
signal navigate_requested(page: String)
const GUIDES = {
	"DEVELOPMENT": [
		["BUILD YOUR CORE", "Start with a young player you want to build around. Compare current skills and potential in Rebuild HQ; potential is a runway, not a guaranteed outcome."],
		["GIVE GROWTH A PLAN", "Choose up to three players below. Pick a skill target or playing opportunity, then review the plan. Confirm only when you're ready: goals stay fixed for the season and do not grant ratings."],
		["TURN THE PLAN INTO OPPORTUNITY", "Use Roster to review minutes and roles. Opportunity goals need at least ten appearances. During offseason, Training Camp and mentoring provide another development path."],
		["FOLLOW THE PLAYER ARC", "Return after games to compare actual progress. Review career histories for prior growth; a current target can fall below its threshold again. Training Camp is inside Offseason.", "OFFSEASON", "EXPLORE TRAINING CAMP"]
	],
	"ROSTER": [
		["BUILD A ROLE BEFORE A TRADE", "Inspect player profiles and your depth chart. Decide which young players deserve a path to minutes before shopping for replacements."],
		["MAKE THE ROTATION FIT", "Review five starters and 240 planned minutes. Changing a development opportunity goal does not change the rotation for you."],
		["CONNECT MINUTES TO EXPECTATIONS", "Player expectations and the minutes you actually give them affect morale. Review the Locker Room before promising a bigger role.", "LOCKER ROOM", "REVIEW PLAYER ROLES"]
	],
	"LOCKER ROOM": [
		["LISTEN BEFORE PROMISING", "Select a player and compare morale, role satisfaction, expectations and recent usage. The dialogue represents this simulation's context."],
		["PREVIEW THE CONVERSATION", "Choose a meeting response or a role promise, then inspect the consequence preview. Confirming saves the action; cooldowns prevent repeated reassurance."],
		["FOLLOW THROUGH ON COURT", "A role promise changes expectations, not the rotation. Keep the promised minutes and starts during its review window; missed promises leave memory.", "ROSTER", "REVIEW THE ROTATION"]
	],
	"SCOUTING": [
		["SCOUT BEFORE YOU NEED THE PICK", "Start with your draft capital and the roster's future needs. Confidence is earned through scouting, not by opening a prospect card."],
		["NARROW YOUR BOARD", "Compare prospects, assign focus where available and complete scouting weeks. Revisit dossiers as evidence improves instead of treating early projections as certainty."],
		["DRAFT INTO A DEVELOPMENT PATH", "Think about where a prospect will play and who can mentor them. A promising pick needs an opportunity after Draft Night.", "DEVELOPMENT", "PLAN PLAYER DEVELOPMENT"]
	],
	"TRADES": [
		["NAME THE PROBLEM FIRST", "Choose a roster need: position depth, an age timeline or flexibility. Compare an internal development solution before moving a player."],
		["COMPARE THE WHOLE RETURN", "Consider contracts, draft capital and player roles alongside ratings. Use the transaction preview to review legality and effects before executing."],
		["REBUILD THE PLAN AFTER A DEAL", "A new roster changes the opportunity available to your core. Review your rotation and expectations after a committed trade.", "ROSTER", "REVIEW ROSTER FIT"]
	],
	"FREE AGENCY": [
		["SIGN FOR A PURPOSE", "Identify the role you need and how long you need it. Protect minutes for the players you're developing."],
		["REVIEW THE CONTRACT", "Compare market options, cap space and roster limits. Preview a signing before confirming; opening the market does not sign anyone."],
		["MAKE ROOM FOR THE PLAYER", "After a signing, review depth and minutes. A contract alone doesn't give a player a useful role.", "ROSTER", "REVIEW THE DEPTH CHART"]
	],
	"GAME DAY": [
		["PREPARE THE TEAM YOU BUILT", "Review the opponent, availability and coaching information before advancing. Look for what your developing players can contribute."],
		["SIMULATE WITH INTENT", "Simulation advances the franchise. Review the matchup and rotation first; the result comes from the production engine."],
		["LEARN FROM THE RESULT", "Review the box score and development progress after games. Theater presents recorded postgame chapters; it is not a live possession replay.", "DEVELOPMENT", "CHECK DEVELOPMENT PROGRESS"]
	],
	"OFFSEASON": [
		["START WITH THE PLAYERS YOU HAVE", "Review the young core and last season before addressing the market. The offseason hub connects the available phases."],
		["USE CAMP AND MENTORING", "When Training Camp is available, review focused skill slots and eligible mentors. Preview gains and cost before committing; camp is limited to once per offseason."],
		["BUILD THE NEXT SEASON'S PLAN", "Connect draft picks and acquisitions to real roster roles, then set development goals when that window opens.", "DEVELOPMENT", "OPEN DEVELOPMENT"]
	]
}
var page_name = ""
var step = 0
var expanded = false
var preferences = ConfigFile.new()
var preferences_path = PREFS
var detail: VBoxContainer

func _ready() -> void:
	name = "FeatureGuideRail"
	preferences.load(preferences_path)
	add_theme_constant_override("separation", 6)

func show_page(value: String) -> void:
	page_name = value
	step = 0
	expanded = false
	visible = GUIDES.has(value)
	_render()

func _render() -> void:
	for child in get_children():
		remove_child(child)
		child.queue_free()
	if not GUIDES.has(page_name):
		return
	var header = HBoxContainer.new()
	add_child(header)
	var title = Label.new()
	title.text = "BUILD YOUR CORE FIRST" if page_name == "DEVELOPMENT" else "YOUR %s PLAYBOOK" % page_name
	title.add_theme_font_size_override("font_size", 14)
	title.add_theme_color_override("font_color", DS.GOLD)
	title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	header.add_child(title)
	var toggle = Button.new()
	toggle.name = "FeatureGuideToggle"
	toggle.text = "CLOSE GUIDE" if expanded else ("REOPEN GUIDE" if preferences.get_value("read", page_name, false) else "START HERE • QUICK GUIDE")
	toggle.custom_minimum_size.y = 36
	toggle.pressed.connect(func(): expanded = not expanded; _render())
	header.add_child(toggle)
	if not expanded:
		return
	detail = VBoxContainer.new()
	detail.name = "FeatureGuideDetails"
	detail.add_theme_constant_override("separation", 8)
	add_child(detail)
	var entry: Array = GUIDES[page_name][step]
	var heading = Label.new()
	heading.text = "%s / %s • %s" % [step + 1, GUIDES[page_name].size(), entry[0]]
	heading.add_theme_font_size_override("font_size", 18)
	heading.add_theme_color_override("font_color", DS.TEXT)
	detail.add_child(heading)
	var copy = Label.new()
	copy.text = entry[1]
	copy.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	copy.add_theme_font_size_override("font_size", 14)
	copy.add_theme_color_override("font_color", DS.MUTED)
	detail.add_child(copy)
	var controls = HBoxContainer.new()
	detail.add_child(controls)
	var back = Button.new()
	back.text = "BACK"
	back.disabled = step == 0
	back.pressed.connect(func(): step -= 1; _render())
	controls.add_child(back)
	var next = Button.new()
	next.name = "FeatureGuideNext"
	next.text = "GOT IT • USE THIS PAGE" if step == GUIDES[page_name].size() - 1 else "NEXT"
	next.pressed.connect(_next)
	controls.add_child(next)
	if entry.size() == 4:
		var action = Button.new()
		action.text = entry[3]
		action.pressed.connect(func(): navigate_requested.emit(entry[2]))
		controls.add_child(action)

func _next() -> void:
	if step < GUIDES[page_name].size() - 1:
		step += 1
	else:
		expanded = false
		preferences.set_value("read", page_name, true)
		preferences.save(preferences_path)
	_render()
