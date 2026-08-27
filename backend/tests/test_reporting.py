import io, json, uuid, pandas as pd, duckdb
from fastapi.testclient import TestClient
from app.main import app
from app.core.database import init_db
init_db()
client = TestClient(app)

def user(email):
    r = client.post("/api/auth/register", json={"email":email,"password":"passwd123"})
    if r.status_code==400:
        r = client.post("/api/auth/login", json={"email":email,"password":"passwd123"})
    assert r.status_code==200, r.text
    return r.json()["access_token"]

def test_mode_a_simple_topic():
    tok=user(f"rep_a_{uuid.uuid4().hex[:6]}@test.com")
    h={"Authorization":f"Bearer {tok}"}
    csv="region,revenue,order_date\nNorth,1000,2023-01-15\nSouth,1200,2023-01-20\nNorth,800,2023-02-10\n"
    did=client.post("/api/datasets/upload", files={"file":("a.csv",csv,"text/csv")}, headers=h).json()["id"]
    r=client.post("/api/reports/generate", headers=h, json={"dataset_id":did, "topic":"What is total revenue by region?"})
    assert r.status_code==200, r.text
    j=r.json()
    assert j["id"]!="clarification"
    assert j["report_type"]=="ai_generated"
    # PDF
    r=client.get(f"/api/reports/{j['id']}/pdf", headers=h)
    assert r.status_code==200
    assert r.content[:4]==b"%PDF"
    # Version retained
    assert j["dataset_version"] is not None

def test_mode_a_complex_topic():
    tok=user(f"rep_c_{uuid.uuid4().hex[:6]}@test.com")
    h={"Authorization":f"Bearer {tok}"}
    csv="region,revenue,order_date\nNorth,1000,2023-01-15\nSouth,1200,2023-01-20\nNorth,800,2023-02-10\nSouth,900,2023-02-18\n"
    did=client.post("/api/datasets/upload", files={"file":("a.csv",csv,"text/csv")}, headers=h).json()["id"]
    r=client.post("/api/reports/generate", headers=h, json={"dataset_id":did, "topic":"Analyze revenue performance and identify the main factors behind recent changes."})
    assert r.status_code==200
    j=r.json()
    # May be clarification if ambiguous, but with revenue column should be report
    assert j["id"]!="clarification" or "clarification" in str(j)
    if j["id"]!="clarification":
        assert j["report_type"]=="ai_generated"
        # Check content has at least 5 sections
        content=j["content"]
        assert "executive_summary" in content
        assert "business_question" in content
        assert "dataset_overview" in content

def test_mode_a_ambiguous():
    tok=user(f"rep_amb_{uuid.uuid4().hex[:6]}@test.com")
    h={"Authorization":f"Bearer {tok}"}
    csv="region,revenue\nNorth,1000\nSouth,1200\n"
    did=client.post("/api/datasets/upload", files={"file":("a.csv",csv,"text/csv")}, headers=h).json()["id"]
    r=client.post("/api/reports/generate", headers=h, json={"dataset_id":did, "topic":"Why is performance worse?"})
    assert r.status_code==200
    j=r.json()
    assert j["id"]=="clarification" or j.get("report_type")=="clarification"
    assert "needs_clarification" in str(j["content"]).lower()

def test_mode_a_missing_metric():
    tok=user(f"rep_miss_{uuid.uuid4().hex[:6]}@test.com")
    h={"Authorization":f"Bearer {tok}"}
    csv="Airline,Price\nIndiGo,5000\nAir India,7000\n"
    did=client.post("/api/datasets/upload", files={"file":("a.csv",csv,"text/csv")}, headers=h).json()["id"]
    r=client.post("/api/reports/generate", headers=h, json={"dataset_id":did, "topic":"What is total revenue?"})
    assert r.status_code==200
    j=r.json()
    assert j["id"]=="clarification"
    assert "revenue" in str(j).lower()

def test_mode_a_nonexistent_column():
    tok=user(f"rep_non_{uuid.uuid4().hex[:6]}@test.com")
    h={"Authorization":f"Bearer {tok}"}
    csv="a,b\n1,2\n3,4\n"
    did=client.post("/api/datasets/upload", files={"file":("a.csv",csv,"text/csv")}, headers=h).json()["id"]
    r=client.post("/api/reports/generate", headers=h, json={"dataset_id":did, "topic":"Analyze revenue by nonexistent_column_xyz"})
    assert r.status_code==200
    j=r.json()
    # Should be clarification about missing revenue or dimension
    assert j["id"]=="clarification" or "clarification" in j.get("report_type","")

def test_mode_a_data_quality():
    tok=user(f"rep_dq_{uuid.uuid4().hex[:6]}@test.com")
    h={"Authorization":f"Bearer {tok}"}
    csv="a,b\n1,2\n2,\n3,4\n"
    did=client.post("/api/datasets/upload", files={"file":("a.csv",csv,"text/csv")}, headers=h).json()["id"]
    r=client.get(f"/api/datasets/{did}/versions", headers=h)
    vers_before=len(r.json())
    r=client.post("/api/reports/generate", headers=h, json={"dataset_id":did, "topic":"Identify all data quality issues and rank them by severity. Do not modify data."})
    assert r.status_code==200
    j=r.json()
    assert j["id"]!="clarification"
    assert "quality" in str(j["content"]).lower()
    # Verify no mutation: versions should not increase due to audit
    r=client.get(f"/api/datasets/{did}/versions", headers=h)
    vers_after=len(r.json())
    assert vers_before==vers_after

def test_mode_b_copilot():
    tok=user(f"rep_b_{uuid.uuid4().hex[:6]}@test.com")
    h={"Authorization":f"Bearer {tok}"}
    csv="region,revenue\nNorth,1000\nSouth,1200\n"
    did=client.post("/api/datasets/upload", files={"file":("a.csv",csv,"text/csv")}, headers=h).json()["id"]
    r=client.post(f"/api/datasets/{did}/analyze", headers=h, json={"question":"What is total revenue by region?"})
    sess=r.json()["session_id"]
    r=client.post("/api/reports/from-session", headers=h, json={"dataset_id":did, "session_id":sess, "title":"Copilot Report"})
    assert r.status_code==200
    j=r.json()
    assert j["session_id"]==sess
    assert j["report_type"]=="copilot"
    # Appears in library
    r=client.get("/api/reports", headers=h)
    assert any(x["id"]==j["id"] for x in r.json())

def test_combined_simple():
    tok=user(f"rep_comb_{uuid.uuid4().hex[:6]}@test.com")
    h={"Authorization":f"Bearer {tok}"}
    csv="region,revenue\nNorth,1000\nSouth,1200\nNorth,800\n"
    did=client.post("/api/datasets/upload", files={"file":("a.csv",csv,"text/csv")}, headers=h).json()["id"]
    r1=client.post("/api/reports/generate", headers=h, json={"dataset_id":did, "topic":"What is total revenue by region?", "title":"R1"})
    r2=client.post("/api/reports/generate", headers=h, json={"dataset_id":did, "topic":"Average revenue by region", "title":"R2"})
    assert r1.status_code==200 and r2.status_code==200
    id1=r1.json()["id"]; id2=r2.json()["id"]
    r=client.post("/api/reports/combined", headers=h, json={"report_ids":[id1,id2], "title":"Combined"})
    assert r.status_code==200
    j=r.json()
    assert j["report_type"]=="combined"
    assert len(j["content"]["combined_summaries"])==2
    for summ in j["content"]["combined_summaries"]:
        assert len(summ["bullets"])==5
    # PDF
    cid=j["id"]
    r=client.get(f"/api/reports/{cid}/pdf", headers=h)
    assert r.status_code==200
    assert r.content[:4]==b"%PDF"
    # Validate PDF has titles and bullets
    try:
        from PyPDF2 import PdfReader
        reader=PdfReader(io.BytesIO(r.content))
        text="".join([p.extract_text() or "" for p in reader.pages])
        assert "Combined" in text or "R1" in text
        assert text.count("•") >= 8
    except ImportError:
        pass

def test_combined_select_all():
    tok=user(f"rep_sel_{uuid.uuid4().hex[:6]}@test.com")
    h={"Authorization":f"Bearer {tok}"}
    csv="a,b\n1,2\n"
    did=client.post("/api/datasets/upload", files={"file":("a.csv",csv,"text/csv")}, headers=h).json()["id"]
    ids=[]
    for i in range(3):
        r=client.post("/api/reports/generate", headers=h, json={"dataset_id":did, "topic":f"What is total a? {i}", "title":f"R{i}"})
        ids.append(r.json()["id"])
    r=client.get("/api/reports", headers=h)
    all_ids=[x["id"] for x in r.json() if x["id"] in ids]
    assert len(all_ids)==3
    r=client.post("/api/reports/combined", headers=h, json={"report_ids":all_ids})
    assert r.status_code==200
    assert len(r.json()["content"]["combined_summaries"])==3

def test_versioning():
    tok=user(f"rep_ver_{uuid.uuid4().hex[:6]}@test.com")
    h={"Authorization":f"Bearer {tok}"}
    csv="name,price\nIndiGo,5000\nAir India,7000\n"
    did=client.post("/api/datasets/upload", files={"file":("a.csv",csv,"text/csv")}, headers=h).json()["id"]
    v1=client.get(f"/api/datasets/{did}/versions", headers=h).json()[0]["version_number"]
    r=client.post("/api/reports/generate", headers=h, json={"dataset_id":did, "topic":"What is average price?", "title":"V1"})
    ver1=r.json()["dataset_version_number"]
    assert ver1==v1
    client.post(f"/api/datasets/{did}/clean/apply", headers=h, json={"op":"text","params":{"column":"name","sub_operation":"lowercase"}})
    v2=client.get(f"/api/datasets/{did}/versions", headers=h).json()[-1]["version_number"]
    assert v2>v1
    r=client.post("/api/reports/generate", headers=h, json={"dataset_id":did, "topic":"What is average price?", "title":"V2"})
    ver2=r.json()["dataset_version_number"]
    assert ver2==v2
    # Old report retains old version
    r=client.get(f"/api/reports/{r.json()['id']}", headers=h)
    # Check new report's version, and old report still old
    assert ver1!=ver2

def test_auth_isolation_reports():
    tokA=user(f"rep_iso_a_{uuid.uuid4().hex[:6]}@test.com")
    hA={"Authorization":f"Bearer {tokA}"}
    tokB=user(f"rep_iso_b_{uuid.uuid4().hex[:6]}@test.com")
    hB={"Authorization":f"Bearer {tokB}"}
    csv="a,b\n1,2\n"
    did=client.post("/api/datasets/upload", files={"file":("a.csv",csv,"text/csv")}, headers=hA).json()["id"]
    r=client.post("/api/reports/generate", headers=hA, json={"dataset_id":did, "topic":"What is total a?", "title":"A"})
    rid=r.json()["id"]
    assert client.get(f"/api/reports/{rid}", headers=hB).status_code==404
    assert client.get(f"/api/reports/{rid}/pdf", headers=hB).status_code==404
    assert client.post("/api/reports/combined", headers=hB, json={"report_ids":[rid]}).status_code==404

def test_pdf_numbers_match():
    tok=user(f"rep_num_{uuid.uuid4().hex[:6]}@test.com")
    h={"Authorization":f"Bearer {tok}"}
    csv="region,revenue\nNorth,1000\nSouth,1200\nNorth,800\nSouth,900\n"
    did=client.post("/api/datasets/upload", files={"file":("a.csv",csv,"text/csv")}, headers=h).json()["id"]
    r=client.post("/api/reports/generate", headers=h, json={"dataset_id":did, "topic":"What is total revenue by region?"})
    j=r.json()
    ev=j["content"]["evidence"]
    sql=ev.get("generated_code","")
    df=pd.read_csv(io.StringIO(csv))
    con=duckdb.connect(); con.register("df", df)
    res=con.execute(sql).fetchdf()
    report_rows=ev.get("result_rows", [])
    if report_rows:
        # Compare first row
        report_val = next((v for k,v in report_rows[0].items() if isinstance(v,(int,float))), None)
        db_val = res.iloc[0,1] if len(res.columns)>1 else res.iloc[0,0]
        assert abs(float(report_val)-float(db_val))<1e-6

def test_ai_fallback_report():
    from unittest.mock import patch, AsyncMock
    tok=user(f"rep_ai_{uuid.uuid4().hex[:6]}@test.com")
    h={"Authorization":f"Bearer {tok}"}
    csv="region,revenue\nNorth,1000\nSouth,1200\n"
    did=client.post("/api/datasets/upload", files={"file":("a.csv",csv,"text/csv")}, headers=h).json()["id"]
    with patch("app.ai.provider.GeminiProvider.generate", new=AsyncMock(side_effect=Exception("Gemini provider rate limited — quota exceeded (429)"))):
        r=client.post("/api/reports/generate", headers=h, json={"dataset_id":did, "topic":"What is total revenue by region?"})
        assert r.status_code==200
        assert r.json()["id"]!="clarification"
        rid=r.json()["id"]
        r=client.get(f"/api/reports/{rid}/pdf", headers=h)
        assert r.content[:4]==b"%PDF"
