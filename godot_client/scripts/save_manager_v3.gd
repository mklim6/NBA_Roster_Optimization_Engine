extends Control

signal active_save_changed

const SUMMARY_URL := "http://127.0.0.1:8765/v3/saves"
const BOOTSTRAP_URL := "http://127.0.0.1:8765/v3/saves/bootstrap"
const SAVE_CURRENT_URL := "http://127.0.0.1:8765/v3/saves/save-current"
const CREATE_URL := "http://127.0.0.1:8765/v3/saves/create"
const NEW_FRANCHISE_URL := "http://127.0.0.1:8765/v3/saves/new-franchise"
const RENAME_URL := "http://127.0.0.1:8765/v3/saves/rename"
const LOAD_URL := "http://127.0.0.1:8765/v3/saves/load"
const DELETE_URL := "http://127.0.0.1:8765/v3/saves/delete"

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
var payload: Dictionary = {}
var selected_slot_id := ""
var pending_action := ""
var pending_confirm_action := ""
var rename_mode := false
var new_franchise_mode := false
var pending_new_franchise_body: Dictionary = {}
var desktop_preferences: Dictionary = {
	"confirm_load": true,
	"confirm_delete": true,
	"confirm_new_franchise": true,
	"return_home_after_save_switch": true,
}

var status_label: Label
var active_slot_value: Label
var save_count_value: Label
var franchise_value: Label
var season_value: Label
var slots_box: VBoxContainer
var selected_title: Label
var selected_detail: Label
var name_label: Label
var name_input: LineEdit
var name_help: Label
var team_label: Label
var team_selector: OptionButton
var bootstrap_button: Button
var new_franchise_button: Button
var create_franchise_button: Button
var save_current_button: Button
var create_button: Button
var rename_button: Button
var load_button: Button
var delete_button: Button
var confirm_dialog: ConfirmationDialog


func _ready() -> void:
	_build_ui()
	_build_http()


func refresh() -> void:
	_request_summary()


func apply_preferences(next_preferences: Dictionary) -> void:
	desktop_preferences = next_preferences.duplicate(true)


func _build_http() -> void:
	summary_request = HTTPRequest.new()
	summary_request.timeout = 30.0
	summary_request.request_completed.connect(_on_summary_completed)
	add_child(summary_request)

	action_request = HTTPRequest.new()
	action_request.timeout = 180.0
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
	_set_margins(outer, 28, 24, 28, 28)
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
	titles.add_child(_small_label("FRANCHISE OPERATIONS • SAVE CONTROL", TEAM_PRIMARY_HOVER))
	var title := Label.new()
	title.text = "FRANCHISES"
	title.add_theme_color_override("font_color", TEXT)
	title.add_theme_font_size_override("font_size", 31)
	titles.add_child(title)
	var subtitle := Label.new()
	subtitle.text = "Protect, copy, rename, and switch isolated V3 franchise saves without touching the validated V2 checkpoint."
	subtitle.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	subtitle.add_theme_color_override("font_color", MUTED)
	subtitle.add_theme_font_size_override("font_size", 12)
	titles.add_child(subtitle)

	var refresh_button := _action_button("REFRESH", false)
	refresh_button.pressed.connect(_request_summary)
	header.add_child(refresh_button)

	var safety := _card(Vector2(0, 58))
	var safety_body := _card_body(safety, 12)
	status_label = Label.new()
	status_label.text = "Open Franchise Saves to read the current V3 working session."
	status_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	status_label.add_theme_color_override("font_color", MUTED)
	status_label.add_theme_font_size_override("font_size", 11)
	safety_body.add_child(status_label)
	column.add_child(safety)

	var metrics := HBoxContainer.new()
	metrics.add_theme_constant_override("separation", 10)
	column.add_child(metrics)
	active_slot_value = _metric(metrics, "ACTIVE SAVE", "--")
	save_count_value = _metric(metrics, "SAVE SLOTS", "--")
	franchise_value = _metric(metrics, "FRANCHISE", "--")
	season_value = _metric(metrics, "SEASON", "--")

	var content := HBoxContainer.new()
	content.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	content.size_flags_vertical = Control.SIZE_EXPAND_FILL
	content.add_theme_constant_override("separation", 14)
	column.add_child(content)

	var list_card := _card(Vector2(0, 600))
	list_card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	list_card.size_flags_vertical = Control.SIZE_EXPAND_FILL
	var list_body := _card_body(list_card, 16)
	list_body.add_child(_small_label("MULTI-SAVE LIBRARY", ACCENT))
	list_body.add_child(_section_title("FRANCHISE SAVES"))
	var list_help := Label.new()
	list_help.text = "The active V3 working checkpoint remains the live session. Loading another slot snapshots the current session first, then switches the working checkpoint atomically."
	list_help.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	list_help.add_theme_color_override("font_color", MUTED)
	list_help.add_theme_font_size_override("font_size", 10)
	list_body.add_child(list_help)

	var list_scroll := ScrollContainer.new()
	list_scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	list_scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	list_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	list_body.add_child(list_scroll)
	slots_box = VBoxContainer.new()
	slots_box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	slots_box.add_theme_constant_override("separation", 7)
	list_scroll.add_child(slots_box)
	content.add_child(list_card)

	var actions_card := _card(Vector2(370, 600))
	actions_card.custom_minimum_size = Vector2(370, 600)
	var actions_body := _card_body(actions_card, 16)
	actions_body.add_child(_small_label("WRITE-SAFE SAVE OPERATIONS", GOLD))
	selected_title = _section_title("SELECT A SAVE")
	actions_body.add_child(selected_title)
	selected_detail = Label.new()
	selected_detail.text = "Choose a save slot to view its actions."
	selected_detail.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	selected_detail.add_theme_color_override("font_color", MUTED)
	selected_detail.add_theme_font_size_override("font_size", 10)
	selected_detail.custom_minimum_size = Vector2(0, 92)
	actions_body.add_child(selected_detail)

	name_label = _small_label("SAVE NAME / COPY NAME", ACCENT)
	actions_body.add_child(name_label)
	name_input = LineEdit.new()
	name_input.placeholder_text = "Enter franchise save name"
	name_input.max_length = 48
	name_input.custom_minimum_size = Vector2(0, 40)
	name_input.add_theme_color_override("font_color", TEXT)
	name_input.add_theme_color_override("font_placeholder_color", MUTED)
	name_input.add_theme_stylebox_override("normal", _box(PANEL_ALT, 8, BORDER))
	name_input.add_theme_stylebox_override("focus", _box(PANEL_ALT, 8, ACCENT))
	name_input.text_submitted.connect(_on_name_submitted)
	actions_body.add_child(name_input)

	name_help = Label.new()
	name_help.text = "For a copy, type the new name and choose CREATE COPY. For a rename, choose RENAME SELECTED, edit the highlighted field, then choose APPLY RENAME."
	name_help.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	name_help.add_theme_color_override("font_color", MUTED)
	name_help.add_theme_font_size_override("font_size", 9)
	actions_body.add_child(name_help)

	team_label = _small_label("NEW FRANCHISE TEAM", ACCENT)
	team_label.visible = false
	actions_body.add_child(team_label)
	team_selector = OptionButton.new()
	team_selector.custom_minimum_size = Vector2(0, 42)
	team_selector.visible = false
	team_selector.add_theme_color_override("font_color", TEXT)
	team_selector.add_theme_font_size_override("font_size", 11)
	team_selector.add_theme_stylebox_override("normal", _box(PANEL_ALT, 8, BORDER))
	team_selector.item_selected.connect(_on_new_franchise_team_selected)
	actions_body.add_child(team_selector)

	bootstrap_button = _action_button("PROTECT CURRENT FRANCHISE", true)
	bootstrap_button.pressed.connect(_bootstrap)
	actions_body.add_child(bootstrap_button)

	new_franchise_button = _action_button("NEW FRANCHISE", false)
	new_franchise_button.pressed.connect(_toggle_new_franchise_mode)
	actions_body.add_child(new_franchise_button)

	create_franchise_button = _action_button("CREATE FRANCHISE", true)
	create_franchise_button.pressed.connect(_confirm_new_franchise)
	create_franchise_button.visible = false
	actions_body.add_child(create_franchise_button)

	save_current_button = _action_button("SAVE CURRENT", true)
	save_current_button.pressed.connect(_save_current)
	actions_body.add_child(save_current_button)

	create_button = _action_button("CREATE COPY", false)
	create_button.pressed.connect(_create_copy)
	actions_body.add_child(create_button)

	rename_button = _action_button("RENAME SELECTED", false)
	rename_button.pressed.connect(_rename_selected)
	actions_body.add_child(rename_button)

	load_button = _action_button("LOAD SELECTED", true)
	load_button.pressed.connect(_confirm_load)
	actions_body.add_child(load_button)

	delete_button = _action_button("DELETE SELECTED", false)
	delete_button.pressed.connect(_confirm_delete)
	actions_body.add_child(delete_button)

	var spacer := Control.new()
	spacer.size_flags_vertical = Control.SIZE_EXPAND_FILL
	actions_body.add_child(spacer)
	var safety_note := Label.new()
	safety_note.text = "V2 remains read-only. Load operations create a recovery copy of the live V3 working save and verify the selected slot before activation. The active slot cannot be deleted."
	safety_note.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	safety_note.add_theme_color_override("font_color", MUTED)
	safety_note.add_theme_font_size_override("font_size", 10)
	actions_body.add_child(safety_note)
	content.add_child(actions_card)

	confirm_dialog = ConfirmationDialog.new()
	confirm_dialog.title = "Confirm franchise save action"
	confirm_dialog.confirmed.connect(_on_confirmed)
	add_child(confirm_dialog)
	var confirm_label := confirm_dialog.get_label()
	confirm_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	confirm_label.custom_minimum_size = Vector2(520, 120)
	confirm_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL

	_update_controls()


func _request_summary() -> void:
	if summary_request == null or summary_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	status_label.text = "Reading the isolated V3 Save Manager..."
	status_label.add_theme_color_override("font_color", ACCENT)
	var error := summary_request.request(SUMMARY_URL)
	if error != OK:
		status_label.text = "Could not start Save Manager request."
		status_label.add_theme_color_override("font_color", BAD)


func _on_summary_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	if result != HTTPRequest.RESULT_SUCCESS or body.is_empty():
		status_label.text = "Save Manager is unavailable. Make sure the V3 Python bridge is running."
		status_label.add_theme_color_override("font_color", BAD)
		return
	var parsed = JSON.parse_string(body.get_string_from_utf8())
	if response_code != 200 or typeof(parsed) != TYPE_DICTIONARY:
		status_label.text = "Save Manager returned an invalid response."
		status_label.add_theme_color_override("font_color", BAD)
		return
	if parsed.has("error"):
		status_label.text = str(parsed.get("detail", parsed.get("error", "Save Manager failed.")))
		status_label.add_theme_color_override("font_color", BAD)
		return
	payload = parsed
	_render_summary()


func _render_summary() -> void:
	var initialized: bool = bool(payload.get("initialized", false))
	var slots: Array = payload.get("slots", [])
	var active_id: String = str(payload.get("active_slot_id", ""))
	if selected_slot_id.is_empty() or not _slot_exists(selected_slot_id):
		selected_slot_id = active_id

	_clear_children(slots_box)
	if not initialized:
		slots_box.add_child(_small_label("No multi-save library yet. Protect the current V3 franchise to create Slot 1.", MUTED))
	else:
		for raw_slot in slots:
			if typeof(raw_slot) == TYPE_DICTIONARY:
				slots_box.add_child(_slot_row(raw_slot))

	var active_slot: Dictionary = _slot_by_id(active_id)
	active_slot_value.text = str(active_slot.get("name", "NOT INITIALIZED")) if initialized else "NOT INITIALIZED"
	save_count_value.text = str(int(payload.get("slot_count", 0)))
	franchise_value.text = str(active_slot.get("team", "--")) if initialized else "--"
	season_value.text = str(active_slot.get("season", "--")) if initialized else "--"

	if not bool(payload.get("working_save_unchanged", true)) or not bool(payload.get("active_v2_unchanged", true)):
		status_label.text = "SAFETY FAILURE • Save Manager read changed a protected checkpoint."
		status_label.add_theme_color_override("font_color", BAD)
	elif not initialized:
		status_label.text = "Save Manager is ready to adopt your current V3 franchise as Slot 1. Protected V2 remains untouched."
		status_label.add_theme_color_override("font_color", GOLD)
	elif bool(payload.get("live_session_ahead_of_snapshot", false)):
		status_label.text = "LIVE SESSION AHEAD OF SNAPSHOT • your working franchise is durable, but SAVE CURRENT will refresh its named slot snapshot."
		status_label.add_theme_color_override("font_color", GOLD)
	else:
		status_label.text = "SAVE LIBRARY HEALTHY • active working session and protected V2 verified."
		status_label.add_theme_color_override("font_color", GOOD)

	_populate_new_franchise_teams()
	_render_selected()
	_update_controls()


func _slot_row(slot: Dictionary) -> Control:
	var panel := PanelContainer.new()
	var selected := str(slot.get("slot_id", "")) == selected_slot_id
	panel.add_theme_stylebox_override("panel", _box(PANEL_HOVER if selected else PANEL_ALT, 9, ACCENT if selected else BORDER))
	var margin := MarginContainer.new()
	_set_margins(margin, 12, 10, 12, 10)
	panel.add_child(margin)
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 10)
	margin.add_child(row)

	var identity := VBoxContainer.new()
	identity.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	identity.add_theme_constant_override("separation", 3)
	row.add_child(identity)
	var title := Label.new()
	var active_text := "  • ACTIVE" if bool(slot.get("active", false)) else ""
	title.text = "%s%s" % [str(slot.get("name", "Unnamed Save")), active_text]
	title.add_theme_color_override("font_color", GOOD if bool(slot.get("active", false)) else TEXT)
	title.add_theme_font_size_override("font_size", 13)
	identity.add_child(title)
	var detail := Label.new()
	detail.text = "%s • %s • %s • %s • Day %s" % [
		str(slot.get("team", "--")), str(slot.get("season", "--")),
		str(slot.get("record", "--")), _pretty(str(slot.get("phase", ""))),
		str(slot.get("day_index", 0))
	]
	detail.add_theme_color_override("font_color", MUTED)
	detail.add_theme_font_size_override("font_size", 10)
	identity.add_child(detail)

	var health := _pill("VERIFIED" if bool(slot.get("healthy", false)) else "CHECK", GOOD if bool(slot.get("healthy", false)) else GOLD)
	row.add_child(health)
	var select_button := _mini_button("SELECT")
	select_button.pressed.connect(_select_slot.bind(str(slot.get("slot_id", ""))))
	row.add_child(select_button)
	return panel


func _select_slot(slot_id: String) -> void:
	rename_mode = false
	new_franchise_mode = false
	selected_slot_id = slot_id
	_render_summary()


func _render_selected() -> void:
	if new_franchise_mode:
		var team := _selected_new_franchise_team()
		selected_title.text = "CREATE NEW FRANCHISE"
		selected_detail.text = "Start a clean 2026-27 franchise from the certified Sep. 7, 2026 universe.\nChoose any NBA team. Your current franchise is snapshotted before the new slot is activated."
		if name_input.text.strip_edges().is_empty() and not team.is_empty():
			name_input.text = "%s Franchise" % _team_name_for_code(team)
		return
	var selected := _slot_by_id(selected_slot_id)
	if selected.is_empty():
		selected_title.text = "SELECT A SAVE"
		selected_detail.text = "Choose a save slot to view its actions."
		name_input.text = ""
		return
	selected_title.text = str(selected.get("name", "Unnamed Save"))
	selected_detail.text = "%s\n%s • %s • %s\n%s • Day %s%s" % [
		str(selected.get("team_name", selected.get("team", ""))),
		str(selected.get("season", "--")), str(selected.get("record", "--")),
		_pretty(str(selected.get("phase", ""))),
		"ACTIVE WORKING FRANCHISE" if bool(selected.get("active", false)) else "Stored franchise snapshot",
		str(selected.get("day_index", 0)),
		"\nIntegrity verified" if bool(selected.get("healthy", false)) else "\nIntegrity requires review"
	]
	name_input.text = str(selected.get("name", ""))


func _update_controls() -> void:
	var initialized := bool(payload.get("initialized", false))
	var busy := pending_action != ""
	var selected := _slot_by_id(selected_slot_id)
	var has_selected := not selected.is_empty()
	var active_selected := bool(selected.get("active", false)) if has_selected else false
	bootstrap_button.visible = not initialized
	bootstrap_button.disabled = busy or not bool(payload.get("bootstrap_available", false))

	new_franchise_button.visible = initialized
	new_franchise_button.text = "CANCEL NEW FRANCHISE" if new_franchise_mode else "NEW FRANCHISE"
	new_franchise_button.disabled = busy or not initialized or rename_mode
	create_franchise_button.visible = initialized and new_franchise_mode
	create_franchise_button.disabled = busy or not new_franchise_mode or _selected_new_franchise_team().is_empty()
	team_label.visible = new_franchise_mode
	team_selector.visible = new_franchise_mode
	name_label.text = "NEW FRANCHISE NAME" if new_franchise_mode else "SAVE NAME / COPY NAME"
	name_help.text = (
		"Choose a team and name. CREATE FRANCHISE builds a clean certified 2026-27 universe and protects the current live save before switching."
		if new_franchise_mode
		else "For a copy, type the new name and choose CREATE COPY. For a rename, choose RENAME SELECTED, edit the highlighted field, then choose APPLY RENAME."
	)

	save_current_button.visible = initialized and not new_franchise_mode
	save_current_button.disabled = busy or not initialized or rename_mode
	create_button.visible = initialized and not new_franchise_mode
	create_button.disabled = busy or not initialized or rename_mode
	rename_button.visible = initialized and not new_franchise_mode
	rename_button.text = "APPLY RENAME" if rename_mode else "RENAME SELECTED"
	rename_button.disabled = busy or not has_selected
	load_button.visible = initialized and not new_franchise_mode
	load_button.disabled = busy or rename_mode or not has_selected or active_selected or not bool(selected.get("healthy", false))
	delete_button.visible = initialized and not new_franchise_mode
	delete_button.disabled = busy or rename_mode or not has_selected or active_selected


func _populate_new_franchise_teams() -> void:
	if team_selector == null:
		return
	var prior := _selected_new_franchise_team()
	team_selector.clear()
	var options: Array = payload.get("new_franchise_teams", [])
	var active_team := ""
	var active := _slot_by_id(str(payload.get("active_slot_id", "")))
	if not active.is_empty():
		active_team = str(active.get("team", ""))
	var select_index := 0
	for raw_option in options:
		if typeof(raw_option) != TYPE_DICTIONARY:
			continue
		var team := str(raw_option.get("team", ""))
		var team_name := str(raw_option.get("team_name", team))
		team_selector.add_item("%s  •  %s" % [team, team_name])
		var index := team_selector.item_count - 1
		team_selector.set_item_metadata(index, team)
		if team == prior or (prior.is_empty() and team == active_team):
			select_index = index
	if team_selector.item_count > 0:
		team_selector.select(select_index)


func _selected_new_franchise_team() -> String:
	if team_selector == null or team_selector.item_count <= 0:
		return ""
	var index := team_selector.selected
	if index < 0:
		return ""
	return str(team_selector.get_item_metadata(index))


func _team_name_for_code(team: String) -> String:
	for raw_option in payload.get("new_franchise_teams", []):
		if typeof(raw_option) == TYPE_DICTIONARY and str(raw_option.get("team", "")) == team:
			return str(raw_option.get("team_name", team))
	return team


func _on_new_franchise_team_selected(_index: int) -> void:
	if not new_franchise_mode:
		return
	var team := _selected_new_franchise_team()
	if not team.is_empty():
		name_input.text = "%s Franchise" % _team_name_for_code(team)
	_render_selected()
	_update_controls()


func _toggle_new_franchise_mode() -> void:
	if pending_action != "":
		return
	rename_mode = false
	new_franchise_mode = not new_franchise_mode
	if new_franchise_mode:
		var team := _selected_new_franchise_team()
		if not team.is_empty():
			name_input.text = "%s Franchise" % _team_name_for_code(team)
		status_label.text = "NEW FRANCHISE MODE • choose a team and create a clean certified 2026-27 franchise save."
		status_label.add_theme_color_override("font_color", ACCENT)
	else:
		status_label.text = "New franchise creation cancelled. No save was changed."
		status_label.add_theme_color_override("font_color", MUTED)
	_render_selected()
	_update_controls()


func _confirm_new_franchise() -> void:
	if not new_franchise_mode:
		return
	var team := _selected_new_franchise_team()
	if team.is_empty():
		status_label.text = "Choose an NBA team before creating a franchise."
		status_label.add_theme_color_override("font_color", GOLD)
		return
	var clean_name := name_input.text.strip_edges()
	if clean_name.is_empty():
		clean_name = "%s Franchise" % _team_name_for_code(team)
		name_input.text = clean_name
	pending_new_franchise_body = {"team": team, "name": clean_name}
	if not bool(desktop_preferences.get("confirm_new_franchise", true)):
		_post_action("new_franchise", NEW_FRANCHISE_URL, pending_new_franchise_body)
		pending_new_franchise_body = {}
		return
	pending_confirm_action = "new_franchise"
	confirm_dialog.dialog_text = "Create '%s' as %s?\n\nThis builds a clean 2026-27 franchise from the certified Sep. 7 universe. Your current live session is snapshotted to its existing save before the new franchise becomes active. Protected V2 remains unchanged." % [clean_name, _team_name_for_code(team)]
	confirm_dialog.ok_button_text = "CREATE FRANCHISE"
	confirm_dialog.popup_centered(Vector2i(620, 340))


func _bootstrap() -> void:
	_post_action("bootstrap", BOOTSTRAP_URL, {"name": name_input.text.strip_edges()})


func _save_current() -> void:
	_post_action("save_current", SAVE_CURRENT_URL, {})


func _create_copy() -> void:
	_post_action("create", CREATE_URL, {"name": name_input.text.strip_edges()})


func _rename_selected() -> void:
	if selected_slot_id.is_empty():
		return
	var selected := _slot_by_id(selected_slot_id)
	if selected.is_empty():
		return
	if not rename_mode:
		rename_mode = true
		name_input.text = str(selected.get("name", ""))
		name_input.grab_focus()
		name_input.select_all()
		status_label.text = "RENAME MODE • edit the highlighted SAVE NAME field, then choose APPLY RENAME (or press Enter)."
		status_label.add_theme_color_override("font_color", ACCENT)
		_update_controls()
		return

	var new_name := name_input.text.strip_edges()
	if new_name.is_empty():
		status_label.text = "Rename requires a non-empty franchise save name."
		status_label.add_theme_color_override("font_color", GOLD)
		name_input.grab_focus()
		return
	if new_name == str(selected.get("name", "")):
		status_label.text = "Enter a different franchise save name before applying the rename."
		status_label.add_theme_color_override("font_color", GOLD)
		name_input.grab_focus()
		name_input.select_all()
		return
	rename_mode = false
	_update_controls()
	_post_action("rename", RENAME_URL, {"slot_id": selected_slot_id, "name": new_name})


func _on_name_submitted(_value: String) -> void:
	if rename_mode:
		_rename_selected()


func _confirm_load() -> void:
	var selected := _slot_by_id(selected_slot_id)
	if selected.is_empty() or bool(selected.get("active", false)):
		return
	if not bool(desktop_preferences.get("confirm_load", true)):
		_post_action("load", LOAD_URL, {"slot_id": selected_slot_id})
		return
	pending_confirm_action = "load"
	confirm_dialog.dialog_text = "Load '%s'?\n\nYour current live V3 session will first be snapshotted to its active slot. A recovery copy of the working checkpoint is created before the switch. Protected V2 remains unchanged." % str(selected.get("name", "selected save"))
	confirm_dialog.ok_button_text = "LOAD SAVE"
	confirm_dialog.popup_centered(Vector2i(590, 310))


func _confirm_delete() -> void:
	var selected := _slot_by_id(selected_slot_id)
	if selected.is_empty() or bool(selected.get("active", false)):
		return
	if not bool(desktop_preferences.get("confirm_delete", true)):
		_post_action("delete", DELETE_URL, {"slot_id": selected_slot_id})
		return
	pending_confirm_action = "delete"
	confirm_dialog.dialog_text = "Delete '%s'?\n\nThe active franchise cannot be deleted. This non-active slot will be copied to Save Manager recovery before removal." % str(selected.get("name", "selected save"))
	confirm_dialog.ok_button_text = "DELETE SAVE"
	confirm_dialog.popup_centered(Vector2i(590, 290))


func _on_confirmed() -> void:
	if pending_confirm_action == "load":
		_post_action("load", LOAD_URL, {"slot_id": selected_slot_id})
	elif pending_confirm_action == "new_franchise":
		_post_action("new_franchise", NEW_FRANCHISE_URL, pending_new_franchise_body)
		pending_new_franchise_body = {}
	elif pending_confirm_action == "delete":
		_post_action("delete", DELETE_URL, {"slot_id": selected_slot_id})
	pending_confirm_action = ""


func _post_action(action: String, url: String, body: Dictionary) -> void:
	if action_request == null or pending_action != "":
		return
	if action_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	pending_action = action
	status_label.text = "Running %s with recovery and checkpoint verification..." % action.replace("_", " ")
	status_label.add_theme_color_override("font_color", ACCENT)
	_update_controls()
	var headers := PackedStringArray(["Content-Type: application/json"])
	var error := action_request.request(url, headers, HTTPClient.METHOD_POST, JSON.stringify(body))
	if error != OK:
		pending_action = ""
		status_label.text = "Could not start Save Manager action."
		status_label.add_theme_color_override("font_color", BAD)
		_update_controls()


func _on_action_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	var completed_action := pending_action
	pending_action = ""
	if result != HTTPRequest.RESULT_SUCCESS or body.is_empty():
		status_label.text = "Save Manager action failed before a valid bridge response was received."
		status_label.add_theme_color_override("font_color", BAD)
		_update_controls()
		return
	var parsed = JSON.parse_string(body.get_string_from_utf8())
	if typeof(parsed) != TYPE_DICTIONARY:
		status_label.text = "Save Manager action returned invalid JSON."
		status_label.add_theme_color_override("font_color", BAD)
		_update_controls()
		return
	if response_code != 200 or parsed.has("error"):
		status_label.text = str(parsed.get("detail", parsed.get("error", "Save Manager action was blocked.")))
		status_label.add_theme_color_override("font_color", GOLD if response_code == 409 else BAD)
		_update_controls()
		return
	payload = parsed
	if completed_action == "create":
		selected_slot_id = str(parsed.get("created_slot_id", selected_slot_id))
	elif completed_action == "new_franchise":
		selected_slot_id = str(parsed.get("created_slot_id", parsed.get("loaded_slot_id", selected_slot_id)))
		new_franchise_mode = false
	elif completed_action == "rename":
		rename_mode = false
	elif completed_action == "load":
		selected_slot_id = str(parsed.get("loaded_slot_id", selected_slot_id))
	elif completed_action == "delete":
		selected_slot_id = str(parsed.get("active_slot_id", ""))
	_render_summary()
	status_label.text = "SAVE MANAGER %s • V3 working session verified • protected V2 unchanged." % completed_action.replace("_", " ").to_upper()
	status_label.add_theme_color_override("font_color", GOOD)
	if completed_action == "load" or completed_action == "new_franchise":
		active_save_changed.emit()


func _slot_by_id(slot_id: String) -> Dictionary:
	for raw_slot in payload.get("slots", []):
		if typeof(raw_slot) == TYPE_DICTIONARY and str(raw_slot.get("slot_id", "")) == slot_id:
			return raw_slot
	return {}


func _slot_exists(slot_id: String) -> bool:
	return not _slot_by_id(slot_id).is_empty()


func _metric(parent: HBoxContainer, label_text: String, value_text: String) -> Label:
	var card := _card(Vector2(0, 86))
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var body := _card_body(card, 13)
	body.add_child(_small_label(label_text, MUTED))
	var value := Label.new()
	value.text = value_text
	value.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	value.add_theme_color_override("font_color", TEXT)
	value.add_theme_font_size_override("font_size", 16)
	body.add_child(value)
	parent.add_child(card)
	return value


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


func _mini_button(text_value: String) -> Button:
	var button := Button.new()
	button.custom_minimum_size = Vector2(72, 30)
	button.text = text_value
	button.add_theme_font_size_override("font_size", 9)
	button.add_theme_color_override("font_color", TEXT)
	button.add_theme_stylebox_override("normal", _box(PANEL, 7, BORDER))
	button.add_theme_stylebox_override("hover", _box(PANEL_HOVER, 7, ACCENT))
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


func _pill(text_value: String, color: Color) -> Label:
	var label := Label.new()
	label.text = "  %s  " % text_value
	label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	label.add_theme_color_override("font_color", color)
	label.add_theme_font_size_override("font_size", 9)
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


func _clear_children(node: Node) -> void:
	for child in node.get_children():
		child.queue_free()


func _pretty(value: String) -> String:
	if value.is_empty():
		return "--"
	return value.replace("_", " ").capitalize()
