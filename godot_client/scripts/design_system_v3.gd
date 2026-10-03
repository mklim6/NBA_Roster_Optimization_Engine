class_name DesignSystemV3
extends RefCounted

const VERSION := "v3-design-system-batch-19a-v1.0.0-2026-10-03"

const BG := Color("060910")
const BG_ELEVATED := Color("090d15")
const SIDEBAR := Color("0b1019")
const PANEL := Color("111824")
const PANEL_ALT := Color("172130")
const PANEL_HOVER := Color("202d40")
const PANEL_PRESSED := Color("0d131d")
const TEXT := Color("f5f7fb")
const TEXT_STRONG := Color("ffffff")
const MUTED := Color("9ba8bb")
const MUTED_DARK := Color("68778b")
const ACCENT := Color("72c7f5")
const ACCENT_HOVER := Color("9edcff")
const GOOD := Color("59d69a")
const WARNING := Color("f4c76a")
const BAD := Color("ff667a")
const BORDER := Color("2a3950")
const SOFT_BORDER := Color("1d2a3b")
const TEAM_PRIMARY := Color("d9273c")
const TEAM_PRIMARY_HOVER := Color("ef4055")
const GOLD := Color("f0c866")
const OVERLAY := Color(0.0, 0.0, 0.0, 0.78)

const FONT_MICRO := 9
const FONT_CAPTION := 10
const FONT_SMALL := 11
const FONT_BODY := 13
const FONT_BODY_LARGE := 14
const FONT_SECTION := 18
const FONT_SUBTITLE := 22
const FONT_TITLE := 32
const FONT_HERO := 36

const SPACE_XS := 4
const SPACE_SM := 8
const SPACE_MD := 12
const SPACE_LG := 16
const SPACE_XL := 20
const SPACE_2XL := 28

const RADIUS_SM := 7
const RADIUS_MD := 11
const RADIUS_LG := 15
const RADIUS_XL := 18

const MOTION_FAST := 0.10
const MOTION_NORMAL := 0.18
const MOTION_SLOW := 0.28

const TEAM_BRANDS := {
	"ATL": {"primary": Color("e03a3e"), "secondary": Color("c1d32f")},
	"BOS": {"primary": Color("007a33"), "secondary": Color("ba9653")},
	"BKN": {"primary": Color("000000"), "secondary": Color("ffffff")},
	"CHA": {"primary": Color("1d1160"), "secondary": Color("00788c")},
	"CHI": {"primary": Color("ce1141"), "secondary": Color("000000")},
	"CLE": {"primary": Color("860038"), "secondary": Color("fdbb30")},
	"DAL": {"primary": Color("00538c"), "secondary": Color("002b5e")},
	"DEN": {"primary": Color("0e2240"), "secondary": Color("fec524")},
	"DET": {"primary": Color("c8102e"), "secondary": Color("1d42ba")},
	"GSW": {"primary": Color("1d428a"), "secondary": Color("ffc72c")},
	"HOU": {"primary": Color("ce1141"), "secondary": Color("000000")},
	"IND": {"primary": Color("002d62"), "secondary": Color("fdbb30")},
	"LAC": {"primary": Color("c8102e"), "secondary": Color("1d428a")},
	"LAL": {"primary": Color("552583"), "secondary": Color("fdb927")},
	"MEM": {"primary": Color("5d76a9"), "secondary": Color("12173f")},
	"MIA": {"primary": Color("98002e"), "secondary": Color("f9a01b")},
	"MIL": {"primary": Color("00471b"), "secondary": Color("eee1c6")},
	"MIN": {"primary": Color("0c2340"), "secondary": Color("78be20")},
	"NOP": {"primary": Color("0c2340"), "secondary": Color("c8102e")},
	"NYK": {"primary": Color("006bb6"), "secondary": Color("f58426")},
	"OKC": {"primary": Color("007ac1"), "secondary": Color("ef3b24")},
	"ORL": {"primary": Color("0077c0"), "secondary": Color("c4ced4")},
	"PHI": {"primary": Color("006bb6"), "secondary": Color("ed174c")},
	"PHX": {"primary": Color("1d1160"), "secondary": Color("e56020")},
	"POR": {"primary": Color("e03a3e"), "secondary": Color("000000")},
	"SAC": {"primary": Color("5a2d81"), "secondary": Color("63727a")},
	"SAS": {"primary": Color("c4ced4"), "secondary": Color("000000")},
	"TOR": {"primary": Color("ce1141"), "secondary": Color("000000")},
	"UTA": {"primary": Color("002b5c"), "secondary": Color("f9a01b")},
	"WAS": {"primary": Color("002b5c"), "secondary": Color("e31837")},
}

static func team_palette(team_abbreviation: String) -> Dictionary:
	var key := team_abbreviation.strip_edges().to_upper()
	var found = TEAM_BRANDS.get(key)
	if found is Dictionary:
		return {"primary": found.get("primary", TEAM_PRIMARY), "secondary": found.get("secondary", TEXT)}
	return {"primary": TEAM_PRIMARY, "secondary": TEXT}

static func style_box(
	fill: Color,
	radius: int = RADIUS_MD,
	border: Color = SOFT_BORDER,
	border_width: int = 1,
	shadow_strength: float = 0.0
) -> StyleBoxFlat:
	var box := StyleBoxFlat.new()
	box.bg_color = fill
	box.border_color = border
	box.border_width_left = border_width
	box.border_width_top = border_width
	box.border_width_right = border_width
	box.border_width_bottom = border_width
	box.corner_radius_top_left = radius
	box.corner_radius_top_right = radius
	box.corner_radius_bottom_left = radius
	box.corner_radius_bottom_right = radius
	box.content_margin_left = 12.0
	box.content_margin_top = 9.0
	box.content_margin_right = 12.0
	box.content_margin_bottom = 9.0
	if shadow_strength > 0.0:
		box.shadow_color = Color(0.0, 0.0, 0.0, clamp(shadow_strength, 0.0, 0.55))
		box.shadow_size = 7
	return box

static func _button_box(fill: Color, border: Color) -> StyleBoxFlat:
	var box := style_box(fill, RADIUS_MD, border, 1, 0.16)
	box.content_margin_left = 15.0
	box.content_margin_right = 15.0
	box.content_margin_top = 9.0
	box.content_margin_bottom = 9.0
	return box

static func _field_box(fill: Color, border: Color) -> StyleBoxFlat:
	var box := style_box(fill, RADIUS_SM, border, 1, 0.0)
	box.content_margin_left = 11.0
	box.content_margin_right = 11.0
	box.content_margin_top = 8.0
	box.content_margin_bottom = 8.0
	return box

static func build_theme() -> Theme:
	var ui := Theme.new()
	ui.default_font_size = FONT_BODY

	ui.set_color("font_color", "Label", TEXT)
	ui.set_color("font_shadow_color", "Label", Color(0, 0, 0, 0.38))
	ui.set_constant("shadow_offset_x", "Label", 0)
	ui.set_constant("shadow_offset_y", "Label", 1)

	ui.set_color("font_color", "Button", TEXT)
	ui.set_color("font_hover_color", "Button", TEXT_STRONG)
	ui.set_color("font_pressed_color", "Button", TEXT_STRONG)
	ui.set_color("font_disabled_color", "Button", MUTED_DARK)
	ui.set_font_size("font_size", "Button", FONT_SMALL)
	ui.set_stylebox("normal", "Button", _button_box(PANEL_ALT, BORDER))
	ui.set_stylebox("hover", "Button", _button_box(PANEL_HOVER, ACCENT))
	ui.set_stylebox("pressed", "Button", _button_box(PANEL_PRESSED, ACCENT))
	ui.set_stylebox("disabled", "Button", _button_box(Color(PANEL_ALT, 0.48), Color(SOFT_BORDER, 0.65)))
	ui.set_stylebox("focus", "Button", _button_box(Color(PANEL_HOVER, 0.82), ACCENT))

	ui.set_color("font_color", "LineEdit", TEXT)
	ui.set_color("font_placeholder_color", "LineEdit", MUTED_DARK)
	ui.set_color("caret_color", "LineEdit", ACCENT)
	ui.set_color("selection_color", "LineEdit", Color(ACCENT, 0.28))
	ui.set_font_size("font_size", "LineEdit", FONT_BODY)
	ui.set_stylebox("normal", "LineEdit", _field_box(BG_ELEVATED, SOFT_BORDER))
	ui.set_stylebox("focus", "LineEdit", _field_box(BG_ELEVATED, ACCENT))
	ui.set_stylebox("read_only", "LineEdit", _field_box(Color(PANEL_ALT, 0.60), SOFT_BORDER))

	ui.set_color("font_color", "OptionButton", TEXT)
	ui.set_color("font_hover_color", "OptionButton", TEXT_STRONG)
	ui.set_font_size("font_size", "OptionButton", FONT_BODY)
	ui.set_stylebox("normal", "OptionButton", _field_box(BG_ELEVATED, SOFT_BORDER))
	ui.set_stylebox("hover", "OptionButton", _field_box(PANEL_HOVER, BORDER))
	ui.set_stylebox("pressed", "OptionButton", _field_box(PANEL_PRESSED, ACCENT))
	ui.set_stylebox("focus", "OptionButton", _field_box(BG_ELEVATED, ACCENT))

	ui.set_color("font_color", "CheckBox", TEXT)
	ui.set_color("font_hover_color", "CheckBox", TEXT_STRONG)
	ui.set_color("font_pressed_color", "CheckBox", ACCENT_HOVER)
	ui.set_font_size("font_size", "CheckBox", FONT_SMALL)

	ui.set_stylebox("panel", "PanelContainer", style_box(PANEL, RADIUS_LG, SOFT_BORDER, 1, 0.14))
	ui.set_stylebox("panel", "TooltipPanel", style_box(Color("121a27"), RADIUS_SM, BORDER, 1, 0.22))
	ui.set_color("font_color", "TooltipLabel", TEXT)
	ui.set_font_size("font_size", "TooltipLabel", FONT_SMALL)

	ui.set_color("font_color", "PopupMenu", TEXT)
	ui.set_color("font_hover_color", "PopupMenu", TEXT_STRONG)
	ui.set_color("font_accelerator_color", "PopupMenu", MUTED)
	ui.set_stylebox("panel", "PopupMenu", style_box(BG_ELEVATED, RADIUS_SM, BORDER, 1, 0.24))
	ui.set_stylebox("hover", "PopupMenu", style_box(PANEL_HOVER, RADIUS_SM, Color(PANEL_HOVER, 0.0), 0, 0.0))
	return ui
