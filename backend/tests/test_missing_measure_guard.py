"""
Regression: aggregation of a NAMED measure that does not exist as a column must
produce a clarification, never a fabricated answer built from an unrelated column.

Root cause fixed in app/data_engine/report_pipeline.py: a guard now runs before
any AI provider call. Previously "What is the average employee salary?" on a
dataset with no salary column silently returned AVG("unit_price") as if it were
the answer (BUG-B), violating the deterministic-truth / no-fabrication rule.
"""
import time
import pandas as pd
from fastapi.testclient import TestClient
from app.main import app
from app.core.database import init_db
from app.data_engine.report_pipeline import (
    _extract_aggregation_measure,
    _measure_maps_to_column,
)

init_db()
client = TestClient(app)

SALES = pd.DataFrame({
    "transaction_date": ["2023-01-01", "2023-02-01", "2023-03-01"],
    "product_id": ["P1", "P2", "P3"],
    "customer_id": ["C1", "C2", "C3"],
    "unit_price": [10.0, 12.0, 14.0],
    "quantity": [1, 2, 3],
    "revenue": [10.0, 24.0, 42.0],
})


def test_missing_measure_is_detected():
    # Named measure absent from the dataset -> extracted and flagged as unmapped.
    m = _extract_aggregation_measure("What is the average employee salary?")
    assert m is not None, "should extract the aggregation target"
    assert "salary" in m
    assert _measure_maps_to_column(m, SALES) is False


def test_present_measures_are_not_blocked():
    # These all name a real column (directly or via normalization) and must pass.
    for q in [
        "What is the average unit price?",
        "total revenue by month",
        "What is the maximum quantity?",
        "average unit price trends over time",
        "sum of revenue",
    ]:
        m = _extract_aggregation_measure(q)
        # Either not treated as a named-measure aggregation, or it maps to a column.
        assert (m is None) or _measure_maps_to_column(m, SALES), f"wrongly blocked: {q!r} -> {m!r}"


def test_count_style_questions_are_not_treated_as_measure_aggregation():
    for q in [
        "How many records are there?",
        "total number of orders",
        "count of transactions",
    ]:
        assert _extract_aggregation_measure(q) is None, f"count-style wrongly extracted: {q!r}"


def test_generic_targets_do_not_block():
    # Pure generic words after the aggregation verb -> not a concrete named measure.
    for q in ["show me the average value", "what is the total"]:
        m = _extract_aggregation_measure(q)
        assert (m is None) or _measure_maps_to_column(m, SALES), f"generic wrongly blocked: {q!r}"


def test_e2e_missing_measure_returns_clarification_not_fabrication():
    email = f"aggguard_{int(time.time()*1000)}@t.com"
    r = client.post("/api/auth/register", json={"email": email, "password": "password123"})
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}

    csv = "transaction_date,product_id,customer_id,unit_price,quantity,revenue\n"
    csv += "2023-01-01,P1,C1,10,1,10\n2023-02-01,P2,C2,12,2,24\n2023-03-01,P3,C3,14,3,42\n"
    files = {"file": ("sales.csv", csv, "text/csv")}
    r = client.post("/api/datasets/upload", files=files, headers=h)
    assert r.status_code == 200, r.text
    ds_id = r.json()["id"]

    r = client.post(f"/api/datasets/{ds_id}/analyze", headers=h,
                    json={"question": "What is the average employee salary?"})
    assert r.status_code == 200, r.text
    body = r.json()
    msg = body.get("message", {})
    # No SQL executed, no generated code, flagged as clarification.
    assert msg.get("execution_status") == "clarification", body
    assert msg.get("generated_code") in (None, ""), body
    assert body.get("needs_clarification") is True, body
    # Must NOT fabricate an answer from an unrelated column.
    content = (msg.get("content") or "").lower()
    assert "average unit price is" not in content, f"fabricated answer leaked: {content}"
    assert "salary" in content, "clarification should reference the missing measure"


def test_e2e_present_measure_still_executes():
    email = f"aggok_{int(time.time()*1000)}@t.com"
    r = client.post("/api/auth/register", json={"email": email, "password": "password123"})
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    csv = "transaction_date,product_id,customer_id,unit_price,quantity,revenue\n"
    csv += "2023-01-01,P1,C1,10,1,10\n2023-02-01,P2,C2,12,2,24\n2023-03-01,P3,C3,14,3,42\n"
    files = {"file": ("sales.csv", csv, "text/csv")}
    r = client.post("/api/datasets/upload", files=files, headers=h)
    assert r.status_code == 200, r.text
    ds_id = r.json()["id"]

    r = client.post(f"/api/datasets/{ds_id}/analyze", headers=h,
                    json={"question": "What is the average unit price?"})
    assert r.status_code == 200, r.text
    body = r.json()
    msg = body.get("message", {})
    # A real column -> must actually run, not clarify.
    assert msg.get("execution_status") == "success", body
    assert body.get("needs_clarification") in (False, None), body
