from pydantic import BaseModel, ConfigDict, EmailStr, Field
from typing import Optional, List, Any
from datetime import datetime

class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    name: Optional[str] = None

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserOut(BaseModel):
    id: str
    email: str
    name: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut

class DatasetOut(BaseModel):
    id: str
    name: str
    original_filename: str
    file_type: str
    file_size: int
    row_count: int
    column_count: int
    quality_score: float
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

class DatasetColumnOut(BaseModel):
    id: str
    name: str
    data_type: str
    null_count: int
    null_percentage: float
    unique_count: int
    min_value: Optional[str] = None
    max_value: Optional[str] = None
    mean_value: Optional[float] = None
    median_value: Optional[float] = None
    std_value: Optional[float] = None
    model_config = ConfigDict(from_attributes=True)

class DatasetProfileOut(BaseModel):
    dataset: DatasetOut
    columns: List[DatasetColumnOut]
    quality_details: dict
    insights: List[str]
    duplicates: int
    sample_rows: List[dict]

class PreviewOut(BaseModel):
    rows: List[dict]
    total_rows: int
    page: int
    page_size: int

class QueryRequest(BaseModel):
    question: str
    session_id: Optional[str] = None

class PythonRequest(BaseModel):
    code: Optional[str] = None
    question: Optional[str] = None
    session_id: Optional[str] = None

class ChartOut(BaseModel):
    id: str
    chart_type: str
    configuration: dict
    model_config = ConfigDict(from_attributes=True)

class AnalysisResultOut(BaseModel):
    id: str
    result_type: str
    result_data: Any
    model_config = ConfigDict(from_attributes=True)

class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    generated_code: Optional[str] = None
    execution_status: Optional[str] = None
    created_at: datetime
    results: List[AnalysisResultOut] = []
    charts: List[ChartOut] = []
    model_config = ConfigDict(from_attributes=True)

class SessionOut(BaseModel):
    id: str
    title: str
    dataset_id: str
    created_at: datetime
    updated_at: datetime
    messages: List[MessageOut] = []
    dataset_name: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)

class ReportCreate(BaseModel):
    title: str
    dataset_id: str
    topic: Optional[str] = None
    session_id: Optional[str] = None
    analysis_type: Optional[str] = None
    report_type: Optional[str] = None
    source_report_ids: Optional[List[str]] = None

class ReportGenerateRequest(BaseModel):
    topic: str
    title: Optional[str] = None
    dataset_id: Optional[str] = None
    confirm: Optional[bool] = False
    clarification_choice: Optional[str] = None

class CombinedReportRequest(BaseModel):
    report_ids: List[str]
    title: Optional[str] = None

class ReportOut(BaseModel):
    id: str
    title: str
    dataset_id: str
    content: Any
    created_at: datetime
    dataset_version: Optional[str] = None
    dataset_version_number: Optional[int] = None
    session_id: Optional[str] = None
    analysis_type: Optional[str] = None
    report_type: Optional[str] = None
    source_report_ids: Optional[Any] = None
    model_config = ConfigDict(from_attributes=True)
