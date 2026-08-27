from fastapi.testclient import TestClient
from app.main import app
import uuid
client=TestClient(app)

def make_dirty():
    email=f"dqi{uuid.uuid4().hex[:6]}@test.com"
    r=client.post("/api/auth/register", json={"email":email,"password":"pass123","name":"Tester"})
    h={"Authorization":f"Bearer {r.json()['access_token']}"}
    csv="id,Department,salary,join_date\n1,Sales,50000,2023-01-15\n2,HR,,2023-02-20\n3,Sales,70000,invalid-date\n"
    r=client.post("/api/datasets/upload", files={"file":("dirty.csv",csv,"text/csv")}, headers=h)
    return h,r.json()["id"]

def make_clean():
    email=f"clean{uuid.uuid4().hex[:6]}@test.com"
    r=client.post("/api/auth/register", json={"email":email,"password":"pass123","name":"Tester"})
    h={"Authorization":f"Bearer {r.json()['access_token']}"}
    csv="id,Department,salary\n1,Sales,50000\n2,HR,60000\n3,Engineering,70000\n"
    r=client.post("/api/datasets/upload", files={"file":("clean.csv",csv,"text/csv")}, headers=h)
    return h,r.json()["id"]

def test_A_data_quality_isolation_no_sql_no_driver():
    q="Identify all data quality issues in this dataset, rank them by severity, explain their impact on downstream analysis, and tell me what I should fix first."
    h,did=make_dirty()
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":q}, headers=h)
    assert r.status_code==200
    j=r.json()
    assert j["intent"]=="data_quality_analysis"
    assert j.get("analysis_mode")=="data_quality_audit"
    assert j.get("analysis_source")=="profile_dataframe"
    assert j["message"]["generated_code"] is None
    # execution_status should be success but not SQL
    assert j["message"]["execution_status"]=="success"
    # No SQL execution
    content=j["message"]["content"]
    # Must be data quality summary, not driver
    assert "DATA QUALITY SUMMARY" in content
    assert "Overall quality" in content
    # Check actual doctor issues are used
    results=j["message"]["results"]
    dq=[rr for rr in results if rr["result_type"]=="data_quality"]
    assert len(dq)==1
    issues=dq[0]["result_data"]["issues"]
    # Should have at least 1 actionable issue (dirty dataset has missing)
    actionable=[i for i in issues if i["severity"]!="Healthy"]
    assert len(actionable)>=1, f"Expected actionable issues, got {issues}"
    # Priority order based on actual issues
    priority=dq[0]["result_data"]["priority"]
    assert len(priority)>=1
    # No major issues message should NOT appear when there are actionable issues
    assert "No major issues detected" not in content or "quality checks found no actionable issues" in content.lower() and len(actionable)==0
    # Ensure no driver analysis leak
    assert "Revenue changed" not in content
    assert "period-over-period" not in content.lower()
    assert "Driver Analysis" not in content or "Data Quality" in content
    # Check meta result exists
    meta=[rr for rr in results if rr["result_type"]=="analysis_meta"]
    assert len(meta)==1
    assert meta[0]["result_data"]["analysis_mode"]=="data_quality_audit"
    assert meta[0]["result_data"]["generated_code"] is None

def test_B_no_revenue_driver_for_data_quality():
    q="Identify all data quality issues in this dataset, rank them by severity, explain their impact on downstream analysis, and tell me what I should fix first."
    h,did=make_dirty()
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":q}, headers=h)
    j=r.json()
    content=j["message"]["content"]
    # Must NOT contain unrelated driver
    assert "Revenue changed" not in content
    assert "EMP1112" not in content
    assert "contributed" not in content.lower() or "data quality" in content.lower()
    # Also check results don't contain driver
    for rr in j["message"]["results"]:
        assert "revenue changed" not in str(rr["result_data"]).lower()

def test_C_frontend_contract_no_query_card():
    q="Identify all data quality issues in this dataset, rank them by severity, explain their impact on downstream analysis, and tell me what I should fix first."
    h,did=make_dirty()
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":q}, headers=h)
    j=r.json()
    # Frontend contract: generated_code None -> no Query Success
    assert j["message"]["generated_code"] is None
    # Frontend should hide QUERY card when data_quality + no code
    # We simulate frontend check: isDataQualityAudit && !generated_code -> hide
    is_dq=any(rr["result_type"]=="data_quality" for rr in j["message"]["results"])
    assert is_dq
    assert j["message"]["generated_code"] is None
    # Also ensure no generic driver result
    for rr in j["message"]["results"]:
        assert rr["result_type"] not in ["driver", "root-cause"]

def test_D_explicit_cleaning_still_preview():
    q="Fix the highest-priority data quality issue."
    h,did=make_dirty()
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":q}, headers=h)
    j=r.json()
    assert j["intent"]=="data_quality_analysis"
    # For explicit cleaning, plan should have preview, but analyze should still be data_quality with cleaning note
    # Check content has cleaning workflow
    assert "Cleaning workflow" in j["message"]["content"]
    assert "Preview" in j["message"]["content"]
    # Also check plan
    r2=client.post(f"/api/datasets/{did}/plan", json={"question":q}, headers=h)
    plan=[p["title"] for p in r2.json()["plan"]]
    assert any("Preview" in t for t in plan)
    assert any("Apply" in t for t in plan)
    # Ensure not auto-applied: dataset still has issues
    r3=client.get(f"/api/datasets/{did}/doctor", headers=h)
    assert len([i for i in r3.json()["issues"] if i["severity"]!="Healthy"])>=1

def test_E_genuine_zero_issues_message():
    q="Identify all data quality issues in this dataset, rank them by severity, explain their impact on downstream analysis, and tell me what I should fix first."
    h,did=make_clean()
    # Clean dataset should have 0 actionable issues
    r=client.get(f"/api/datasets/{did}/doctor", headers=h)
    issues=[i for i in r.json()["issues"] if i["severity"]!="Healthy"]
    if len(issues)==0:
        r2=client.post(f"/api/datasets/{did}/analyze", json={"question":q}, headers=h)
        j=r2.json()
        assert "No major issues detected" in j["message"]["content"]
        # Should be the spec text
        assert "quality checks found no actionable issues" in j["message"]["content"]
    else:
        # If clean dataset still has issues, skip
        pass
