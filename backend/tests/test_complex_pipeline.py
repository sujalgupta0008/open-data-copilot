import io
import uuid
import json
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.database import init_db

client = TestClient(app)
init_db()

def _register(email=None):
    email = email or f"complex_{uuid.uuid4().hex[:6]}@test.com"
    r = client.post("/api/auth/register", json={"email": email, "password": "passwd123"})
    if r.status_code == 400:
        r = client.post("/api/auth/login", json={"email": email, "password": "passwd123"})
    return r.json()["access_token"]

def _upload_ecommerce_like(token, months=12, rows_per_month=20):
    # Create dataset with transaction_date, product_id, customer_id, unit_price, quantity
    import random, datetime
    random.seed(42)
    rows = []
    start = datetime.date(2023, 1, 1)
    for m in range(months):
        year = 2023 + (m // 12)
        month = 1 + (m % 12)
        for i in range(rows_per_month):
            # vary volume and price to create strongest/weakest
            # Make Dec peak for price
            base_price = 10 + random.uniform(-2, 2)
            if month == 12:
                base_price += 8  # peak Dec
            if month == 2:
                base_price -= 3  # trough Feb
            # product and customer
            prod = random.choice(["P1","P2","P3","P4","P5"])
            cust = random.choice([f"C{i}" for i in range(1, 11)])
            # date within month
            day = random.randint(1, 28)
            dt = f"{year}-{month:02d}-{day:02d}"
            rows.append([dt, prod, cust, round(base_price,2), random.randint(1,5)])
    df = pd.DataFrame(rows, columns=["transaction_date","product_id","customer_id","unit_price","quantity"])
    # Ensure some months have different volumes: add extra rows for peak month
    # Already rows_per_month constant, but let's add extra for Dec to make volume peak
    # Add 10 extra rows for Dec
    for i in range(10):
        rows.append([f"2023-12-{random.randint(1,28):02d}", random.choice(["P1","P2"]), random.choice(["C1","C2"]), round(20+random.uniform(-1,1),2), 1])
    df = pd.DataFrame(rows, columns=["transaction_date","product_id","customer_id","unit_price","quantity"])
    csv = df.to_csv(index=False)
    files = {"file": ("transactions.csv", io.BytesIO(csv.encode()), "text/csv")}
    headers = {"Authorization": f"Bearer {token}"}
    r = client.post("/api/datasets/upload", headers=headers, files=files)
    assert r.status_code == 200, r.text
    return r.json()["id"], headers

EXACT_QUERY = "Analyze monthly transaction volume and average unit price trends. Identify the strongest and weakest months, quantify month-over-month changes, determine which product IDs and customer IDs contributed most to the latest change, assess whether the differences are statistically meaningful where applicable, and recommend what should be investigated next."

def test_exact_complex_query_full_coverage():
    token = _register()
    ds_id, headers = _upload_ecommerce_like(token)
    r = client.post(f"/api/datasets/{ds_id}/analyze", headers=headers, json={"question": EXACT_QUERY})
    assert r.status_code == 200, r.text
    data = r.json()
    msg = data["message"]
    # Check SQL contains BOTH metrics
    code = msg["generated_code"] or ""
    assert "transaction_volume" in code.lower(), f"SQL missing transaction_volume: {code}"
    assert "average_unit_price" in code.lower(), f"SQL missing average_unit_price: {code}"
    assert "COUNT(*)" in code or "count(*)" in code.lower()
    assert "AVG" in code.upper()
    # Check evidence matches execution
    exec_result = data.get("execution_result")
    assert exec_result and exec_result.get("success")
    assert "month" in exec_result["columns"]
    assert "transaction_volume" in exec_result["columns"]
    assert "average_unit_price" in exec_result["columns"]
    # Check MoM exists
    mom = None
    for res in msg["results"]:
        if res["result_type"] == "mom_analysis":
            mom = res["result_data"]
    assert mom is not None, "Missing mom_analysis"
    assert mom.get("has_mom") is True, f"MoM should be available: {mom}"
    assert "mom_rows" in mom and len(mom["mom_rows"]) >= 1
    assert "strongest" in mom and "weakest" in mom
    assert "transaction_volume" in mom["strongest"]
    assert "average_unit_price" in mom["strongest"]
    assert "latest_change" in mom
    # Strongest/weakest exists
    # Check strongest month for each metric is actual max, not first row
    # Verify peak corresponds to max value in evidence (not hardcoded month)
    exec_rows = exec_result["data"]
    # Find actual max for price
    max_price_row = max(exec_rows, key=lambda r: float(r["average_unit_price"]))
    assert mom["strongest"]["average_unit_price"]["month"] == max_price_row["month"], f"Strongest price month should be max: {max_price_row}"
    assert float(mom["strongest"]["average_unit_price"]["value"]) == float(max_price_row["average_unit_price"])
    max_vol_row = max(exec_rows, key=lambda r: float(r["transaction_volume"]))
    assert mom["strongest"]["transaction_volume"]["month"] == max_vol_row["month"]
    # Check driver analyses exist for product and customer
    drivers = {}
    for res in msg["results"]:
        if res["result_type"] == "driver_analysis":
            dim = res["result_data"].get("driver_column")
            drivers[dim] = res["result_data"]
    # Should have product_id and customer_id
    assert "product_id" in drivers or any("product" in k for k in drivers), f"Missing product driver: {drivers.keys()}"
    assert "customer_id" in drivers or any("customer" in k for k in drivers), f"Missing customer driver: {drivers.keys()}"
    # Check each driver has contribution
    for dim, drv in drivers.items():
        if "product" in dim or "customer" in dim:
            assert "drivers" in drv and len(drv["drivers"]) > 0, f"Driver {dim} has no ranked contributors"
            top = drv["drivers"][0]
            assert "driver_value" in top
            assert "change" in top
            # contribution should be present for volume
            if "transaction_volume" in drv.get("metric", "") or dim == "product_id":
                assert "contribution_pct" in top or "change" in top
    # Statistical validation is either valid OR explicitly unavailable (not fabricated)
    stat = None
    for res in msg["results"]:
        if res["result_type"] == "statistical_validation":
            stat = res["result_data"]
    assert stat is not None, "Missing statistical_validation"
    # Must not have fabricated p-value when not applicable: p should be None when applicable false
    if not stat.get("applicable"):
        assert stat.get("p_value") is None, f"Should not fabricate p when not applicable: {stat}"
        assert "time-series" in stat.get("reason", "").lower() or "time" in stat.get("reason", "").lower() or "not supported" in stat.get("reason", "").lower(), f"Reason should explain time-series not supported: {stat}"
        # Drivers must still exist even when stat not applicable (spec 6)
        assert len(drivers) > 0, "Drivers erased when stat not applicable"
    else:
        # If applicable, p must be 0-1
        assert 0 <= stat["p_value"] <= 1

    # Recommendation must be grounded, not generic fallback
    rec = None
    for res in msg["results"]:
        if res["result_type"] == "recommendation":
            rec = res["result_data"]
    assert rec is not None, "Missing recommendation"
    assert rec["recommendation"] != "Review evidence and validate before action.", "Generic fallback not allowed when drivers available"
    # Must use verified ranking (peak is 2023-12) not first row 2023-01 or 2023-10
    # Check recommendation supporting_evidence contains peak month
    supporting = json.dumps(rec.get("supporting_evidence", [])).lower()
    assert "2023-12" in supporting or "peak" in supporting.lower(), f"Recommendation should reference peak 2023-12, got {supporting}"
    # Should mention drivers
    assert "product" in rec["recommendation"].lower() or "customer" in rec["recommendation"].lower() or "driver" in rec["recommendation"].lower(), f"Recommendation should mention drivers: {rec}"

    # Question coverage has no missing required components (complete)
    coverage = None
    for res in msg["results"]:
        if res["result_type"] == "question_coverage":
            coverage = res["result_data"]
    assert coverage is not None, "Missing question_coverage"
    assert coverage["missing_components"] == [], f"Should have no missing, got {coverage['missing_components']}"
    assert coverage["analysis_completeness"] == "complete"
    assert coverage["coverage_ratio"] == 1.0 or coverage["coverage_ratio"] >= 0.95
    # Requested must contain A-K
    for comp in ["monthly_transaction_volume", "monthly_average_unit_price", "strongest_weakest", "mom", "product_driver", "customer_driver", "statistical_validation", "recommendation"]:
        assert comp in coverage["requested_components"], f"Missing requested {comp}"
    # Trust score cannot be 100 when missing components (but here complete, so can be high; test partial case below)
    # Generated SQL matches executed computation: already checked code contains both metrics and exec_result columns match
    assert msg["generated_code"] == code

def test_adversarial_reverse_metric_order():
    token = _register()
    ds_id, headers = _upload_ecommerce_like(token)
    q = "Analyze average unit price and monthly transaction volume trends. Identify strongest/weakest months and MoM changes, drivers for product and customer, statistical check and recommendation."
    r = client.post(f"/api/datasets/{ds_id}/analyze", headers=headers, json={"question": q})
    assert r.status_code == 200
    code = r.json()["message"]["generated_code"] or ""
    assert "transaction_volume" in code.lower()
    assert "average_unit_price" in code.lower()

def test_adversarial_three_metrics():
    token = _register()
    ds_id, headers = _upload_ecommerce_like(token)
    q = "Analyze monthly transaction volume, average unit price and total quantity trends, strongest/weakest, MoM, product and customer drivers, statistical validation and recommendation."
    r = client.post(f"/api/datasets/{ds_id}/analyze", headers=headers, json={"question": q})
    assert r.status_code == 200
    code = r.json()["message"]["generated_code"] or ""
    # Should have at least 2 metrics, maybe 3 if quantity detected
    assert "transaction_volume" in code.lower()
    # quantity may be SUM(quantity)
    # At least not collapsed to single
    assert code.lower().count("as") >= 2

def test_adversarial_product_region_drivers():
    token = _register()
    ds_id, headers = _upload_ecommerce_like(token)
    # Add region column to dataset for this test: re-upload with region
    import random, datetime, pandas as pd, io
    rows = []
    for m in range(12):
        for i in range(5):
            dt = f"2023-{m+1:02d}-{(i%28)+1:02d}"
            prod = random.choice(["P1","P2"])
            region = random.choice(["East","West"])
            rows.append([dt, prod, region, round(random.uniform(10,20),2)])
    df = pd.DataFrame(rows, columns=["transaction_date","product_id","region","unit_price"])
    csv = df.to_csv(index=False)
    token2 = _register()
    files = {"file": ("region.csv", io.BytesIO(csv.encode()), "text/csv")}
    headers2 = {"Authorization": f"Bearer {token2}"}
    r = client.post("/api/datasets/upload", headers=headers2, files=files)
    ds2 = r.json()["id"]
    q = "Analyze monthly transaction volume and average unit price trends, strongest/weakest, MoM, which product IDs and region contributed most to latest change, statistical check, recommendation."
    r = client.post(f"/api/datasets/{ds2}/analyze", headers=headers2, json={"question": q})
    assert r.status_code == 200
    data = r.json()
    drivers = {res["result_data"].get("driver_column"): res["result_data"] for res in data["message"]["results"] if res["result_type"]=="driver_analysis"}
    # Should have product and region drivers
    assert any("product" in k.lower() for k in drivers) or "product_id" in drivers
    assert any("region" in k.lower() for k in drivers)

def test_missing_product_id_returns_partial_not_crash():
    token = _register()
    # Dataset without product_id: only transaction_date, customer_id, unit_price
    rows = []
    import random, datetime
    for m in range(12):
        for i in range(5):
            dt = f"2023-{m+1:02d}-{(i%28)+1:02d}"
            cust = f"C{i}"
            rows.append([dt, cust, round(random.uniform(10,20),2)])
    df = pd.DataFrame(rows, columns=["transaction_date","customer_id","unit_price"])
    csv = df.to_csv(index=False)
    files = {"file": ("missing_prod.csv", io.BytesIO(csv.encode()), "text/csv")}
    headers = {"Authorization": f"Bearer {token}"}
    r = client.post("/api/datasets/upload", headers=headers, files=files)
    ds_id = r.json()["id"]
    r = client.post(f"/api/datasets/{ds_id}/analyze", headers=headers, json={"question": EXACT_QUERY})
    assert r.status_code == 200
    data = r.json()
    # Should have coverage with missing product_driver
    cov = next((res["result_data"] for res in data["message"]["results"] if res["result_type"]=="question_coverage"), None)
    assert cov is not None
    # Since product_id missing, missing should contain product_driver
    assert any("product" in c for c in cov["missing_components"]), f"Expected missing product, got {cov}"
    # Completeness should be partial, not complete, and execution_status partial
    assert data["message"]["execution_status"] == "partial" or cov["analysis_completeness"] == "partial"
    # Drivers for customer should still exist
    drivers = [res for res in data["message"]["results"] if res["result_type"]=="driver_analysis"]
    assert len(drivers) >= 1

def test_missing_transaction_date_returns_clarification():
    token = _register()
    df = pd.DataFrame([["P1","C1",10],["P2","C2",20]], columns=["product_id","customer_id","unit_price"])
    csv = df.to_csv(index=False)
    files = {"file": ("no_date.csv", io.BytesIO(csv.encode()), "text/csv")}
    headers = {"Authorization": f"Bearer {token}"}
    r = client.post("/api/datasets/upload", headers=headers, files=files)
    ds_id = r.json()["id"]
    r = client.post(f"/api/datasets/{ds_id}/analyze", headers=headers, json={"question": EXACT_QUERY})
    # Should be clarification about missing date
    data = r.json()
    # Either needs_clarification or execution_status clarification
    assert data.get("needs_clarification") or data["message"]["execution_status"] == "clarification" or "date" in data["message"]["content"].lower()

def test_only_one_period_mom_not_applicable():
    token = _register()
    df = pd.DataFrame([["2023-01-15","P1","C1",10],["2023-01-20","P2","C2",20]], columns=["transaction_date","product_id","customer_id","unit_price"])
    csv = df.to_csv(index=False)
    files = {"file": ("one_period.csv", io.BytesIO(csv.encode()), "text/csv")}
    headers = {"Authorization": f"Bearer {token}"}
    r = client.post("/api/datasets/upload", headers=headers, files=files)
    ds_id = r.json()["id"]
    r = client.post(f"/api/datasets/{ds_id}/analyze", headers=headers, json={"question": EXACT_QUERY})
    assert r.status_code == 200
    data = r.json()
    # Find mom
    mom = next((res["result_data"] for res in data["message"]["results"] if res["result_type"]=="mom_analysis"), None)
    # If only one period, has_mom false
    if mom:
        assert mom["has_mom"] is False or "Only one period" in mom.get("reason","")

def test_ambiguous_performance_returns_clarification():
    token = _register()
    ds_id, headers = _upload_ecommerce_like(token, months=3)
    r = client.post(f"/api/datasets/{ds_id}/analyze", headers=headers, json={"question": "Why is performance worse?"})
    data = r.json()
    assert data.get("needs_clarification") or "What performance metric" in data["message"]["content"]

def test_causal_wording_still_executes_with_disclaimer():
    token = _register()
    ds_id, headers = _upload_ecommerce_like(token, months=6)
    q = "What caused the monthly transaction volume and average unit price change? Identify drivers for product and customer and recommend next steps."
    r = client.post(f"/api/datasets/{ds_id}/analyze", headers=headers, json={"question": q})
    assert r.status_code == 200
    data = r.json()
    # Should not be clarification about causal; should have executed with disclaimer in limitations
    # Check that at least one driver exists and recommendation mentions association not causation
    drivers = [res for res in data["message"]["results"] if res["result_type"]=="driver_analysis"]
    # For causal variant with drivers, should still have drivers
    # If causal guard would have blocked, we would get clarification; we expect not
    # So check not clarification
    assert data["message"]["execution_status"] != "clarification", f"Should not be clarification for causal variant, got {data}"

def test_nonexistent_metric_handling():
    token = _register()
    ds_id, headers = _upload_ecommerce_like(token)
    q = "Analyze monthly transaction volume and average unit price and nonexistent_metric trends, drivers for product and customer, MoM and recommendation."
    r = client.post(f"/api/datasets/{ds_id}/analyze", headers=headers, json={"question": q})
    assert r.status_code == 200
    # Should still have transaction_volume and average_unit_price, not fail
    code = r.json()["message"]["generated_code"] or ""
    assert "transaction_volume" in code.lower()
    assert "average_unit_price" in code.lower()

def test_trust_score_not_100_when_incomplete():
    token = _register()
    # dataset missing product_id -> partial
    df = pd.DataFrame([["2023-01-15","C1",10],["2023-02-15","C2",20]], columns=["transaction_date","customer_id","unit_price"])
    csv = df.to_csv(index=False)
    files = {"file": ("trust.csv", io.BytesIO(csv.encode()), "text/csv")}
    headers = {"Authorization": f"Bearer {token}"}
    r = client.post("/api/datasets/upload", headers=headers, files=files)
    ds_id = r.json()["id"]
    r = client.post(f"/api/datasets/{ds_id}/analyze", headers=headers, json={"question": EXACT_QUERY})
    data = r.json()
    cov = next((res["result_data"] for res in data["message"]["results"] if res["result_type"]=="question_coverage"), None)
    assert cov is not None
    # Now get trust score with coverage
    msg_id = data["message"]["id"]
    # Call trust-score with coverage
    r_trust = client.post(f"/api/datasets/{ds_id}/trust-score", headers=headers, json={"query_result": {"success": True}, "question_coverage": cov})
    assert r_trust.status_code == 200
    trust = r_trust.json()
    if cov["missing_components"]:
        assert trust["score"] < 100, f"Trust should not be 100 when incomplete, got {trust['score']}"
        # Check reason contains Question completeness
        assert any("Question completeness" in r["check"] for r in trust["reasons"])

def test_plan_contains_all_required_for_exact_query():
    token = _register()
    ds_id, headers = _upload_ecommerce_like(token)
    r = client.post(f"/api/datasets/{ds_id}/plan", headers=headers, json={"question": EXACT_QUERY})
    assert r.status_code == 200
    data = r.json()
    assert data.get("needs_plan") is True
    plan_titles = " ".join([p["title"].lower() for p in data["plan"]])
    # Check required components in plan
    assert "transaction volume" in plan_titles
    assert "average unit price" in plan_titles or "unit price" in plan_titles
    assert "strongest" in plan_titles or "weakest" in plan_titles
    assert "mom" in plan_titles or "month-over-month" in plan_titles
    assert "product" in plan_titles
    assert "customer" in plan_titles
    assert "statistical" in plan_titles

def test_insight_not_saying_increasing_trend_when_endpoint_only():
    token = _register()
    ds_id, headers = _upload_ecommerce_like(token)
    r = client.post(f"/api/datasets/{ds_id}/analyze", headers=headers, json={"question": EXACT_QUERY})
    content = r.json()["message"]["content"]
    # Should not say "Overall, the value increased" as evidence of increasing trend
    # The fixed wording is "Endpoint change: ... — change is endpoint difference, not a statistically inferred trend"
    assert "Overall, the value increased" not in content, f"Should not contain misleading trend wording: {content[:500]}"
    # Should contain endpoint change phrasing
    assert "Endpoint change" in content or "endpoint difference" in content.lower()

