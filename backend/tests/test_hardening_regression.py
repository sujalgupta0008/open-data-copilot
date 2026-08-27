"""Hardening regression - SQL injection semicolon/comment and C Trend correctness"""
import io
import pandas as pd
from fastapi.testclient import TestClient
from app.main import app
from app.execution.sql import validate_sql, execute_sql

client = TestClient(app)

def test_sql_semicolon_blocked():
    ok, msg = validate_sql("SELECT * FROM df; SELECT * FROM df")
    assert not ok
    assert "semicolon" in msg.lower()
    # trailing semicolon allowed
    ok2, _ = validate_sql("SELECT * FROM df;")
    assert ok2
    ok3, _ = validate_sql("SELECT * FROM df")
    assert ok3

def test_sql_comment_blocked():
    ok, msg = validate_sql("SELECT * FROM df -- comment")
    assert not ok
    assert "comment" in msg.lower()
    ok2, _ = validate_sql("SELECT * FROM df /* comment */")
    assert not ok2

def test_sql_injection_drop_blocked():
    ok, msg = validate_sql("SELECT * FROM df; DROP TABLE df")
    assert not ok

def test_c_trend_uses_revenue_not_credit():
    # Repro: ensure trend on ecom uses revenue
    from app.core.database import SessionLocal
    from app.models.models import Dataset
    import uuid
    # use helper to create user/dataset via API
    # register user
    email = f"hard_{uuid.uuid4().hex[:6]}@test.com"
    r = client.post("/api/auth/register", json={"email": email, "password": "passwd123"})
    tok = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {tok}"}
    # upload ecom
    csv = "order_id,order_date,region,revenue\n1,2023-01-15,North,100\n2,2023-02-15,South,200\n"
    files = {"file": ("ecom.csv", io.BytesIO(csv.encode()), "text/csv")}
    r = client.post("/api/datasets/upload", headers=headers, files=files)
    assert r.status_code == 200
    ds_id = r.json()["id"]
    r = client.post(f"/api/datasets/{ds_id}/analyze", headers=headers, json={"question":"Revenue decreased significantly in the latest month compared to the previous month. When did the decline start?"})
    assert r.status_code == 200
    data = r.json()
    code = data["message"]["generated_code"] or ""
    assert "revenue" in code.lower()
    assert "credit_history" not in code.lower()
    # Should not be clarification
    assert data["message"]["execution_status"] != "clarification"

def test_versioning_report_immutability():
    import uuid, io
    email = f"ver_{uuid.uuid4().hex[:6]}@test.com"
    r = client.post("/api/auth/register", json={"email": email, "password": "passwd123"})
    tok = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {tok}"}
    csv = "id,revenue\n1,10\n2,20\n"
    files = {"file": ("v.csv", io.BytesIO(csv.encode()), "text/csv")}
    r = client.post("/api/datasets/upload", headers=headers, files=files)
    ds_id = r.json()["id"]
    r = client.post("/api/reports", headers=headers, json={"dataset_id": ds_id, "title":"V1"})
    assert r.status_code == 200
    rep1 = r.json()
    v1 = rep1["dataset_version"]
    # create new version
    r = client.post(f"/api/datasets/{ds_id}/clean/apply", headers=headers, json={"op":"text","params":{"column":"revenue","sub_operation":"trim"}})
    # also create snapshot
    r = client.post(f"/api/datasets/{ds_id}/versions", headers=headers, json={"name":"V2"})
    r = client.get(f"/api/reports/{rep1['id']}", headers=headers)
    assert r.status_code == 200
    rep1_after = r.json()
    assert rep1_after["dataset_version"] == v1

def test_export_after_trim():
    import uuid, io
    email = f"exp_{uuid.uuid4().hex[:6]}@test.com"
    r = client.post("/api/auth/register", json={"email": email, "password": "passwd123"})
    tok = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {tok}"}
    csv = "Airline,Price\n  IndiGo  ,100\n Air India ,200\n"
    files = {"file": ("ws.csv", io.BytesIO(csv.encode()), "text/csv")}
    r = client.post("/api/datasets/upload", headers=headers, files=files)
    ds_id = r.json()["id"]
    r = client.post(f"/api/datasets/{ds_id}/clean/apply", headers=headers, json={"op":"text","params":{"column":"Airline","sub_operation":"trim"}})
    assert r.status_code == 200
    r = client.get(f"/api/datasets/{ds_id}/export?format=csv", headers=headers)
    assert r.status_code == 200
    df = pd.read_csv(io.BytesIO(r.content))
    assert all(not str(v).startswith(" ") and not str(v).endswith(" ") for v in df["Airline"] if pd.notna(v))
