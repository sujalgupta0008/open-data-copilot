"""
Regression tests for second pass adversarial QA bugs
"""
from fastapi.testclient import TestClient
from app.main import app
from app.core.database import init_db
import uuid, io, pandas as pd, duckdb
init_db()
client = TestClient(app)

def user(email):
    r = client.post("/api/auth/register", json={"email":email,"password":"passwd123"})
    if r.status_code==400:
        r=client.post("/api/auth/login", json={"email":email,"password":"passwd123"})
    return r.json()["access_token"]

def test_wide_dataset_constant_quality():
    # Wide 80 cols with 2 rows same value -> 80 constant cols -> quality 0, not 80
    tok=user(f"wide{uuid.uuid4().hex[:4]}@test.com")
    h={"Authorization":f"Bearer {tok}"}
    header=",".join([f"col{i}" for i in range(80)])
    row=",".join(["1"]*80)
    csv=header+"\n"+row+"\n"+row+"\n"
    files={"file":("wide.csv",csv,"text/csv")}
    r=client.post("/api/datasets/upload", files=files, headers=h)
    assert r.status_code==200
    did=r.json()["id"]
    r=client.get(f"/api/datasets/{did}/profile", headers=h)
    assert r.status_code==200
    j=r.json()
    assert j["dataset"]["column_count"]==80
    assert j["quality_details"]["factors"]["constant_columns"]==80
    assert j["quality_details"]["score"]==0  # 100 -80*5 =0

def test_export_after_cleaning_matches_current_version():
    tok=user(f"export{uuid.uuid4().hex[:4]}@test.com")
    h={"Authorization":f"Bearer {tok}"}
    csv='name,price\n"  IndiGo ",5000\n"air india",7000\n'
    files={"file":("w.csv",csv,"text/csv")}
    r=client.post("/api/datasets/upload", files=files, headers=h)
    did=r.json()["id"]
    # trim
    r=client.post(f"/api/datasets/{did}/clean/apply", headers=h, json={"op":"text","params":{"column":"name","sub_operation":"trim"}})
    assert r.status_code==200
    r=client.get(f"/api/datasets/{did}/export?format=csv", headers=h)
    assert r.status_code==200
    df=pd.read_csv(io.BytesIO(r.content))
    assert not any('  ' in str(v) for v in df['name']), "export should be trimmed"
    # lowercase
    r=client.post(f"/api/datasets/{did}/clean/apply", headers=h, json={"op":"text","params":{"column":"name","sub_operation":"lowercase"}})
    r=client.get(f"/api/datasets/{did}/export?format=csv", headers=h)
    df=pd.read_csv(io.BytesIO(r.content))
    assert all(str(v)==str(v).lower() for v in df['name'])

def test_audit_never_mutates():
    tok=user(f"audit{uuid.uuid4().hex[:4]}@test.com")
    h={"Authorization":f"Bearer {tok}"}
    csv='a,b\n1,2\n2,\n3,4\n'
    files={"file":("audit.csv",csv,"text/csv")}
    did=client.post("/api/datasets/upload", files=files, headers=h).json()["id"]
    before=client.get(f"/api/datasets/{did}/profile", headers=h).json()["dataset"]["row_count"]
    vers_before=client.get(f"/api/datasets/{did}/versions", headers=h).json()
    r=client.post(f"/api/datasets/{did}/analyze", headers=h, json={"question":"Identify all data quality issues and rank them by severity. Do not modify data."})
    assert r.status_code==200
    assert r.json().get("intent")=="data_quality_analysis"
    after=client.get(f"/api/datasets/{did}/profile", headers=h).json()["dataset"]["row_count"]
    vers_after=client.get(f"/api/datasets/{did}/versions", headers=h).json()
    assert before==after
    assert len(vers_before)==len(vers_after)

def test_semantic_trap_status_not_dimension():
    tok=user(f"trap{uuid.uuid4().hex[:4]}@test.com")
    h={"Authorization":f"Bearer {tok}"}
    csv='Airline,Price,Date\nIndiGo,5000,2023-01-15\nAir India,7000,2023-01-20\n'
    did=client.post("/api/datasets/upload", files={"file":("cop.csv",csv,"text/csv")}, headers=h).json()["id"]
    r=client.post(f"/api/datasets/{did}/analyze", headers=h, json={"question":"Which status has highest approval?"})
    assert r.status_code==200
    # should be clarification, not MAX Price
    code=r.json()["message"].get("generated_code") or ""
    assert not ("MAX" in code and "Price" in code), f"should not be MAX Price, got {code}"
    assert r.json().get("intent")=="needs_clarification" or "couldn't find" in r.json()["message"]["content"].lower()

def test_driver_binder_fix():
    tok=user(f"driver{uuid.uuid4().hex[:4]}@test.com")
    h={"Authorization":f"Bearer {tok}"}
    csv="order_date,region,revenue\n2023-01-15,North,1000\n2023-01-20,South,1200\n2023-02-10,North,800\n"
    did=client.post("/api/datasets/upload", files={"file":("time.csv",csv,"text/csv")}, headers=h).json()["id"]
    r=client.post(f"/api/datasets/{did}/analyze", headers=h, json={"question":"Why did revenue decline?"})
    mid=r.json()["message"]["id"]
    r=client.post(f"/api/datasets/{did}/root-cause", headers=h, json={"message_id":mid,"dimension":"region"})
    assert r.status_code==200, r.text
    assert "UnboundLocalError" not in r.text
    assert "drivers" in r.json()

def test_clarification_endpoint_exists():
    tok=user(f"clar{uuid.uuid4().hex[:4]}@test.com")
    h={"Authorization":f"Bearer {tok}"}
    csv="a,b\n1,2\n"
    did=client.post("/api/datasets/upload", files={"file":("c.csv",csv,"text/csv")}, headers=h).json()["id"]
    r=client.post(f"/api/datasets/{did}/clarify", headers=h, json={"question":"Why is performance worse?"})
    assert r.status_code==200
    assert "needs_clarification" in r.json()
    r=client.post(f"/api/datasets/{did}/plan", headers=h, json={"question":"What is total revenue?"})
    assert r.status_code==200
    assert "needs_plan" in r.json()
