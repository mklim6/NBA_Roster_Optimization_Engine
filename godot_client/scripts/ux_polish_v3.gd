class_name UxPolishV3
extends RefCounted

const DesignSystemV3 = preload("res://scripts/design_system_v3.gd")
const VERSION := "v3-ux-polish-batch-21a-v1.0.0-2026-10-04"

const BUTTON_HOVER_SCALE := Vector2(1.018, 1.018)
const BUTTON_PRESS_SCALE := Vector2(0.985, 0.985)
const BUTTON_REST_SCALE := Vector2.ONE
const PAGE_OFFSET_X := 14.0
const OVERLAY_START_SCALE := Vector2(0.985, 0.985)


static func animate_page_in(page: Control, _accent: Color = DesignSystemV3.ACCENT):
	if page == null:
		return null

	page.visible = true
	var final_position := page.position
	page.modulate = Color(1.0, 1.0, 1.0, 0.0)
	page.position = final_position + Vector2(PAGE_OFFSET_X, 0.0)

	var tween := page.create_tween()
	tween.set_parallel(true)
	tween.set_trans(Tween.TRANS_QUAD)
	tween.set_ease(Tween.EASE_OUT)
	tween.tween_property(
		page,
		"modulate:a",
		1.0,
		DesignSystemV3.MOTION_NORMAL
	)
	tween.tween_property(
		page,
		"position",
		final_position,
		DesignSystemV3.MOTION_NORMAL
	)
	return tween


static func animate_overlay_in(overlay: Control):
	if overlay == null:
		return null

	overlay.visible = true
	overlay.pivot_offset = overlay.size * 0.5
	overlay.modulate = Color(1.0, 1.0, 1.0, 0.0)
	overlay.scale = OVERLAY_START_SCALE

	var tween := overlay.create_tween()
	tween.set_parallel(true)
	tween.set_trans(Tween.TRANS_QUAD)
	tween.set_ease(Tween.EASE_OUT)
	tween.tween_property(
		overlay,
		"modulate:a",
		1.0,
		DesignSystemV3.MOTION_FAST
	)
	tween.tween_property(
		overlay,
		"scale",
		BUTTON_REST_SCALE,
		DesignSystemV3.MOTION_NORMAL
	)
	return tween


static func install_button_motion(root: Node) -> void:
	if root == null:
		return
	if root is Button:
		attach_button_motion(root)
	for child in root.get_children():
		install_button_motion(child)


static func attach_button_motion(button: Button) -> void:
	if button == null or button.has_meta("ux_motion_attached"):
		return

	button.set_meta("ux_motion_attached", true)
	button.mouse_entered.connect(func(): UxPolishV3._on_button_mouse_entered(button))
	button.mouse_exited.connect(func(): UxPolishV3._on_button_mouse_exited(button))
	button.button_down.connect(func(): UxPolishV3._on_button_down(button))
	button.button_up.connect(func(): UxPolishV3._on_button_up(button))


static func _on_button_mouse_entered(button: Button) -> void:
	if button == null or button.disabled:
		return
	_tween_button_scale(button, BUTTON_HOVER_SCALE)


static func _on_button_mouse_exited(button: Button) -> void:
	if button == null:
		return
	_tween_button_scale(button, BUTTON_REST_SCALE)


static func _on_button_down(button: Button) -> void:
	if button == null or button.disabled:
		return
	_tween_button_scale(button, BUTTON_PRESS_SCALE)


static func _on_button_up(button: Button) -> void:
	if button == null or button.disabled:
		return
	var target := BUTTON_HOVER_SCALE if button.is_hovered() else BUTTON_REST_SCALE
	_tween_button_scale(button, target)


static func _tween_button_scale(button: Button, target: Vector2) -> void:
	if button == null or not is_instance_valid(button):
		return

	button.pivot_offset = button.size * 0.5
	var previous = null
	if button.has_meta("ux_motion_tween"):
		previous = button.get_meta("ux_motion_tween")
	if previous is Tween and previous.is_valid():
		previous.kill()

	var tween := button.create_tween()
	button.set_meta("ux_motion_tween", tween)
	tween.set_trans(Tween.TRANS_QUAD)
	tween.set_ease(Tween.EASE_OUT)
	tween.tween_property(
		button,
		"scale",
		target,
		DesignSystemV3.MOTION_FAST
	)


static func animate_success_flash(control: Control, accent: Color = DesignSystemV3.GOOD) -> void:
	if control == null:
		return
	var base := control.modulate
	control.modulate = Color(
		lerpf(base.r, accent.r, 0.22),
		lerpf(base.g, accent.g, 0.22),
		lerpf(base.b, accent.b, 0.22),
		base.a
	)
	var tween := control.create_tween()
	tween.set_trans(Tween.TRANS_QUAD)
	tween.set_ease(Tween.EASE_OUT)
	tween.tween_property(control, "modulate", base, DesignSystemV3.MOTION_SLOW)


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
	if busy:
		button.scale = BUTTON_REST_SCALE


static func attach_tooltip(control: Control, text_value: String) -> void:
	if control == null:
		return
	control.tooltip_text = text_value
