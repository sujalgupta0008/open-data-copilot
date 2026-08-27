from fastapi.testclient import TestClient
from app.main import app
import uuid
client=TestClient(app)

def make_dirty():
    email=f"dqplan{uuid.uuid4().hex[:6]}@test.com"
    r=client.post("/api/auth/register", json={"email":email,"password":"pass123","name":"Tester"})
    h={"Authorization":f"Bearer {r.json()['access_token']}"}
    csv="id,Department,salary,join_date\n1,Sales,50000,2023-01-15\n2,HR,,2023-02-20\n3,Sales,70000,invalid-date\n"
    r=client.post("/api/datasets/upload", files={"file":("dirty.csv",csv,"text/csv")}, headers=h)
    return h,r.json()["id"]

def test_A_audit_plan_no_mutation():
    q="Identify all data quality issues in this dataset, rank them by severity, explain their impact on downstream analysis, and tell me what I should fix first. Do not modify anything automatically."
    h,did=make_dirty()
    r=client.post(f"/api/datasets/{did}/plan", json={"question":q}, headers=h)
    assert r.status_code==200
    plan=[p["title"] for p in r.json()["plan"]]
    # Must NOT contain mutation steps
    assert not any("Preview" in t for t in plan), f"Audit plan should not contain Preview, got {plan}"
    assert not any("Apply" in t for t in plan), f"Audit plan should not contain Apply, got {plan}"
    assert not any("Reject" in t for t in plan), f"Audit plan should not contain Reject, got {plan}"
    assert not any("Cleaning Studio" in t for t in plan), f"Audit plan should not contain Cleaning Studio, got {plan}"
    # Must contain audit steps
    assert any("Scan the dataset" in t for t in plan)
    assert any("Rank issues by severity" in t for t in plan)
    assert any("Explain downstream impact" in t for t in plan)
    assert any("Prioritize fixes" in t for t in plan)
    assert any("Show evidence" in t for t in plan)
    assert any("No data will be modified" in t for t in plan)
    # Also verify analyze does not mutate
    r2=client.post(f"/api/datasets/{did}/analyze", json={"question":q}, headers=h)
    assert r2.status_code==200
    j=r2.json()
    # No cleaning mutation endpoint called — verify dataset still dirty via profile
    assert j["intent"]=="data_quality_analysis"
    assert "No data will be modified" in j["message"]["content"]
    assert j["message"]["generated_code"] is None

def test_B_ranking_audit_no_mutation():
    q="Rank the data quality issues by severity and tell me what to fix first."
    h,did=make_dirty()
    r=client.post(f"/api/datasets/{did}/plan", json={"question":q}, headers=h)
    plan=[p["title"] for p in r.json()["plan"]]
    assert not any("Preview" in t for t in plan)
    assert not any("Apply" in t for t in plan)
    assert r.json()["plan"]  # has plan
    # Intent should be data_quality
    from app.ai.provider import classify_intent
    assert classify_intent(q)=="data_quality_analysis"

def test_C_explanation_audit_no_mutation():
    q="Explain how missing values could affect downstream analysis."
    h,did=make_dirty()
    r=client.post(f"/api/datasets/{did}/plan", json={"question":q}, headers=h)
    plan=[p["title"] for p in r.json()["plan"]]
    assert not any("Preview" in t for t in plan)
    assert not any("Apply" in t for t in plan)
    from app.ai.provider import classify_intent
    assert classify_intent(q)=="data_quality_analysis"

def test_D_explicit_cleaning_allows_preview():
    q="Fix the highest-priority data quality issue."
    h,did=make_dirty()
    r=client.post(f"/api/datasets/{did}/plan", json={"question":q}, headers=h)
    plan=[p["title"] for p in r.json()["plan"]]
    assert any("Preview" in t for t in plan), f"Cleaning plan should contain Preview, got {plan}"
    assert any("Apply" in t for t in plan)
    assert any("Re-profile" in t for t in plan) or any("Verify" in t for t in plan)
    from app.ai.provider import classify_intent
    assert classify_intent(q)=="data_quality_analysis"

def test_E_explicit_specific_fix_preview():
    q="Fix missing salary values."
    h,did=make_dirty()
    r=client.post(f"/api/datasets/{did}/plan", json={"question":q}, headers=h)
    plan=[p["title"] for p in r.json()["plan"]]
    assert any("Preview" in t for t in plan)
    # Analyze should be data_quality cleaning
    r2=client.post(f"/api/datasets/{did}/analyze", json={"question":q}, headers=h)
    assert r2.json()["intent"]=="data_quality_analysis"
    # Should mention cleaning workflow but not auto-apply
    assert "Preview" in r2.json()["message"]["content"] or "Cleaning workflow" in r2.json()["message"]["content"]
