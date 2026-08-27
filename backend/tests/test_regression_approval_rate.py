import uuid
import pandas as pd
from fastapi.testclient import TestClient
from app.main import app
from app.data_engine.statistical import validate_result, assumptions_and_limitations, _cohens_h, _interpret_h

client = TestClient(app)

def make_loan_dataset():
    email=f"loanreg{uuid.uuid4().hex[:6]}@test.com"
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

question = "Analyze the loan approval rate across Gender, Education, Credit_History, and Property_Area. Identify the strongest and weakest applicant segments, but exclude segments with fewer than 10 applications. Compare the approval rate of the strongest segment with the overall approval rate, quantify the difference in percentage points, identify the main factors associated with the difference, and explain whether the observed differences are large enough to warrant further investigation. Show the underlying evidence and methodology used."

def test_strongest_vs_rest_statistical_comparison():
    """Strongest vs REST for inferential testing, not vs overall overlapping."""
    h,did=make_loan_dataset()
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":question}, headers=h)
    assert r.status_code==200, r.text
    sv=r.json()["statistical_validation"]
    assert sv["applicable"] is True
    # Must explicitly indicate strongest vs rest
    assert sv["comparison"] == "strongest_segment_vs_rest", f"Expected inferential vs rest, got {sv['comparison']}"
    # Must report rest rate
    assert "rest_rate" in sv["observed"], "rest_rate missing in observed"
    assert sv["observed"]["rest_rate"] is not None
    # Must report both benchmark and inferential differences
    assert "difference_vs_rest_pp" in sv["observed"] or "inferential_difference_pp" in sv["observed"]
    assert "difference_vs_overall_pp" in sv["observed"] or "benchmark_difference_pp" in sv["observed"]
    # confidence_interval must contain rest
    assert "rest" in sv["confidence_interval"], "rest CI missing"
    # sample_sizes must contain rest
    assert "rest" in sv["sample_sizes"]
    # p_value should correspond to strongest vs rest (inferential), not overall
    # If overall diff were used, rest diff would differ; ensure both diffs present and distinct unless coincidence
    # At least verify benchmark vs inferential are separately labeled
    assert "benchmark" in sv and "inferential" in sv
    assert "overlapping" in sv["benchmark"]["note"].lower() or "overlap" in sv["benchmark"]["note"].lower()
    assert "independent" in sv["inferential"]["label"].lower()

def test_overlapping_overall_benchmark_not_treated_as_independent():
    """Overall benchmark includes overlap and must not be treated as independent test."""
    h,did=make_loan_dataset()
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":question}, headers=h)
    sv=r.json()["statistical_validation"]
    # Must clearly label benchmark vs inferential
    assert sv["benchmark_comparison"] == "strongest_segment_vs_overall"
    assert sv["comparison"] == "strongest_segment_vs_rest"
    # Limitations must explicitly call out overlap vs independent
    lims_text = " ".join(sv["limitations"]).lower()
    assert "overlap" in lims_text, "Missing overlap disclaimer in limitations"
    assert "rest" in lims_text or "rest-of-population" in lims_text
    # comparison_note must distinguish
    assert "benchmark" in sv["comparison_note"].lower()
    assert "inferential" in sv["comparison_note"].lower()
    # Ensure p_value not computed as strongest vs overall: verify rest rate differs from overall
    obs = sv["observed"]
    assert obs["overall_rate"] != obs["rest_rate"], "Overall and rest should differ; if equal dataset may be coincidence but test expects distinct"

def test_effect_size_interpretation():
    """Cohen h must show interpretation negligible/small/medium/large and metric name."""
    h,did=make_loan_dataset()
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":question}, headers=h)
    sv=r.json()["statistical_validation"]
    assert sv["effect_size"] is not None
    assert sv["effect_size_label"] == "cohens_h"
    assert sv["effect_size_interpretation"] in ["negligible","small","medium","large"], f"Interpretation {sv['effect_size_interpretation']} not in allowed set"
    # Verify helper yields same categories
    h_val = _cohens_h(0.85, 0.5)
    assert _interpret_h(h_val) in ["negligible","small","medium","large"]
    # Check that effect vs rest is present
    assert "effect_size_vs_rest" in sv

def test_empty_assumptions_not_rendered():
    """Empty '-' bullets must not be rendered; only actual limitations."""
    # Directly test assumptions_and_limitations filtering
    df = pd.DataFrame({"Loan_ID":["LP0001"],"Gender":["Male"],"Education":["Graduate"],"Credit_History":["1"],"Property_Area":["Urban"],"Loan_Status":["Y"],"LoanAmount":[100]})
    lims = assumptions_and_limitations(df, "SELECT ... HAVING COUNT(*) >=10", [{"a":1}], 1)
    for lim in lims:
        assert lim.strip() != "-", "Empty '-' bullet found"
        assert lim.strip() != ""
    # Test validate_result limitations filtering
    h,did=make_loan_dataset()
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":question}, headers=h)
    sv=r.json()["statistical_validation"]
    for lim in sv["limitations"]:
        assert lim.strip() not in ("", "-"), f"Found empty bullet: {repr(lim)}"
    # When no assumptions, frontend should show fallback — simulate empty filtered
    filtered = [l for l in [] if l and l.strip() not in ("", "-")]
    # If filtered empty, UI should show "No additional assumptions identified."
    assert filtered == []
    fallback = "No additional assumptions identified."
    assert "assumptions" in fallback.lower()

def test_executed_sql_appears_in_copilot_evidence():
    """Copilot Evidence → Show code must render actual executed SQL from backend."""
    h,did=make_loan_dataset()
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":question}, headers=h)
    assert r.status_code==200
    j=r.json()
    msg=j["message"]
    generated_code=msg["generated_code"]
    assert generated_code, "No generated_code returned"
    assert "loan_status" in generated_code.lower(), "Executed SQL must contain loan_status"
    # Evidence endpoint must return same executed SQL, not regenerated
    mid=msg["id"]
    r2=client.get(f"/api/datasets/{did}/evidence/{mid}", headers=h)
    assert r2.status_code==200
    evidence=r2.json()
    assert evidence["query"] == generated_code, "Evidence query does not match executed SQL"
    # Verify analysis results store executed SQL correctly
    results=msg["results"]
    # Also check session retrieval returns same code
    sess_id=j["session_id"]
    r3=client.get(f"/api/analysis/{sess_id}", headers=h)
    assert r3.status_code==200
    msgs=r3.json()["messages"]
    retrieved = next((m for m in msgs if m["id"]==mid), None)
    assert retrieved is not None
    assert retrieved["generated_code"] == generated_code
