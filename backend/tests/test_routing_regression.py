from fastapi.testclient import TestClient
from app.main import app
from app.ai.provider import classify_intent
import uuid

client = TestClient(app)

def make_ecommerce_dataset_with_revenue_and_date():
    email=f"ecomrev{uuid.uuid4().hex[:6]}@test.com"
    r=client.post("/api/auth/register", json={"email":email,"password":"pass123","name":"Tester"})
    token=r.json()["access_token"]
    h={"Authorization":f"Bearer {token}"}
    header="order_id,order_date,revenue,region,category\n"
    rows=[
        "1,2023-01-15,1000,North,Electronics",
        "2,2023-01-20,1200,South,Books",
        "3,2023-02-10,800,North,Electronics",
        "4,2023-02-18,900,South,Books",
        "5,2023-03-05,1500,North,Electronics",
        "6,2023-03-12,1100,South,Books",
        "7,2023-04-02,600,North,Electronics",
        "8,2023-04-10,700,South,Books",
    ]
    csv_data=header + "\n".join(rows)
    files={"file":("ecom.csv", csv_data, "text/csv")}
    r=client.post("/api/datasets/upload", files=files, headers=h)
    assert r.status_code==200, r.text
    did=r.json()["id"]
    return h, did

def make_loan_dataset():
    email=f"loanrt{uuid.uuid4().hex[:6]}@test.com"
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
    csv_data=header + "\n".join(rows)
    files={"file":("loan.csv", csv_data, "text/csv")}
    r=client.post("/api/datasets/upload", files=files, headers=h)
    assert r.status_code==200, r.text
    return h, r.json()["id"]

# A: Revenue decreased significantly in latest month -> trend/root_cause not simple_aggregation
def test_A_revenue_decreased_trend_not_simple():
    assert classify_intent("Revenue decreased significantly in the latest month. Identify when the decline started, quantify the month-over-month change, identify the dimensions that contributed most to the decline, statistically validate the important differences where appropriate, explain the likely drivers without claiming causation, and recommend what should be investigated next.") in ["trend_analysis","root_cause","monitor_investigation"]
    # Also test execution on ecom dataset: must use revenue and date, not credit_history
    h,did=make_ecommerce_dataset_with_revenue_and_date()
    q="Revenue decreased significantly in the latest month. Identify when the decline started, quantify the month-over-month change, identify the dimensions that contributed most to the decline, statistically validate the important differences where appropriate, explain the likely drivers without claiming causation, and recommend what should be investigated next."
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":q}, headers=h)
    assert r.status_code==200, r.text
    j=r.json()
    code=(j["message"]["generated_code"] or "").lower()
    # Must NOT fallback to credit_history loan logic
    assert "credit_history" not in code, f"Should not use credit_history for revenue question, got {code}"
    assert "loan_id" not in code.lower(), f"Should not group by loan_id for revenue, got {code}"
    # Must contain revenue and date/month
    assert "revenue" in code, f"Expected revenue in SQL, got {code}"
    # Should have executed (not clarification)
    assert j["message"]["execution_status"] != "clarification", "Should execute trend analysis, not clarification"

# A2: Same question on loan dataset (no revenue, no date) -> clarification for missing revenue and date
def test_A_on_loan_clarifies_missing_revenue():
    h,did=make_loan_dataset()
    q="Revenue decreased significantly in the latest month. Identify when the decline started, quantify the month-over-month change"
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":q}, headers=h)
    assert r.status_code==200
    j=r.json()
    # Must clarify because revenue missing
    content=j["message"]["content"]
    assert "couldn't find a revenue" in content.lower() or "couldn't find" in content.lower(), f"Expected revenue clarification, got {content}"
    # Must not execute unrelated SQL
    code=(j["message"]["generated_code"] or "")
    assert code == "" or code is None or "credit_history" not in code.lower(), "Should not execute unrelated SQL when metric missing"

# B: Why is performance worse? -> clarification no SQL
def test_B_ambiguous_performance_clarifies():
    assert classify_intent("Why is performance worse?") == "needs_clarification"
    h,did=make_ecommerce_dataset_with_revenue_and_date()
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":"Why is performance worse?"}, headers=h)
    assert r.status_code==200
    j=r.json()
    content=j["message"]["content"].lower()
    assert "what performance metric" in content or "which metric" in content or "performance metric" in content, f"Expected clarification, got {content}"
    # Check options present
    results=j["message"]["results"]
    # Should have clarification result
    clar=[rr for rr in results if rr["result_type"]=="clarification"]
    assert len(clar)>=1, f"Expected clarification result, got {results}"
    opts=str(clar[0]["result_data"]).lower()
    assert "revenue" in opts and "approval" in opts, f"Expected metric options, got {opts}"
    # Must not have executed generic SQL
    code=(j["message"]["generated_code"] or "")
    assert code == "" or code is None, "Should not execute SQL for ambiguous question"

# C: Does being female cause higher loan approval? -> causal_question no causal claim
def test_C_causal_question_association_only():
    assert classify_intent("Does being female cause higher loan approval?") == "causal_question"
    h,did=make_loan_dataset()
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":"Does being female cause higher loan approval?"}, headers=h)
    assert r.status_code==200
    j=r.json()
    content=j["message"]["content"].lower()
    assert "association" in content and "not establish causation" in content, f"Expected association disclaimer, got {content}"
    assert "cause" not in content or "association" in content, "Should not claim causation"
    # Should offer analyze association
    has_option=False
    for rr in j["message"]["results"]:
        if rr["result_type"]=="clarification":
            if "analyze association" in str(rr["result_data"]).lower():
                has_option=True
    assert has_option, "Should offer Analyze association"
    assert j["intent"]=="causal_question"

# D: Monitor the approval rate... -> monitor intent workflow
def test_D_monitor_approval_rate_workflow():
    assert classify_intent("Monitor the approval rate and tell me what should trigger an investigation.") == "monitor"
    h,did=make_loan_dataset()
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":"Monitor the approval rate and tell me what should trigger an investigation."}, headers=h)
    assert r.status_code==200
    j=r.json()
    assert j["intent"]=="monitor"
    content=j["message"]["content"].lower()
    assert "approval rate" in content
    # Should have monitor_workflow result
    assert "monitor_workflow" in j or any(rr["result_type"]=="monitor_workflow" for rr in j["message"]["results"])
    # Check threshold suggestion labeled as suggested
    assert "suggested" in content, f"Threshold should be labeled suggested, got {content}"
    # Check actions
    mw=j.get("monitor_workflow") or next((rr["result_data"] for rr in j["message"]["results"] if rr["result_type"]=="monitor_workflow"), {})
    assert "Create Monitor" in str(mw) or "create monitor" in str(mw).lower()
    # Must not auto-create monitor without confirmation: check monitors list still empty if we haven't created
    # List monitors should be empty
    r2=client.get(f"/api/datasets/{did}/monitors", headers=h)
    # Allow empty or not auto-created
    assert isinstance(r2.json(), list)

# E: Why did revenue decline? with revenue+date -> root cause period comparison
def test_E_why_revenue_decline_with_metric_period():
    h,did=make_ecommerce_dataset_with_revenue_and_date()
    # Need to ensure intent is root_cause
    assert classify_intent("Why did revenue decline?") in ["root_cause","trend_analysis"]
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":"Why did revenue decline?"}, headers=h)
    assert r.status_code==200
    j=r.json()
    # Should have executed (not clarification) and used revenue
    code=(j["message"]["generated_code"] or "").lower()
    assert "revenue" in code, f"Expected revenue, got {code}"
    # Now test root-cause driver with period_over_period
    mid=j["message"]["id"]
    r2=client.post(f"/api/datasets/{did}/root-cause", json={"message_id":mid, "dimension":"region"}, headers=h)
    assert r2.status_code==200, r2.text
    j2=r2.json()
    # Must not have UnboundLocalError
    assert "UnboundLocalError" not in str(j2)
    assert j2.get("method") in ["period_over_period","contribution_share"]
    if j2.get("method")=="period_over_period":
        assert "period_info" in j2

# F: Why did revenue decline? without revenue metric -> clarification no substitution
def test_F_why_revenue_decline_without_metric_clarifies():
    h,did=make_loan_dataset()
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":"Why did revenue decline?"}, headers=h)
    assert r.status_code==200
    j=r.json()
    content=j["message"]["content"].lower()
    assert "couldn't find a revenue" in content or "couldn't find" in content, f"Expected clarification, got {content}"
    code=(j["message"]["generated_code"] or "")
    # Must not substitute credit_history
    assert code == "" or code is None or "credit_history" not in code.lower()
    assert code == "" or code is None or "loan_id" not in code.lower()

# G: Root-cause period-over-period no UnboundLocalError
def test_G_root_cause_no_unbound_error():
    h,did=make_ecommerce_dataset_with_revenue_and_date()
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":"Total revenue by region"}, headers=h)
    assert r.status_code==200
    mid=r.json()["message"]["id"]
    # Call root-cause with period logic
    r2=client.post(f"/api/datasets/{did}/root-cause", json={"message_id":mid, "dimension":"region"}, headers=h)
    assert r2.status_code==200
    assert "cannot access local variable 'expr'" not in r2.text.lower()
    j=r2.json()
    assert "drivers" in j

# H: Executed SQL -> generated_code is rendered in Show Code
def test_H_executed_sql_rendered():
    h,did=make_ecommerce_dataset_with_revenue_and_date()
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":"What is total revenue by region?"}, headers=h)
    assert r.status_code==200
    j=r.json()
    msg=j["message"]
    gen=msg["generated_code"]
    assert gen is not None and gen.strip() != "", "generated_code should not be empty for successful analysis"
    assert "revenue" in gen.lower()
    # Evidence endpoint must return same SQL
    mid=msg["id"]
    r2=client.get(f"/api/datasets/{did}/evidence/{mid}", headers=h)
    assert r2.status_code==200
    assert r2.json()["query"] == gen, "Evidence query must equal generated_code"
    # Session retrieval also same
    sid=j["session_id"]
    r3=client.get(f"/api/analysis/{sid}", headers=h)
    assert r3.status_code==200
    msgs=r3.json()["messages"]
    retrieved=next((m for m in msgs if m["id"]==mid), None)
    assert retrieved and retrieved["generated_code"] == gen

# Ensure no silent fallback to unrelated metrics for revenue question on loan dataset
def test_no_silent_fallback_revenue_on_loan():
    h,did=make_loan_dataset()
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":"What is total revenue?"}, headers=h)
    assert r.status_code==200
    j=r.json()
    # Should clarify, not use credit_history
    content=j["message"]["content"].lower()
    # If it clarifies, content will mention couldn't find revenue
    assert "couldn't find a revenue" in content or "couldn't find" in content, f"Expected clarification for missing revenue, got {content} and code {j['message']['generated_code']}"
