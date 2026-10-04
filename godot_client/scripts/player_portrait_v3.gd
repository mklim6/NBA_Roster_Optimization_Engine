extends PanelContainer

const DesignSystemV3 = preload("res://scripts/design_system_v3.gd")
const VERSION := "v3-player-portrait-batch-20a-v1.0.0-2026-10-03"
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
var request: HTTPRequest
var configured_player_id := ""
var configured_name := ""
var configured_generated := false


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_theme_stylebox_override(
		"panel",
		DesignSystemV3.style_box(
			DesignSystemV3.PANEL_PRESSED,
			DesignSystemV3.RADIUS_SM,
			DesignSystemV3.BORDER,
			1,
			0.0
		)
	)

	texture_rect = TextureRect.new()
	texture_rect.mouse_filter = Control.MOUSE_FILTER_IGNORE
	texture_rect.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	texture_rect.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	texture_rect.visible = false
	add_child(texture_rect)

	fallback_label = Label.new()
	fallback_label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	fallback_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	fallback_label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	fallback_label.add_theme_color_override("font_color", DesignSystemV3.TEXT)
	fallback_label.add_theme_font_size_override("font_size", 12)
	add_child(fallback_label)

	request = HTTPRequest.new()
	request.timeout = 8.0
	request.request_completed.connect(_on_request_completed)
	add_child(request)


func configure(player: Dictionary) -> void:
	# A reused portrait must discard the previous player's in-flight request.
	if request != null and str(player.get("player_id", "")).strip_edges() != configured_player_id:
		request.cancel_request()
	configured_player_id = str(player.get("player_id", "")).strip_edges()
	configured_name = str(player.get("name", "Unknown Player")).strip_edges()
	configured_generated = bool(player.get("generated_prospect", false))

	if fallback_label == null:
		call_deferred("configure", player)
		return

	fallback_label.text = _initials(configured_name)
	fallback_label.visible = true
	texture_rect.visible = false

	if configured_generated:
		_load_generated_stock()
		return

	if configured_player_id.is_valid_int():
		_load_real_player_headshot()


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
	var stock_root := ProjectSettings.globalize_path(
		"res://../assets/generated_player_stock_portraits"
	)
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
	return (
		str(pieces[0]).left(1)
		+ str(pieces[pieces.size() - 1]).left(1)
	).to_upper()
