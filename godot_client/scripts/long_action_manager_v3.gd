extends RefCounted

signal action_started(snapshot)
signal action_finished(snapshot)

const LONG_ACTION_MANAGER_VERSION := "v3-long-action-manager-batch-18c-v1.0.0-2026-10-03"
const STEP_INTERVAL_SECONDS := 2.5
const DEFAULT_STEPS := [
	"Starting the production franchise engine...",
	"Processing the requested franchise action...",
	"Persisting the isolated V3 working checkpoint...",
	"Reloading and verifying the durable result...",
	"Confirming protected V2 remains unchanged...",
]

var _busy := false
var _key := ""
var _title := ""
var _detail := ""
var _steps: Array = []
var _started_msec := 0
var _actions_started := 0
var _actions_finished := 0
var _actions_failed := 0
var _rejected_starts := 0


func begin_action(key: String, title: String, detail: String, steps: Array = []) -> bool:
	var normalized := key.strip_edges().to_lower()
	if normalized == "":
		return false
	if _busy:
		_rejected_starts += 1
		return false

	_busy = true
	_key = normalized
	_title = title.strip_edges()
	_detail = detail.strip_edges()
	_steps = steps.duplicate()
	if _steps.is_empty():
		_steps = DEFAULT_STEPS.duplicate()
	_started_msec = Time.get_ticks_msec()
	_actions_started += 1
	action_started.emit(snapshot())
	return true


func finish_action(key: String, success: bool, message: String = "") -> bool:
	if not _busy:
		return false
	var normalized := key.strip_edges().to_lower()
	if normalized != "" and normalized != _key:
		return false

	var final_snapshot := snapshot()
	final_snapshot["success"] = success
	final_snapshot["message"] = message
	final_snapshot["elapsed_seconds"] = elapsed_seconds()
	_actions_finished += 1
	if not success:
		_actions_failed += 1

	_busy = false
	_key = ""
	_title = ""
	_detail = ""
	_steps = []
	_started_msec = 0
	action_finished.emit(final_snapshot)
	return true


func is_busy() -> bool:
	return _busy


func active_key() -> String:
	return _key


func elapsed_seconds() -> float:
	if not _busy or _started_msec <= 0:
		return 0.0
	return max(0.0, float(Time.get_ticks_msec() - _started_msec) / 1000.0)


func status_text() -> String:
	if not _busy:
		return ""
	if _steps.is_empty():
		return _detail
	var index := int(floor(elapsed_seconds() / STEP_INTERVAL_SECONDS))
	index = clamp(index, 0, _steps.size() - 1)
	return str(_steps[index])


func snapshot() -> Dictionary:
	return {
		"version": LONG_ACTION_MANAGER_VERSION,
		"busy": _busy,
		"key": _key,
		"title": _title,
		"detail": _detail,
		"status": status_text(),
		"elapsed_seconds": elapsed_seconds(),
		"actions_started": _actions_started,
		"actions_finished": _actions_finished,
		"actions_failed": _actions_failed,
		"rejected_starts": _rejected_starts,
	}
