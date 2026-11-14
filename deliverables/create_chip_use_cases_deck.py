#!/usr/bin/env python3
"""Create a five-slide, editable CHIP/PDO use-case presentation."""

from pathlib import Path
import sys


DEPS = Path("/tmp/chip-slide-deps")
if DEPS.exists():
    sys.path.insert(0, str(DEPS))

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_AUTO_SHAPE_TYPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.enum.dml import MSO_LINE_DASH_STYLE
from pptx.util import Inches, Pt


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "deliverables" / "CHIP_Community_Health_Use_Cases.pptx"
PDO_MARK = ROOT / "branding" / "pdo" / "pdo-observatory-mark.png"


COLORS = {
    "navy": "003F61",
    "blue": "3576BA",
    "blue_dark": "014F7A",
    "blue_soft": "9ABBDD",
    "peach": "F0B97D",
    "peach_soft": "FFD5B0",
    "bg": "F4F7FB",
    "panel": "FFFFFF",
    "text": "123247",
    "slate": "546E7A",
    "line": "CFD8DC",
    "teal": "178B8B",
    "white": "FFFFFF",
}

HEADLINE = "Roboto Slab"
BODY = "Arial"


def rgb(hex_color):
    return RGBColor.from_string(COLORS.get(hex_color, hex_color))


def add_rect(slide, x, y, w, h, fill, line=None, radius=True, line_width=1, dash=None):
    shape_type = MSO_AUTO_SHAPE_TYPE.ROUNDED_RECTANGLE if radius else MSO_AUTO_SHAPE_TYPE.RECTANGLE
    shape = slide.shapes.add_shape(shape_type, Inches(x), Inches(y), Inches(w), Inches(h))
    shape.fill.solid()
    shape.fill.fore_color.rgb = rgb(fill)
    if line:
        shape.line.color.rgb = rgb(line)
        shape.line.width = Pt(line_width)
        if dash:
            shape.line.dash_style = dash
    else:
        shape.line.fill.background()
    return shape


def add_text(
    slide,
    text,
    x,
    y,
    w,
    h,
    size=18,
    color="text",
    font=BODY,
    bold=False,
    align=PP_ALIGN.LEFT,
    valign=MSO_ANCHOR.TOP,
    margin=0,
    line_spacing=1.0,
):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    frame = box.text_frame
    frame.clear()
    frame.margin_left = Inches(margin)
    frame.margin_right = Inches(margin)
    frame.margin_top = Inches(margin)
    frame.margin_bottom = Inches(margin)
    frame.vertical_anchor = valign
    frame.word_wrap = True
    paragraph = frame.paragraphs[0]
    paragraph.alignment = align
    paragraph.line_spacing = line_spacing
    run = paragraph.add_run()
    run.text = text
    run.font.name = font
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = rgb(color)
    return box


def add_rich_text(slide, pieces, x, y, w, h, size=16, color="text", font=BODY, margin=0):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    frame = box.text_frame
    frame.clear()
    frame.margin_left = Inches(margin)
    frame.margin_right = Inches(margin)
    frame.margin_top = Inches(margin)
    frame.margin_bottom = Inches(margin)
    frame.word_wrap = True
    paragraph = frame.paragraphs[0]
    paragraph.line_spacing = 1.05
    for piece in pieces:
        run = paragraph.add_run()
        run.text = piece[0]
        run.font.name = piece[4] if len(piece) > 4 else font
        run.font.size = Pt(piece[3] if len(piece) > 3 else size)
        run.font.bold = bool(piece[1])
        run.font.color.rgb = rgb(piece[2] if len(piece) > 2 else color)
    return box


def add_pdo_identity(slide, dark=True, compact=True):
    mark_size = 0.45 if compact else 0.68
    slide.shapes.add_picture(str(PDO_MARK), Inches(0.35), Inches(0.13 if compact else 0.30), Inches(mark_size), Inches(mark_size))
    add_text(
        slide,
        "CHIP",
        0.93 if compact else 1.18,
        0.14 if compact else 0.34,
        0.85,
        0.24 if compact else 0.32,
        size=14 if compact else 18,
        color="white" if dark else "navy",
        font=HEADLINE,
        bold=True,
        valign=MSO_ANCHOR.MIDDLE,
    )
    add_text(
        slide,
        "BY PUBLIC DATA OBSERVATORY",
        0.93 if compact else 1.18,
        0.38 if compact else 0.70,
        2.45,
        0.18 if compact else 0.22,
        size=6.8 if compact else 8.5,
        color="blue_soft" if dark else "slate",
        bold=True,
        valign=MSO_ANCHOR.MIDDLE,
    )


def add_footer(slide, number, light=True):
    add_rect(slide, 0, 5.35, 10, 0.275, "bg" if light else "navy", line=None, radius=False)
    add_text(
        slide,
        "publicdataobservatory.org  •  Illustrative scenario — source-aware analysis, not a substitute for local judgment",
        0.35,
        5.405,
        8.8,
        0.12,
        size=6.8,
        color="slate" if light else "blue_soft",
        valign=MSO_ANCHOR.MIDDLE,
    )
    add_text(
        slide,
        f"{number:02d}",
        9.35,
        5.385,
        0.30,
        0.15,
        size=8,
        color="blue" if light else "peach",
        bold=True,
        align=PP_ALIGN.RIGHT,
        valign=MSO_ANCHOR.MIDDLE,
    )


def add_section_header(slide, title, audience, number):
    add_rect(slide, 0, 0, 10, 0.82, "navy", line=None, radius=False)
    add_pdo_identity(slide, dark=True, compact=True)
    add_text(
        slide,
        title,
        3.00,
        0.17,
        5.45,
        0.43,
        size=23,
        color="white",
        font=HEADLINE,
        bold=True,
        valign=MSO_ANCHOR.MIDDLE,
    )
    chip = add_rect(slide, 8.55, 0.22, 1.10, 0.34, "blue", line=None, radius=True)
    add_text(
        slide,
        audience.upper(),
        8.61,
        0.30,
        0.98,
        0.14,
        size=7.2,
        color="white",
        bold=True,
        align=PP_ALIGN.CENTER,
        valign=MSO_ANCHOR.MIDDLE,
    )
    add_rect(slide, 0, 0.82, 10, 0.055, "peach", line=None, radius=False)
    add_footer(slide, number, light=True)


def add_workflow_step(slide, number, label, body, y, accent="blue"):
    add_rect(slide, 0.45, y, 0.46, 0.46, accent, line=None, radius=True)
    add_text(
        slide,
        str(number),
        0.45,
        y + 0.075,
        0.46,
        0.17,
        size=10,
        color="white",
        font=HEADLINE,
        bold=True,
        align=PP_ALIGN.CENTER,
        valign=MSO_ANCHOR.MIDDLE,
    )
    add_text(slide, label.upper(), 1.03, y - 0.01, 3.84, 0.24, size=9.5, color=accent, bold=True)
    add_text(slide, body, 1.03, y + 0.23, 3.83, 0.57, size=10.6, color="text", line_spacing=0.95)


def add_screenshot_placeholder(slide, label, prompt, decision, datasets):
    add_rect(
        slide,
        5.22,
        1.20,
        4.33,
        3.18,
        "panel",
        line="blue_soft",
        radius=True,
        line_width=1.5,
        dash=MSO_LINE_DASH_STYLE.DASH,
    )
    add_rect(slide, 5.46, 1.43, 0.90, 0.26, "peach_soft", line=None, radius=True)
    add_text(
        slide,
        "SCREENSHOT",
        5.50,
        1.49,
        0.82,
        0.12,
        size=6.6,
        color="navy",
        bold=True,
        align=PP_ALIGN.CENTER,
        valign=MSO_ANCHOR.MIDDLE,
    )
    # Simple wireframe to make replacement zones obvious without competing with the final image.
    add_rect(slide, 5.48, 1.86, 3.80, 1.58, "bg", line="line", radius=False, line_width=0.8)
    add_rect(slide, 5.48, 1.86, 3.80, 0.20, "navy", line=None, radius=False)
    add_rect(slide, 5.62, 2.19, 2.35, 1.06, "blue_soft", line=None, radius=False)
    add_rect(slide, 8.08, 2.19, 1.02, 0.20, "panel", line="line", radius=False, line_width=0.5)
    add_rect(slide, 8.08, 2.48, 1.02, 0.20, "panel", line="line", radius=False, line_width=0.5)
    add_rect(slide, 8.08, 2.77, 1.02, 0.48, "panel", line="line", radius=False, line_width=0.5)
    add_text(slide, label, 5.48, 3.60, 3.80, 0.28, size=12, color="navy", font=HEADLINE, bold=True, align=PP_ALIGN.CENTER)
    add_text(slide, prompt, 5.58, 3.92, 3.60, 0.30, size=8.6, color="slate", align=PP_ALIGN.CENTER, line_spacing=0.9)

    add_rect(slide, 5.22, 4.57, 4.33, 0.58, "navy", line=None, radius=True)
    add_text(slide, "DECISION ENABLED", 5.40, 4.68, 1.18, 0.15, size=7.5, color="peach", bold=True)
    add_text(slide, decision, 6.68, 4.63, 2.50, 0.40, size=9.2, color="white", bold=True, valign=MSO_ANCHOR.MIDDLE)
    add_text(slide, datasets, 0.47, 5.08, 4.60, 0.17, size=7.2, color="slate", bold=True)


def add_scenario_slide(prs, content):
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    background = slide.background.fill
    background.solid()
    background.fore_color.rgb = rgb("bg")
    add_section_header(slide, content["title"], content["audience"], content["number"])

    add_text(slide, "HYPOTHETICAL USE CASE", 0.45, 1.16, 2.10, 0.18, size=8.2, color="teal", bold=True)
    add_text(slide, content["headline"], 0.45, 1.39, 4.45, 0.69, size=19.2, color="navy", font=HEADLINE, bold=True, line_spacing=0.9)
    add_text(slide, content["context"], 0.45, 2.05, 4.42, 0.40, size=10.0, color="slate", line_spacing=0.95)

    y = 2.60
    accents = ["blue", "teal", "blue_dark"]
    for idx, (label, body) in enumerate(content["steps"], start=1):
        add_workflow_step(slide, idx, label, body, y + (idx - 1) * 0.80, accents[idx - 1])

    add_screenshot_placeholder(
        slide,
        content["screenshot_label"],
        content["screenshot_prompt"],
        content["decision"],
        content["datasets"],
    )
    return slide


def add_title_slide(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    bg = slide.background.fill
    bg.solid()
    bg.fore_color.rgb = rgb("navy")
    add_rect(slide, 0, 0, 0.18, 5.625, "blue", line=None, radius=False)
    add_pdo_identity(slide, dark=True, compact=False)

    add_text(
        slide,
        "Four decisions.\nOne shared evidence base.",
        0.55,
        1.35,
        5.25,
        1.40,
        size=31,
        color="white",
        font=HEADLINE,
        bold=True,
        line_spacing=0.85,
    )
    add_text(
        slide,
        "Hypothetical ways CHIP can support community health action — from neighborhood targeting to public-health policy design.",
        0.58,
        2.86,
        5.15,
        0.66,
        size=14,
        color="blue_soft",
        line_spacing=0.95,
    )
    add_rect(slide, 0.58, 3.70, 1.50, 0.055, "peach", line=None, radius=False)
    add_text(slide, "ILLUSTRATIVE USE CASES  •  AUGUST 2026", 0.58, 3.93, 4.70, 0.24, size=8.2, color="blue_soft", bold=True)

    # Hero screenshot placeholder.
    add_rect(
        slide,
        6.10,
        1.08,
        3.38,
        2.92,
        "panel",
        line="blue_soft",
        radius=True,
        line_width=1.4,
        dash=MSO_LINE_DASH_STYLE.DASH,
    )
    add_rect(slide, 6.32, 1.31, 2.94, 1.75, "bg", line="line", radius=False, line_width=0.7)
    add_rect(slide, 6.32, 1.31, 2.94, 0.20, "blue", line=None, radius=False)
    add_rect(slide, 6.50, 1.72, 1.72, 1.03, "blue_soft", line=None, radius=False)
    add_rect(slide, 8.36, 1.72, 0.68, 0.22, "panel", line="line", radius=False, line_width=0.5)
    add_rect(slide, 8.36, 2.04, 0.68, 0.22, "panel", line="line", radius=False, line_width=0.5)
    add_rect(slide, 8.36, 2.36, 0.68, 0.39, "panel", line="line", radius=False, line_width=0.5)
    add_text(slide, "INSERT CHIP HERO VIEW", 6.35, 3.23, 2.88, 0.24, size=11, color="navy", font=HEADLINE, bold=True, align=PP_ALIGN.CENTER)
    add_text(slide, "Recommended: map + selected geography profile", 6.42, 3.55, 2.74, 0.18, size=8, color="slate", align=PP_ALIGN.CENTER)

    audiences = [
        ("LOCAL HEALTH", "Prioritize"),
        ("NONPROFITS", "Coordinate"),
        ("POLICYMAKERS", "Prepare"),
        ("LAWMAKERS", "Legislate"),
    ]
    start_x = 0.58
    for idx, (audience, verb) in enumerate(audiences):
        x = start_x + idx * 2.18
        fill = "blue" if idx in (0, 2) else "teal"
        add_rect(slide, x, 4.47, 1.93, 0.57, fill, line=None, radius=True)
        add_text(slide, audience, x + 0.10, 4.55, 1.73, 0.13, size=6.8, color="white", bold=True, align=PP_ALIGN.CENTER)
        add_text(slide, verb, x + 0.10, 4.72, 1.73, 0.16, size=9.2, color="white", font=HEADLINE, bold=True, align=PP_ALIGN.CENTER)

    add_footer(slide, 1, light=False)
    return slide


def main():
    prs = Presentation()
    prs.slide_width = Inches(10)
    prs.slide_height = Inches(5.625)
    prs.core_properties.title = "CHIP Community Health Use Cases"
    prs.core_properties.subject = "Hypothetical uses for local health departments, nonprofits, policymakers, and lawmakers"
    prs.core_properties.author = "Public Data Observatory"
    prs.core_properties.keywords = "CHIP, community health, public data, use cases, policy"
    prs.core_properties.comments = "Editable five-slide deck with labeled screenshot placeholders."

    add_title_slide(prs)

    scenarios = [
        {
            "number": 2,
            "audience": "Local health",
            "title": "Put prevention where risks overlap",
            "headline": "Target outreach before the next heat or chronic-disease surge",
            "context": "A county health department needs to focus limited field capacity without reducing the decision to a single indicator.",
            "steps": [
                ("See the pattern", "Map tract-level health burden, social vulnerability, provider shortage, and heat risk in the same geography."),
                ("Test the response", "Compare candidate neighborhoods and generate a profile that documents sources, years, and methodology."),
                ("Act & measure", "Place mobile screening, cooling outreach, or referral partners where multiple signals converge; track the same baseline measures."),
            ],
            "screenshot_label": "Map + county/tract profile panel",
            "screenshot_prompt": "Capture a selected tract with PLACES, SVI, HPSA, or FEMA context visible.",
            "decision": "Which neighborhoods should receive the first wave of outreach?",
            "datasets": "CHIP LAYERS  •  CDC PLACES  •  SVI / ACS  •  HRSA HPSA  •  FEMA NRI",
        },
        {
            "number": 3,
            "audience": "Nonprofits",
            "title": "Build a defensible service footprint",
            "headline": "Turn a needs assessment into a defensible expansion plan",
            "context": "A food-access nonprofit is deciding where a mobile market, produce-prescription partner, or benefits navigator could add the most value.",
            "steps": [
                ("Find the gap", "Pair USDA food-access and food-environment measures with diabetes, obesity, vulnerability, and care-access signals."),
                ("Compare options", "Use consistent profiles to rank candidate service areas and reveal where existing partners or provider shortages change feasibility."),
                ("Design the service", "Translate the evidence into a partner brief, service boundary, operating plan, and measurable starting baseline."),
            ],
            "screenshot_label": "Food access map + area profile",
            "screenshot_prompt": "Capture a candidate county or tract with the relevant USDA layer and profile detail.",
            "decision": "Where should the organization expand, and what should it measure first?",
            "datasets": "CHIP LAYERS  •  USDA FOOD ACCESS / ENVIRONMENT  •  PLACES  •  SVI / ACS  •  HPSA",
        },
        {
            "number": 4,
            "audience": "Policymakers",
            "title": "Hazard context for health readiness",
            "headline": "Use FEMA risk as context—not as a stand-in for health need",
            "context": "A state or regional public health agency is updating a heat, flood, or severe-weather plan and needs to see where hazards may amplify existing health and access challenges.",
            "steps": [
                ("Set the health baseline", "Review PLACES burden, CMS signals, provider shortages, and social vulnerability before adding hazard information."),
                ("Add hazard context", "Use FEMA NRI to identify where heat, flooding, storms, or other hazards could intensify continuity-of-care and response challenges."),
                ("Plan coordinated action", "Strengthen pre-event outreach, continuity plans, and cross-agency partnerships while documenting each source’s scope and limits."),
            ],
            "screenshot_label": "FEMA risk map + area profile",
            "screenshot_prompt": "Capture a FEMA hazard layer for a selected county; pair it with related health context.",
            "decision": "Where should preparedness partnerships and protective actions be strengthened first?",
            "datasets": "COMPLEMENTARY LAYERS  •  FEMA NRI  •  CDC PLACES  •  CMS  •  HRSA HPSA  •  SVI / ACS",
        },
        {
            "number": 5,
            "audience": "Lawmakers",
            "title": "Evidence for public-health policy",
            "headline": "Turn place-based evidence into sharper policy questions",
            "context": "Legislative staff are examining a public health issue and need a consistent picture of outcomes, access, vulnerability, and environmental context across constituent communities.",
            "steps": [
                ("Define the problem", "Compare state, county, or tract profiles to identify where health burden or service-access challenges differ across places."),
                ("Test the policy lens", "Examine whether a proposed intervention fits the observed health, provider, food-access, vulnerability, and hazard context."),
                ("Build accountability", "Use the evidence to shape hearings, bill provisions, reporting requirements, and practical benchmarks for monitoring progress."),
            ],
            "screenshot_label": "County/tract profile + Ask CHIP",
            "screenshot_prompt": "Capture a place profile or sourced CHIP response with methodology context visible.",
            "decision": "Which public-health problem should legislation address, and how will progress be measured?",
            "datasets": "PUBLIC HEALTH LAYERS  •  PLACES  •  SVI / ACS  •  HPSA  •  CMS  •  USDA  •  FEMA NRI",
        },
    ]

    for scenario in scenarios:
        add_scenario_slide(prs, scenario)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUT)
    print(OUT)


if __name__ == "__main__":
    main()
