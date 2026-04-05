from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

REPORT_BRANDING_VERSION = "chip_concept_a_v1"

BRAND_NAME = "Community Health Intelligence Platform"
BRAND_TAGLINE = "Local Data. Strategic Insight."
FOOTER_LEFT_TEXT = f"CHIP • {BRAND_TAGLINE}"

PRIMARY_NAVY_HEX = "#0F2D46"
SECONDARY_SLATE_BLUE_HEX = "#2C5F8A"
TEAL_ACCENT_HEX = "#1FA3A3"
BACKGROUND_NEUTRAL_HEX = "#F4F6F8"
BODY_TEXT_HEX = "#1f2937"
CAPTION_TEXT_HEX = "#374151"
AXIS_TEXT_HEX = "#334155"
GRIDLINE_HEX = "#E5E7EB"
TABLE_BORDER_HEX = "#E3E8ED"
TABLE_HEADER_BG_HEX = "#EEF3F7"
TABLE_ZEBRA_BG_HEX = "#F9FBFD"
HEADER_RIGHT_TEXT_HEX = "#E5EDF3"
FOOTER_TEXT_HEX = "#4B5563"

PRIMARY_NAVY = colors.HexColor(PRIMARY_NAVY_HEX)
SECONDARY_SLATE_BLUE = colors.HexColor(SECONDARY_SLATE_BLUE_HEX)
TEAL_ACCENT = colors.HexColor(TEAL_ACCENT_HEX)
BACKGROUND_NEUTRAL = colors.HexColor(BACKGROUND_NEUTRAL_HEX)
BODY_TEXT = colors.HexColor(BODY_TEXT_HEX)
CAPTION_TEXT = colors.HexColor(CAPTION_TEXT_HEX)
AXIS_TEXT = colors.HexColor(AXIS_TEXT_HEX)
GRIDLINE = colors.HexColor(GRIDLINE_HEX)
TABLE_BORDER = colors.HexColor(TABLE_BORDER_HEX)
TABLE_HEADER_BG = colors.HexColor(TABLE_HEADER_BG_HEX)
TABLE_ZEBRA_BG = colors.HexColor(TABLE_ZEBRA_BG_HEX)
HEADER_RIGHT_TEXT = colors.HexColor(HEADER_RIGHT_TEXT_HEX)
FOOTER_TEXT = colors.HexColor(FOOTER_TEXT_HEX)

PAGE_WIDTH, PAGE_HEIGHT = letter

DOC_LEFT_MARGIN = 0.78 * inch
DOC_RIGHT_MARGIN = 0.78 * inch
DOC_TOP_MARGIN = 1.06 * inch
DOC_BOTTOM_MARGIN = 0.86 * inch
HEADER_BAR_HEIGHT = 0.56 * inch
FOOTER_DIVIDER_Y = 0.62 * inch
FOOTER_TEXT_Y = 0.34 * inch

APP_ROOT = Path(__file__).resolve().parents[1]
ASSETS_DIR = APP_ROOT / "assets"
BRAND_ASSETS_DIR = ASSETS_DIR / "brand"
FONTS_DIR = ASSETS_DIR / "fonts"

LOGO_MONO_SMALL_PNG = BRAND_ASSETS_DIR / "chip-logo-monochrome-dark-small.png"
LOGO_FALLBACK_SMALL_PNG = BRAND_ASSETS_DIR / "chip-logo-fullcolor-light-small.png"


def _register_font(alias: str, path: Path) -> bool:
    if not path.exists():
        return False
    if alias in pdfmetrics.getRegisteredFontNames():
        return True
    try:
        pdfmetrics.registerFont(TTFont(alias, str(path)))
    except Exception:
        return False
    return True


@lru_cache(maxsize=1)
def reportlab_fonts() -> dict[str, str]:
    inter_regular = FONTS_DIR / "Inter-Regular.ttf"
    inter_semibold = FONTS_DIR / "Inter-SemiBold.ttf"
    inter_italic = FONTS_DIR / "Inter-Italic.ttf"
    if (
        _register_font("Inter-Regular", inter_regular)
        and _register_font("Inter-SemiBold", inter_semibold)
        and _register_font("Inter-Italic", inter_italic)
    ):
        return {
            "regular": "Inter-Regular",
            "semibold": "Inter-SemiBold",
            "bold": "Inter-SemiBold",
            "italic": "Inter-Italic",
        }

    source_regular = FONTS_DIR / "SourceSans3-Regular.ttf"
    source_semibold = FONTS_DIR / "SourceSans3-SemiBold.ttf"
    source_italic = FONTS_DIR / "SourceSans3-Italic.ttf"
    if (
        _register_font("SourceSans3-Regular", source_regular)
        and _register_font("SourceSans3-SemiBold", source_semibold)
        and _register_font("SourceSans3-Italic", source_italic)
    ):
        return {
            "regular": "SourceSans3-Regular",
            "semibold": "SourceSans3-SemiBold",
            "bold": "SourceSans3-SemiBold",
            "italic": "SourceSans3-Italic",
        }

    return {
        "regular": "Helvetica",
        "semibold": "Helvetica-Bold",
        "bold": "Helvetica-Bold",
        "italic": "Helvetica-Oblique",
    }


def chart_font_families() -> list[str]:
    return ["Inter", "Source Sans 3", "DejaVu Sans"]


def full_report_styles() -> dict[str, ParagraphStyle]:
    sample_styles = getSampleStyleSheet()
    fonts = reportlab_fonts()
    return {
        "title": ParagraphStyle(
            "ChipFullTitle",
            parent=sample_styles["Title"],
            fontName=fonts["semibold"],
            fontSize=20,
            leading=24,
            textColor=PRIMARY_NAVY,
            spaceAfter=3,
        ),
        "subtitle": ParagraphStyle(
            "ChipFullSubtitle",
            parent=sample_styles["BodyText"],
            fontName=fonts["regular"],
            fontSize=10,
            leading=13,
            textColor=SECONDARY_SLATE_BLUE,
            spaceAfter=4,
        ),
        "h2": ParagraphStyle(
            "ChipFullH2",
            parent=sample_styles["Heading2"],
            fontName=fonts["semibold"],
            fontSize=13,
            leading=16,
            textColor=PRIMARY_NAVY,
            spaceBefore=7,
            spaceAfter=5,
        ),
        "h3": ParagraphStyle(
            "ChipFullH3",
            parent=sample_styles["Heading3"],
            fontName=fonts["semibold"],
            fontSize=12,
            leading=15,
            textColor=PRIMARY_NAVY,
            spaceBefore=3,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "ChipFullBody",
            parent=sample_styles["BodyText"],
            fontName=fonts["regular"],
            fontSize=10.5,
            leading=14,
            textColor=BODY_TEXT,
            spaceAfter=4,
        ),
        "caption": ParagraphStyle(
            "ChipFullCaption",
            parent=sample_styles["BodyText"],
            fontName=fonts["regular"],
            fontSize=9,
            leading=11.5,
            textColor=CAPTION_TEXT,
            spaceAfter=4,
        ),
        "small": ParagraphStyle(
            "ChipFullSmall",
            parent=sample_styles["BodyText"],
            fontName=fonts["regular"],
            fontSize=9,
            leading=12,
            textColor=AXIS_TEXT,
            spaceAfter=3,
        ),
    }


def brief_report_styles() -> dict[str, ParagraphStyle]:
    sample_styles = getSampleStyleSheet()
    fonts = reportlab_fonts()
    return {
        "title": ParagraphStyle(
            "ChipBriefTitle",
            parent=sample_styles["Title"],
            fontName=fonts["semibold"],
            fontSize=19,
            leading=23,
            textColor=PRIMARY_NAVY,
            spaceAfter=3,
        ),
        "subtitle": ParagraphStyle(
            "ChipBriefSubtitle",
            parent=sample_styles["BodyText"],
            fontName=fonts["regular"],
            fontSize=10,
            leading=13,
            textColor=SECONDARY_SLATE_BLUE,
            spaceAfter=3,
        ),
        "note": ParagraphStyle(
            "ChipBriefNote",
            parent=sample_styles["BodyText"],
            fontName=fonts["italic"],
            fontSize=9,
            leading=11,
            textColor=CAPTION_TEXT,
            spaceAfter=6,
        ),
        "h2": ParagraphStyle(
            "ChipBriefH2",
            parent=sample_styles["Heading2"],
            fontName=fonts["semibold"],
            fontSize=12.5,
            leading=15,
            textColor=PRIMARY_NAVY,
            spaceBefore=4,
            spaceAfter=3,
        ),
        "body": ParagraphStyle(
            "ChipBriefBody",
            parent=sample_styles["BodyText"],
            fontName=fonts["regular"],
            fontSize=10.25,
            leading=13.5,
            textColor=BODY_TEXT,
            spaceAfter=3,
        ),
        "small": ParagraphStyle(
            "ChipBriefSmall",
            parent=sample_styles["BodyText"],
            fontName=fonts["regular"],
            fontSize=9,
            leading=11.5,
            textColor=AXIS_TEXT,
            spaceAfter=2,
        ),
    }


def standard_table_style_commands(
    *,
    font_size: float = 9.0,
    right_align_columns: list[int] | None = None,
) -> list[tuple[Any, ...]]:
    fonts = reportlab_fonts()
    commands: list[tuple[Any, ...]] = [
        ("BACKGROUND", (0, 0), (-1, 0), TABLE_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), PRIMARY_NAVY),
        ("FONTNAME", (0, 0), (-1, 0), fonts["semibold"]),
        ("FONTNAME", (0, 1), (-1, -1), fonts["regular"]),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ("GRID", (0, 0), (-1, -1), 0.45, TABLE_BORDER),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, TABLE_ZEBRA_BG]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5.5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, 0), "LEFT"),
    ]
    for column_index in (right_align_columns or []):
        commands.append(("ALIGN", (column_index, 1), (column_index, -1), "RIGHT"))
    return commands


def compact_table_style_commands(
    *,
    font_size: float = 8.6,
    right_align_columns: list[int] | None = None,
) -> list[tuple[Any, ...]]:
    return standard_table_style_commands(
        font_size=font_size,
        right_align_columns=right_align_columns,
    )


@lru_cache(maxsize=1)
def _logo_reader() -> ImageReader | None:
    for candidate in (LOGO_MONO_SMALL_PNG, LOGO_FALLBACK_SMALL_PNG):
        if not candidate.exists():
            continue
        try:
            return ImageReader(str(candidate))
        except Exception:
            continue
    return None


def draw_page_chrome(pdf_canvas: canvas.Canvas, page_number: int, page_count: int) -> None:
    fonts = reportlab_fonts()
    pdf_canvas.saveState()

    pdf_canvas.setFillColor(PRIMARY_NAVY)
    pdf_canvas.rect(0, PAGE_HEIGHT - HEADER_BAR_HEIGHT, PAGE_WIDTH, HEADER_BAR_HEIGHT, stroke=0, fill=1)

    logo_reader = _logo_reader()
    if logo_reader is not None:
        logo_width, logo_height = logo_reader.getSize()
        if logo_width > 0 and logo_height > 0:
            target_height = HEADER_BAR_HEIGHT - 0.12 * inch
            target_width = target_height * (float(logo_width) / float(logo_height))
            target_width = min(target_width, 1.6 * inch)
            logo_x = DOC_LEFT_MARGIN
            logo_y = PAGE_HEIGHT - HEADER_BAR_HEIGHT + ((HEADER_BAR_HEIGHT - target_height) / 2.0)
            pdf_canvas.drawImage(
                logo_reader,
                logo_x,
                logo_y,
                width=target_width,
                height=target_height,
                mask="auto",
                preserveAspectRatio=True,
                anchor="sw",
            )
    else:
        pdf_canvas.setFillColor(colors.white)
        pdf_canvas.setFont(fonts["semibold"], 8.5)
        pdf_canvas.drawString(DOC_LEFT_MARGIN, PAGE_HEIGHT - HEADER_BAR_HEIGHT + 0.18 * inch, "CHIP")

    pdf_canvas.setFillColor(HEADER_RIGHT_TEXT)
    pdf_canvas.setFont(fonts["regular"], 8.2)
    pdf_canvas.drawRightString(
        PAGE_WIDTH - DOC_RIGHT_MARGIN,
        PAGE_HEIGHT - HEADER_BAR_HEIGHT + 0.21 * inch,
        BRAND_NAME,
    )

    pdf_canvas.setStrokeColor(TABLE_BORDER)
    pdf_canvas.setLineWidth(0.8)
    pdf_canvas.line(DOC_LEFT_MARGIN, FOOTER_DIVIDER_Y, PAGE_WIDTH - DOC_RIGHT_MARGIN, FOOTER_DIVIDER_Y)

    pdf_canvas.setFillColor(FOOTER_TEXT)
    pdf_canvas.setFont(fonts["regular"], 8.2)
    pdf_canvas.drawString(DOC_LEFT_MARGIN, FOOTER_TEXT_Y, FOOTER_LEFT_TEXT)
    pdf_canvas.drawRightString(
        PAGE_WIDTH - DOC_RIGHT_MARGIN,
        FOOTER_TEXT_Y,
        f"Page {page_number} of {page_count}",
    )
    pdf_canvas.restoreState()


class BrandedNumberedCanvas(canvas.Canvas):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict[str, Any]] = []

    def showPage(self) -> None:
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        if not self._saved_page_states:
            self._saved_page_states.append(dict(self.__dict__))

        page_count = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            draw_page_chrome(self, self._pageNumber, page_count)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)
