extends Control

# 50A.4 hero-only portrait: transparent broadcast cutout with a compact nameplate.
const VERSION := "v3-visual-overhaul-50a4-hero-player-v1.0.0-2026-10-05"
const DS = preload("res://scripts/design_system_v3.gd")
const CACHE_DIR := "user://v3_media_cache/player_headshots"

const STOCK_PORTRAITS := [
	"pexels_basketball_20615464.jpg",
	"pexels_basketball_16933611.jpg",
	"pexels_basketball_37918084.jpg",
	"pexels_basketball_32600307.jpg",
	"pexels_basketball_32759162.jpg",
	"pexels_basketball_15670134.jpg",
	"pexels_basketball_8980782.jpg",
	"pexels_basketball_10476654.jpg",
	"pexels_basketball_18078520.jpg",
	"pexels_basketball_8979932.jpg",
	"pexels_basketball_32036155.jpg",
	"pexels_basketball_8980808.jpg",
]

var texture_rect: TextureRect
var fallback_label: Label
var name_label: Label
var meta_label: Label
var request: HTTPRequest
var configured_player_id := ""
var configured_name := ""
var configured_generated := false
var accent := Color("007a33")
var featured := false


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	clip_contents = false

	texture_rect = TextureRect.new()
	texture_rect.mouse_filter = Control.MOUSE_FILTER_IGNORE
	texture_rect.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	texture_rect.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	texture_rect.set_anchors_preset(Control.PRESET_FULL_RECT)
	texture_rect.offset_bottom = -28
	texture_rect.visible = false
	add_child(texture_rect)

	fallback_label = Label.new()
	fallback_label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	fallback_label.set_anchors_preset(Control.PRESET_FULL_RECT)
	fallback_label.offset_bottom = -28
	fallback_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	fallback_label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	fallback_label.add_theme_color_override("font_color", DS.TEXT)
	fallback_label.add_theme_font_size_override("font_size", 18)
	add_child(fallback_label)

	var plate := PanelContainer.new()
	plate.mouse_filter = Control.MOUSE_FILTER_IGNORE
	plate.anchor_left = 0.08
	plate.anchor_right = 0.92
	plate.anchor_top = 1.0
	plate.anchor_bottom = 1.0
	plate.offset_top = -37
	plate.offset_bottom = -2
	plate.add_theme_stylebox_override(
		"panel",
		DS.style_box(Color(Color("070a10"), 0.78), 8, Color(accent, 0.16), 1, 0.0)
	)
	add_child(plate)
	plate.set_meta("hero_name_plate", true)

	var copy := VBoxContainer.new()
	copy.alignment = BoxContainer.ALIGNMENT_CENTER
	copy.add_theme_constant_override("separation", 0)
	plate.add_child(copy)

	name_label = Label.new()
	name_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	name_label.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	name_label.add_theme_color_override("font_color", DS.TEXT_STRONG)
	name_label.add_theme_font_size_override("font_size", 10)
	copy.add_child(name_label)

	meta_label = Label.new()
	meta_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	meta_label.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	meta_label.add_theme_color_override("font_color", accent.lightened(0.30))
	meta_label.add_theme_font_size_override("font_size", 7)
	copy.add_child(meta_label)

	request = HTTPRequest.new()
	request.timeout = 8.0
	request.request_completed.connect(_on_request_completed)
	add_child(request)


func apply_team_brand(next_accent: Color) -> void:
	accent = next_accent
	if meta_label != null:
		meta_label.add_theme_color_override("font_color", accent.lightened(0.34))
	for child in get_children():
		if child is PanelContainer and bool(child.get_meta("hero_name_plate", false)):
			child.add_theme_stylebox_override(
				"panel",
				DS.style_box(Color(Color("070a10"), 0.78), 8, Color(accent, 0.16), 1, 0.0)
			)


func configure(player: Dictionary, next_accent: Color, is_featured: bool = false) -> void:
	accent = next_accent
	featured = is_featured
	configured_player_id = str(player.get("player_id", "")).strip_edges()
	configured_name = str(player.get("name", "Unknown Player")).strip_edges()
	configured_generated = bool(player.get("generated_prospect", false))

	if fallback_label == null:
		call_deferred("configure", player, next_accent, is_featured)
		return

	apply_team_brand(accent)
	name_label.text = configured_name
	name_label.add_theme_font_size_override("font_size", 11 if featured else 9)
	var position := str(player.get("position", ""))
	var overall = player.get("overall", null)
	meta_label.text = "%s  •  OVR %s" % [position, "--" if overall == null else str(int(round(float(overall))))]
	fallback_label.text = _initials(configured_name)
	fallback_label.visible = true
	texture_rect.visible = false

	if request != null:
		request.cancel_request()

	if configured_generated:
		_load_generated_stock()
	elif configured_player_id.is_valid_int():
		_load_real_player_headshot()
	else:
		_show_fallback()


func _load_real_player_headshot() -> void:
	var cache_path := "%s/%s.png" % [CACHE_DIR, configured_player_id]
	if FileAccess.file_exists(cache_path):
		var image := Image.new()
		if image.load(cache_path) == OK:
			_apply_image(image)
			return

	var remote_url := "https://cdn.nba.com/headshots/nba/latest/260x190/%s.png" % configured_player_id
	if request.request(remote_url) != OK:
		_show_fallback()


func _load_generated_stock() -> void:
	var stock_root := ProjectSettings.globalize_path("res://../assets/generated_player_stock_portraits")
	if STOCK_PORTRAITS.is_empty():
		_show_fallback()
		return
	var start_index: int = abs(int(configured_player_id.hash())) % int(STOCK_PORTRAITS.size())
	for offset in range(STOCK_PORTRAITS.size()):
		var index: int = (start_index + int(offset)) % int(STOCK_PORTRAITS.size())
		var candidate := stock_root.path_join(STOCK_PORTRAITS[index])
		if not FileAccess.file_exists(candidate):
			continue
		var image := Image.new()
		if image.load(candidate) == OK:
			_apply_image(image)
			return
	_show_fallback()


func _on_request_completed(
	_result: int,
	response_code: int,
	_headers: PackedStringArray,
	body: PackedByteArray
) -> void:
	if response_code != 200 or body.is_empty():
		_show_fallback()
		return
	var image := Image.new()
	if image.load_png_from_buffer(body) != OK:
		_show_fallback()
		return
	var absolute_cache_dir := ProjectSettings.globalize_path(CACHE_DIR)
	DirAccess.make_dir_recursive_absolute(absolute_cache_dir)
	var cache_path := "%s/%s.png" % [CACHE_DIR, configured_player_id]
	image.save_png(cache_path)
	_apply_image(image)


func _apply_image(image: Image) -> void:
	if image == null or image.is_empty():
		_show_fallback()
		return
	texture_rect.texture = ImageTexture.create_from_image(image)
	texture_rect.visible = true
	fallback_label.visible = false


func _show_fallback() -> void:
	texture_rect.visible = false
	fallback_label.visible = true


func _initials(name_value: String) -> String:
	var pieces := name_value.split(" ", false)
	if pieces.is_empty():
		return "NBA"
	if pieces.size() == 1:
		return str(pieces[0]).left(2).to_upper()
	return (str(pieces[0]).left(1) + str(pieces[pieces.size() - 1]).left(1)).to_upper()
