extends RefCounted

const REQUEST_COORDINATOR_VERSION := "v3-request-coordinator-batch-18b-v1.0.0-2026-10-03"
const DEFAULT_REUSE_WINDOW_MS := 1250

var reuse_window_ms: int = DEFAULT_REUSE_WINDOW_MS
var _in_flight: Dictionary = {}
var _last_success_msec: Dictionary = {}
var _started_msec: Dictionary = {}
var _suppressed_in_flight := 0
var _suppressed_recent := 0
var _requests_started := 0
var _requests_completed := 0
var _requests_failed := 0


func _normalize_key(key: String) -> String:
	return key.strip_edges().to_lower()


func begin_request(key: String, force: bool = false) -> bool:
	var normalized := _normalize_key(key)
	if normalized == "":
		return true

	var now := Time.get_ticks_msec()
	if not force:
		if bool(_in_flight.get(normalized, false)):
			_suppressed_in_flight += 1
			return false

		var last_success := int(_last_success_msec.get(normalized, -1000000000))
		if now - last_success < reuse_window_ms:
			_suppressed_recent += 1
			return false

	_in_flight[normalized] = true
	_started_msec[normalized] = now
	_requests_started += 1
	return true


func finish_request(key: String, success: bool) -> void:
	var normalized := _normalize_key(key)
	if normalized == "":
		return

	_in_flight.erase(normalized)
	_started_msec.erase(normalized)
	_requests_completed += 1
	if success:
		_last_success_msec[normalized] = Time.get_ticks_msec()
	else:
		_requests_failed += 1
		_last_success_msec.erase(normalized)


func invalidate(key: String) -> void:
	var normalized := _normalize_key(key)
	if normalized == "":
		return
	_in_flight.erase(normalized)
	_started_msec.erase(normalized)
	_last_success_msec.erase(normalized)


func invalidate_all() -> void:
	_in_flight.clear()
	_started_msec.clear()
	_last_success_msec.clear()


func is_in_flight(key: String) -> bool:
	return bool(_in_flight.get(_normalize_key(key), false))


func snapshot() -> Dictionary:
	return {
		"version": REQUEST_COORDINATOR_VERSION,
		"reuse_window_ms": reuse_window_ms,
		"in_flight": _in_flight.keys(),
		"requests_started": _requests_started,
		"requests_completed": _requests_completed,
		"requests_failed": _requests_failed,
		"suppressed_in_flight": _suppressed_in_flight,
		"suppressed_recent": _suppressed_recent,
	}
