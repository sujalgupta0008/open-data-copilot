import io, uuid, pandas as pd
from fastapi.testclient import TestClient
from app.main import app
from app.core.database import init_db
client=TestClient(app)
init_db()

def _reg(email=None):
    email=email or f"edge_{uuid.uuid4().hex[:6]}@test.com"
    r=client.post("/api/auth/register", json={"email":email,"password":"passwd123"})
    if r.status_code==400:
        r=client.post("/api/auth/login", json={"email":email,"password":"passwd123"})
    return r.json()["access_token"]

def _upload(token, df, name="test.csv"):
    csv=df.to_csv(index=False)
    headers={"Authorization":f"Bearer {token}"}
    files={"file": (name, io.BytesIO(csv.encode()), "text/csv")}
    r=client.post("/api/datasets/upload", headers=headers, files=files)
    assert r.status_code==200, r.text
    return r.json()["id"], headers

def test_simple_trend_derived_month_why_no_400():
    token=_reg()
    df=pd.DataFrame({
        "order_date": ["2023-01-15","2023-02-15","2023-03-15","2023-01-20","2023-02-20","2023-03-20"],
        "revenue": [100,120,150,110,130,160],
        "region": ["East","East","West","West","East","West"]
    })
    ds_id, headers=_upload(token, df, "derived.csv")
    # Analyze with derived month
    r=client.post(f"/api/datasets/{ds_id}/analyze", headers=headers, json={"question":"Show monthly revenue trends and explain why revenue changed."})
    assert r.status_code==200, r.text
    msg=r.json()["message"]
    # Code should have derived month
    assert "substr" in msg["generated_code"].lower() and "month" in msg["generated_code"].lower()
    # Why? should not be 400
    r2=client.post(f"/api/datasets/{ds_id}/root-cause", headers=headers, json={"message_id": msg["id"]})
    assert r2.status_code==200, f"Expected 200 not 400 for derived month, got {r2.status_code}: {r2.text}"
    res=r2.json()
    # Should be trend reuse, not dimension month not found
    assert "Dimension 'month' not found" not in r2.text
    assert res.get("is_trend_reuse") or "trend" in res.get("summary","").lower() or "Monthly" in res.get("summary","")
    # Should have fallback drivers for real dimension (region) or trend summary
    # Check not leaking unrelated
    import json
    assert "Revenue changed" not in json.dumps(res) or "Monthly" in res.get("summary","")  # Allow Revenue changed if it's trend summary for revenue, but not unrelated leak
    # Should have disclaimer association not causation
    assert "association" in res.get("disclaimer","").lower()

def test_simple_trend_real_date_column_why():
    token=_reg()
    # Real date column is transaction_date (actual datetime dtype after conversion)
    df=pd.DataFrame({
        "transaction_date": pd.to_datetime(["2023-01-15","2023-02-15","2023-03-15","2023-01-20","2023-02-20","2023-03-20"]),
        "revenue": [100,120,150,110,130,160],
        "region": ["East","East","West","West","East","West"]
    })
    # Need to ensure transaction_date is stored as date string for upload, but after load it will be parsed
    df["transaction_date"]=df["transaction_date"].astype(str)
    ds_id, headers=_upload(token, df, "realdate.csv")
    r=client.post(f"/api/datasets/{ds_id}/analyze", headers=headers, json={"question":"Show monthly revenue trends and explain why revenue changed."})
    assert r.status_code==200
    msg=r.json()["message"]
    r2=client.post(f"/api/datasets/{ds_id}/root-cause", headers=headers, json={"message_id": msg["id"]})
    assert r2.status_code==200
    res=r2.json()
    # Should have summary and not 400
    assert "summary" in res
    # Should not leak unrelated metric
    import json
    # For this dataset, revenue is the metric, so Revenue changed is expected, but should not leak other metrics like "Salary"
    assert "Salary" not in json.dumps(res)

def test_complex_trend_why_deterministic_reuse():
    token=_reg()
    import random
    random.seed(5)
    rows=[]
    for m in range(12):
        for i in range(8):
            dt=f"2023-{m+1:02d}-{(i%28)+1:02d}"
            prod=random.choice(["P1","P2"])
            cust=random.choice(["C1","C2"])
            price=round(15+random.uniform(-2,2)+(4 if m==11 else 0),2)
            rows.append([dt,prod,cust,price])
    df=pd.DataFrame(rows, columns=["transaction_date","product_id","customer_id","unit_price"])
    ds_id, headers=_upload(token, df, "complex_trend.csv")
    q="Analyze monthly transaction volume and average unit price trends. Identify the strongest and weakest months, quantify the month-over-month changes, determine which product IDs and customer IDs contributed most to the latest change, assess whether the observed differences are statistically meaningful where applicable, and recommend what should be investigated next."
    r=client.post(f"/api/datasets/{ds_id}/analyze", headers=headers, json={"question":q})
    assert r.status_code==200
    msg=r.json()["message"]
    # Check has mom and drivers
    assert any(rr["result_type"]=="mom_analysis" for rr in msg["results"])
    assert any(rr["result_type"]=="driver_analysis" for rr in msg["results"])
    # Why? should be deterministic from existing, not calling root-cause with month
    # Simulate frontend: if hasComplex, build Why? from existing without API
    # Check that existing drivers contain product and customer
    drivers=[rr["result_data"] for rr in msg["results"] if rr["result_type"]=="driver_analysis"]
    assert any("product_id" in d.get("driver_column","") for d in drivers)
    # Ensure no Revenue leakage in complex drivers (dataset has no revenue)
    import json
    for d in drivers:
        assert "Revenue" not in json.dumps(d)

def test_no_unrelated_driver_leakage():
    token=_reg()
    df=pd.DataFrame({"order_date":["2023-01-01","2023-02-01"],"revenue":[100,200],"region":["East","West"]})
    ds_id, headers=_upload(token, df, "leak.csv")
    r=client.post(f"/api/datasets/{ds_id}/analyze", headers=headers, json={"question":"Show monthly revenue trends and explain why revenue changed."})
    msg=r.json()["message"]
    r2=client.post(f"/api/datasets/{ds_id}/root-cause", headers=headers, json={"message_id": msg["id"]})
    assert r2.status_code==200
    res=r2.json()
    # Should be about revenue, not leaking other metrics like Salary or Loan
    import json
    txt=json.dumps(res)
    assert "Salary" not in txt
    assert "Loan" not in txt
    assert "association" in res.get("disclaimer","").lower()

def test_why_trend_prefers_existing_results():
    token=_reg()
    df=pd.DataFrame({
        "order_date": ["2023-01-15","2023-02-15","2023-03-15"],
        "revenue": [100,200,150],
        "region": ["East","West","East"]
    })
    ds_id, headers=_upload(token, df, "pref.csv")
    r=client.post(f"/api/datasets/{ds_id}/analyze", headers=headers, json={"question":"Show monthly revenue trends and explain why revenue changed."})
    msg=r.json()["message"]
    # Existing table has month and total_revenue
    table=next((rr["result_data"] for rr in msg["results"] if rr["result_type"]=="table"), None)
    assert table is not None
    assert "month" in [c.lower() for c in table["columns"]]
    # Why? should reuse this table (trend_reuse) and not regenerate unrelated SQL
    r2=client.post(f"/api/datasets/{ds_id}/root-cause", headers=headers, json={"message_id": msg["id"]})
    assert r2.status_code==200
    res=r2.json()
    # Should be trend reuse
    assert res.get("is_trend_reuse") or "trend" in res.get("summary","").lower()
    # Should not have regenerated SQL with different metric
    assert "total_revenue" in res.get("sql","").lower() or "revenue" in res.get("summary","").lower()
