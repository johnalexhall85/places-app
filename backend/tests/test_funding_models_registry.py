from __future__ import annotations

from app.funding_models import registry


def test_funding_mode_registry_falls_back_to_built_ins(monkeypatch) -> None:
    monkeypatch.setattr(registry, "registry_tables_available", lambda _db: False)

    items = registry.list_funding_mode_options(None)

    assert [item["value"] for item in items[:3]] == [
        "chip_normalized_v1_1",
        "raw_total",
        "chip_normalized",
    ]
    assert all(item["system"] for item in items[:3])
