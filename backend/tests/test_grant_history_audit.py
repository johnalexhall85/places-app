"""Independent reconciliation audit for CDC grant history and state funding MCP tools.

Implements Grant History Contract §7 invariants 1–7 against the active
`state_funding` and `funding_report` builds on `places_staging`.

Read-only SQL and in-process function calls only; writes no database rows
and makes no network calls.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db import SessionLocal
from app.funding_report import keys as funding_keys
from app.funding_report import lookup as funding_lookup
from app.state_funding import lookup

pytestmark = pytest.mark.integration

TOLERANCE_DECIMAL = Decimal("0.01")
TOLERANCE_FLOAT = 0.01

REQUIRED_FIXED_NOFOS = ("PS212102", "OT202004", "NH28CE4")
MCP_AUDIT_NOFOS = ("PS212102", "OT202004")
MCP_AUDIT_STATES = ("CA", "TX")
ALL_FISCAL_YEARS = (2021, 2022, 2023, 2024, 2025, 2026)
ALL_NON_POSITIVE_NOTE = (
    "No fiscal year from FY2021 to FY2026 has a positive net obligation for this grant."
)


def _select_audit_nofos(db, build_id: int) -> tuple[tuple[str, ...], str | None]:
    """Deterministically select Contract §7 NOFOs.

    Returns (nofo_keys, split_state_nofo_key):
      - 10 largest NOFOs by FY2026 grant total (DESC, tie-break fon_key ASC)
      - PS212102, OT202004, NH28CE4
      - the NOFO with the most split-state awards (checked first within latest_fy,
        falling back to multi-state grant awards across all fiscal years)
    """
    top_10 = [
        str(row[0])
        for row in db.execute(
            text(
                """
                SELECT a.fon_key
                FROM state_funding.award a
                JOIN state_funding.obligation o USING (build_id, award_unique_key)
                WHERE a.build_id = :build_id
                  AND a.award_type = 'grant'
                  AND o.fiscal_year = 2026
                  AND a.fon_key IS NOT NULL
                GROUP BY a.fon_key
                ORDER BY sum(o.amount) DESC, a.fon_key ASC
                LIMIT 10
                """
            ),
            {"build_id": build_id},
        ).all()
    ]

    split_latest = db.execute(
        text(
            """
            WITH fy_totals AS (
                SELECT a.fon_key, o.fiscal_year, sum(o.amount) AS fy_total
                FROM state_funding.award a
                JOIN state_funding.obligation o USING (build_id, award_unique_key)
                WHERE a.build_id = :build_id
                  AND a.award_type = 'grant'
                  AND a.fon_key IS NOT NULL
                GROUP BY 1, 2
            ),
            latest_fys AS (
                SELECT fon_key,
                       coalesce(max(fiscal_year) FILTER (WHERE fy_total > 0), max(fiscal_year)) AS latest_fy
                FROM fy_totals
                GROUP BY 1
            ),
            split_awards AS (
                SELECT a.fon_key, a.award_unique_key, count(DISTINCT o.state) AS n_states
                FROM state_funding.award a
                JOIN state_funding.obligation o USING (build_id, award_unique_key)
                JOIN latest_fys lf ON lf.fon_key = a.fon_key AND lf.latest_fy = o.fiscal_year
                WHERE a.build_id = :build_id
                  AND a.award_type = 'grant'
                GROUP BY 1, 2
                HAVING count(DISTINCT o.state) > 1
            )
            SELECT fon_key
            FROM split_awards
            GROUP BY fon_key
            ORDER BY count(*) DESC, sum(n_states) DESC, fon_key ASC
            LIMIT 1
            """
        ),
        {"build_id": build_id},
    ).scalar()

    if split_latest:
        most_split = str(split_latest)
    else:
        split_all_years = db.execute(
            text(
                """
                WITH multi_state_awards AS (
                    SELECT a.fon_key, a.award_unique_key, count(DISTINCT o.state) AS n_states
                    FROM state_funding.award a
                    JOIN state_funding.obligation o USING (build_id, award_unique_key)
                    WHERE a.build_id = :build_id
                      AND a.award_type = 'grant'
                      AND a.fon_key IS NOT NULL
                    GROUP BY 1, 2
                    HAVING count(DISTINCT o.state) > 1
                )
                SELECT fon_key
                FROM multi_state_awards
                GROUP BY fon_key
                ORDER BY count(*) DESC, sum(n_states) DESC, fon_key ASC
                LIMIT 1
                """
            ),
            {"build_id": build_id},
        ).scalar()
        most_split = str(split_all_years) if split_all_years else None

    ordered: list[str] = []
    for key in [*top_10, *REQUIRED_FIXED_NOFOS, *([most_split] if most_split else [])]:
        if key not in ordered:
            ordered.append(key)
    return tuple(ordered), most_split


@pytest.fixture(scope="module")
def audit_context():
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1")).scalar()
        sf_build = lookup.build_info(db)
        fr_build = funding_lookup.active_build(db)
    except SQLAlchemyError as exc:
        db.close()
        pytest.skip(f"Database unreachable or funding schemas unavailable: {exc}")

    if not sf_build:
        db.close()
        pytest.skip("No active state_funding build available")
    if not fr_build:
        db.close()
        pytest.skip("No active funding_report build available")

    try:
        nofos, most_split = _select_audit_nofos(db, sf_build["build_id"])
        histories = {key: lookup.grant_history(db, key) for key in nofos}
        yield {
            "db": db,
            "build": sf_build,
            "build_id": sf_build["build_id"],
            "funding_report_build": fr_build,
            "nofos": nofos,
            "most_split_nofo": most_split,
            "histories": histories,
        }
    finally:
        db.rollback()
        db.close()


def test_invariant_1_by_fiscal_year_sum_reconciles_to_sql(audit_context):
    """Invariant 1: sum of by_fiscal_year.total across selected NOFOs equals SQL sum within $0.01."""
    db = audit_context["db"]
    build_id = audit_context["build_id"]
    nofos = audit_context["nofos"]
    histories = audit_context["histories"]

    sql_by_fy: dict[int, Decimal] = {fy: Decimal("0.00") for fy in ALL_FISCAL_YEARS}
    sql_per_nofo_fy: dict[tuple[str, int], Decimal] = {}
    rows = db.execute(
        text(
            """
            SELECT a.fon_key, o.fiscal_year, sum(o.amount) AS total
            FROM state_funding.award a
            JOIN state_funding.obligation o USING (build_id, award_unique_key)
            WHERE a.build_id = :build_id
              AND a.award_type = 'grant'
              AND a.fon_key = ANY(:nofos)
            GROUP BY a.fon_key, o.fiscal_year
            """
        ),
        {"build_id": build_id, "nofos": list(nofos)},
    ).mappings()
    for row in rows:
        fy = int(row["fiscal_year"])
        amt = Decimal(row["total"])
        sql_per_nofo_fy[(str(row["fon_key"]), fy)] = amt
        sql_by_fy[fy] = sql_by_fy.get(fy, Decimal("0.00")) + amt

    # Per-NOFO per-FY reconciliation
    for key in nofos:
        by_fy_map = {int(item["fiscal_year"]): item for item in histories[key]["by_fiscal_year"]}
        for fy in ALL_FISCAL_YEARS:
            expected = sql_per_nofo_fy.get((key, fy), Decimal("0.00"))
            actual = Decimal(str(by_fy_map[fy]["total"]))
            diff = abs(actual - expected)
            assert diff <= TOLERANCE_DECIMAL, (
                f"Invariant 1 (per-NOFO) failed: nofo={key!r} fy={fy} state='ALL' "
                f"sql_total={expected:.2f} lookup_total={actual:.2f} diff={diff:.2f}"
            )

    # Combined sum across all selected NOFOs per fiscal year
    for fy in ALL_FISCAL_YEARS:
        expected = sql_by_fy[fy]
        actual = sum(
            Decimal(str(next(x["total"] for x in histories[k]["by_fiscal_year"] if x["fiscal_year"] == fy)))
            for k in nofos
        )
        diff = abs(actual - expected)
        assert diff <= TOLERANCE_DECIMAL, (
            f"Invariant 1 (combined {len(nofos)} NOFOs) failed: nofo='SELECTED({len(nofos)})' fy={fy} "
            f"state='ALL' sql_total={expected:.2f} lookup_sum={actual:.2f} diff={diff:.2f}"
        )


def test_invariant_2_latest_fy_total_equals_by_state_and_current_awards(audit_context):
    """Invariant 2: totals.latest_fy.total == sum(by_state.latest_fy_total) == sum(current awards latest_fy_amount.total)."""
    for key in audit_context["nofos"]:
        gh = audit_context["histories"][key]
        latest_fy = gh["latest_fy"]

        latest_total = round(float(gh["totals"]["latest_fy"]["total"]), 2)
        latest_regular = round(float(gh["totals"]["latest_fy"]["regular"]), 2)
        latest_supp = round(float(gh["totals"]["latest_fy"]["supplemental"]), 2)

        by_state_total = round(
            sum(float(s["latest_fy_total"]) for s in gh["by_state"] if s["latest_fy_total"] is not None), 2
        )
        by_state_regular = round(
            sum(float(s["regular"]) for s in gh["by_state"] if s["regular"] is not None), 2
        )
        by_state_supp = round(
            sum(float(s["supplemental"]) for s in gh["by_state"] if s["supplemental"] is not None), 2
        )

        current_awards = [a for a in gh["awards"] if a["is_current"]]
        awards_total = round(sum(float(a["latest_fy_amount"]["total"]) for a in current_awards), 2)
        awards_regular = round(sum(float(a["latest_fy_amount"]["regular"]) for a in current_awards), 2)
        awards_supp = round(sum(float(a["latest_fy_amount"]["supplemental"]) for a in current_awards), 2)

        assert abs(latest_total - by_state_total) <= TOLERANCE_FLOAT, (
            f"Invariant 2 (totals vs by_state total) failed: nofo={key!r} fy={latest_fy} state='ALL' "
            f"totals_latest_fy={latest_total:.2f} by_state_sum={by_state_total:.2f}"
        )
        assert abs(latest_total - awards_total) <= TOLERANCE_FLOAT, (
            f"Invariant 2 (totals vs current awards total) failed: nofo={key!r} fy={latest_fy} state='ALL' "
            f"totals_latest_fy={latest_total:.2f} current_awards_sum={awards_total:.2f}"
        )
        assert abs(by_state_total - awards_total) <= TOLERANCE_FLOAT, (
            f"Invariant 2 (by_state vs current awards total) failed: nofo={key!r} fy={latest_fy} state='ALL' "
            f"by_state_sum={by_state_total:.2f} current_awards_sum={awards_total:.2f}"
        )
        assert abs(latest_regular - by_state_regular) <= TOLERANCE_FLOAT, (
            f"Invariant 2 (regular vs by_state) failed: nofo={key!r} fy={latest_fy} state='ALL' "
            f"totals_regular={latest_regular:.2f} by_state_regular={by_state_regular:.2f}"
        )
        assert abs(latest_regular - awards_regular) <= TOLERANCE_FLOAT, (
            f"Invariant 2 (regular vs current awards) failed: nofo={key!r} fy={latest_fy} state='ALL' "
            f"totals_regular={latest_regular:.2f} current_awards_regular={awards_regular:.2f}"
        )
        assert abs(latest_supp - by_state_supp) <= TOLERANCE_FLOAT, (
            f"Invariant 2 (supplemental vs by_state) failed: nofo={key!r} fy={latest_fy} state='ALL' "
            f"totals_supplemental={latest_supp:.2f} by_state_supplemental={by_state_supp:.2f}"
        )
        assert abs(latest_supp - awards_supp) <= TOLERANCE_FLOAT, (
            f"Invariant 2 (supplemental vs current awards) failed: nofo={key!r} fy={latest_fy} state='ALL' "
            f"totals_supplemental={latest_supp:.2f} current_awards_supplemental={awards_supp:.2f}"
        )


def _page_all_state_grants(db, state: str, fy: int, build: dict[str, Any]) -> list[dict[str, Any]]:
    """Page through every row of app.state_funding.lookup.grants for (state, fy, award_type='grant')."""
    filters = {
        "funding_type": "all",
        "award_type": "grant",
        "category": None,
        "recipient_type": "all",
    }
    collected: list[dict[str, Any]] = []
    page = 1
    page_size = 100
    while True:
        chunk = lookup.grants(
            db,
            state,
            fy,
            filters,
            build,
            page=page,
            page_size=page_size,
            all_rows=False,
        )
        rows = chunk["rows"]
        collected.extend(rows)
        if not rows or len(collected) >= chunk["total_rows"]:
            assert len(collected) == chunk["total_rows"], (
                f"Invariant 3 paging incomplete: nofo='ALL' fy={fy} state={state!r} "
                f"expected_total_rows={chunk['total_rows']} collected_rows={len(collected)}"
            )
            break
        page += 1
    return collected


def test_invariant_3_by_state_reconciles_to_paged_state_grants(audit_context):
    """Invariant 3: each state in by_state (excl. '__') matches paged lookup.grants filtered to the NOFO."""
    db = audit_context["db"]
    build = audit_context["build"]
    paged_cache: dict[tuple[str, int], list[dict[str, Any]]] = {}

    for key in audit_context["nofos"]:
        gh = audit_context["histories"][key]
        latest_fy = gh["latest_fy"]

        for state_entry in gh["by_state"]:
            st = state_entry["state"]
            if st == "__":
                continue

            cache_key = (st, latest_fy)
            if cache_key not in paged_cache:
                paged_cache[cache_key] = _page_all_state_grants(db, st, latest_fy, build)

            matching = [
                row
                for row in paged_cache[cache_key]
                if row.get("fon") and funding_keys.nofo_key(row["fon"]) == key
            ]
            grants_sum = round(sum(float(r["total"]) for r in matching), 2)

            if state_entry["latest_fy_total"] is None:
                assert len(matching) == 0, (
                    f"Invariant 3 (past-only state has latest_fy rows) failed: nofo={key!r} fy={latest_fy} "
                    f"state={st!r} by_state_current_count=0 state_grants_matching_count={len(matching)}"
                )
                assert abs(grants_sum) <= TOLERANCE_FLOAT, (
                    f"Invariant 3 (past-only state sum) failed: nofo={key!r} fy={latest_fy} state={st!r} "
                    f"by_state_total=0.00 state_grants_sum={grants_sum:.2f}"
                )
            else:
                expected_state_total = round(float(state_entry["latest_fy_total"]), 2)
                assert abs(expected_state_total - grants_sum) <= TOLERANCE_FLOAT, (
                    f"Invariant 3 (state total mismatch) failed: nofo={key!r} fy={latest_fy} state={st!r} "
                    f"grant_history_state_total={expected_state_total:.2f} state_grants_sum={grants_sum:.2f}"
                )
                assert state_entry["current_count"] == len(matching), (
                    f"Invariant 3 (state current_count mismatch) failed: nofo={key!r} fy={latest_fy} state={st!r} "
                    f"grant_history_current_count={state_entry['current_count']} "
                    f"state_grants_matching_count={len(matching)}"
                )


def test_invariant_4_award_history_and_all_years_total_reconcile_to_sql(audit_context):
    """Invariant 4: each award's history equals SQL per-FY sums and all_years_total equals sum(history)."""
    db = audit_context["db"]
    build_id = audit_context["build_id"]

    for key in audit_context["nofos"]:
        gh = audit_context["histories"][key]
        sql_rows = db.execute(
            text(
                """
                SELECT a.award_unique_key,
                       o.fiscal_year,
                       coalesce(sum(o.amount) FILTER (WHERE NOT o.is_supplemental), 0) AS regular,
                       coalesce(sum(o.amount) FILTER (WHERE o.is_supplemental), 0) AS supplemental,
                       sum(o.amount) AS total
                FROM state_funding.award a
                JOIN state_funding.obligation o USING (build_id, award_unique_key)
                WHERE a.build_id = :build_id
                  AND a.award_type = 'grant'
                  AND a.fon_key = :nofo_key
                GROUP BY a.award_unique_key, o.fiscal_year
                ORDER BY a.award_unique_key, o.fiscal_year
                """
            ),
            {"build_id": build_id, "nofo_key": key},
        ).mappings()

        sql_by_award: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in sql_rows:
            sql_by_award[str(row["award_unique_key"])].append(
                {
                    "fiscal_year": int(row["fiscal_year"]),
                    "regular": Decimal(row["regular"]),
                    "supplemental": Decimal(row["supplemental"]),
                    "total": Decimal(row["total"]),
                }
            )

        for award in gh["awards"]:
            auk = award["award_unique_key"]
            st = award["state"]
            expected_hist = sql_by_award.get(auk, [])
            actual_hist = award["history"]

            exp_years = [h["fiscal_year"] for h in expected_hist]
            act_years = [int(h["fiscal_year"]) for h in actual_hist]
            assert act_years == exp_years, (
                f"Invariant 4 (history years) failed: nofo={key!r} fy='ALL' state={st!r} award={auk!r} "
                f"sql_years={exp_years} lookup_years={act_years}"
            )

            for exp_h, act_h in zip(expected_hist, actual_hist):
                fy = exp_h["fiscal_year"]
                for field in ("regular", "supplemental", "total"):
                    exp_val = exp_h[field]
                    act_val = Decimal(str(act_h[field]))
                    assert abs(act_val - exp_val) <= TOLERANCE_DECIMAL, (
                        f"Invariant 4 (history {field}) failed: nofo={key!r} fy={fy} state={st!r} award={auk!r} "
                        f"sql_{field}={exp_val:.2f} lookup_{field}={act_val:.2f}"
                    )

            hist_sum = round(sum(float(h["total"]) for h in actual_hist), 2)
            all_years_total = round(float(award["all_years_total"]), 2)
            assert abs(all_years_total - hist_sum) <= TOLERANCE_FLOAT, (
                f"Invariant 4 (all_years_total vs sum(history)) failed: nofo={key!r} fy='ALL' state={st!r} "
                f"award={auk!r} all_years_total={all_years_total:.2f} history_sum={hist_sum:.2f}"
            )


def test_invariant_5_latest_fy_rule_checked_in_sql(audit_context):
    """Invariant 5: latest_fy follows Contract §1 rule (largest FY with net total > 0, else largest FY with note)."""
    db = audit_context["db"]
    build_id = audit_context["build_id"]

    for key in audit_context["nofos"]:
        gh = audit_context["histories"][key]
        rows = db.execute(
            text(
                """
                SELECT o.fiscal_year, sum(o.amount) AS total
                FROM state_funding.award a
                JOIN state_funding.obligation o USING (build_id, award_unique_key)
                WHERE a.build_id = :build_id
                  AND a.award_type = 'grant'
                  AND a.fon_key = :nofo_key
                GROUP BY o.fiscal_year
                ORDER BY o.fiscal_year
                """
            ),
            {"build_id": build_id, "nofo_key": key},
        ).mappings().all()

        positive_years = [int(r["fiscal_year"]) for r in rows if Decimal(r["total"]) > 0]
        if positive_years:
            expected_latest_fy = max(positive_years)
            expected_note = None
        else:
            expected_latest_fy = max(int(r["fiscal_year"]) for r in rows)
            expected_note = ALL_NON_POSITIVE_NOTE

        actual_latest_fy = gh["latest_fy"]
        assert actual_latest_fy == expected_latest_fy, (
            f"Invariant 5 (latest_fy) failed: nofo={key!r} fy={actual_latest_fy} state='ALL' "
            f"sql_latest_fy={expected_latest_fy} lookup_latest_fy={actual_latest_fy}"
        )
        assert gh["latest_fy_note"] == expected_note, (
            f"Invariant 5 (latest_fy_note) failed: nofo={key!r} fy={actual_latest_fy} state='ALL' "
            f"expected_note={expected_note!r} actual_note={gh['latest_fy_note']!r}"
        )


def test_invariant_6_award_coverage_and_split_state_exclusivity(audit_context):
    """Invariant 6: every award in scope appears >=1; only current awards appear >1, and only with split_state=true."""
    db = audit_context["db"]
    build_id = audit_context["build_id"]

    for key in audit_context["nofos"]:
        gh = audit_context["histories"][key]
        latest_fy = gh["latest_fy"]

        sql_awards = {
            str(r[0])
            for r in db.execute(
                text(
                    """
                    SELECT DISTINCT a.award_unique_key
                    FROM state_funding.award a
                    JOIN state_funding.obligation o USING (build_id, award_unique_key)
                    WHERE a.build_id = :build_id
                      AND a.award_type = 'grant'
                      AND a.fon_key = :nofo_key
                    """
                ),
                {"build_id": build_id, "nofo_key": key},
            ).all()
        }

        sql_latest_states: dict[str, set[str]] = defaultdict(set)
        for row in db.execute(
            text(
                """
                SELECT DISTINCT a.award_unique_key, o.state
                FROM state_funding.award a
                JOIN state_funding.obligation o USING (build_id, award_unique_key)
                WHERE a.build_id = :build_id
                  AND a.award_type = 'grant'
                  AND a.fon_key = :nofo_key
                  AND o.fiscal_year = :latest_fy
                """
            ),
            {"build_id": build_id, "nofo_key": key, "latest_fy": latest_fy},
        ).all():
            sql_latest_states[str(row[0])].add(str(row[1]))

        by_award: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in gh["awards"]:
            by_award[item["award_unique_key"]].append(item)

        missing = sorted(sql_awards - set(by_award.keys()))
        extra = sorted(set(by_award.keys()) - sql_awards)
        assert not missing, (
            f"Invariant 6 (missing awards) failed: nofo={key!r} fy={latest_fy} state='ALL' "
            f"sql_award_count={len(sql_awards)} lookup_award_count={len(by_award)} missing={missing[:5]}"
        )
        assert not extra, (
            f"Invariant 6 (unexpected awards) failed: nofo={key!r} fy={latest_fy} state='ALL' "
            f"sql_award_count={len(sql_awards)} lookup_award_count={len(by_award)} extra={extra[:5]}"
        )

        for auk, entries in by_award.items():
            expected_current_states = sql_latest_states.get(auk, set())
            is_expected_current = len(expected_current_states) > 0

            if len(entries) > 1:
                for e in entries:
                    assert e["is_current"] is True, (
                        f"Invariant 6 (past award duplicated) failed: nofo={key!r} fy={latest_fy} "
                        f"state={e['state']!r} award={auk!r} expected_is_current=True actual_is_current={e['is_current']!r}"
                    )
                    assert e["split_state"] is True, (
                        f"Invariant 6 (duplicate without split_state) failed: nofo={key!r} fy={latest_fy} "
                        f"state={e['state']!r} award={auk!r} expected_split_state=True actual_split_state={e['split_state']!r}"
                    )
                actual_states = {e["state"] for e in entries}
                assert actual_states == expected_current_states, (
                    f"Invariant 6 (split states mismatch) failed: nofo={key!r} fy={latest_fy} state='SPLIT' "
                    f"award={auk!r} sql_states={sorted(expected_current_states)} lookup_states={sorted(actual_states)}"
                )
            else:
                e = entries[0]
                assert e["split_state"] is False, (
                    f"Invariant 6 (single entry with split_state=True) failed: nofo={key!r} fy={latest_fy} "
                    f"state={e['state']!r} award={auk!r} expected_split_state=False actual_split_state={e['split_state']!r}"
                )
                assert e["is_current"] is is_expected_current, (
                    f"Invariant 6 (is_current mismatch) failed: nofo={key!r} fy={latest_fy} "
                    f"state={e['state']!r} award={auk!r} expected_is_current={is_expected_current!r} "
                    f"actual_is_current={e['is_current']!r}"
                )
                if not is_expected_current:
                    assert e["latest_fy_amount"] is None, (
                        f"Invariant 6 (past award has latest_fy_amount) failed: nofo={key!r} fy={latest_fy} "
                        f"state={e['state']!r} award={auk!r} expected_latest_fy_amount=None "
                        f"actual_latest_fy_amount={e['latest_fy_amount']!r}"
                    )


def test_invariant_7_mcp_tools_match_lookup_totals(audit_context):
    """Invariant 7: MCP get_grant_history and get_state_funding return the same totals as lookup."""
    pytest.importorskip("mcp", reason="mcp package requires .venv-mcp")
    from app.mcp_server import tools

    db = audit_context["db"]
    build = audit_context["build"]

    # Two NOFOs: get_grant_history vs lookup.grant_history
    for key in MCP_AUDIT_NOFOS:
        expected = audit_context["histories"][key]
        env = tools.get_grant_history(key)
        actual = env.data
        latest_fy = expected["latest_fy"]

        assert actual["latest_fy"] == latest_fy, (
            f"Invariant 7 (MCP get_grant_history latest_fy) failed: nofo={key!r} fy={latest_fy} state='ALL' "
            f"lookup_latest_fy={latest_fy} mcp_latest_fy={actual['latest_fy']}"
        )
        assert actual["totals"] == expected["totals"], (
            f"Invariant 7 (MCP get_grant_history totals) failed: nofo={key!r} fy={latest_fy} state='ALL' "
            f"lookup_totals={expected['totals']!r} mcp_totals={actual['totals']!r}"
        )
        assert actual["by_fiscal_year"] == expected["by_fiscal_year"], (
            f"Invariant 7 (MCP get_grant_history by_fiscal_year) failed: nofo={key!r} fy={latest_fy} state='ALL' "
            f"lookup_by_fy={expected['by_fiscal_year']!r} mcp_by_fy={actual['by_fiscal_year']!r}"
        )
        assert actual["by_state"] == expected["by_state"], (
            f"Invariant 7 (MCP get_grant_history by_state) failed: nofo={key!r} fy={latest_fy} state='ALL' "
            f"lookup_by_state_len={len(expected['by_state'])} mcp_by_state_len={len(actual['by_state'])}"
        )

    # Two states: get_state_funding vs lookup.summary
    filters = {
        "funding_type": "all",
        "award_type": "grant",
        "category": None,
        "recipient_type": "all",
    }
    for state in MCP_AUDIT_STATES:
        expected = lookup.summary(db, state, 2026, filters, build)
        env = tools.get_state_funding(state, fiscal_year=2026, funding_type="all", award_type="grant")
        actual = env.data

        assert actual["totals"] == expected["totals"], (
            f"Invariant 7 (MCP get_state_funding totals) failed: nofo='ALL' fy=2026 state={state!r} "
            f"lookup_totals={expected['totals']!r} mcp_totals={actual['totals']!r}"
        )
        assert actual["by_category"] == expected["by_category"], (
            f"Invariant 7 (MCP get_state_funding by_category) failed: nofo='ALL' fy=2026 state={state!r} "
            f"lookup_cat_count={len(expected['by_category'])} mcp_cat_count={len(actual['by_category'])}"
        )
