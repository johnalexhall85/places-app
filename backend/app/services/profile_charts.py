from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _draw_no_data(ax: Any, message: str) -> None:
    ax.axis("off")
    ax.text(
        0.5,
        0.5,
        message,
        horizontalalignment="center",
        verticalalignment="center",
        transform=ax.transAxes,
        fontsize=10,
        color="#475569",
    )


def _as_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed:
        return None
    return parsed


def _plot_comparison_panel(
    ax: Any,
    *,
    title: str,
    unit: str,
    location_value: float | None,
    state_value: float | None,
    us_value: float | None,
) -> None:
    labels = ["Location", "State", "US"]
    values = [location_value, state_value, us_value]
    finite_values = [value for value in values if value is not None]
    if not finite_values:
        _draw_no_data(ax, "No comparison values available.")
        return

    plot_values = [value if value is not None else 0.0 for value in values]
    colors = ["#2563eb", "#0ea5e9", "#334155"]
    bars = ax.bar(labels, plot_values, color=colors, alpha=0.9)
    max_value = max(max(finite_values), 1.0)
    ax.set_ylim(0, max_value * 1.2)
    ax.set_ylabel(unit)
    ax.set_title(title, fontsize=11)
    ax.grid(axis="y", alpha=0.2, linestyle="--")
    for idx, bar in enumerate(bars):
        value = values[idx]
        label = "N/A" if value is None else f"{value:.1f}"
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + (max_value * 0.03),
            label,
            ha="center",
            va="bottom",
            fontsize=9,
            color="#0f172a",
        )


def _plot_distribution(
    output_path: Path,
    *,
    values: list[float],
    location_value: float | None,
    label: str,
    unit: str,
) -> None:
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=150)
    try:
        if not values:
            _draw_no_data(ax, "No distribution data available.")
        else:
            ax.hist(values, bins=24, color="#0ea5e9", alpha=0.65, edgecolor="white")
            if location_value is not None:
                ax.axvline(
                    location_value,
                    color="#dc2626",
                    linewidth=2,
                    linestyle="-",
                    label=f"Location ({location_value:.1f})",
                )
                ax.legend(loc="upper right", fontsize=9)
            ax.set_title(f"US Distribution: {label}", fontsize=11)
            ax.set_xlabel(unit)
            ax.set_ylabel("Count")
            ax.grid(axis="y", linestyle="--", alpha=0.25)
        fig.tight_layout()
        fig.savefig(output_path, format="png")
    finally:
        plt.close(fig)


def _plot_scatter(
    output_path: Path,
    *,
    points: list[dict[str, Any]],
    x_label: str,
    y_label: str,
    location_point: tuple[float | None, float | None],
) -> None:
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=150)
    try:
        x_values = []
        y_values = []
        for point in points:
            x = _as_float(point.get("x"))
            y = _as_float(point.get("y"))
            if x is None or y is None:
                continue
            x_values.append(x)
            y_values.append(y)

        if not x_values or not y_values:
            _draw_no_data(ax, "No scatter pairs available.")
        else:
            ax.scatter(x_values, y_values, s=10, alpha=0.2, color="#2563eb", edgecolors="none")
            lx, ly = location_point
            if lx is not None and ly is not None:
                ax.scatter([lx], [ly], s=90, color="#dc2626", edgecolors="#7f1d1d", linewidths=1.0)
            ax.set_title("PLACES vs Top ACS Correlate", fontsize=11)
            ax.set_xlabel(x_label)
            ax.set_ylabel(y_label)
            ax.grid(linestyle="--", alpha=0.25)
        fig.tight_layout()
        fig.savefig(output_path, format="png")
    finally:
        plt.close(fig)


def generate_profile_charts(
    *,
    profile_id: str,
    profile_json: dict[str, Any],
    chart_inputs: dict[str, Any],
    profiles_root: Path,
) -> dict[str, dict[str, str]]:
    profile_dir = _ensure_dir(profiles_root / profile_id)
    charts_dir = _ensure_dir(profile_dir / "charts")

    chart_assets: dict[str, dict[str, str]] = {}

    places_comparison = chart_inputs.get("places_comparison") if isinstance(chart_inputs, dict) else {}
    acs_primary_comparison = chart_inputs.get("acs_primary_comparison") if isinstance(chart_inputs, dict) else None

    bars_path = charts_dir / "bars_comparison.png"
    fig, axes = plt.subplots(
        nrows=1,
        ncols=2 if isinstance(acs_primary_comparison, dict) else 1,
        figsize=(11, 4.4),
        dpi=150,
    )
    try:
        axes_list = axes if isinstance(axes, (list, tuple)) else [axes]
        if hasattr(axes, "flatten"):
            axes_list = list(axes.flatten())

        _plot_comparison_panel(
            axes_list[0],
            title="PLACES: Location vs State vs US",
            unit=str(places_comparison.get("unit") or "Value"),
            location_value=_as_float(places_comparison.get("location_value")),
            state_value=_as_float(places_comparison.get("state_mean")),
            us_value=_as_float(places_comparison.get("us_mean")),
        )

        if len(axes_list) > 1:
            _plot_comparison_panel(
                axes_list[1],
                title="ACS: Location vs State vs US",
                unit=str((acs_primary_comparison or {}).get("unit") or "Value"),
                location_value=_as_float((acs_primary_comparison or {}).get("location_value")),
                state_value=_as_float((acs_primary_comparison or {}).get("state_mean")),
                us_value=_as_float((acs_primary_comparison or {}).get("us_mean")),
            )

        fig.tight_layout()
        fig.savefig(bars_path, format="png")
    finally:
        plt.close(fig)
    chart_assets["bars_comparison"] = {
        "asset_name": "bars_comparison",
        "mime_type": "image/png",
        "path": str(bars_path),
    }

    us_distribution = chart_inputs.get("us_distribution") if isinstance(chart_inputs, dict) else {}
    distribution_path = charts_dir / "us_distribution.png"
    distribution_values: list[float] = []
    for raw_value in (us_distribution.get("values") or []):
        parsed = _as_float(raw_value)
        if parsed is not None:
            distribution_values.append(parsed)
    _plot_distribution(
        distribution_path,
        values=distribution_values,
        location_value=_as_float(us_distribution.get("location_value")),
        label=str(us_distribution.get("label") or "Selected measure"),
        unit=str(us_distribution.get("unit") or "Value"),
    )
    chart_assets["us_distribution"] = {
        "asset_name": "us_distribution",
        "mime_type": "image/png",
        "path": str(distribution_path),
    }

    scatter_payload = chart_inputs.get("scatter") if isinstance(chart_inputs, dict) else None
    scatter_path = charts_dir / "scatter_top_correlate.png"
    _plot_scatter(
        scatter_path,
        points=(scatter_payload or {}).get("points") or [],
        x_label=str((scatter_payload or {}).get("measure") or "ACS value"),
        y_label=str(
            places_comparison.get("label")
            or profile_json.get("places_measure", {}).get("measure_id")
            or "PLACES value"
        ),
        location_point=(
            _as_float((chart_inputs.get("acs_primary_comparison") or {}).get("location_value")),
            _as_float((chart_inputs.get("places_comparison") or {}).get("location_value")),
        ),
    )
    chart_assets["scatter_top_correlate"] = {
        "asset_name": "scatter_top_correlate",
        "mime_type": "image/png",
        "path": str(scatter_path),
    }

    return chart_assets
