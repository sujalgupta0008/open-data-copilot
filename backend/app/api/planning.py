from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import User, Dataset, Metric

router = APIRouter(prefix="/api/datasets", tags=["planning"])

def ensure_user_dataset(dataset_id: str, user: User, db: Session):
    ds = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not ds or ds.user_id != user.id:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return ds

def detect_ambiguity(question: str, dataset: Dataset, metrics: list, df_columns: list):
    """Return list of clarifications needed"""
    from app.ai.provider import classify_intent
    intent = classify_intent(question)
    # Do not run generic dimension detection for data-quality / causal / monitor intents
    # For needs_clarification we still want to produce metric clarification, so don't early-return entirely
    if intent in ["data_quality_analysis", "causal_question", "monitor", "data_health"]:
        return []
    q = question.lower()
    clarifications=[]
    # Metric ambiguity: if question mentions a business metric term but no saved metric or multiple interpretations
    business_terms = ["revenue","orders","profit","margin","aov","average order value","conversion","approval","churn","retention"]
    matched_terms=[]
    for term in business_terms:
        if term in q:
            matched_terms.append(term)
    # If matched term but no metric with that name
    metric_names_lower = [m.name.lower() for m in metrics]
    for term in matched_terms:
        # Skip approval if Loan_Status exists - approval rate is well-defined via Loan_Status
        if term == "approval" and any(c.lower() == "loan_status" for c in df_columns):
            continue
        # check if any metric name contains term
        has_metric = any(term in mn or mn in term for mn in metric_names_lower)
        # If column directly matches term, no clarification needed (use column)
        has_column = any(term.lower() == c.lower() for c in df_columns) or any(term.lower() in c.lower() or c.lower() in term.lower() for c in df_columns)
        if has_column:
            continue
        if not has_metric:
            # Suggest definitions
            if term=="revenue":
                clarifications.append({
                    "type": "metric_definition",
                    "field": term,
                    "question": f"Which '{term}' definition should I use?",
                    "options": [
                        {"value": "gross", "label": "Gross sales", "detail": "SUM(OrderAmount)"},
                        {"value": "net", "label": "Net sales after refunds", "detail": "SUM(OrderAmount) - SUM(RefundAmount)"}
                    ],
                    "message": f"You don't have a saved definition for {term}. Should I calculate it as SUM({term})?"
                })
            elif term in ("approval","approval rate"):
                # Approval rate is defined via Loan_Status, no clarification needed
                continue
            else:
                clarifications.append({
                    "type": "metric_definition",
                    "field": term,
                    "question": f"How should I calculate '{term}'?",
                    "options": [{"value": f"sum_{term}", "label": f"SUM({term})"}, {"value": f"avg_{term}", "label": f"AVG({term})"}],
                    "message": f"No saved metric for {term}. Choose a definition."
                })
        else:
            # If metric exists, we can suggest using it, not ambiguity unless multiple metrics match?
            pass
    # Ambiguous vague performance question
    if "why is performance worse" in q or ("performance" in q and "worse" in q and not matched_terms):
        clarifications.append({
            "type": "metric_definition",
            "field": "performance_metric",
            "question": "What performance metric do you mean?",
            "options": [
                {"value":"revenue","label":"Revenue"},
                {"value":"profit","label":"Profit"},
                {"value":"approval_rate","label":"Approval Rate"},
                {"value":"conversion_rate","label":"Conversion Rate"},
                {"value":"other","label":"Other"}
            ],
            "message": "What performance metric do you mean?"
        })
    # Date range ambiguity: if question contains "last month", "previous period", "last week" and dataset has date column
    date_keywords = ["last month","previous month","last week","previous period","this month","ytd"]
    has_date_col = any("date" in c.lower() or "time" in c.lower() for c in df_columns)
    for kw in date_keywords:
        if kw in q and has_date_col:
            clarifications.append({
                "type": "date_range",
                "field": "date_range",
                "question": f"'{kw}' could be interpreted in different ways. Which date column should I use?",
                "options": [{"value": c, "label": c} for c in df_columns if "date" in c.lower()][:3],
                "message": f"Clarify date range for '{kw}'"
            })
            break
    # Aggregation ambiguity: if question says "revenue" without aggregation but metric needs aggregation
    # Skip for trend/time-series where aggregation is implied (SUM/AVG over time)
    if "revenue" in q and not any(agg in q for agg in ["sum","total","average","avg","count","max","min"]):
        if any(kw in q for kw in ["trend","over time","change over","time series","month","week","year","decline","increase"]):
            # For trend, aggregation is implied (e.g., monthly total), no clarification
            pass
        elif any("revenue" in term for term in matched_terms):
            # Only add if not already added metric clarification
            if not any(c["type"]=="metric_definition" for c in clarifications):
                clarifications.append({
                    "type": "aggregation",
                    "field": "aggregation",
                    "question": "Which aggregation should I use?",
                    "options": [{"value":"sum","label":"Total (SUM)"},{"value":"avg","label":"Average (AVG)"},{"value":"count","label":"Count"}],
                    "message": "Specify aggregation for revenue"
                })
    # Dimension ambiguity: if question says "by region" but region not in columns?
    # Skip analytical output concepts that are not dataset columns
    OUTPUT_CONCEPTS = {"severity","impact","priority","importance","risk"}
    # We check "by X" phrase
    import re
    m = re.search(r"by\s+([a-z_]+)", q)
    if m:
        dim = m.group(1)
        if dim.lower() in OUTPUT_CONCEPTS:
            # Do not treat output ranking concepts as dataset dimensions
            pass
        elif dim not in [c.lower() for c in df_columns] and dim.rstrip('s') not in [c.lower() for c in df_columns]:
            clarifications.append({
                "type": "dimension",
                "field": "dimension",
                "question": f"Dimension '{dim}' not found. Which dimension did you mean?",
                "options": [{"value": c, "label": c} for c in df_columns[:5]],
                "message": f"Column '{dim}' not in dataset"
            })
    # If no metric exists and question is simple "What is average LoanAmount by Gender?" -> no clarification
    return clarifications

def build_analysis_plan(question: str, clarifications: list, dataset: Dataset, metrics: list):
    from app.ai.provider import classify_intent
    complexity = classify_intent(question)
    q = question.lower()
    # === COMPLEX MULTI-METRIC/TREND/DRIVER PLAN (Fix for pipeline completeness) ===
    try:
        from app.data_engine.complex_requirements import extract_requirements, build_plan as _build_complex_plan
        import os
        import pandas as _pd
        from app.data_engine.profiler import load_dataframe as _load_df
        _df = None
        try:
            if dataset and dataset.storage_path and os.path.exists(dataset.storage_path):
                _df = _load_df(dataset.storage_path)
                # Try current version if exists (best effort without DB)
                from pathlib import Path as _Path
                cur_path = _Path(dataset.storage_path).parent / dataset.id / "v999.csv"  # placeholder, will fallback
                # Instead, just use original df; extraction only needs column names and sample, not current version precision
            else:
                _df = _pd.DataFrame()
        except:
            _df = _pd.DataFrame()
        if _df is not None and not _df.empty:
            _req = extract_requirements(question, _df)
            _comps = _req.get("requested_components", [])
            if len([c for c in _comps if c.startswith("monthly_")]) >= 2 or ("monthly transaction volume and average unit price" in q) or (len(_req.get("metrics", [])) >= 2 and ("product_driver" in _comps or "customer_driver" in _comps or "region_driver" in _comps)):
                _plan = _build_complex_plan(_req)
                if _plan:
                    return _plan
            if len(_comps) >= 6 and "mom" in _comps and "strongest_weakest" in _comps:
                _plan = _build_complex_plan(_req)
                if _plan:
                    return _plan
    except Exception as _e:
        pass
    # Simple questions skip plan
    if complexity == "simple_aggregation" and not clarifications:
        return None
    # Data quality analysis — separate audit vs cleaning
    if complexity == "data_quality_analysis":
        import re as _re
        q_low = q
        # Determine explicit cleaning request deterministically (no LLM)
        is_explicit_cleaning = False
        # Audit indicators take precedence
        is_audit = any(k in q_low for k in ["identify data quality", "rank issues", "severity", "downstream", "what should i fix", "prioritize", "audit", "assess data quality", "explain data quality", "explain how missing"])
        has_do_not_modify = "do not modify" in q_low
        # Explicit cleaning must be imperative and not just recommendation request
        if has_do_not_modify:
            is_explicit_cleaning = False
        elif "what should i fix" in q_low:
            is_explicit_cleaning = False
        elif _re.search(r"^\s*(fix|clean|remove|replace|impute|normalize|deduplicate|rename|convert)\b", q_low):
            is_explicit_cleaning = True
        elif "fix the highest" in q_low and "what should" not in q_low:
            is_explicit_cleaning = True
        elif any(v in q_low for v in ["clean the missing", "remove duplicate", "fix missing", "fix the invalid"]):
            is_explicit_cleaning = True

        if is_explicit_cleaning and not is_audit:
            # Allow cleaning workflow only for explicit requests
            return [
                {"step": 1, "title": "Scan dataset with Data Health + AI Data Doctor", "detail": "Detect missing, duplicates, outliers, invalid values"},
                {"step": 2, "title": "Rank issues by severity", "detail": "Critical > High > Medium > Low using affected rows"},
                {"step": 3, "title": "Explain downstream impact", "detail": "How each issue biases analysis"},
                {"step": 4, "title": "Recommend fix order", "detail": "Priority based on severity and impact"},
                {"step": 5, "title": "Preview cleaning operation", "detail": "Show before/after without auto-apply"},
                {"step": 6, "title": "Apply / Reject with user approval", "detail": "Cleaning Studio preview, user decides"},
                {"step": 7, "title": "Re-profile after apply", "detail": "Recompute quality score and verify improvement"},
                {"step": 8, "title": "Verify quality improvement", "detail": "Compare before/after metrics"},
            ]
        # Default audit path — no mutation
        return [
            {"step": 1, "title": "Scan the dataset", "detail": "Detect missing values, duplicates, outliers, invalid values, and schema/type issues."},
            {"step": 2, "title": "Rank issues by severity", "detail": "Critical → High → Medium → Low using affected rows and analytical impact."},
            {"step": 3, "title": "Explain downstream impact", "detail": "Explain how each issue can affect calculations, trends, segmentation, models, or other analysis."},
            {"step": 4, "title": "Prioritize fixes", "detail": "Recommend which issue should be addressed first and why."},
            {"step": 5, "title": "Show evidence and methodology", "detail": "Include affected columns, affected rows, quality metrics, and methodology."},
            {"step": 6, "title": "No data will be modified.", "detail": "Audit only — cleaning requires explicit user approval in a follow-up request."},
        ]
    # Special handling for complex approval-rate segmentation
    if complexity == "complex_multi_stage" and "approval rate" in q:
        return [
            {"step": 1, "title": "Inspect Loan_Status values and determine approval encoding", "detail": "Check distinct Loan_Status values (Y/N, Yes/No) to define approved"},
            {"step": 2, "title": "Calculate overall approval rate", "detail": "Approved / total * 100 across all applications"},
            {"step": 3, "title": "Group by Gender, Education, Credit_History, Property_Area", "detail": "Create segments Gender×Education×Credit_History×Property_Area"},
            {"step": 4, "title": "Exclude groups with fewer than 10 applications", "detail": "HAVING COUNT(*) >= 10"},
            {"step": 5, "title": "Rank strongest and weakest segments by approval rate", "detail": "Order by approval_rate DESC"},
            {"step": 6, "title": "Compare strongest segment with overall approval rate", "detail": "Strongest vs benchmark"},
            {"step": 7, "title": "Calculate percentage-point difference", "detail": "Strongest rate - overall rate = pp difference"},
            {"step": 8, "title": "Analyze which dimensions are associated with the difference", "detail": "Contribution of Gender/Education/Credit_History/Property_Area"},
            {"step": 9, "title": "Return evidence and methodology", "detail": "Evidence table, SQL, trust score"},
        ]
    steps=[]
    step_num=1
    if clarifications:
        steps.append({"step": step_num, "title": "Resolve ambiguity", "detail": "Clarify metric/date/dimension with you"})
        step_num+=1
    # Detect metric reuse
    metric_names = [m.name.lower() for m in metrics]
    used_metric = None
    for mn in metric_names:
        if mn in q:
            used_metric = mn
            steps.append({"step": step_num, "title": f"Use saved metric '{mn}'", "detail": f"Apply definition for {mn}"})
            step_num+=1
            break
    if any(word in q for word in ["compare","previous","change","versus","vs"]):
        steps.append({"step": step_num, "title": "Compare with previous period", "detail": "Compute current vs previous"})
        step_num+=1
        steps.append({"step": step_num, "title": "Break down by dimension", "detail": "Identify largest contributors"})
        step_num+=1
    elif "trend" in q:
        steps.append({"step": step_num, "title": "Analyze trend over time", "detail": "Group by time grain"})
        step_num+=1
    else:
        steps.append({"step": step_num, "title": "Generate SQL", "detail": "Translate question to validated SQL"})
        step_num+=1
    steps.append({"step": step_num, "title": "Execute with DuckDB", "detail": "Run SQL and collect evidence"})
    step_num+=1
    steps.append({"step": step_num, "title": "Verify evidence & explain", "detail": "Show chart, trust score, and human summary"})
    return steps

@router.post("/{dataset_id}/clarify")
def clarify(dataset_id: str, payload: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    question = (payload.get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question required")
    metrics = db.query(Metric).filter(Metric.dataset_id==dataset_id, Metric.user_id==current_user.id).all()
    from app.api.cleaning import _get_current_df_and_version
    try:
        df, _ = _get_current_df_and_version(ds, db)
        columns = list(df.columns)
    except:
        columns=[]
    clarifications = detect_ambiguity(question, ds, metrics, columns)
    needs = len(clarifications)>0
    return {"needs_clarification": needs, "clarifications": clarifications, "question": question}

@router.post("/{dataset_id}/plan")
def get_plan(dataset_id: str, payload: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = ensure_user_dataset(dataset_id, current_user, db)
    question = (payload.get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question required")
    clarifications = payload.get("clarifications") or []
    # If not provided, detect
    if not clarifications:
        metrics = db.query(Metric).filter(Metric.dataset_id==dataset_id, Metric.user_id==current_user.id).all()
        from app.api.cleaning import _get_current_df_and_version
        try:
            df, _ = _get_current_df_and_version(ds, db)
            cols=list(df.columns)
        except:
            cols=[]
        clarifications = detect_ambiguity(question, ds, metrics, cols)
    metrics = db.query(Metric).filter(Metric.dataset_id==dataset_id, Metric.user_id==current_user.id).all()
    plan = build_analysis_plan(question, clarifications, ds, metrics)
    if plan is None:
        return {"needs_plan": False, "plan": [], "message": "Simple question — executing directly"}
    return {"needs_plan": True, "plan": plan, "clarifications": clarifications}

