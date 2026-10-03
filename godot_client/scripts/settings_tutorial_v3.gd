extends Control

signal preferences_changed(preferences)
signal tutorial_finished(started_from_startup)

const SUMMARY_URL := "http://127.0.0.1:8765/v3/preferences"
const UPDATE_URL := "http://127.0.0.1:8765/v3/preferences"
const RESET_URL := "http://127.0.0.1:8765/v3/preferences/reset"
const TUTORIAL_COMPLETE_URL := "http://127.0.0.1:8765/v3/preferences/tutorial-complete"

const PANEL := Color("121824")
const PANEL_ALT := Color("171f2d")
const PANEL_HOVER := Color("202b3d")
const TEXT := Color("f7f8fb")
const MUTED := Color("8d99aa")
const ACCENT := Color("8ed8ff")
const GOOD := Color("61d69b")
const BAD := Color("ff6577")
const BORDER := Color("263247")
const TEAM_PRIMARY := Color("d9273c")
const TEAM_PRIMARY_HOVER := Color("ef4055")
const GOLD := Color("f3c96b")

var summary_request: HTTPRequest
var action_request: HTTPRequest
var preferences: Dictionary = {
	"show_tutorial_on_startup": true,
	"tutorial_completed": false,
	"confirm_load": true,
	"confirm_delete": true,
	"confirm_new_franchise": true,
	"return_home_after_save_switch": true,
}
var pending_action := ""

var status_label: Label
var tutorial_status_label: Label
var show_tutorial_toggle: CheckButton
var confirm_load_toggle: CheckButton
var confirm_delete_toggle: CheckButton
var confirm_new_franchise_toggle: CheckButton
var return_home_toggle: CheckButton
var save_button: Button
var reset_button: Button
var tutorial_overlay: Control
var tutorial_step_label: Label
var tutorial_title_label: Label
var tutorial_body_label: Label
var tutorial_back_button: Button
var tutorial_next_button: Button
var tutorial_index := 0
var tutorial_started_from_startup := false

const TUTORIAL_STEPS := [
	{
		"title": "WELCOME TO V3 FRANCHISE MODE",
		"body": "Franchise HQ is your command center. The sidebar opens every major desktop module, while all franchise-changing actions write only to the isolated V3 working save. Your validated V2 release checkpoint remains protected.",
	},
	{
		"title": "ROSTER + GAME DAY",
		"body": "ROSTER manages depth, rotation, player roles, contracts, health, morale, and development context. GAME DAY prepares and simulates your next controlled-team game while synchronizing the rest of the league calendar.",
	},
	{
		"title": "TRADES + FREE AGENCY",
		"body": "TRADES uses the production transaction and CBA legality engines for offers, Trade Finder, player packages, and draft capital. FREE AGENCY handles the live market, contract previews, and write-safe signings.",
	},
	{
		"title": "SCOUTING + SEASON",
		"body": "SCOUTING follows the upcoming draft class from season scouting through Draft Night. SEASON controls lifecycle transitions including postseason creation, offseason stages, Draft progression, and opening the next regular season.",
	},
	{
		"title": "LEAGUE + FRONT OFFICE",
		"body": "LEAGUE tracks standings, leaders, results, awards, and league context. FRONT OFFICE combines team health, chemistry, staff, financial position, competitive outlook, and long-term roster planning.",
	},
	{
		"title": "FRANCHISES + MULTI-SAVE",
		"body": "FRANCHISES protects named save slots, creates copies, switches universes, and starts clean franchises for any NBA team. Before switching, the current live session is snapshotted and recovery copies are created automatically.",
	},
	{
		"title": "SETTINGS + SAVE SAFETY",
		"body": "SETTINGS controls confirmations, startup tutorial behavior, and post-switch navigation. These desktop preferences are stored separately from franchise checkpoints. You can reopen this tutorial at any time without advancing or editing a franchise.",
	},
]


func _ready() -> void:
	_build_ui()
	_build_http()


func refresh() -> void:
	_request_summary()


func apply_preferences(next_preferences: Dictionary) -> void:
	preferences = next_preferences.duplicate(true)
	_apply_preferences_to_controls()


func _build_http() -> void:
	summary_request = HTTPRequest.new()
	summary_request.timeout = 10.0
	summary_request.request_completed.connect(_on_summary_completed)
	add_child(summary_request)

	action_request = HTTPRequest.new()
	action_request.timeout = 10.0
	action_request.request_completed.connect(_on_action_completed)
	add_child(action_request)


func _build_ui() -> void:
	var page_scroll := ScrollContainer.new()
	page_scroll.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	page_scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	page_scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	page_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	add_child(page_scroll)

	var outer := MarginContainer.new()
	outer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_set_margins(outer, 30, 26, 30, 30)
	page_scroll.add_child(outer)

	var column := VBoxContainer.new()
	column.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	column.add_theme_constant_override("separation", 16)
	outer.add_child(column)

	var header := HBoxContainer.new()
	header.add_theme_constant_override("separation", 12)
	column.add_child(header)

	var titles := VBoxContainer.new()
	titles.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	header.add_child(titles)
	titles.add_child(_small_label("DESKTOP EXPERIENCE • SETTINGS + HELP", TEAM_PRIMARY_HOVER))
	var title := Label.new()
	title.text = "SETTINGS"
	title.add_theme_color_override("font_color", TEXT)
	title.add_theme_font_size_override("font_size", 31)
	titles.add_child(title)
	var subtitle := Label.new()
	subtitle.text = "Configure V3 desktop behavior and reopen the guided franchise tutorial at any time. These preferences are stored separately from every franchise save."
	subtitle.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	subtitle.add_theme_color_override("font_color", MUTED)
	subtitle.add_theme_font_size_override("font_size", 12)
	titles.add_child(subtitle)

	var refresh_button := _action_button("REFRESH", false)
	refresh_button.pressed.connect(_request_summary)
	header.add_child(refresh_button)

	var status_card := _card(Vector2(0, 58))
	var status_body := _card_body(status_card, 12)
	status_label = Label.new()
	status_label.text = "Loading V3 desktop preferences..."
	status_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	status_label.add_theme_color_override("font_color", MUTED)
	status_label.add_theme_font_size_override("font_size", 11)
	status_body.add_child(status_label)
	column.add_child(status_card)

	var content := HBoxContainer.new()
	content.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	content.add_theme_constant_override("separation", 14)
	column.add_child(content)

	var preferences_card := _card(Vector2(0, 520))
	preferences_card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var pref_body := _card_body(preferences_card, 18)
	pref_body.add_child(_small_label("DESKTOP PREFERENCES", ACCENT))
	pref_body.add_child(_section_title("CONFIRMATIONS + NAVIGATION"))

	show_tutorial_toggle = _setting_toggle(
		"SHOW TUTORIAL ON STARTUP",
		"Open the guided V3 tutorial automatically when the desktop client starts."
	)
	pref_body.add_child(show_tutorial_toggle)
	pref_body.add_child(_divider())

	confirm_new_franchise_toggle = _setting_toggle(
		"CONFIRM NEW FRANCHISE",
		"Require a confirmation before a clean certified franchise universe is created and activated."
	)
	pref_body.add_child(confirm_new_franchise_toggle)
	pref_body.add_child(_divider())

	confirm_load_toggle = _setting_toggle(
		"CONFIRM SAVE SWITCH",
		"Require a confirmation before loading a different named franchise save."
	)
	pref_body.add_child(confirm_load_toggle)
	pref_body.add_child(_divider())

	confirm_delete_toggle = _setting_toggle(
		"CONFIRM SAVE DELETE",
		"Require a confirmation before deleting a non-active franchise slot. Active saves remain protected."
	)
	pref_body.add_child(confirm_delete_toggle)
	pref_body.add_child(_divider())

	return_home_toggle = _setting_toggle(
		"RETURN HOME AFTER SAVE SWITCH",
		"After loading or creating a franchise, open Franchise HQ immediately. Turn this off to remain on the Franchises page."
	)
	pref_body.add_child(return_home_toggle)

	var pref_spacer := Control.new()
	pref_spacer.size_flags_vertical = Control.SIZE_EXPAND_FILL
	pref_body.add_child(pref_spacer)

	var actions := HBoxContainer.new()
	actions.add_theme_constant_override("separation", 10)
	save_button = _action_button("SAVE SETTINGS", true)
	save_button.pressed.connect(_save_settings)
	actions.add_child(save_button)
	reset_button = _action_button("RESET SAFE DEFAULTS", false)
	reset_button.pressed.connect(_reset_settings)
	actions.add_child(reset_button)
	pref_body.add_child(actions)

	var storage_note := Label.new()
	storage_note.text = "Desktop preferences never edit simulation state, named franchise checkpoints, or the protected V2 release."
	storage_note.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	storage_note.add_theme_color_override("font_color", MUTED)
	storage_note.add_theme_font_size_override("font_size", 10)
	pref_body.add_child(storage_note)
	content.add_child(preferences_card)

	var tutorial_card := _card(Vector2(380, 520))
	tutorial_card.custom_minimum_size = Vector2(380, 520)
	var tutorial_body := _card_body(tutorial_card, 18)
	tutorial_body.add_child(_small_label("GUIDED HELP", GOLD))
	tutorial_body.add_child(_section_title("V3 FRANCHISE TUTORIAL"))

	var tutorial_text := Label.new()
	tutorial_text.text = "A seven-step walkthrough covers Franchise HQ, Game Day, roster management, trades, free agency, scouting, season progression, league intelligence, Front Office tools, multi-save franchises, and V3 save safety."
	tutorial_text.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	tutorial_text.add_theme_color_override("font_color", TEXT)
	tutorial_text.add_theme_font_size_override("font_size", 12)
	tutorial_body.add_child(tutorial_text)

	var tutorial_safety := Label.new()
	tutorial_safety.text = "You can reopen the walkthrough at any time. Running the tutorial does not advance the season or change a franchise save."
	tutorial_safety.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	tutorial_safety.add_theme_color_override("font_color", MUTED)
	tutorial_safety.add_theme_font_size_override("font_size", 10)
	tutorial_body.add_child(tutorial_safety)

	var tutorial_spacer := Control.new()
	tutorial_spacer.size_flags_vertical = Control.SIZE_EXPAND_FILL
	tutorial_body.add_child(tutorial_spacer)

	tutorial_status_label = Label.new()
	tutorial_status_label.text = "Tutorial status: loading..."
	tutorial_status_label.add_theme_color_override("font_color", MUTED)
	tutorial_status_label.add_theme_font_size_override("font_size", 11)
	tutorial_body.add_child(tutorial_status_label)

	var start_tutorial := _action_button("START TUTORIAL", true)
	start_tutorial.pressed.connect(_request_tutorial)
	tutorial_body.add_child(start_tutorial)
	content.add_child(tutorial_card)

	_apply_preferences_to_controls()


func _setting_toggle(title_text: String, detail_text: String) -> CheckButton:
	var toggle := CheckButton.new()
	toggle.text = "%s\n%s" % [title_text, detail_text]
	toggle.custom_minimum_size = Vector2(0, 68)
	toggle.add_theme_color_override("font_color", TEXT)
	toggle.add_theme_color_override("font_hover_color", TEXT)
	toggle.add_theme_color_override("font_pressed_color", TEXT)
	toggle.add_theme_font_size_override("font_size", 11)
	return toggle


func _request_summary() -> void:
	if summary_request == null or summary_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	status_label.text = "Reading desktop preferences..."
	status_label.add_theme_color_override("font_color", ACCENT)
	var error := summary_request.request(SUMMARY_URL)
	if error != OK:
		status_label.text = "Could not start desktop-preferences request."
		status_label.add_theme_color_override("font_color", BAD)


func _on_summary_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	if result != HTTPRequest.RESULT_SUCCESS or response_code != 200 or body.is_empty():
		status_label.text = "Desktop preferences are unavailable. Safe confirmation defaults remain active."
		status_label.add_theme_color_override("font_color", GOLD)
		return
	var parsed = JSON.parse_string(body.get_string_from_utf8())
	if typeof(parsed) != TYPE_DICTIONARY or parsed.has("error"):
		status_label.text = "Desktop preferences returned an invalid response. Safe defaults remain active."
		status_label.add_theme_color_override("font_color", GOLD)
		return
	var parsed_preferences = parsed.get("preferences", {})
	if typeof(parsed_preferences) == TYPE_DICTIONARY:
		preferences = parsed_preferences.duplicate(true)
	_apply_preferences_to_controls()
	status_label.text = "DESKTOP SETTINGS READY • preferences are isolated from franchise saves and protected V2."
	status_label.add_theme_color_override("font_color", GOOD)
	preferences_changed.emit(preferences.duplicate(true))


func _apply_preferences_to_controls() -> void:
	if show_tutorial_toggle == null:
		return
	show_tutorial_toggle.button_pressed = bool(preferences.get("show_tutorial_on_startup", true))
	confirm_load_toggle.button_pressed = bool(preferences.get("confirm_load", true))
	confirm_delete_toggle.button_pressed = bool(preferences.get("confirm_delete", true))
	confirm_new_franchise_toggle.button_pressed = bool(preferences.get("confirm_new_franchise", true))
	return_home_toggle.button_pressed = bool(preferences.get("return_home_after_save_switch", true))
	if tutorial_status_label != null:
		tutorial_status_label.text = (
			"Tutorial status: COMPLETED • reopen anytime below."
			if bool(preferences.get("tutorial_completed", false))
			else "Tutorial status: NOT COMPLETED • first-launch guidance is available."
		)
		tutorial_status_label.add_theme_color_override(
			"font_color",
			GOOD if bool(preferences.get("tutorial_completed", false)) else GOLD
		)


func _settings_body() -> Dictionary:
	return {
		"show_tutorial_on_startup": show_tutorial_toggle.button_pressed,
		"confirm_load": confirm_load_toggle.button_pressed,
		"confirm_delete": confirm_delete_toggle.button_pressed,
		"confirm_new_franchise": confirm_new_franchise_toggle.button_pressed,
		"return_home_after_save_switch": return_home_toggle.button_pressed,
	}


func _save_settings() -> void:
	_post_action("save", UPDATE_URL, _settings_body())


func _reset_settings() -> void:
	_post_action("reset", RESET_URL, {})


func _request_tutorial() -> void:
	start_tutorial(false)


func start_tutorial(from_startup: bool = false) -> void:
	_close_tutorial_overlay()
	tutorial_started_from_startup = from_startup
	tutorial_index = 0

	tutorial_overlay = Control.new()
	tutorial_overlay.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	tutorial_overlay.mouse_filter = Control.MOUSE_FILTER_STOP
	add_child(tutorial_overlay)
	tutorial_overlay.move_to_front()

	var dim := ColorRect.new()
	dim.color = Color(0, 0, 0, 0.78)
	dim.mouse_filter = Control.MOUSE_FILTER_STOP
	tutorial_overlay.add_child(dim)
	dim.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)

	var center := CenterContainer.new()
	center.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	center.mouse_filter = Control.MOUSE_FILTER_PASS
	tutorial_overlay.add_child(center)

	var card := _card(Vector2(760, 500))
	card.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	card.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	center.add_child(card)

	var body := _card_body(card, 24)
	body.add_theme_constant_override("separation", 16)

	var header := HBoxContainer.new()
	body.add_child(header)
	var header_text := VBoxContainer.new()
	header_text.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	header.add_child(header_text)
	header_text.add_child(_small_label("V3 DESKTOP • GUIDED FRANCHISE TOUR", TEAM_PRIMARY_HOVER))
	tutorial_step_label = Label.new()
	tutorial_step_label.add_theme_color_override("font_color", MUTED)
	tutorial_step_label.add_theme_font_size_override("font_size", 11)
	header_text.add_child(tutorial_step_label)

	var skip_button := _action_button("SKIP TUTORIAL", false)
	skip_button.pressed.connect(_finish_tutorial)
	header.add_child(skip_button)

	var divider := _divider()
	body.add_child(divider)

	tutorial_title_label = Label.new()
	tutorial_title_label.add_theme_color_override("font_color", TEXT)
	tutorial_title_label.add_theme_font_size_override("font_size", 26)
	tutorial_title_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	body.add_child(tutorial_title_label)

	tutorial_body_label = Label.new()
	tutorial_body_label.size_flags_vertical = Control.SIZE_EXPAND_FILL
	tutorial_body_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	tutorial_body_label.add_theme_color_override("font_color", TEXT)
	tutorial_body_label.add_theme_font_size_override("font_size", 14)
	body.add_child(tutorial_body_label)

	var safety := Label.new()
	safety.text = "GUIDED HELP ONLY • This walkthrough never simulates games or edits franchise state."
	safety.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	safety.add_theme_color_override("font_color", GOOD)
	safety.add_theme_font_size_override("font_size", 10)
	body.add_child(safety)

	var buttons := HBoxContainer.new()
	buttons.add_theme_constant_override("separation", 10)
	body.add_child(buttons)
	tutorial_back_button = _action_button("BACK", false)
	tutorial_back_button.pressed.connect(_tutorial_back)
	buttons.add_child(tutorial_back_button)
	var button_spacer := Control.new()
	button_spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	buttons.add_child(button_spacer)
	tutorial_next_button = _action_button("NEXT", true)
	tutorial_next_button.pressed.connect(_tutorial_next)
	buttons.add_child(tutorial_next_button)

	_render_tutorial_step()


func _render_tutorial_step() -> void:
	if tutorial_overlay == null or not is_instance_valid(tutorial_overlay):
		return
	var total := TUTORIAL_STEPS.size()
	if total <= 0:
		return
	tutorial_index = clampi(tutorial_index, 0, total - 1)
	var step: Dictionary = TUTORIAL_STEPS[tutorial_index]
	tutorial_step_label.text = "STEP %s OF %s" % [tutorial_index + 1, total]
	tutorial_title_label.text = str(step.get("title", "V3 TUTORIAL"))
	tutorial_body_label.text = str(step.get("body", ""))
	tutorial_back_button.disabled = tutorial_index <= 0
	tutorial_next_button.text = "FINISH" if tutorial_index == total - 1 else "NEXT"


func _tutorial_back() -> void:
	if tutorial_index > 0:
		tutorial_index -= 1
		_render_tutorial_step()


func _tutorial_next() -> void:
	if tutorial_index >= TUTORIAL_STEPS.size() - 1:
		_finish_tutorial()
		return
	tutorial_index += 1
	_render_tutorial_step()


func _finish_tutorial() -> void:
	_close_tutorial_overlay()
	_post_action("tutorial_complete", TUTORIAL_COMPLETE_URL, {})


func _close_tutorial_overlay() -> void:
	if tutorial_overlay != null and is_instance_valid(tutorial_overlay):
		tutorial_overlay.queue_free()
	tutorial_overlay = null
	tutorial_step_label = null
	tutorial_title_label = null
	tutorial_body_label = null
	tutorial_back_button = null
	tutorial_next_button = null


func _post_action(action: String, url: String, body: Dictionary) -> void:
	if action_request == null or pending_action != "":
		return
	if action_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	pending_action = action
	status_label.text = "Saving desktop %s..." % action
	status_label.add_theme_color_override("font_color", ACCENT)
	save_button.disabled = true
	reset_button.disabled = true
	var headers := PackedStringArray(["Content-Type: application/json"])
	var error := action_request.request(url, headers, HTTPClient.METHOD_POST, JSON.stringify(body))
	if error != OK:
		pending_action = ""
		save_button.disabled = false
		reset_button.disabled = false
		status_label.text = "Could not start desktop-preferences write."
		status_label.add_theme_color_override("font_color", BAD)


func _on_action_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	var completed_action := pending_action
	pending_action = ""
	save_button.disabled = false
	reset_button.disabled = false
	if result != HTTPRequest.RESULT_SUCCESS or body.is_empty():
		status_label.text = "Desktop-preferences write failed before a valid bridge response was received."
		status_label.add_theme_color_override("font_color", BAD)
		return
	var parsed = JSON.parse_string(body.get_string_from_utf8())
	if response_code != 200 or typeof(parsed) != TYPE_DICTIONARY or parsed.has("error"):
		status_label.text = str(parsed.get("detail", parsed.get("error", "Desktop-preferences write was blocked."))) if typeof(parsed) == TYPE_DICTIONARY else "Desktop-preferences write returned invalid JSON."
		status_label.add_theme_color_override("font_color", BAD)
		return
	var parsed_preferences = parsed.get("preferences", {})
	if typeof(parsed_preferences) == TYPE_DICTIONARY:
		preferences = parsed_preferences.duplicate(true)
	_apply_preferences_to_controls()
	status_label.text = "DESKTOP %s SAVED • no franchise checkpoint was modified." % completed_action.to_upper()
	status_label.add_theme_color_override("font_color", GOOD)
	preferences_changed.emit(preferences.duplicate(true))
	if completed_action == "tutorial_complete":
		tutorial_finished.emit(tutorial_started_from_startup)
		tutorial_started_from_startup = false


func _action_button(text_value: String, primary: bool = false) -> Button:
	var button := Button.new()
	button.custom_minimum_size = Vector2(0, 42)
	button.text = text_value
	button.add_theme_font_size_override("font_size", 10)
	button.add_theme_color_override("font_color", TEXT)
	button.add_theme_color_override("font_hover_color", TEXT)
	var normal := TEAM_PRIMARY if primary else PANEL_ALT
	var hover := TEAM_PRIMARY_HOVER if primary else PANEL_HOVER
	button.add_theme_stylebox_override("normal", _box(normal, 9, normal if primary else BORDER))
	button.add_theme_stylebox_override("hover", _box(hover, 9, hover if primary else ACCENT))
	button.add_theme_stylebox_override("pressed", _box(hover, 9, hover))
	return button


func _small_label(text_value: String, color: Color) -> Label:
	var label := Label.new()
	label.text = text_value
	label.add_theme_color_override("font_color", color)
	label.add_theme_font_size_override("font_size", 9)
	return label


func _section_title(text_value: String) -> Label:
	var label := Label.new()
	label.text = text_value
	label.add_theme_color_override("font_color", TEXT)
	label.add_theme_font_size_override("font_size", 17)
	return label


func _card(minimum: Vector2) -> PanelContainer:
	var card := PanelContainer.new()
	card.custom_minimum_size = minimum
	card.add_theme_stylebox_override("panel", _box(PANEL, 12, BORDER))
	return card


func _card_body(card: PanelContainer, pad: int) -> VBoxContainer:
	var margin := MarginContainer.new()
	_set_margins(margin, pad, pad, pad, pad)
	card.add_child(margin)
	var body := VBoxContainer.new()
	body.add_theme_constant_override("separation", 10)
	margin.add_child(body)
	return body


func _divider() -> HSeparator:
	var line := HSeparator.new()
	line.modulate = Color(1, 1, 1, 0.12)
	return line


func _box(color: Color, radius: int, border_color: Color = Color.TRANSPARENT) -> StyleBoxFlat:
	var box := StyleBoxFlat.new()
	box.bg_color = color
	box.corner_radius_top_left = radius
	box.corner_radius_top_right = radius
	box.corner_radius_bottom_left = radius
	box.corner_radius_bottom_right = radius
	if border_color != Color.TRANSPARENT:
		box.border_width_left = 1
		box.border_width_top = 1
		box.border_width_right = 1
		box.border_width_bottom = 1
		box.border_color = border_color
	return box


func _set_margins(container: MarginContainer, left: int, top: int, right: int, bottom: int) -> void:
	container.add_theme_constant_override("margin_left", left)
	container.add_theme_constant_override("margin_top", top)
	container.add_theme_constant_override("margin_right", right)
	container.add_theme_constant_override("margin_bottom", bottom)
