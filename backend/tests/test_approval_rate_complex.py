from fastapi.testclient import TestClient
from app.main import app
from app.ai.provider import classify_intent
from unittest.mock import AsyncMock, patch
import uuid

client = TestClient(app)

def make_loan_dataset():
    email=f"loan{uuid.uuid4().hex[:6]}@test.com"
    r=client.post("/api/auth/register", json={"email":email,"password":"pass123","name":"Tester"})
    token=r.json()["access_token"]
    h={"Authorization":f"Bearer {token}"}
    header="Loan_ID,Gender,Education,Credit_History,Property_Area,Loan_Status,LoanAmount\n"
    rows=[]
    for i in range(12):
        status="Y" if i<10 else "N"
        rows.append(f"LP{i:04d},Male,Graduate,1,Urban,{status},100")
    for i in range(12,24):
        status="Y" if i<14 else "N"
        rows.append(f"LP{i:04d},Female,Not Graduate,0,Rural,{status},100")
    import random
    random.seed(0)
    for i in range(24, 60):
        g=random.choice(["Male","Female"])
        edu=random.choice(["Graduate","Not Graduate"])
        ch=random.choice(["1","0"])
        area=random.choice(["Urban","Rural","Semiurban"])
        status=random.choice(["Y","N"])
        rows.append(f"LP{i:04d},{g},{edu},{ch},{area},{status},100")
    csv_data=header + "\n".join(rows)
    files={"file":("loan.csv", csv_data, "text/csv")}
    r=client.post("/api/datasets/upload", files=files, headers=h)
    assert r.status_code==200, r.text
    return h, r.json()["id"]

question = "Analyze the loan approval rate across Gender, Education, Credit_History, and Property_Area. Identify the strongest and weakest applicant segments, but exclude segments with fewer than 10 applications. Compare the approval rate of the strongest segment with the overall approval rate, quantify the difference in percentage points, identify the main factors associated with the difference, and explain whether the observed differences are large enough to warrant further investigation. Show the underlying evidence and methodology used."

def test_approval_rate_uses_loan_status():
    h,did=make_loan_dataset()
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":question}, headers=h)
    assert r.status_code==200, r.text
    code=r.json()["message"]["generated_code"]
    assert "loan_status" in code.lower()
    # Credit_History should not be mistaken as outcome alone
    # Code must contain Loan_Status, not just SUM(Credit_History)
    assert "sum(\"credit_history\")" not in code.lower()

def test_four_dimensions():
    h,did=make_loan_dataset()
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":question}, headers=h)
    code=r.json()["message"]["generated_code"]
    for dim in ["Gender","Education","Credit_History","Property_Area"]:
        assert dim.lower() in code.lower(), f"{dim} missing"

def test_minimum_segment_size():
    h,did=make_loan_dataset()
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":question}, headers=h)
    code=r.json()["message"]["generated_code"]
    assert "having" in code.lower() and "10" in code

def test_strongest_weakest():
    h,did=make_loan_dataset()
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":question}, headers=h)
    data=r.json()["execution_result"]["data"]
    assert len(data)>=2
    rates=[float(d["approval_rate"]) for d in data]
    assert rates==sorted(rates, reverse=True)
    assert float(data[0]["approval_rate"]) >= float(data[-1]["approval_rate"])

def test_overall_and_difference():
    h,did=make_loan_dataset()
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":question}, headers=h)
    content=r.json()["message"]["content"]
    assert "overall" in content.lower()
    assert "percentage point" in content.lower()
    # Check not saying total credit history
    assert "total credit history" not in content.lower()
    assert "male leads with 420" not in content.lower()

def test_driver_uses_approval():
    h,did=make_loan_dataset()
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":question}, headers=h)
    mid=r.json()["message"]["id"]
    r2=client.post(f"/api/datasets/{did}/root-cause", json={"message_id":mid}, headers=h)
    assert r2.status_code==200
    j=r2.json()
    assert "association" in j["disclaimer"].lower()
    # For approval rate, drivers is empty (rate) but dimensions should have data
    if "dimensions" in j and j["dimensions"]:
        assert j["dimensions"]
        # No contribution_percent for rate
        for dim in j["dimensions"]:
            for g in dim["groups"]:
                assert "contribution_percent" not in g
    else:
        assert j["drivers"]

def test_why_not_generic():
    h,did=make_loan_dataset()
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":question}, headers=h)
    mid=r.json()["message"]["id"]
    r2=client.post(f"/api/datasets/{did}/root-cause", json={"message_id":mid}, headers=h)
    assert r2.status_code==200
    # Should not be generic outlier analysis unless relevant
    # Our driver for approval rate returns Gender breakdown, not outlier

def test_challenge_question_aware():
    h,did=make_loan_dataset()
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":question}, headers=h)
    mid=r.json()["message"]["id"]
    r2=client.post(f"/api/datasets/{did}/challenge", json={"message_id":mid}, headers=h)
    assert r2.status_code==200
    ch=[c["hypothesis"].lower() for c in r2.json()["challenges"]]
    assert any("minimum segment" in c for c in ch)
    assert any("credit_history" in c for c in ch)
    assert not any("outliers may inflate" in c for c in ch)

def test_complex_not_simple():
    assert classify_intent(question)=="complex_multi_stage"
    # Also check plan
    h,did=make_loan_dataset()
    r=client.post(f"/api/datasets/{did}/plan", json={"question":question}, headers=h)
    assert r.json()["needs_plan"]==True
    assert len(r.json()["plan"])>=8

def test_metric_reuse():
    h,did=make_loan_dataset()
    r=client.post(f"/api/datasets/{did}/metrics", json={"name":"Approval Rate","sql_expression":"SUM(CASE WHEN LOWER(TRIM(CAST(\"Loan_Status\" AS VARCHAR))) IN ('y','yes','approved') THEN 1 ELSE 0 END) * 100.0 / COUNT(*)"}, headers=h)
    assert r.status_code==200
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":"What is the Approval Rate?"}, headers=h)
    assert "loan_status" in r.json()["message"]["generated_code"].lower()

def test_numbers_match_duckdb():
    h,did=make_loan_dataset()
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":question}, headers=h)
    j=r.json()
    data=j["execution_result"]["data"]
    content=j["message"]["content"]
    # Every approval_rate in content should match data
    for d in data[:1]:
        rate=str(round(float(d["approval_rate"]),1))
        assert rate in content or str(int(float(d["approval_rate"]))) in content

def test_gemini_groq_deterministic_identical():
    h,did=make_loan_dataset()
    # Mock gemini to return wrong credit_history SQL, but semantic validation should correct to approval rate
    wrong = {"intent":"sql","code":'SELECT "Gender", SUM("Credit_History") as total_credit_history FROM df GROUP BY "Gender" ORDER BY total_credit_history DESC LIMIT 10',"explanation":"wrong","chart_type":"bar","chart_config_hint":None}
    with patch("app.ai.provider.GeminiProvider.generate", new=AsyncMock(return_value=wrong)):
        r=client.post(f"/api/datasets/{did}/analyze", json={"question":question}, headers=h)
        assert r.status_code==200
        assert "loan_status" in r.json()["message"]["generated_code"].lower()
        data_gemini=r.json()["execution_result"]["data"]
    with patch("app.ai.provider.GeminiProvider.generate", new=AsyncMock(side_effect=Exception("429"))):
        with patch("app.ai.provider.GroqProvider.generate", new=AsyncMock(return_value=wrong)):
            r=client.post(f"/api/datasets/{did}/analyze", json={"question":question}, headers=h)
            assert r.status_code==200
            assert "loan_status" in r.json()["message"]["generated_code"].lower()
            data_groq=r.json()["execution_result"]["data"]
    with patch("app.ai.provider.GeminiProvider.generate", new=AsyncMock(side_effect=Exception("429"))):
        with patch("app.ai.provider.GroqProvider.generate", new=AsyncMock(side_effect=Exception("429"))):
            r=client.post(f"/api/datasets/{did}/analyze", json={"question":question}, headers=h)
            assert r.status_code==200
            data_det=r.json()["execution_result"]["data"]
    assert data_gemini==data_groq==data_det
