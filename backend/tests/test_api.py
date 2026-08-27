from fastapi.testclient import TestClient
from app.main import app
from app.core.database import init_db
import os, tempfile, io
import pandas as pd

init_db()
client = TestClient(app)

def test_register_login():
    email = "test_user@example.com"
    pwd = "password123"
    r = client.post("/api/auth/register", json={"email": email, "password": pwd, "name": "Test"})
    # may already exist -> try login
    if r.status_code == 400:
        r = client.post("/api/auth/login", json={"email": email, "password": pwd})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    assert token
    # me
    r2 = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200
    assert r2.json()["email"] == email

def test_dataset_upload_and_ownership():
    # create user A and B
    r = client.post("/api/auth/register", json={"email":"a@a.com","password":"passwd123"})
    if r.status_code==400:
        r = client.post("/api/auth/login", json={"email":"a@a.com","password":"passwd123"})
    token_a = r.json()["access_token"]
    r = client.post("/api/auth/register", json={"email":"b@b.com","password":"passwd123"})
    if r.status_code==400:
        r = client.post("/api/auth/login", json={"email":"b@b.com","password":"passwd123"})
    token_b = r.json()["access_token"]
    # upload as A
    csv_data = "col1,col2\n1,hello\n2,world\n"
    files = {"file": ("test.csv", csv_data, "text/csv")}
    r = client.post("/api/datasets/upload", files=files, headers={"Authorization": f"Bearer {token_a}"})
    assert r.status_code==200, r.text
    ds_id = r.json()["id"]
    # B tries to access -> 404
    r = client.get(f"/api/datasets/{ds_id}", headers={"Authorization": f"Bearer {token_b}"})
    assert r.status_code==404
    # A can access
    r = client.get(f"/api/datasets/{ds_id}", headers={"Authorization": f"Bearer {token_a}"})
    assert r.status_code==200
    # profile
    r = client.get(f"/api/datasets/{ds_id}/profile", headers={"Authorization": f"Bearer {token_a}"})
    assert r.status_code==200
    assert "quality_details" in r.json()
    # sql validation blocked
    from app.execution.sql import validate_sql
    ok,msg = validate_sql("DROP TABLE df")
    assert not ok
    ok,msg = validate_sql("SELECT * FROM df")
    assert ok

def test_sql_execution():
    from app.execution.sql import execute_sql
    df = pd.DataFrame({"category":["A","B","A"],"revenue":[100,200,150]})
    res = execute_sql(df, 'SELECT category, SUM(revenue) as total FROM df GROUP BY category ORDER BY total DESC')
    assert res["success"]
    assert len(res["data"])==2

def test_python_execution():
    from app.execution.python_exec import execute_python
    df = pd.DataFrame({"a":[1,2,None],"b":[4,5,6]})
    res = execute_python(df, "result = df.isnull().sum().to_frame('missing')\nprint(result)")
    assert res["success"]

def test_aggregation_intents():
    import asyncio
    from app.ai.provider import MockProvider
    provider = MockProvider()
    context = {
        "columns": [
            {"name": "Airline", "data_type": "object"},
            {"name": "Source", "data_type": "object"},
            {"name": "Destination", "data_type": "object"},
            {"name": "Price", "data_type": "int64"},
            {"name": "Date", "data_type": "object"},
        ],
        "dataset_name": "flight_price",
        "row_count": 100,
        "column_count": 5
    }

    # 1. average price by airline
    res = asyncio.run(provider.generate(context, "Which airline has the highest average price, and what is the average price?"))
    assert "AVG" in res["code"], f"Expected AVG, got {res['code']}"
    assert "average_price" in res["code"].lower(), f"Alias should be average_price, got {res['code']}"
    assert "Airline" in res["code"]
    assert "average" in res["explanation"].lower()

    # 2. total price by airline
    res = asyncio.run(provider.generate(context, "Total price by airline"))
    assert "SUM" in res["code"], f"Expected SUM, got {res['code']}"
    assert "total_price" in res["code"].lower() or "total" in res["code"].lower()
    assert "Airline" in res["code"]

    # 3. minimum price
    res = asyncio.run(provider.generate(context, "What is the minimum price?"))
    assert "MIN" in res["code"], f"Expected MIN, got {res['code']}"
    assert "min_price" in res["code"].lower()

    # 4. maximum price
    res = asyncio.run(provider.generate(context, "What is the maximum price?"))
    assert "MAX" in res["code"], f"Expected MAX, got {res['code']}"
    assert "max_price" in res["code"].lower()

    # 5. count by airline
    res = asyncio.run(provider.generate(context, "Count by airline"))
    assert "COUNT" in res["code"], f"Expected COUNT, got {res['code']}"
    assert "count" in res["code"].lower()

    # 6. monthly average price
    res = asyncio.run(provider.generate(context, "Monthly average price"))
    assert "AVG" in res["code"], f"Expected AVG for monthly average, got {res['code']}"
    assert "average_price" in res["code"].lower()
    assert "month" in res["code"].lower()
    assert "average" in res["explanation"].lower()

    # Also test top 5 airlines by total price still uses SUM
    res = asyncio.run(provider.generate(context, "Top 5 airlines by total price"))
    assert "SUM" in res["code"]
    assert "total" in res["code"].lower()

def test_strict_csv_validation():
    # Valid CSV should pass
    import time
    email = f"csvval_{int(time.time()*1000)}@test.com"
    pwd = "password123"
    r = client.post("/api/auth/register", json={"email": email, "password": pwd})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    # 1. ragged CSV (row with extra column)
    ragged = "col1,col2\n1,2,3,4\n5,6\n"
    files = {"file": ("ragged.csv", ragged, "text/csv")}
    r = client.post("/api/datasets/upload", files=files, headers=h)
    assert r.status_code == 400, f"Ragged CSV should be rejected, got {r.status_code} {r.text}"
    assert "column count" in r.text.lower() or "inconsistent" in r.text.lower()
    # 2. duplicate column names
    dup = "name,name\nAlice,30\nBob,25\n"
    files = {"file": ("dup.csv", dup, "text/csv")}
    r = client.post("/api/datasets/upload", files=files, headers=h)
    assert r.status_code == 400, r.text
    assert "duplicate" in r.text.lower()
    # 3. empty header cell
    empty_h = "col1,,col3\n1,2,3\n4,5,6\n"
    files = {"file": ("emptyh.csv", empty_h, "text/csv")}
    r = client.post("/api/datasets/upload", files=files, headers=h)
    assert r.status_code == 400, r.text
    assert "empty header" in r.text.lower() or "header name" in r.text.lower()
    # 4. header only, no data
    header_only = "col1,col2,col3\n"
    files = {"file": ("headeronly.csv", header_only, "text/csv")}
    r = client.post("/api/datasets/upload", files=files, headers=h)
    assert r.status_code == 400, r.text
    # 5. valid CSV should still pass
    valid = "col1,col2\n1,hello\n2,world\n"
    files = {"file": ("valid.csv", valid, "text/csv")}
    r = client.post("/api/datasets/upload", files=files, headers=h)
    assert r.status_code == 200, r.text
    # 6. ragged with missing column (fewer columns)
    ragged2 = "a,b,c\n1,2,3\n4,5\n"
    files = {"file": ("ragged2.csv", ragged2, "text/csv")}
    r = client.post("/api/datasets/upload", files=files, headers=h)
    assert r.status_code == 400, r.text

def test_aggregation_e2e_via_api():
    # Upload a flight-like dataset and test via API that correct aggregation is used
    import time
    email = f"agg_{int(time.time()*1000)}@test.com"
    pwd = "password123"
    r = client.post("/api/auth/register", json={"email": email, "password": pwd})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    csv_data = "Airline,Source,Destination,Price,Date\nIndiGo,Delhi,Cochin,5000,2023-01-15\nAir India,Delhi,Cochin,7000,2023-01-20\nIndiGo,Mumbai,Hyderabad,4000,2023-02-10\nAir India,Mumbai,Hyderabad,8000,2023-02-12\nSpiceJet,Delhi,Cochin,6000,2023-01-25\n"
    files = {"file": ("flight.csv", csv_data, "text/csv")}
    r = client.post("/api/datasets/upload", files=files, headers=h)
    assert r.status_code == 200, r.text
    ds_id = r.json()["id"]

    # Test average price by airline via analyze
    r = client.post(f"/api/datasets/{ds_id}/analyze", headers=h, json={"question": "Which airline has the highest average price, and what is the average price?"})
    assert r.status_code == 200, r.text
    j = r.json()
    code = j["message"]["generated_code"]
    assert "AVG" in code, f"Should use AVG, got {code}"
    assert "average_price" in code.lower(), f"Alias should be average_price, got {code}"
    # Verify execution succeeded and result column is average_price
    results = j["message"]["results"]
    assert len(results) > 0
    cols = results[0]["result_data"]["columns"]
    # check alias appears
    assert any("average_price" in str(c).lower() for c in cols), f"Columns should contain average_price, got {cols}"
    assert j["message"]["execution_status"] == "success"
    # explanation should mention average
    assert "average" in j["message"]["content"].lower()

    # Test minimum price
    r = client.post(f"/api/datasets/{ds_id}/analyze", headers=h, json={"question": "What is the minimum price?", "session_id": j["session_id"]})
    assert r.status_code == 200
    code2 = r.json()["message"]["generated_code"]
    assert "MIN" in code2, f"Expected MIN, got {code2}"
    assert "min_price" in code2.lower()

    # Test count by airline
    r = client.post(f"/api/datasets/{ds_id}/analyze", headers=h, json={"question": "Count by airline", "session_id": j["session_id"]})
    assert r.status_code == 200
    code3 = r.json()["message"]["generated_code"]
    assert "COUNT" in code3, f"Expected COUNT, got {code3}"

    # Test monthly average price
    r = client.post(f"/api/datasets/{ds_id}/analyze", headers=h, json={"question": "Monthly average price", "session_id": j["session_id"]})
    assert r.status_code == 200
    code4 = r.json()["message"]["generated_code"]
    assert "AVG" in code4, f"Monthly average should use AVG, got {code4}"
    assert "average_price" in code4.lower()

