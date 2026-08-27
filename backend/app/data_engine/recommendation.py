from typing import Dict, Any, List

SENSITIVE_KEYWORDS = ["reject applicants", "approve loans", "fire", "terminate", "change price", "increase price", "decrease price", "hiring", "firing", "loan approval"]

def is_sensitive_action(text: str) -> bool:
    low = (text or "").lower()
    for kw in SENSITIVE_KEYWORDS:
        if kw in low:
            return True
    # generic risky: automatically reject/approve
    if "automatically" in low and ("reject" in low or "approve" in low):
        return True
    return False

def build_recommendation(question: str, sql: str, columns: List[str], rows: List[Dict], statistical_validation: Dict[str, Any], drivers: Dict[str, Any] = None, dataset_name: str = "", total_rows: int = 0) -> Dict[str, Any]:
    """
    Evidence-backed recommendation. Uses actual evidence, not invented values.
    """
    q_low = (question or "").lower()
    # Extract evidence
    evidence = []
    limitations = []
    requires_validation = False

    # Evidence from rows
    if rows:
        # Use peak (max) for time-series, otherwise first row; never use first row if peak is elsewhere
        is_time_series = False
        try:
            if columns and any(k in columns[0].lower() for k in ["month","date","year","time"]):
                is_time_series = True
        except:
            pass
        evidence.append(f"Executed SQL returned {len(rows)} rows; columns: {', '.join(columns[:5])}")
        # For approval rate case
        lower_cols = [c.lower() for c in columns]
        if "approval_rate" in lower_cols and rows:
            strongest = rows[0]
            weakest = rows[-1] if len(rows)>1 else rows[0]
            try:
                rate_col = next(c for c in columns if c.lower()=="approval_rate")
                sp = float(strongest.get(rate_col))
                wp = float(weakest.get(rate_col))
                evidence.append(f"Strongest segment approval rate = {sp:.1f}% ({strongest.get('application_count','')} applications)")
                evidence.append(f"Weakest segment approval rate = {wp:.1f}%")
                if statistical_validation and statistical_validation.get("applicable"):
                    obs = statistical_validation.get("observed", {})
                    if obs:
                        evidence.append(f"Overall approval rate = {obs.get('overall_rate','')}% ; difference = {obs.get('difference_pp','')} pp")
                    ci = statistical_validation.get("confidence_interval", {})
                    if ci:
                        evidence.append(f"Statistical validation: p={statistical_validation.get('p_value')} significance={statistical_validation.get('significance')} effect={statistical_validation.get('effect_size')} ({statistical_validation.get('effect_size_interpretation')})")
            except:
                pass
        else:
            # generic - for time-series, use peak (max) not first row sorted by month
            try:
                is_time_series = False
                try:
                    if columns and any(k in columns[0].lower() for k in ["month","date","year","time"]):
                        is_time_series = True
                except:
                    pass
                if is_time_series and len(columns) >= 2 and len(rows) >= 2:
                    # Find metric col (first non-time)
                    metric_col = columns[1]
                    # Find row with max metric value
                    max_row = max(rows, key=lambda r: float(r.get(metric_col) or 0) if r.get(metric_col) is not None else float('-inf'))
                    evidence.append(f"Peak result: {max_row} (highest {metric_col}) — verified ranking, not first row")
                    # Also add weakest for context
                    min_row = min(rows, key=lambda r: float(r.get(metric_col) or 0) if r.get(metric_col) is not None else float('inf'))
                    evidence.append(f"Weakest: {min_row}")
                else:
                    top = rows[0]
                    evidence.append(f"Top result: {top}")
            except:
                try:
                    top = rows[0]
                    evidence.append(f"Top result: {top}")
                except:
                    pass

    # Evidence from statistical validation
    if statistical_validation:
        if statistical_validation.get("applicable"):
            evidence.append(f"Method: {statistical_validation.get('method')}")
            limitations.extend(statistical_validation.get("limitations", []))
        else:
            limitations.append(f"Statistical validation not applicable: {statistical_validation.get('reason')}")
            limitations.extend(statistical_validation.get("limitations", []))

    # Drivers evidence
    if drivers:
        if drivers.get("dimensions"):
            dims = drivers.get("dimensions", [])
            # find largest diff
            largest = drivers.get("largest_difference")
            if largest:
                evidence.append(f"Largest driver difference {largest.get('difference_pp')} pp in {largest.get('dimension')}")
        elif drivers.get("primary_drivers"):
            pd = drivers.get("primary_drivers", [])[:2]
            for d in pd:
                evidence.append(f"Driver {d.get('dimension_value')} contributes {d.get('contribution_percent')}% of total")
        limitations.append(drivers.get("disclaimer") or "Drivers show association, not causation")

    # Build title and recommendation based on evidence
    title = ""
    recommendation = ""
    rationale = ""
    expected_impact = ""
    confidence = "medium"

    # Approval rate specific
    if "approval_rate" in [c.lower() for c in columns]:
        strongest_desc = "strongest segment"
        # Build readable description from strongest row dims
        try:
            dims = [c for c in columns if c.lower() not in ["application_count","approved_count","approval_rate"]]
            strongest = rows[0]
            parts = []
            for d in dims:
                v = strongest.get(d)
                if v is None or str(v).strip()=="":
                    parts.append("Missing")
                else:
                    parts.append(str(v))
            strongest_desc = ", ".join(parts) if parts else "strongest segment"
        except:
            pass
        title = "Investigate strongest segment characteristics"
        # Use evidence values, not invent
        obs = statistical_validation.get("observed") if statistical_validation else {}
        if obs and obs.get("difference_pp"):
            rationale = f"Approval rate in strongest segment ({strongest_desc}) is materially above overall benchmark by {obs.get('difference_pp')} pp."
        else:
            rationale = f"Strongest segment {strongest_desc} shows higher observed approval rate than overall."
        recommendation = f"Prioritize further investigation of the strongest segment's characteristics ({strongest_desc}) for application-processing optimization. Review associated factors without automated operational changes."
        expected_impact = "If further investigation confirms stable drivers, process improvements may be considered."
        # Confidence based on sample size and significance
        if statistical_validation and statistical_validation.get("applicable"):
            sig = statistical_validation.get("significance","")
            n = statistical_validation.get("sample_sizes",{}).get("strongest",0)
            if "significant" in sig and n >=30:
                confidence = "high"
            elif "significant" in sig:
                confidence = "medium"
            else:
                confidence = "low"
        else:
            confidence = "low"
        limitations.append("Association does not establish causation; requires human/business validation before operational use.")
        requires_validation = True
    elif any(k in q_low for k in ["revenue", "sales", "profit", "decline", "fall", "drop", "decrease"]):
        title = "Investigate drivers of change"
        recommendation = "Drill into period-over-period contribution by dimension and review underlying data quality before action."
        rationale = "Metric change detected; drivers indicate which dimensions contributed most to the change."
        if statistical_validation and statistical_validation.get("applicable"):
            rationale += f" Statistical test: {statistical_validation.get('significance')} (p={statistical_validation.get('p_value')})."
        expected_impact = "Clarifies whether decline is concentrated or broad-based."
        confidence = "medium"
        requires_validation = True
    else:
        # Generic recommendation
        title = "Review evidence and validate"
        recommendation = "Review the evidence table, verify with domain knowledge, and consider a follow-up period comparison where applicable."
        rationale = "Analysis is grounded in executed SQL and deterministic checks; further validation helps confirm practical relevance."
        expected_impact = "Ensures decisions are based on verified evidence."
        confidence = "low"
        requires_validation = True

    # Ensure sensitive actions require validation
    if is_sensitive_action(recommendation) or is_sensitive_action(question):
        requires_validation = True
        limitations.append("Sensitive business decision — requires human/business validation.")
    else:
        # Always require validation for operational recommendations per spec
        if not requires_validation:
            # per spec sensitive decisions must say requires validation; we already set true for approval case
            pass
        # For non-sensitive, still include validation flag if limited evidence
        if statistical_validation and not statistical_validation.get("applicable"):
            requires_validation = True

    # Ensure limitations not empty
    if not limitations:
        limitations = ["Observed association; confounding not controlled.", "Requires human validation before operational change."]

    # De-duplicate limitations
    seen = set()
    uniq_lims = []
    for lim in limitations:
        if lim not in seen:
            seen.add(lim)
            uniq_lims.append(lim)

    # Confidence mapping
    # statistical validation influences confidence
    if statistical_validation and statistical_validation.get("applicable"):
        if statistical_validation.get("significance") == "not statistically significant":
            confidence = "low"

    # Build rationale: must be derived from evidence, not invented
    # Ensure supporting_evidence list
    supporting = evidence[:6] if evidence else ["No additional evidence"]

    # Expected impact must be conservative
    if not expected_impact:
        expected_impact = "Informs further investigation."

    return {
        "title": title,
        "recommendation": recommendation,
        "rationale": rationale,
        "supporting_evidence": supporting,
        "expected_impact": expected_impact,
        "confidence": confidence,
        "limitations": uniq_lims,
        "requires_validation": requires_validation
    }

def recommendation_for_monitor(monitor_context: Dict[str, Any], statistical_validation: Dict[str, Any] = None, drivers: Dict[str, Any] = None) -> Dict[str, Any]:
    """Special case for monitor alert investigation"""
    metric_name = monitor_context.get("metric_name", "Metric")
    change_pct = monitor_context.get("change_percent") or 0
    current = monitor_context.get("current_value")
    previous = monitor_context.get("previous_value")
    prev_str = f"{previous:.2f}" if previous is not None else "—"
    curr_str = f"{current:.2f}" if current is not None else "—"
    chg = change_pct if change_pct is not None else 0
    evidence = [
        f"Monitor {metric_name}: {prev_str} -> {curr_str} (change {chg:.1f}%)",
        f"Threshold: {monitor_context.get('threshold_percent')}% ; status: {monitor_context.get('status')}",
    ]
    if monitor_context.get("period_start"):
        evidence.append(f"Period {monitor_context.get('period_start')} to {monitor_context.get('period_end')}")
    if drivers and drivers.get("summary"):
        evidence.append(drivers["summary"])
    if statistical_validation and statistical_validation.get("applicable"):
        evidence.append(f"Statistical validation: {statistical_validation.get('significance')} p={statistical_validation.get('p_value')}")
    limitations = ["Association not causation", "Requires human validation before operational action"]
    if statistical_validation and statistical_validation.get("limitations"):
        limitations.extend(statistical_validation["limitations"][:2])
    # Direction-aware recommendation
    rec_text = f"Investigate drivers of {metric_name} change; prioritize dimensions with largest period-over-period contribution."
    abs_chg = abs(chg) if chg is not None else 0
    rationale = f"{metric_name} changed {abs_chg:.1f}% since previous check; monitor threshold exceeded." if abs_chg > (monitor_context.get('threshold_percent') or 10) else f"{metric_name} shows material change."
    return {
        "title": f"Investigate {metric_name} change",
        "recommendation": rec_text,
        "rationale": rationale,
        "supporting_evidence": evidence,
        "expected_impact": "Isolates whether change is broad or concentrated.",
        "confidence": "medium",
        "limitations": limitations,
        "requires_validation": True
    }
