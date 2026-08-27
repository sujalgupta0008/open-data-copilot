from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal

RequirementStatus = Literal["completed", "partial", "not_applicable", "blocked", "failed"]

class RequirementContract(BaseModel):
    id: str
    description: str
    type: str
    dependencies: List[str] = Field(default_factory=list)
    status: RequirementStatus = "not_applicable"
    evidence: Dict[str, Any] = Field(default_factory=dict)
    result: Dict[str, Any] = Field(default_factory=dict)
    validation: Dict[str, Any] = Field(default_factory=dict)
    failure_reason: Optional[str] = None

class RequirementCoverage(BaseModel):
    requested_requirements: List[str]
    completed_requirements: List[str]
    missing_requirements: List[str]
    coverage_ratio: float
    execution_status: Literal["completed", "partial", "failed"]
    analysis_completeness: Literal["complete", "partial", "incomplete"] = "complete"

def compute_coverage(requested: List[str], completed: List[str], failed: List[str] = None) -> RequirementCoverage:
    """
    Measure coverage and determine status per spec:
    - coverage_ratio = len(completed)/len(requested) if requested else 1.0
    - If coverage_ratio < 1.0, execution_status MUST be "partial" (not completed)
    - analysis_completeness: complete if coverage_ratio ==1.0 else partial if >=0.5 else incomplete
    - One failed sub-requirement must NOT drop valid sub-requirements.
    """
    failed = failed or []
    missing = [r for r in requested if r not in completed]
    # Failed requirements remain missing, but completed ones are preserved
    # Do not drop valid sub-requirements when one fails
    cov = len(completed) / len(requested) if requested else 1.0
    cov = round(cov,2)
    if not requested:
        execution_status = "completed"
        analysis_completeness = "complete"
    elif failed and len(completed)==0:
        execution_status = "failed"
        analysis_completeness = "incomplete"
    elif cov < 1.0:
        execution_status = "partial"
        if cov >= 0.5:
            analysis_completeness = "partial"
        else:
            analysis_completeness = "incomplete"
    else:
        execution_status = "completed"
        analysis_completeness = "complete"
    return RequirementCoverage(
        requested_requirements=requested,
        completed_requirements=completed,
        missing_requirements=missing,
        coverage_ratio=cov,
        execution_status=execution_status,
        analysis_completeness=analysis_completeness
    )

def build_requirement_contracts(question: str, df_columns: List[str] = None, requested: List[str] = None, results_map: Dict[str, Any] = None) -> List[RequirementContract]:
    """
    Create RequirementContract list from decomposition.
    Generic: each requested component becomes a contract.
    """
    requested = requested or []
    results_map = results_map or {}
    df_columns = df_columns or []
    contracts: List[RequirementContract] = []
    for req in requested:
        res = results_map.get(req, {})
        # Determine status based on presence of result/evidence
        # If result indicates success, status completed, else blocked/failed
        status: RequirementStatus = "completed"
        failure_reason = None
        evidence = res.get("evidence", {}) if isinstance(res, dict) else {}
        result = res.get("result", {}) if isinstance(res, dict) else {}
        validation = res.get("validation", {}) if isinstance(res, dict) else {}
        # Heuristics: if req indicates missing column or failure, mark blocked/failed
        if "missing" in req.lower() or "missing_components" in str(req):
            status = "blocked"
            failure_reason = f"Required column or time dimension missing for {req}"
        elif res.get("status") in ["failed","blocked","not_applicable"]:
            status = res["status"]
            failure_reason = res.get("failure_reason")
        elif not res:
            # No result yet, mark not_applicable or blocked depending on question
            status = "not_applicable"
        # Determine type from req prefix
        req_type = "analysis"
        if "statistical" in req.lower():
            req_type = "statistical_validation"
        elif "assumption" in req.lower():
            req_type = "assumptions"
        elif "evidence" in req.lower():
            req_type = "evidence"
        elif "recommendation" in req.lower():
            req_type = "recommendation"
        elif "driver" in req.lower():
            req_type = "driver_analysis"
        elif "mom" in req.lower() or "month-over-month" in req.lower():
            req_type = "time_series"
        # Dependencies: simplified
        dependencies = []
        if req_type == "driver_analysis":
            dependencies = ["monthly_transaction_volume", "latest_period"]
        elif req_type == "statistical_validation":
            dependencies = ["evidence"]
        contracts.append(RequirementContract(
            id=req,
            description=req.replace("_"," "),
            type=req_type,
            dependencies=dependencies,
            status=status,
            evidence=evidence,
            result=result,
            validation=validation,
            failure_reason=failure_reason
        ))
    return contracts
