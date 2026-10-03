class_name UxPolishV3
extends RefCounted

const DesignSystemV3 = preload("res://scripts/design_system_v3.gd")
const VERSION := "v3-ux-polish-batch-19d-v1.0.0-2026-10-03"


static func animate_page_in(page: Control, _accent: Color = DesignSystemV3.ACCENT):
	if page == null:
		return null

	page.visible = true
	page.modulate = Color(1.0, 1.0, 1.0, 0.0)

	var tween := page.create_tween()
	tween.set_trans(Tween.TRANS_QUAD)
	tween.set_ease(Tween.EASE_OUT)
	tween.tween_property(
		page,
		"modulate:a",
		1.0,
		DesignSystemV3.MOTION_NORMAL
	)
	return tween


static func animate_overlay_in(overlay: Control):
	if overlay == null:
		return null

	overlay.visible = true
	overlay.modulate = Color(1.0, 1.0, 1.0, 0.0)

	var tween := overlay.create_tween()
	tween.set_trans(Tween.TRANS_QUAD)
	tween.set_ease(Tween.EASE_OUT)
	tween.tween_property(
		overlay,
		"modulate:a",
		1.0,
		DesignSystemV3.MOTION_FAST
	)
	return tween


static func set_button_busy(
	button: Button,
	busy: bool,
	busy_text: String,
	ready_text: String
) -> void:
	if button == null:
		return
	button.disabled = busy
	button.text = busy_text if busy else ready_text


static func attach_tooltip(control: Control, text_value: String) -> void:
	if control == null:
		return
	control.tooltip_text = text_value
