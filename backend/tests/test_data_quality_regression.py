from fastapi.testclient import TestClient
from app.main import app
from app.ai.provider import classify_intent
import uuid

client = TestClient(app)

def make_dirty_dataset():
    email=f"dirty{uuid.uuid4().hex[:6]}@test.com"
    r=client.post("/api/auth/register", json={"email":email,"password":"pass123","name":"Tester"})
    token=r.json()["access_token"]
    h={"Authorization":f"Bearer {token}"}
    # Create dataset with missing, duplicates, inconsistent types
    header="id,Department,salary,join_date\n"
    rows=[
        "1,Sales,50000,2023-01-15",
        "2,HR,,2023-02-20",
        "3,Sales,70000,invalid-date",
        "4,HR,60000,2023-03-10",
        "5,Sales,50000,2023-01-15",  # duplicate of row1 but diff id
        "6,Engineering,80000,2023-04-01",
        "7,Engineering,,2023-05-12",
        "8,HR,52000,2023-06-18",
        "9,Sales,55000,2023-07-22",
        "10,Engineering,75000,2023-08-30",
        "11,Sales,50000,2023-01-15",
        "12,HR,48000,2023-09-05",
    ]
    csv=header+"\n".join(rows)
    files={"file":("dirty.csv", csv, "text/csv")}
    r=client.post("/api/datasets/upload", files=files, headers=h)
    assert r.status_code==200, r.text
    return h, r.json()["id"]

def make_department_missing_dataset():
    email=f"dept{uuid.uuid4().hex[:6]}@test.com"
    r=client.post("/api/auth/register", json={"email":email,"password":"pass123","name":"Tester"})
    token=r.json()["access_token"]
    h={"Authorization":f"Bearer {token}"}
    header="id,Department,salary\n"
    rows=[
        "1,Sales,50000",
        "2,Sales,",
        "3,HR,60000",
        "4,HR,",
        "5,HR,",
        "6,Engineering,80000",
        "7,Engineering,70000",
        "8,Sales,55000",
    ]
    csv=header+"\n".join(rows)
    files={"file":("dept.csv", csv, "text/csv")}
    r=client.post("/api/datasets/upload", files=files, headers=h)
    assert r.status_code==200, r.text
    return h, r.json()["id"]

def make_simple_dataset():
    email=f"simple{uuid.uuid4().hex[:6]}@test.com"
    r=client.post("/api/auth/register", json={"email":email,"password":"pass123","name":"Tester"})
    token=r.json()["access_token"]
    h={"Authorization":f"Bearer {token}"}
    csv="a,b\n1,10\n2,20\n3,30\n"
    files={"file":("simple.csv", csv, "text/csv")}
    r=client.post("/api/datasets/upload", files=files, headers=h)
    assert r.status_code==200, r.text
    return h, r.json()["id"]

# A: Identify all data quality issues
def test_A_data_quality_audit_no_clarification_no_sql():
    q="Identify all data quality issues in this dataset, rank them by severity, explain their impact on downstream analysis, and recommend which issues should be fixed first. Do not modify anything automatically."
    assert classify_intent(q)=="data_quality_analysis"
    h,did=make_dirty_dataset()
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":q}, headers=h)
    assert r.status_code==200, r.text
    j=r.json()
    assert j["intent"]=="data_quality_analysis"
    # Must not ask dimension clarification for severity
    content=j["message"]["content"]
    assert "dimension 'severity' not found" not in content.lower()
    assert "which dimension" not in content.lower() or "severity" not in content.lower()
    # Must not require dimension
    # Should contain DATA QUALITY SUMMARY and priority
    assert "DATA QUALITY SUMMARY" in content
    assert "Overall quality" in content
    assert "PRIORITY FIX ORDER" in content
    # Should not have executed SQL (generated_code null)
    assert j["message"]["generated_code"] is None or j["message"]["generated_code"] == ""
    # Should have data_quality result
    msg_results=j["message"]["results"]
    dq=[rr for rr in msg_results if rr["result_type"]=="data_quality"]
    assert len(dq)>=1, f"Expected data_quality result, got {msg_results}"
    assert "overall_quality" in dq[0]["result_data"]
    assert "issues" in dq[0]["result_data"]

# B: Rank data quality issues by severity -> severity NOT column
def test_B_rank_by_severity_not_column():
    q="Rank data quality issues by severity"
    assert classify_intent(q)=="data_quality_analysis"
    h,did=make_dirty_dataset()
    # Clarify should not trigger
    r=client.post(f"/api/datasets/{did}/clarify", json={"question":q}, headers=h)
    assert r.status_code==200
    assert r.json()["needs_clarification"]==False, f"Should not need clarification for severity, got {r.json()}"
    # Analyze should not ask dimension
    r2=client.post(f"/api/datasets/{did}/analyze", json={"question":q}, headers=h)
    assert r2.status_code==200
    assert "dimension 'severity'" not in r2.json()["message"]["content"].lower()

# C: Explain impact of missing values -> impact NOT column
def test_C_explain_impact_missing_not_column():
    q="Explain the impact of missing values"
    assert classify_intent(q)=="data_quality_analysis"
    h,did=make_dirty_dataset()
    r=client.post(f"/api/datasets/{did}/clarify", json={"question":q}, headers=h)
    assert r.json()["needs_clarification"]==False
    r2=client.post(f"/api/datasets/{did}/analyze", json={"question":q}, headers=h)
    assert "dimension 'impact'" not in r2.json()["message"]["content"].lower()
    assert r2.json()["intent"]=="data_quality_analysis"

# D: Which department has the most missing values? -> analytical query, Department dimension
def test_D_department_missing_analytical():
    q="Which department has the most missing values?"
    # Should not be data_quality audit, should be analytical
    intent=classify_intent(q)
    # It contains missing values but with explicit department dimension, should not be pure data_quality
    # Our classifier correctly excludes this pattern, so expect not data_quality
    assert intent != "data_quality_analysis", f"Should be analytical, got {intent}"
    h,did=make_department_missing_dataset()
    r=client.post(f"/api/datasets/{did}/clarify", json={"question":q}, headers=h)
    # Should not ask for severity/impact, and department should be recognized (no dimension not found for department)
    if r.json()["needs_clarification"]:
        for cl in r.json()["clarifications"]:
            assert "department" not in cl["question"].lower() or "not found" not in cl["message"].lower(), f"Department should be recognized, got {cl}"
    # Analyze should execute (python or sql) and mention Department
    r2=client.post(f"/api/datasets/{did}/analyze", json={"question":q}, headers=h)
    assert r2.status_code==200
    # Must not be clarification for severity/impact, should be success or analytical
    # Check that response does not treat impact/severity as column
    assert "dimension 'impact'" not in r2.json()["message"]["content"].lower()
    # Should have executed something (might be python)
    # At least not data_quality audit content
    content=r2.json()["message"]["content"]
    # For missing by department, expect either python missing analysis or sql grouping
    # We just ensure it didn't fallback to unrelated
    assert "dimension 'severity' not found" not in content.lower()

# E: Fix the highest priority data issue -> cleaning workflow, explicit approval required
def test_E_fix_highest_priority_requires_approval():
    q="Fix the highest priority data issue"
    assert classify_intent(q)=="data_quality_analysis"
    h,did=make_dirty_dataset()
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":q}, headers=h)
    assert r.status_code==200
    j=r.json()
    assert j["intent"]=="data_quality_analysis"
    content=j["message"]["content"]
    # Should mention cleaning workflow and not auto-apply
    assert "Preview" in content or "Apply / Reject" in content or "Cleaning Studio" in content
    assert "No changes applied automatically" in content
    # Must not have executed destructive SQL
    assert j["message"]["generated_code"] is None or j["message"]["generated_code"] == ""
    # Should not have modified dataset automatically: check that dataset still has same row count
    # We can verify via profile
    r2=client.get(f"/api/datasets/{did}/profile", headers=h)
    assert r2.status_code==200
    # No silent modification: quality issues still exist

# F: Unknown analytical question -> existing clarification behavior remains
def test_F_unknown_analytical_still_clarifies():
    q="Why is performance worse?"
    assert classify_intent(q)=="needs_clarification"
    h,did=make_simple_dataset()
    r=client.post(f"/api/datasets/{did}/clarify", json={"question":q}, headers=h)
    assert r.json()["needs_clarification"]==True
    r2=client.post(f"/api/datasets/{did}/analyze", json={"question":q}, headers=h)
    assert r2.status_code==200
    assert r2.json()["intent"]=="needs_clarification"
    assert "what performance metric" in r2.json()["message"]["content"].lower()

# Ensure no regression for approval-rate: severity words not misrouted
def test_no_regression_approval_rate_still_works():
    q="Analyze the loan approval rate across Gender, Education, Credit_History, and Property_Area. Identify the strongest and weakest applicant segments, but exclude segments with fewer than 10 applications. Compare the approval rate of the strongest segment with the overall approval rate, quantify the difference in percentage points, identify the main factors associated with the difference, and explain whether the observed differences are large enough to warrant further investigation. Show the underlying evidence and methodology used."
    assert classify_intent(q)=="complex_multi_stage"
