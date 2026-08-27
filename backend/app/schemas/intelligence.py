from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal

RequirementStatus = Literal["completed", "partial", "not_applicable", "blocked", "failed"]

class IntelligenceRequirementContract(BaseModel):
    id: str
    description: str
    type: str
    dependencies: List[str] = Field(default_factory=list)
    status: RequirementStatus = "not_applicable"
    evidence: Dict[str, Any] = Field(default_factory=dict)
    result: Dict[str, Any] = Field(default_factory=dict)
    validation: Dict[str, Any] = Field(default_factory=dict)
    failure_reason: Optional[str] = None

class IntelligenceCoverage(BaseModel):
    requested_requirements: List[str]
    completed_requirements: List[str]
    missing_requirements: List[str]
    coverage_ratio: float
    execution_status: Literal["completed", "partial", "failed"]
    analysis_completeness: Literal["complete", "partial", "incomplete"]

def compute_intelligence_coverage(requested: List[str], completed: List[str], failed: List[str] = None) -> IntelligenceCoverage:
    failed = failed or []
    missing = [r for r in requested if r not in completed]
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
        analysis_completeness = "partial" if cov >=0.5 else "incomplete"
    else:
        execution_status = "completed"
        analysis_completeness = "complete"
    return IntelligenceCoverage(
        requested_requirements=requested,
        completed_requirements=completed,
        missing_requirements=missing,
        coverage_ratio=cov,
        execution_status=execution_status,
        analysis_completeness=analysis_completeness
    )
