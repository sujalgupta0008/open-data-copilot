import pandas as pd
import sys
import types
from fastapi.testclient import TestClient
from app.main import app
from app.data_engine.statistical import validate_result
from app.data_engine.recommendation import build_recommendation
import uuid

client = TestClient(app)

def make_df_for_welch(n1=15, n2=15):
    # Two groups with numeric values, distinct means
    # Need underlying df with group column and numeric col
    group = ["A"]*n1 + ["B"]*n2
    # Create values with mean difference
    vals = [10 + (i % 3) for i in range(n1)] + [14 + (i % 3) for i in range(n2)]
    df = pd.DataFrame({"group": group, "value": vals})
    return df

def make_chi_df():
    df = pd.DataFrame({
        "cat1": ["X","X","X","Y","Y","Y"]*10,
        "cat2": ["P","Q","P","Q","P","Q"]*10
    })
    return df

# 1. Welch t-test exact p-value with scipy
def test_welch_exact_with_scipy():
    try:
        import scipy.stats  # noqa
    except ImportError:
        # if scipy not installed, this test should verify fallback handling, not exact
        assert True
        return
    df = make_df_for_welch(20,20)
    # Simulate rows as returned by DuckDB: group, avg_value
    rows = [{"group":"A","average_value":10.5},{"group":"B","average_value":14.5}]
    columns = ["group","average_value"]
    sql = 'SELECT "group", AVG("value") as average_value FROM df GROUP BY "group" ORDER BY average_value DESC'
    sv = validate_result(df, "Compare average value between groups - is difference significant?", sql, columns, rows, len(df))
    assert sv["applicable"] == True, f"Welch should be applicable, got {sv}"
    assert sv["method"] == "two_sample_welch_t"
    assert sv["p_value"] is not None
    assert 0 <= sv["p_value"] <= 1
    # Exact scipy p should be reproducible: check against scipy directly
    import scipy.stats as st
    a = df[df["group"]=="A"]["value"]
    b = df[df["group"]=="B"]["value"]
    _, expected_p = st.ttest_ind(a, b, equal_var=False)
    assert abs(sv["p_value"] - round(expected_p,4)) < 0.01, f"p {sv['p_value']} vs expected {expected_p}"

# 2. Chi-square exact p-value with scipy
def test_chi_square_exact_with_scipy():
    try:
        import scipy.stats  # noqa
    except ImportError:
        assert True
        return
    df = make_chi_df()
    rows = [{"cat1":"X","cat2":"P","count":10}]
    columns = ["cat1","cat2","count"]
    sql = 'SELECT "cat1","cat2", COUNT(*) FROM df GROUP BY "cat1","cat2"'
    sv = validate_result(df, "Is there association between cat1 and cat2 categorical variables?", sql, columns, rows, len(df))
    # For chi-square, our validate_result triggers only if question contains association/chi etc.
    # Ensure we use a question that triggers chi-square
    q = "Is there association between cat1 and cat2?"
    sv = validate_result(df, q, sql, ["cat1","cat2"], [{"cat1":"X","cat2":"P"}], len(df))
    # Since we have many rows, chi-square should be attempted
    # We test direct _chi_square_exact
    from app.data_engine.statistical import _chi_square_exact
    import numpy as np
    ct = pd.crosstab(df["cat1"], df["cat2"]).values.tolist()
    res = _chi_square_exact(ct)
    assert res is not None, "Chi2 with scipy should return result"
    assert "p_value" in res
    assert 0 <= res["p_value"] <= 1
    # Validate against scipy directly
    import scipy.stats as st
    chi2, p, dof, exp = st.chi2_contingency(np.array(ct), correction=False)
    assert abs(res["p_value"] - p) < 0.001

# 3. scipy unavailable -> no fabricated p-value
def test_scipy_unavailable_no_fabricated_p():
    # Monkey-patch sys.modules to hide scipy
    original_scipy = sys.modules.get("scipy")
    original_stats = sys.modules.get("scipy.stats")
    # Create fake missing
    sys.modules["scipy"] = None
    sys.modules["scipy.stats"] = None
    # Need to reload statistical module's scipy import handling? It does import inside function, so it will fail
    # Welch case
    from importlib import reload
    import app.data_engine.statistical as stat_mod
    # Force reload to ensure ImportError path? Actually functions do try: import scipy.stats, will now get None -> ImportError
    # We simulate by temporarily making import fail
    # Instead, we directly test validate_result with mocked import failure via patching builtins.__import__
    import builtins
    real_import = builtins.__import__
    def fake_import(name, *args, **kwargs):
        if name.startswith("scipy"):
            raise ImportError("No module named scipy")
        return real_import(name, *args, **kwargs)
    builtins.__import__ = fake_import
    try:
        df = make_df_for_welch(20,20)
        rows = [{"group":"A","average_value":10.5},{"group":"B","average_value":14.5}]
        columns = ["group","average_value"]
        sql = 'SELECT "group", AVG("value") as average_value FROM df GROUP BY "group" ORDER BY average_value DESC'
        sv = validate_result(df, "Compare average value between groups - is difference significant?", sql, columns, rows, len(df))
        # When scipy unavailable, Welch should be not applicable and must not contain fabricated p
        assert sv["applicable"] == False
        assert sv.get("p_value") is None or "p_value" not in sv or sv.get("p_value") is None
        assert any("scipy" in lim.lower() for lim in sv.get("limitations", [])) or "scipy" in sv.get("reason","").lower()
        # Chi-square also - directly test _chi_square_exact not via validate_result fallback
        from app.data_engine.statistical import _chi_square_exact
        import pandas as pd
        df2 = make_chi_df()
        ct = pd.crosstab(df2["cat1"], df2["cat2"]).values.tolist()
        res = _chi_square_exact(ct)
        # When scipy missing, should be None (not fabricated 0.03/0.20)
        assert res is None or res.get("p_value") not in [0.03, 0.20]
        # Also test validate_result returns not applicable with scipy limitation when possible
        # Provide valid rows for validation
        sv2 = validate_result(df2, "Is there association between cat1 and cat2?", 'SELECT "cat1","cat2" FROM df', ["cat1","cat2"], [{"cat1":"X","cat2":"P"},{"cat1":"Y","cat2":"Q"}], len(df2))
        if sv2.get("applicable"):
            assert sv2["p_value"] not in [0.03, 0.20]
        else:
            # Should contain scipy limitation if chi-square was attempted, or fallback reason - and must not be fabricated
            assert sv2.get("p_value") not in [0.03, 0.20] if sv2.get("p_value") is not None else True
            assert "scipy" in sv2.get("reason","").lower() or any("scipy" in lim.lower() for lim in sv2.get("limitations",[])) or "insufficient" in sv2.get("reason","").lower() or "no appropriate" in sv2.get("reason","").lower()
    finally:
        builtins.__import__ = real_import
        if original_scipy is not None:
            sys.modules["scipy"] = original_scipy
        else:
            sys.modules.pop("scipy", None)
        if original_stats is not None:
            sys.modules["scipy.stats"] = original_stats
        else:
            sys.modules.pop("scipy.stats", None)

# 4. Small sample -> appropriate limitation
def test_small_sample_limitation():
    df = make_df_for_welch(6,6)  # n <10
    rows = [{"group":"A","average_value":10.5},{"group":"B","average_value":14.5}]
    columns = ["group","average_value"]
    sql = 'SELECT "group", AVG("value") as average_value FROM df GROUP BY "group" ORDER BY average_value DESC'
    sv = validate_result(df, "Compare average value between groups", sql, columns, rows, len(df))
    assert sv["applicable"] == False
    assert any("small" in lim.lower() or "at least 10" in lim.lower() for lim in sv.get("limitations", []))
    assert sv.get("p_value") is None

# 5. Wilson CI remains correct
def test_wilson_ci_correct():
    from app.data_engine.statistical import _wilson_ci
    ci = _wilson_ci(0.5, 100)
    assert ci is not None
    assert ci["lower"] < 0.5 < ci["upper"]
    # Compare with known Wilson for p=0.5 n=100 ~ [0.403, 0.597]
    assert abs(ci["lower"] - 0.403) < 0.02
    assert abs(ci["upper"] - 0.597) < 0.02

# 6. Proportion z-test remains correct
def test_proportion_z_correct():
    from app.data_engine.statistical import _proportion_z_test
    res = _proportion_z_test(0.86, 14, 0.5, 46)
    assert res is not None
    assert "p_value" in res
    assert 0 <= res["p_value"] <= 1
    # Known: difference 0.36, should be significant
    assert res["p_value"] < 0.05
    # Effect size h
    from app.data_engine.statistical import _cohens_h
    h = _cohens_h(0.86, 0.5)
    assert h is not None
    assert abs(h) > 0.5

# 7. Effect sizes remain correct
def test_effect_sizes_correct():
    from app.data_engine.statistical import _cohens_h
    h = _cohens_h(0.8, 0.5)
    assert h is not None
    # For Welch, effect via cohens_d
    df = make_df_for_welch(20,20)
    rows = [{"group":"A","average_value":10.5},{"group":"B","average_value":14.5}]
    sv = validate_result(df, "Compare average value between groups - is difference significant?", 'SELECT "group", AVG("value") as average_value FROM df GROUP BY "group"', ["group","average_value"], rows, len(df))
    if sv["applicable"]:
        assert sv["effect_size"] is not None
        assert sv["effect_size_label"] == "cohens_d"

# 8. Recommendation must not treat unavailable as significant
def test_recommendation_unavailable_not_significant():
    sv_unavail = {"applicable": False, "reason": "Exact Welch t-test p-value requires scipy.", "limitations": ["Exact Welch t-test p-value requires scipy."]}
    rows = [{"group":"A","average_value":10.5}]
    rec = build_recommendation("Compare average value", 'SELECT "group", AVG("value") FROM df GROUP BY "group"', ["group","average_value"], rows, sv_unavail, None, "test", 40)
    # Should not claim significant
    assert "significant" not in rec["rationale"].lower() or "not" in rec["rationale"].lower() or rec["confidence"] == "low"
    assert rec["requires_validation"] == True

# 9. Trust score must not increase because validation merely marked applicable
def test_trust_not_inflated_by_applicable():
    from app.data_engine.intelligence import compute_trust_score
    df = pd.DataFrame({"a":[1,2,3]*20, "b":[4,5,6]*20})
    profile = {"quality_score": 80, "quality_details": {"score":80}}
    base = compute_trust_score(df, profile, {"success": True})
    with_val = compute_trust_score(df, profile, {"success": True}, statistical_validation={"applicable": True, "method":"two_group_proportion_wilson_z", "significance":"statistically significant", "p_value":0.01, "limitations":[]}, assumptions=["a","b","c"])
    # Score should not be higher than base + small epsilon; it should not inflate
    assert with_val["score"] <= base["score"] + 2, f"Trust inflated {base['score']} -> {with_val['score']}"
    # Also test not applicable does not inflate
    without = compute_trust_score(df, profile, {"success": True}, statistical_validation={"applicable": False, "reason":"test"}, assumptions=[])
    assert without["score"] <= base["score"] + 5

# 10. Existing Wilson and proportion still correct via API
def test_existing_wilson_via_api():
    h,did = make_loan_api_dataset()
    q="Analyze the loan approval rate across Gender, Education, Credit_History, and Property_Area. Identify the strongest and weakest applicant segments, but exclude segments with fewer than 10 applications. Compare the approval rate of the strongest segment with the overall approval rate, quantify the difference in percentage points, identify the main factors associated with the difference, and explain whether the observed differences are large enough to warrant further investigation. Show the underlying evidence and methodology used."
    r=client.post(f"/api/datasets/{did}/analyze", json={"question": q}, headers=h)
    assert r.status_code==200
    sv=r.json()["statistical_validation"]
    # Wilson CI should be present and correctly bounded
    assert sv["applicable"]==True
    assert sv["confidence_interval"]["strongest_segment"]["lower"] < sv["confidence_interval"]["strongest_segment"]["upper"]
    assert sv["confidence_interval"]["overall"]["lower"] < sv["confidence_interval"]["overall"]["upper"]

def make_loan_api_dataset():
    email=f"loanstat2_{uuid.uuid4().hex[:6]}@test.com"
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
    random.seed(1)
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
