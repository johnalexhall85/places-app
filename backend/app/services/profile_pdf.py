from __future__ import annotations

from typing import Any, Literal

from app.services.profile_pdf_brief import render_profile_pdf_brief
from app.services.profile_pdf_full import render_profile_pdf_full

PDFTemplate = Literal["full", "brief"]
DEFAULT_PDF_TEMPLATE: PDFTemplate = "full"


def normalize_pdf_template(template: str | None) -> PDFTemplate:
    normalized = str(template or DEFAULT_PDF_TEMPLATE).strip().lower()
    if normalized == "brief":
        return "brief"
    return "full"


def pdf_asset_name(template: str | None) -> str:
    normalized = normalize_pdf_template(template)
    if normalized == "brief":
        return "profile_pdf_brief"
    return "profile_pdf"


def pdf_storage_filename(template: str | None) -> str:
    normalized = normalize_pdf_template(template)
    if normalized == "brief":
        return "profile_brief.pdf"
    return "profile.pdf"


def pdf_download_filename(profile_id: str, template: str | None) -> str:
    normalized = normalize_pdf_template(template)
    if normalized == "brief":
        return f"{profile_id}-policy-brief.pdf"
    return f"{profile_id}.pdf"


def profile_pdf_url(profile_id: str, template: str | None) -> str:
    normalized = normalize_pdf_template(template)
    if normalized == "brief":
        return f"/profiles/{profile_id}.pdf?template=brief"
    return f"/profiles/{profile_id}.pdf"


def render_profile_pdf(
    *,
    profile_json: dict[str, Any],
    chart_paths: dict[str, str],
    template: str | None = DEFAULT_PDF_TEMPLATE,
) -> bytes:
    normalized = normalize_pdf_template(template)
    if normalized == "brief":
        return render_profile_pdf_brief(profile_json=profile_json, chart_paths=chart_paths)
    return render_profile_pdf_full(profile_json=profile_json, chart_paths=chart_paths)
