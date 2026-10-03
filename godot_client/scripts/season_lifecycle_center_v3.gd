extends Control

const SUMMARY_URL := "http://127.0.0.1:8765/v3/lifecycle"
const PREVIEW_URL := "http://127.0.0.1:8765/v3/lifecycle/preview"
const EXECUTE_URL := "http://127.0.0.1:8765/v3/lifecycle/execute"

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
var preview_request: HTTPRequest
var execute_request: HTTPRequest

var season_value: Label
var phase_value: Label
var progress_value: Label
var gate_value: Label
var status_label: Label
var action_title: Label
var action_detail: Label
var preview_button: Button
var execute_button: Button
var refresh_button: Button
var timeline_rows: VBoxContainer
var engine_detail: Label
var confirm_dialog: ConfirmationDialog

var summary_payload: Dictionary = {}
var latest_action: String = ""
var latest_action_fingerprint: String = ""
var latest_working_sha: String = ""
var execute_in_flight: bool = false


var long_action_manager = null


func set_long_action_manager(manager) -> void:
	long_action_manager = manager


func _begin_long_action(key: String, title: String, detail: String, steps: Array) -> bool:
	if long_action_manager == null:
		return true
	return bool(long_action_manager.begin_action(key, title, detail, steps))


func _finish_long_action(key: String, success: bool, message: String = "") -> void:
	if long_action_manager != null:
		long_action_manager.finish_action(key, success, message)


func _ready() -> void:
	_build_ui()
	_build_requests()


func refresh() -> void:
	_invalidate_preview()
	if summary_request == null:
		return
	if summary_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	status_label.text = "Loading certified season lifecycle state..."
	status_label.add_theme_color_override("font_color", MUTED)
	var error: int = summary_request.request(SUMMARY_URL)
	if error != OK:
		status_label.text = "Could not start lifecycle summary request."
		status_label.add_theme_color_override("font_color", BAD)


func _build_requests() -> void:
	summary_request = HTTPRequest.new()
	add_child(summary_request)
	summary_request.request_completed.connect(_on_summary_completed)

	preview_request = HTTPRequest.new()
	add_child(preview_request)
	preview_request.request_completed.connect(_on_preview_completed)

	execute_request = HTTPRequest.new()
	add_child(execute_request)
	execute_request.request_completed.connect(_on_execute_completed)


func _build_ui() -> void:
	var outer := MarginContainer.new()
	outer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	outer.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_set_margins(outer, 28, 24, 28, 26)
	add_child(outer)
	outer.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)

	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 16)
	outer.add_child(column)

	var header := HBoxContainer.new()
	header.add_theme_constant_override("separation", 12)
	column.add_child(header)

	var titles := VBoxContainer.new()
	titles.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	titles.add_theme_constant_override("separation", 4)
	header.add_child(titles)
	titles.add_child(_small_label("FRANCHISE OPERATIONS • SEASON CONTROL", TEAM_PRIMARY_HOVER))
	var title := Label.new()
	title.text = "SEASON LIFECYCLE"
	title.add_theme_color_override("font_color", TEXT)
	title.add_theme_font_size_override("font_size", 29)
	titles.add_child(title)
	var subtitle := Label.new()
	subtitle.text = "Certified phase progression from the current season through the offseason and into the next year."
	subtitle.add_theme_color_override("font_color", MUTED)
	subtitle.add_theme_font_size_override("font_size", 12)
	subtitle.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	titles.add_child(subtitle)

	refresh_button = _action_button("REFRESH")
	refresh_button.custom_minimum_size = Vector2(105, 50)
	refresh_button.pressed.connect(refresh)
	header.add_child(refresh_button)

	var metrics := HBoxContainer.new()
	metrics.add_theme_constant_override("separation", 10)
	column.add_child(metrics)
	season_value = _metric(metrics, "SEASON", "LOADING...")
	phase_value = _metric(metrics, "PHASE", "LOADING...")
	progress_value = _metric(metrics, "LEAGUE PROGRESS", "LOADING...")
	gate_value = _metric(metrics, "NEXT GATE", "LOADING...")

	var content := HBoxContainer.new()
	content.size_flags_vertical = Control.SIZE_EXPAND_FILL
	content.add_theme_constant_override("separation", 14)
	column.add_child(content)

	var timeline_card := _card(Vector2(0, 0))
	timeline_card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	timeline_card.size_flags_vertical = Control.SIZE_EXPAND_FILL
	var timeline_body := _card_body(timeline_card, 18)
	timeline_body.add_child(_small_label("CERTIFIED FRANCHISE CALENDAR", ACCENT))
	timeline_body.add_child(_section_title("SEASON PIPELINE"))
	var timeline_help := Label.new()
	timeline_help.text = "Each boundary is driven by the mature production lifecycle engine. Locked gates cannot be skipped."
	timeline_help.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	timeline_help.add_theme_color_override("font_color", MUTED)
	timeline_help.add_theme_font_size_override("font_size", 11)
	timeline_body.add_child(timeline_help)

	var timeline_scroll := ScrollContainer.new()
	timeline_scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	timeline_scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	timeline_body.add_child(timeline_scroll)
	timeline_rows = VBoxContainer.new()
	timeline_rows.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	timeline_rows.add_theme_constant_override("separation", 6)
	timeline_scroll.add_child(timeline_rows)
	content.add_child(timeline_card)

	var action_column := VBoxContainer.new()
	action_column.custom_minimum_size = Vector2(410, 0)
	action_column.add_theme_constant_override("separation", 14)
	content.add_child(action_column)

	var action_card := _card(Vector2(410, 330))
	var action_body := _card_body(action_card, 18)
	action_body.add_child(_small_label("WRITE-SAFE LIFECYCLE GATE", GOLD))
	action_title = _section_title("CURRENT GATE")
	action_body.add_child(action_title)
	action_detail = Label.new()
	action_detail.text = "Loading lifecycle state..."
	action_detail.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	action_detail.add_theme_color_override("font_color", MUTED)
	action_detail.add_theme_font_size_override("font_size", 11)
	action_body.add_child(action_detail)

	var action_buttons := HBoxContainer.new()
	action_buttons.add_theme_constant_override("separation", 8)
	preview_button = _action_button("PREVIEW ACTION")
	preview_button.disabled = true
	preview_button.pressed.connect(_preview_action)
	action_buttons.add_child(preview_button)
	execute_button = _action_button("COMMIT ACTION", true)
	execute_button.disabled = true
	execute_button.pressed.connect(_confirm_execute)
	action_buttons.add_child(execute_button)
	action_body.add_child(action_buttons)

	status_label = Label.new()
	status_label.text = "Waiting for lifecycle summary."
	status_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	status_label.add_theme_color_override("font_color", MUTED)
	status_label.add_theme_font_size_override("font_size", 11)
	action_body.add_child(status_label)
	action_column.add_child(action_card)

	var safety_card := _card(Vector2(410, 0))
	safety_card.size_flags_vertical = Control.SIZE_EXPAND_FILL
	var safety_body := _card_body(safety_card, 18)
	safety_body.add_child(_small_label("BOUNDARY SAFETY", GOOD))
	safety_body.add_child(_section_title("V3 ISOLATION"))
	var safety_text := Label.new()
	safety_text.text = "Every durable lifecycle action requires a fresh preview fingerprint and exact V3 working-save SHA. A recovery copy is created before writing, the saved checkpoint is reloaded and verified, and the protected V2 checkpoint must remain byte-identical."
	safety_text.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	safety_text.add_theme_color_override("font_color", MUTED)
	safety_text.add_theme_font_size_override("font_size", 11)
	safety_body.add_child(safety_text)
	engine_detail = Label.new()
	engine_detail.text = "Production lifecycle engine versions load with the summary."
	engine_detail.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	engine_detail.add_theme_color_override("font_color", ACCENT)
	engine_detail.add_theme_font_size_override("font_size", 10)
	safety_body.add_child(engine_detail)
	action_column.add_child(safety_card)

	confirm_dialog = ConfirmationDialog.new()
	confirm_dialog.title = "Confirm certified season lifecycle action"
	confirm_dialog.ok_button_text = "COMMIT ACTION"
	confirm_dialog.cancel_button_text = "CANCEL"
	confirm_dialog.confirmed.connect(_execute_action)
	add_child(confirm_dialog)


func _on_summary_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	var raw_payload = JSON.parse_string(body.get_string_from_utf8())
	if result != HTTPRequest.RESULT_SUCCESS or response_code != 200 or typeof(raw_payload) != TYPE_DICTIONARY:
		status_label.text = "Lifecycle summary is unavailable. Start or restart the V3 Python bridge and refresh."
		status_label.add_theme_color_override("font_color", BAD)
		preview_button.disabled = true
		execute_button.disabled = true
		return
	summary_payload = raw_payload
	_render_summary()


func _render_summary() -> void:
	_invalidate_preview()
	var season: Dictionary = summary_payload.get("season", {})
	var schedule: Dictionary = summary_payload.get("schedule", {})
	var postseason: Dictionary = summary_payload.get("postseason", {})
	var draft: Dictionary = summary_payload.get("draft", {})
	var cpu_fa: Dictionary = summary_payload.get("cpu_free_agency", {})

	season_value.text = str(season.get("label", "--"))
	phase_value.text = _pretty(str(season.get("phase", "--")))

	var total_games: int = _safe_int(schedule.get("total", 0))
	var completed_games: int = _safe_int(schedule.get("completed", 0))
	var postseason_stage: String = _safe_string(postseason.get("stage", ""))
	var postseason_games: int = _safe_int(postseason.get("completed_games", 0))
	if not postseason_stage.is_empty() and postseason_stage != "complete":
		progress_value.text = "%s • %d GAMES" % [_pretty(postseason_stage), postseason_games]
	elif postseason_stage == "complete":
		progress_value.text = "POSTSEASON COMPLETE"
	elif total_games > 0:
		progress_value.text = "%d / %d GAMES" % [completed_games, total_games]
	else:
		progress_value.text = "OFFSEASON"

	latest_action = _safe_string(summary_payload.get("next_action", ""))
	var action_label: String = str(summary_payload.get("next_action_label", "NO ACTION AVAILABLE"))
	gate_value.text = action_label
	action_title.text = action_label

	var blockers: Array = summary_payload.get("blockers", [])
	var stage: String = _safe_string(summary_payload.get("stage", ""))
	var detail_parts: Array[String] = []
	detail_parts.append("Stage: %s" % _pretty(stage))
	if blockers.size() > 0:
		for blocker in blockers:
			detail_parts.append(str(blocker))
	else:
		detail_parts.append(_action_explanation(latest_action))
	if bool(postseason.get("initialized", false)):
		var champion: String = _safe_string(postseason.get("champion", ""))
		if not champion.is_empty():
			detail_parts.append("Champion: %s • Runner-up: %s" % [
				champion, _safe_string(postseason.get("runner_up", "--"), "--")
			])
		else:
			detail_parts.append("East seeds: %s" % _seed_summary(postseason.get("east_seeds", [])))
			detail_parts.append("West seeds: %s" % _seed_summary(postseason.get("west_seeds", [])))
	if _safe_int(cpu_fa.get("deficit_team_count", 0)) > 0:
		detail_parts.append("CPU roster deficits: %s team(s), %s total spot(s)." % [
			str(cpu_fa.get("deficit_team_count", 0)),
			str(cpu_fa.get("total_deficit", 0))
		])
	if bool(draft.get("initialized", false)):
		detail_parts.append("Draft: %s • %s picks tracked." % [
			_pretty(str(draft.get("phase", ""))),
			str(draft.get("pick_count", 0))
		])
	action_detail.text = "\n".join(detail_parts)

	preview_button.disabled = latest_action.is_empty()
	status_label.text = "Preview the certified gate before any durable lifecycle write." if not latest_action.is_empty() else "No automatic lifecycle write is currently legal. Continue the active franchise phase first."
	status_label.add_theme_color_override("font_color", ACCENT if not latest_action.is_empty() else MUTED)

	_clear_children(timeline_rows)
	var timeline: Array = summary_payload.get("timeline", [])
	for item in timeline:
		if typeof(item) == TYPE_DICTIONARY:
			timeline_rows.add_child(_timeline_row(item))

	var versions: Dictionary = summary_payload.get("engine_versions", {})
	engine_detail.text = "Postseason %s\nCloseout %s\nDraft %s\nPost-Draft trim %s\nSeason boundary %s" % [
		str(versions.get("postseason", "production")),
		str(versions.get("closeout", "production")),
		str(versions.get("draft", "production")),
		str(versions.get("post_draft_trim", "production")),
		str(versions.get("season_boundary", "production"))
	]


func _preview_action() -> void:
	if latest_action.is_empty() or preview_request == null:
		return
	if preview_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	_invalidate_preview()
	status_label.text = "Building a read-only certified lifecycle candidate..."
	status_label.add_theme_color_override("font_color", ACCENT)
	var headers := PackedStringArray(["Content-Type: application/json"])
	var body := JSON.stringify({"action": latest_action})
	var error: int = preview_request.request(PREVIEW_URL, headers, HTTPClient.METHOD_POST, body)
	if error != OK:
		status_label.text = "Could not start lifecycle preview."
		status_label.add_theme_color_override("font_color", BAD)


func _on_preview_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	var raw_payload = JSON.parse_string(body.get_string_from_utf8())
	if result != HTTPRequest.RESULT_SUCCESS or typeof(raw_payload) != TYPE_DICTIONARY:
		status_label.text = "Lifecycle preview failed before a valid bridge response was received."
		status_label.add_theme_color_override("font_color", BAD)
		return
	if response_code != 200 or not bool(raw_payload.get("can_commit", false)):
		status_label.text = str(raw_payload.get("detail", raw_payload.get("blockers", ["Lifecycle action is blocked."])))
		status_label.add_theme_color_override("font_color", GOLD if response_code == 409 else BAD)
		_invalidate_preview()
		return
	if not bool(raw_payload.get("working_save_unchanged", false)) or not bool(raw_payload.get("active_v2_unchanged", false)):
		status_label.text = "LIFECYCLE SAFETY FAILURE • preview changed a protected checkpoint."
		status_label.add_theme_color_override("font_color", BAD)
		_invalidate_preview()
		return

	latest_action = str(raw_payload.get("action", latest_action))
	latest_action_fingerprint = _safe_string(raw_payload.get("action_fingerprint", ""))
	latest_working_sha = _safe_string(raw_payload.get("working_save_sha256", ""))
	if latest_action_fingerprint.is_empty() or latest_working_sha.is_empty():
		status_label.text = "Lifecycle preview did not return a complete execution token."
		status_label.add_theme_color_override("font_color", BAD)
		_invalidate_preview()
		return

	execute_button.disabled = false
	var detail: Dictionary = raw_payload.get("detail", {})
	status_label.text = "STATUS PASS • COMMITTABLE YES\n%s\nFresh lifecycle token locked to the current V3 working save." % _preview_detail(latest_action, detail)
	status_label.add_theme_color_override("font_color", GOOD)


func _confirm_execute() -> void:
	if execute_in_flight or latest_action_fingerprint.is_empty() or latest_working_sha.is_empty():
		return
	confirm_dialog.dialog_text = "%s\n\nThis writes ONLY the isolated V3 working save. A recovery checkpoint is created first, the result is reloaded and verified, and the protected V2 checkpoint must remain unchanged." % action_title.text
	confirm_dialog.popup_centered(Vector2i(620, 310))


func _execute_action() -> void:
	if execute_request == null or execute_in_flight:
		return
	if execute_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	if not _begin_long_action(
		"season_lifecycle_commit",
		"ADVANCING FRANCHISE LIFECYCLE",
		"Running the certified season/offseason transition on the isolated V3 save...",
		[
			"Rechecking the lifecycle action fingerprint and current stage...",
			"Running the production postseason/offseason lifecycle engine...",
			"Applying CPU roster-market and season-boundary work where required...",
			"Persisting and reloading the V3 franchise checkpoint...",
			"Verifying lifecycle continuity and protected V2 safety...",
		]
	):
		status_label.text = "Another franchise-changing action is already running."
		status_label.add_theme_color_override("font_color", GOLD)
		return
	var request_payload: Dictionary = {
		"action": latest_action,
		"expected_action_fingerprint": latest_action_fingerprint,
		"expected_working_save_sha256": latest_working_sha
	}
	execute_in_flight = true
	execute_button.disabled = true
	preview_button.disabled = true
	status_label.text = "Committing certified lifecycle boundary, then reloading and verifying the V3 checkpoint..."
	status_label.add_theme_color_override("font_color", ACCENT)
	var headers := PackedStringArray(["Content-Type: application/json"])
	var error: int = execute_request.request(EXECUTE_URL, headers, HTTPClient.METHOD_POST, JSON.stringify(request_payload))
	if error != OK:
		_finish_long_action("season_lifecycle_commit", false, "Lifecycle execution request could not start.")
		execute_in_flight = false
		status_label.text = "Could not start lifecycle execution."
		status_label.add_theme_color_override("font_color", BAD)
		preview_button.disabled = latest_action.is_empty()


func _on_execute_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	_finish_long_action(
		"season_lifecycle_commit",
		result == HTTPRequest.RESULT_SUCCESS and response_code == 200,
		"Lifecycle action completed." if result == HTTPRequest.RESULT_SUCCESS and response_code == 200 else "Lifecycle action ended with an error."
	)
	execute_in_flight = false
	var raw_payload = JSON.parse_string(body.get_string_from_utf8())
	if result != HTTPRequest.RESULT_SUCCESS or typeof(raw_payload) != TYPE_DICTIONARY:
		status_label.text = "Lifecycle execution failed before a valid bridge response was received."
		status_label.add_theme_color_override("font_color", BAD)
		_invalidate_preview()
		return
	if response_code != 200:
		var detail: String = str(raw_payload.get("detail", raw_payload.get("error", "Lifecycle execution failed.")))
		if bool(raw_payload.get("rollback_performed", false)):
			detail += "\nRollback: %s" % ("VERIFIED" if bool(raw_payload.get("rollback_verified", false)) else "REQUIRES REVIEW")
		if str(raw_payload.get("error", "")) == "stale_lifecycle_preview":
			detail += "\nRefresh and preview the lifecycle action again."
		status_label.text = detail
		status_label.add_theme_color_override("font_color", GOLD if response_code == 409 else BAD)
		_invalidate_preview()
		preview_button.disabled = latest_action.is_empty()
		return
	if not bool(raw_payload.get("persisted_after_reload", false)) or not bool(raw_payload.get("active_v2_unchanged", false)):
		status_label.text = "LIFECYCLE SAFETY FAILURE • reload persistence or V2 protection was not confirmed."
		status_label.add_theme_color_override("font_color", BAD)
		_invalidate_preview()
		return
	var committed_action: String = str(raw_payload.get("action", latest_action))
	status_label.text = "LIFECYCLE ACTION COMMITTED • %s\nPersisted after reload • protected V2 unchanged\nRecovery: %s" % [
		_pretty(committed_action), str(raw_payload.get("recovery_checkpoint_path", ""))
	]
	status_label.add_theme_color_override("font_color", GOOD)
	_invalidate_preview()
	refresh()


func _invalidate_preview() -> void:
	latest_action_fingerprint = ""
	latest_working_sha = ""
	if execute_button != null:
		execute_button.disabled = true


func _safe_string(value: Variant, fallback: String = "") -> String:
	if value == null:
		return fallback
	return str(value)


func _safe_int(value: Variant, fallback: int = 0) -> int:
	if value == null:
		return fallback
	return int(value)


func _timeline_row(item: Dictionary) -> Control:
	var status: String = _safe_string(item.get("status", "locked"), "locked").to_lower()
	var color := MUTED
	var marker := "LOCKED"
	if status == "complete":
		color = GOOD
		marker = "COMPLETE"
	elif status == "current":
		color = GOLD
		marker = "CURRENT"
	var card := _card(Vector2(0, 58))
	var body := _card_body(card, 11)
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 10)
	body.add_child(row)
	row.add_child(_pill(marker, color))
	var label := Label.new()
	label.text = str(item.get("label", item.get("key", "")))
	label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	label.add_theme_color_override("font_color", TEXT if status != "locked" else MUTED)
	label.add_theme_font_size_override("font_size", 13)
	row.add_child(label)
	return card


func _preview_detail(action: String, detail: Dictionary) -> String:
	match action:
		"postseason_initialize":
			return "Official bracket candidate ready • %s\nEast: %s\nWest: %s" % [
				_pretty(str(detail.get("stage", ""))),
				_seed_summary(detail.get("east_seeds", [])),
				_seed_summary(detail.get("west_seeds", []))
			]
		"postseason_simulate":
			return "Certified postseason candidate built • %s game(s) simulated to a champion. The champion is revealed only after commit." % str(detail.get("games_simulated", 0))
		"contract_closeout":
			return "Contracts decremented %s • expired %s • Draft scouting preserved %s" % [
				str(detail.get("contracts_decremented", 0)),
				str(detail.get("contracts_expired", 0)),
				"YES" if bool(detail.get("draft_scouting_preserved", false)) else "N/A"
			]
		"cpu_free_agency":
			return "%s CPU signings • roster deficit %s → %s • %s" % [
				str(detail.get("committed_signing_count", 0)),
				str(detail.get("total_deficit_before", 0)),
				str(detail.get("total_deficit_after", 0)),
				"ROSTERS READY" if bool(detail.get("round_complete", false)) else "ANOTHER ROUND MAY BE NEEDED"
			]
		"draft_lottery":
			return "Draft year %s • %s picks • %s prospects" % [
				str(detail.get("draft_year", "")),
				str(detail.get("draft_pick_count", 0)),
				str(detail.get("prospect_count", 0))
			]
		"draft_night":
			return "Draft year %s • %s picks ready for Draft Night" % [
				str(detail.get("draft_year", "")), str(detail.get("draft_pick_count", 0))
			]
		"next_season":
			return "Target %s • %s-game schedule • %s rookies activated" % [
				str(detail.get("target_season", "")),
				str(detail.get("schedule_count", 0)),
				str(detail.get("rookies_activated", 0))
			]
	return "Certified production candidate built without writing the save."


func _action_explanation(action: String) -> String:
	match action:
		"postseason_initialize":
			return "Create the official production Play-In and playoff bracket from the final regular-season standings. Preview the East and West seeds before committing."
		"postseason_simulate":
			return "Run the proven production postseason engine through the NBA Finals. The result is isolated until the confirmed V3 lifecycle commit."
		"contract_closeout":
			return "Apply the authoritative completed-season contract closeout before the player market advances."
		"cpu_free_agency":
			return "Let every CPU front office evaluate team fit, legal contract paths, competing offers, player decisions, and emergency roster needs. Previewing never writes the save."
		"draft_lottery":
			return "Initialize the production Draft state, conduct the lottery, and reveal the Draft class."
		"draft_night":
			return "Open the production Draft Night state. Player selections remain in the Scouting & Draft Center."
		"next_season":
			return "Run certified post-Draft roster preparation, season transition, rookie activation, schedule generation, and the atomic season boundary."
	return "No certified automatic action is available."


func _seed_summary(rows_variant: Variant) -> String:
	if typeof(rows_variant) != TYPE_ARRAY:
		return "--"
	var rows: Array = rows_variant
	var parts: Array[String] = []
	for row_variant in rows:
		if typeof(row_variant) != TYPE_DICTIONARY:
			continue
		var row: Dictionary = row_variant
		parts.append("%s %s" % [str(row.get("Seed", "?")), str(row.get("Team", "--"))])
	return " • ".join(parts) if not parts.is_empty() else "--"


func _pretty(value: String) -> String:
	if value.is_empty():
		return "--"
	return value.replace("_", " ").to_upper()


func _metric(parent: HBoxContainer, title: String, value: String) -> Label:
	var card := _card(Vector2(0, 84))
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var body := _card_body(card, 12)
	body.add_child(_small_label(title, MUTED))
	var label := Label.new()
	label.text = value
	label.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	label.add_theme_color_override("font_color", TEXT)
	label.add_theme_font_size_override("font_size", 16)
	body.add_child(label)
	parent.add_child(card)
	return label


func _action_button(text_value: String, primary: bool = false) -> Button:
	var button := Button.new()
	button.custom_minimum_size = Vector2(0, 38)
	button.text = text_value
	button.add_theme_font_size_override("font_size", 10)
	button.add_theme_color_override("font_color", TEXT)
	button.add_theme_color_override("font_hover_color", TEXT)
	var normal_color := TEAM_PRIMARY if primary else PANEL_ALT
	var hover_color := TEAM_PRIMARY_HOVER if primary else PANEL_HOVER
	button.add_theme_stylebox_override("normal", _box(normal_color, 9, normal_color if primary else BORDER))
	button.add_theme_stylebox_override("hover", _box(hover_color, 9, hover_color if primary else ACCENT))
	button.add_theme_stylebox_override("pressed", _box(hover_color, 9, hover_color))
	return button


func _section_title(text_value: String) -> Label:
	var label := Label.new()
	label.text = text_value
	label.add_theme_color_override("font_color", TEXT)
	label.add_theme_font_size_override("font_size", 17)
	return label


func _small_label(text_value: String, color: Color) -> Label:
	var label := Label.new()
	label.text = text_value
	label.add_theme_color_override("font_color", color)
	label.add_theme_font_size_override("font_size", 10)
	return label


func _pill(text_value: String, color: Color) -> Label:
	var label := Label.new()
	label.text = "  %s  " % text_value
	label.add_theme_color_override("font_color", color)
	label.add_theme_font_size_override("font_size", 9)
	label.add_theme_stylebox_override("normal", _box(Color(color, 0.10), 7, Color(color, 0.35)))
	return label


func _card(minimum: Vector2) -> PanelContainer:
	var card := PanelContainer.new()
	card.custom_minimum_size = minimum
	card.add_theme_stylebox_override("panel", _box(PANEL, 14, BORDER))
	return card


func _card_body(card: PanelContainer, margin_size: int) -> VBoxContainer:
	var margin := MarginContainer.new()
	_set_margins(margin, margin_size, margin_size, margin_size, margin_size)
	card.add_child(margin)
	var body := VBoxContainer.new()
	body.add_theme_constant_override("separation", 7)
	margin.add_child(body)
	return body


func _box(color: Color, radius: int, border_color: Color = Color.TRANSPARENT) -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = color
	style.corner_radius_top_left = radius
	style.corner_radius_top_right = radius
	style.corner_radius_bottom_left = radius
	style.corner_radius_bottom_right = radius
	if border_color != Color.TRANSPARENT:
		style.border_width_left = 1
		style.border_width_top = 1
		style.border_width_right = 1
		style.border_width_bottom = 1
		style.border_color = border_color
	style.content_margin_left = 10
	style.content_margin_right = 10
	style.content_margin_top = 8
	style.content_margin_bottom = 8
	return style


func _set_margins(container: MarginContainer, left: int, top: int, right: int, bottom: int) -> void:
	container.add_theme_constant_override("margin_left", left)
	container.add_theme_constant_override("margin_top", top)
	container.add_theme_constant_override("margin_right", right)
	container.add_theme_constant_override("margin_bottom", bottom)


func _clear_children(node: Node) -> void:
	for child in node.get_children():
		node.remove_child(child)
		child.queue_free()
