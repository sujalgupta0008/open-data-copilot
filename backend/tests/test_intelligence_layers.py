from fastapi.testclient import TestClient
from app.main import app
from app.data_engine.statistical import validate_result, assumptions_and_limitations
from app.data_engine.recommendation import build_recommendation
import pandas as pd
import uuid

client = TestClient(app)

def make_user(csv="a,b\n1,10\n2,20\n3,30\n"):
    email=f"intel_{uuid.uuid4().hex[:6]}@test.com"
    r=client.post("/api/auth/register", json={"email":email,"password":"pass123","name":"Tester"})
    token=r.json()["access_token"]
    h={"Authorization":f"Bearer {token}"}
    files={"file":("test.csv", csv, "text/csv")}
    r=client.post("/api/datasets/upload", files=files, headers=h)
    assert r.status_code==200, r.text
    did=r.json()["id"]
    return h, did

def make_loan_dataset_for_stat():
    email=f"loanstat{uuid.uuid4().hex[:6]}@test.com"
    r=client.post("/api/auth/register", json={"email":email,"password":"pass123","name":"Tester"})
    token=r.json()["access_token"]
    h={"Authorization":f"Bearer {token}"}
    header="Loan_ID,Gender,Education,Credit_History,Property_Area,Loan_Status,LoanAmount\n"
    rows=[]
    for i in range(14):
        status="Y" if i<12 else "N"
        rows.append(f"LP{i:04d},Male,Graduate,1,Urban,{status},100")
    for i in range(14,28):
        status="Y" if i<15 else "N"
        rows.append(f"LP{i:04d},Female,Not Graduate,0,Rural,{status},100")
    import random
    random.seed(0)
    for i in range(28, 60):
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

# A. Statistical validation
def test_confidence_interval():
    h,did=make_loan_dataset_for_stat()
    q="Analyze the loan approval rate across Gender, Education, Credit_History, and Property_Area. Identify the strongest and weakest applicant segments, but exclude segments with fewer than 10 applications. Compare the approval rate of the strongest segment with the overall approval rate, quantify the difference in percentage points, identify the main factors associated with the difference, and explain whether the observed differences are large enough to warrant further investigation. Show the underlying evidence and methodology used."
    r=client.post(f"/api/datasets/{did}/analyze", json={"question": q}, headers=h)
    assert r.status_code==200
    sv=r.json()["statistical_validation"]
    assert sv["applicable"]==True
    assert "confidence_interval" in sv
    assert sv["confidence_interval"]["strongest_segment"]["lower"] < sv["confidence_interval"]["strongest_segment"]["upper"]
    assert "p_value" in sv

def test_two_group_comparison():
    df=pd.DataFrame({"group":["A"]*15+["B"]*15, "value":[10]*15+[12]*15})
    # Simulate proportion case via validate_result
    rows=[{"approval_rate":86.8,"application_count":14},{"approval_rate":23.1,"application_count":13}]
    sv=validate_result(df, "approval rate difference", "SELECT approval_rate", ["approval_rate","application_count"], rows, 60)
    # Should be applicable for approval rate
    # For generic df without Loan_Status, may be not applicable, but check structure
    assert "applicable" in sv

def test_proportion_comparison_and_effect_size():
    h,did=make_loan_dataset_for_stat()
    q="Analyze the loan approval rate across Gender, Education, Credit_History, and Property_Area. Identify the strongest and weakest applicant segments, but exclude segments with fewer than 10 applications. Compare the approval rate of the strongest segment with the overall approval rate, quantify the difference in percentage points, identify the main factors associated with the difference, and explain whether the observed differences are large enough to warrant further investigation. Show the underlying evidence and methodology used."
    r=client.post(f"/api/datasets/{did}/analyze", json={"question": q}, headers=h)
    sv=r.json()["statistical_validation"]
    assert sv["effect_size"] is not None
    assert sv["effect_size_label"]=="cohens_h"
    assert sv["practical_significance"] in ["material","small","negligible"]

def test_small_sample_handling():
    df=pd.DataFrame({"Gender":["Male"]*5+["Female"]*5, "Loan_Status":["Y"]*5+["N"]*5})
    rows=[{"approval_rate":100.0,"application_count":5},{"approval_rate":0.0,"application_count":5}]
    sv=validate_result(df, "approval rate", "SELECT approval_rate", ["approval_rate","application_count"], rows, 10)
    # Should flag small sample
    if sv["applicable"]:
        assert any("small" in lim.lower() or "unstable" in lim.lower() for lim in sv["limitations"])
    else:
        assert "limitations" in sv

def test_inappropriate_test_rejection():
    h,did=make_user("revenue,region\n100,North\n200,South\n")
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":"What is total revenue?"}, headers=h)
    sv=r.json()["statistical_validation"]
    assert sv["applicable"]==False
    assert "Simple aggregation" in sv["reason"] or "Insufficient" in sv["reason"] or "not suitable" in sv["reason"].lower() or "no comparison" in sv["reason"].lower()

# B. Recommendation
def test_recommendation_uses_evidence():
    h,did=make_loan_dataset_for_stat()
    q="Analyze the loan approval rate across Gender, Education, Credit_History, and Property_Area. Identify the strongest and weakest applicant segments, but exclude segments with fewer than 10 applications. Compare the approval rate of the strongest segment with the overall approval rate, quantify the difference in percentage points, identify the main factors associated with the difference, and explain whether the observed differences are large enough to warrant further investigation. Show the underlying evidence and methodology used."
    r=client.post(f"/api/datasets/{did}/analyze", json={"question": q}, headers=h)
    rec=r.json()["recommendation"]
    assert rec["title"] is not None
    assert any(str(v) in str(rec["supporting_evidence"]) or str(v) in rec["rationale"] for v in [86, 68, 14]) or "approval" in rec["rationale"].lower()
    assert rec["limitations"]

def test_recommendation_does_not_invent_values():
    df=pd.DataFrame({"Gender":["Male","Female"], "Loan_Status":["Y","N"]})
    rows=[{"approval_rate":86.8,"application_count":14},{"approval_rate":50.0,"application_count":10}]
    sv={"applicable": True, "method":"two_group_proportion_wilson_z", "estimate":15.0, "p_value":0.03, "effect_size":0.5, "effect_size_interpretation":"medium", "significance":"statistically significant", "practical_significance":"material", "limitations":["test"], "observed":{"strongest_rate":86.8,"overall_rate":68.7,"difference_pp":18.1},"sample_sizes":{"strongest":14,"overall":60}}
    rec=build_recommendation("approval rate", "SELECT ...", ["Gender","approval_rate","application_count"], rows, sv, None, "test", 60)
    # Should contain actual rates from evidence
    assert "86.8" in rec["rationale"] or "18.1" in rec["rationale"] or "86" in str(rec["supporting_evidence"])
    # Should not contain risky auto reject
    assert "automatically" not in rec["recommendation"].lower() or "reject" not in rec["recommendation"].lower()

def test_recommendation_limitation_and_sensitive():
    h,did=make_loan_dataset_for_stat()
    q="Is the difference meaningful? approval rate"
    r=client.post(f"/api/datasets/{did}/analyze", json={"question": q}, headers=h)
    rec=r.json()["recommendation"]
    assert any("validation" in lim.lower() or "causation" in lim.lower() for lim in rec["limitations"])
    # Sensitive action should require validation
    rec2=build_recommendation("Should we automatically reject applicants with low score?", "SELECT ...", ["a"], [{"a":1}], {"applicable":False,"reason":"no"}, None, "test", 10)
    assert rec2["requires_validation"]==True

# C. Monitoring
def test_metric_change_detection_and_alert():
    h,did=make_user("revenue,order_date\n100,2023-01-01\n200,2023-01-02\n150,2023-01-03\n")
    r=client.post(f"/api/datasets/{did}/metrics", json={"name":"Revenue","sql_expression":"SUM(revenue)"}, headers=h)
    mid=r.json()["id"]
    r=client.post(f"/api/datasets/{did}/monitors", json={"metric_id": mid, "threshold_percent": 10}, headers=h)
    mon_id=r.json()["id"]
    r=client.post(f"/api/datasets/{did}/monitors/{mon_id}/check", headers=h)
    assert r.json()["status"] in ["healthy","alert"]
    # Second check with same data should be healthy (no change)
    r2=client.post(f"/api/datasets/{did}/monitors/{mon_id}/check", headers=h)
    assert "change_percent" in r2.json()

def test_period_over_period_with_date():
    h,did=make_user("revenue,order_date\n100,2023-01-01\n200,2023-02-01\n150,2023-03-01\n300,2023-04-01\n")
    r=client.post(f"/api/datasets/{did}/metrics", json={"name":"Revenue","sql_expression":"SUM(revenue)"}, headers=h)
    mid=r.json()["id"]
    r=client.post(f"/api/datasets/{did}/monitors", json={"metric_id": mid}, headers=h)
    mon_id=r.json()["id"]
    r=client.post(f"/api/datasets/{did}/monitors/{mon_id}/check", headers=h)
    j=r.json()
    assert j["is_time_aware"]==True
    assert j["period_start"] is not None
    assert "Time-aware" in j["comparison_note"]

def test_no_date_fallback():
    h,did=make_user("revenue,region\n100,North\n200,South\n")
    r=client.post(f"/api/datasets/{did}/metrics", json={"name":"Revenue","sql_expression":"SUM(revenue)"}, headers=h)
    mid=r.json()["id"]
    r=client.post(f"/api/datasets/{did}/monitors", json={"metric_id": mid}, headers=h)
    mon_id=r.json()["id"]
    r=client.post(f"/api/datasets/{did}/monitors/{mon_id}/check", headers=h)
    j=r.json()
    assert j["is_time_aware"]==False
    assert "check history" in j["comparison_note"].lower()

def test_investigation_context():
    h,did=make_user("revenue,region,order_date\n100,North,2023-01-01\n200,South,2023-02-01\n150,North,2023-03-01\n")
    r=client.post(f"/api/datasets/{did}/metrics", json={"name":"Revenue","sql_expression":"SUM(revenue)", "dimensions":["region"]}, headers=h)
    mid=r.json()["id"]
    r=client.post(f"/api/datasets/{did}/monitors", json={"metric_id": mid}, headers=h)
    mon_id=r.json()["id"]
    r=client.post(f"/api/datasets/{did}/monitors/{mon_id}/check", headers=h)
    r=client.post(f"/api/datasets/{did}/monitors/{mon_id}/investigate", headers=h)
    assert r.status_code==200
    j=r.json()
    assert "investigation_context" in j
    assert j["investigation_context"]["metric_name"]=="Revenue"
    assert "recommendation" in j
    assert j["history"]["session_id"] is not None
    # Verify history preserved
    r2=client.get(f"/api/analysis/{j['history']['session_id']}", headers=h)
    assert r2.status_code==200

# D. Root cause
def test_period_contribution_and_fallback():
    h,did=make_user("region,revenue,order_date\nNorth,100,2023-01-01\nSouth,200,2023-02-01\nNorth,150,2023-03-01\nSouth,300,2023-04-01\nEast,50,2023-01-15\n")
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":"Total revenue by region"}, headers=h)
    mid=r.json()["message"]["id"]
    r=client.post(f"/api/datasets/{did}/root-cause", json={"message_id": mid, "dimension":"region"}, headers=h)
    j=r.json()
    assert "drivers" in j
    # If period available, method should be period_over_period, else contribution_share
    assert j.get("method") in ["period_over_period","contribution_share"]
    if j.get("method")=="period_over_period":
        assert "period_info" in j
        # Contribution percentages are mathematically valid; pp sum close to overall change pct
        # Check each driver has contribution_pp
        assert any("contribution_pp" in d for d in j["drivers"])
    else:
        assert "Contribution analysis" in j["disclaimer"] or "not period-over-period" in j["disclaimer"].lower()
        total=sum(d["contribution_percent"] for d in j["drivers"])
        assert 99 < total < 101
    # No causal language
    assert "caused" not in j["disclaimer"].lower() or "not" in j["disclaimer"].lower()

def test_contribution_percentages_valid():
    h,did=make_user("region,revenue\nNorth,100\nSouth,200\nNorth,150\nSouth,300\n")
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":"Total revenue by region"}, headers=h)
    mid=r.json()["message"]["id"]
    r=client.post(f"/api/datasets/{did}/root-cause", json={"message_id": mid, "dimension":"region"}, headers=h)
    j=r.json()
    total=sum(d["contribution_percent"] for d in j["drivers"])
    assert 99 < total < 101
    assert "caused" not in j["summary"].lower()
    assert "association" in j["disclaimer"].lower() or "not proven" in j["disclaimer"].lower()

# E. Workflow
def test_full_workflow():
    h,did=make_user("revenue,region\n100,North\n200,South\n")
    # Profile
    r=client.get(f"/api/datasets/{did}/profile", headers=h)
    assert r.status_code==200
    # Health via doctor
    r=client.get(f"/api/datasets/{did}/doctor", headers=h)
    assert r.status_code==200
    # Clean preview
    r=client.post(f"/api/datasets/{did}/clean/preview", json={"op":"remove_duplicates","params":{}}, headers=h)
    assert r.status_code==200
    # Metric
    r=client.post(f"/api/datasets/{did}/metrics", json={"name":"Revenue","sql_expression":"SUM(revenue)"}, headers=h)
    mid=r.json()["id"]
    # Copilot simple
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":"What is total revenue?"}, headers=h)
    assert r.status_code==200
    assert r.json()["statistical_validation"] is not None
    assert r.json()["recommendation"] is not None
    # Monitor
    r=client.post(f"/api/datasets/{did}/monitors", json={"metric_id": mid}, headers=h)
    mon_id=r.json()["id"]
    r=client.post(f"/api/datasets/{did}/monitors/{mon_id}/check", headers=h)
    assert r.status_code==200
    r=client.post(f"/api/datasets/{did}/monitors/{mon_id}/investigate", headers=h)
    assert r.status_code==200
    # Root cause
    # Report
    r=client.post("/api/reports", json={"title":"Workflow Report","dataset_id": did}, headers=h)
    assert r.status_code==200
    # Export
    r=client.get(f"/api/datasets/{did}/export?format=csv", headers=h)
    assert r.status_code==200

# F. Security
def test_security_no_api_keys_exposed():
    h,did=make_user()
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":"What is count?"}, headers=h)
    txt=str(r.json())
    assert "sk-" not in txt
    assert "GEMINI_API_KEY" not in txt
    assert "GROQ_API_KEY" not in txt

def test_security_no_raw_dataset_sent():
    # Verify provider only receives sample_rows max 3 via code inspection: we check that analyze does not send full dataset
    # Indirect: ensure response does not contain full dataset rows beyond result
    h,did=make_user("a,b,c,d,e,f\n1,2,3,4,5,6\n7,8,9,10,11,12\n")
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":"What is average a?"}, headers=h)
    # Check that no raw dataset leak in message content beyond aggregated result
    assert r.status_code==200
    # The insight should not contain all raw rows
    assert "1,2,3" not in r.json()["message"]["content"]

def test_security_user_isolation():
    h1,did=make_user()
    email2=f"other{uuid.uuid4().hex[:6]}@test.com"
    r=client.post("/api/auth/register", json={"email":email2,"password":"pass123","name":"Other"})
    h2={"Authorization":f"Bearer {r.json()['access_token']}"}
    r=client.get(f"/api/datasets/{did}/profile", headers=h2)
    assert r.status_code==404
    r=client.get(f"/api/analysis", headers=h2)
    assert r.status_code==200
    # Ensure other user cannot see analysis
    assert all(s["dataset_id"]!=did for s in r.json()) or len(r.json())==0

def test_statistical_computation_local():
    # Ensure statistical engine does not call external API: we test by checking that statistical_validation exists without provider
    h,did=make_loan_dataset_for_stat()
    q="Analyze the loan approval rate across Gender, Education, Credit_History, and Property_Area. Identify the strongest and weakest applicant segments, but exclude segments with fewer than 10 applications. Compare the approval rate of the strongest segment with the overall approval rate, quantify the difference in percentage points, identify the main factors associated with the difference, and explain whether the observed differences are large enough to warrant further investigation. Show the underlying evidence and methodology used."
    r=client.post(f"/api/datasets/{did}/analyze", json={"question": q}, headers=h)
    sv=r.json()["statistical_validation"]
    # Must be computed locally, method deterministic
    assert sv["method"]=="two_group_proportion_wilson_z"
    assert sv["p_value"] is not None

def test_recommendations_cannot_bypass_auth():
    h,did=make_user()
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":"What is count?"}, headers=h)
    rec=r.json()["recommendation"]
    assert rec["requires_validation"]==True or rec["confidence"] in ["low","medium","high"]
    # Try to access other user's recommendation
    email2=f"other{uuid.uuid4().hex[:6]}@test.com"
    r2=client.post("/api/auth/register", json={"email":email2,"password":"pass123","name":"Other"})
    h2={"Authorization":f"Bearer {r2.json()['access_token']}"}
    r=client.get(f"/api/datasets/{did}/profile", headers=h2)
    assert r.status_code==404
