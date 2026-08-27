import uuid
from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey, Text, JSON, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.core.database import Base

def gen_uuid():
    return str(uuid.uuid4())

def now():
    return datetime.now(timezone.utc)

class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=gen_uuid)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    name = Column(String, nullable=True)
    created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now, onupdate=now)

    datasets = relationship("Dataset", back_populates="user", cascade="all, delete-orphan")
    sessions = relationship("AnalysisSession", back_populates="user", cascade="all, delete-orphan")
    reports = relationship("Report", back_populates="user", cascade="all, delete-orphan")

class Dataset(Base):
    __tablename__ = "datasets"
    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False)
    original_filename = Column(String, nullable=False)
    file_type = Column(String, nullable=False)
    file_size = Column(Integer, nullable=False)
    row_count = Column(Integer, nullable=False, default=0)
    column_count = Column(Integer, nullable=False, default=0)
    quality_score = Column(Float, default=0)
    storage_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now, onupdate=now)

    user = relationship("User", back_populates="datasets")
    columns = relationship("DatasetColumn", back_populates="dataset", cascade="all, delete-orphan")
    sessions = relationship("AnalysisSession", back_populates="dataset", cascade="all, delete-orphan")
    reports = relationship("Report", back_populates="dataset", cascade="all, delete-orphan")

class DatasetColumn(Base):
    __tablename__ = "dataset_columns"
    id = Column(String, primary_key=True, default=gen_uuid)
    dataset_id = Column(String, ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False)
    data_type = Column(String, nullable=False)
    null_count = Column(Integer, default=0)
    null_percentage = Column(Float, default=0)
    unique_count = Column(Integer, default=0)
    min_value = Column(String, nullable=True)
    max_value = Column(String, nullable=True)
    mean_value = Column(Float, nullable=True)
    median_value = Column(Float, nullable=True)
    std_value = Column(Float, nullable=True)

    dataset = relationship("Dataset", back_populates="columns")

class AnalysisSession(Base):
    __tablename__ = "analysis_sessions"
    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    dataset_id = Column(String, ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String, nullable=False)
    created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now, onupdate=now)

    user = relationship("User", back_populates="sessions")
    dataset = relationship("Dataset", back_populates="sessions")
    messages = relationship("AnalysisMessage", back_populates="session", cascade="all, delete-orphan")

class AnalysisMessage(Base):
    __tablename__ = "analysis_messages"
    id = Column(String, primary_key=True, default=gen_uuid)
    session_id = Column(String, ForeignKey("analysis_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String, nullable=False)  # user | assistant | system
    content = Column(Text, nullable=False)
    generated_code = Column(Text, nullable=True)
    execution_status = Column(String, nullable=True)  # pending, success, failed
    created_at = Column(DateTime, default=now)

    session = relationship("AnalysisSession", back_populates="messages")
    results = relationship("AnalysisResult", back_populates="message", cascade="all, delete-orphan")
    charts = relationship("Chart", back_populates="message", cascade="all, delete-orphan")

class AnalysisResult(Base):
    __tablename__ = "analysis_results"
    id = Column(String, primary_key=True, default=gen_uuid)
    message_id = Column(String, ForeignKey("analysis_messages.id", ondelete="CASCADE"), nullable=False, index=True)
    result_type = Column(String, nullable=False)  # table, scalar, error
    result_data = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=now)

    message = relationship("AnalysisMessage", back_populates="results")

class Chart(Base):
    __tablename__ = "charts"
    id = Column(String, primary_key=True, default=gen_uuid)
    message_id = Column(String, ForeignKey("analysis_messages.id", ondelete="CASCADE"), nullable=False, index=True)
    chart_type = Column(String, nullable=False)
    configuration = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=now)

    message = relationship("AnalysisMessage", back_populates="charts")

class Report(Base):
    __tablename__ = "reports"
    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    dataset_id = Column(String, ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String, nullable=False)
    content = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=now)
    # Extended for reporting workspace (Mode A/B + Combined + Versioning)
    dataset_version = Column(String, nullable=True)  # version id or number
    dataset_version_number = Column(Integer, nullable=True)
    session_id = Column(String, ForeignKey("analysis_sessions.id", ondelete="SET NULL"), nullable=True)
    analysis_type = Column(String, nullable=True)  # e.g., simple_aggregation, trend_analysis, data_quality_analysis
    report_type = Column(String, nullable=True)  # ai_generated, copilot, combined
    source_report_ids = Column(JSON, nullable=True)  # for combined: list of source report ids

    user = relationship("User", back_populates="reports")
    dataset = relationship("Dataset", back_populates="reports")

class DatasetVersion(Base):
    __tablename__ = "dataset_versions"
    id = Column(String, primary_key=True, default=gen_uuid)
    dataset_id = Column(String, ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    name = Column(String, nullable=False)
    storage_path = Column(String, nullable=False)
    row_count = Column(Integer, default=0)
    column_count = Column(Integer, default=0)
    quality_score = Column(Float, default=0)
    transformation_summary = Column(Text, nullable=True)
    created_at = Column(DateTime, default=now)
    is_current = Column(Boolean, default=False)

    dataset = relationship("Dataset", back_populates="versions")

class Transformation(Base):
    __tablename__ = "transformations"
    id = Column(String, primary_key=True, default=gen_uuid)
    dataset_id = Column(String, ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True)
    version_id = Column(String, ForeignKey("dataset_versions.id", ondelete="SET NULL"), nullable=True)
    operation = Column(String, nullable=False)  # e.g., remove_duplicates, fill_missing, rename_column
    params = Column(JSON, nullable=True)
    before_stats = Column(JSON, nullable=True)
    after_stats = Column(JSON, nullable=True)
    preview = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=now)
    undone = Column(Boolean, default=False)

    dataset = relationship("Dataset", back_populates="transformations")

class CleaningRecipe(Base):
    __tablename__ = "cleaning_recipes"
    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False)
    dataset_id = Column(String, ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True)
    operations = Column(JSON, nullable=False)  # list of {operation, params}
    created_at = Column(DateTime, default=now)

    user = relationship("User")

class Metric(Base):
    __tablename__ = "metrics"
    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    dataset_id = Column(String, ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    sql_expression = Column(Text, nullable=False)  # e.g. SUM(revenue) - SUM(refund)
    dimensions = Column(JSON, nullable=True)  # list of dimension columns
    time_grain = Column(String, nullable=True)  # daily, monthly etc
    filters = Column(JSON, nullable=True)
    created_by = Column(String, nullable=True)
    version = Column(Integer, default=1)
    created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now, onupdate=now)

    dataset = relationship("Dataset", back_populates="metrics")
    user = relationship("User")

class Monitor(Base):
    __tablename__ = "monitors"
    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    dataset_id = Column(String, ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True)
    metric_id = Column(String, ForeignKey("metrics.id", ondelete="CASCADE"), nullable=False, index=True)
    comparison = Column(String, default="previous_period")  # previous_period
    threshold_percent = Column(Float, default=10.0)  # e.g. 10% decrease
    frequency = Column(String, default="daily")  # daily/weekly
    status = Column(String, default="healthy")  # healthy/alert
    last_value = Column(Float, nullable=True)
    last_previous_value = Column(Float, nullable=True)
    last_change_percent = Column(Float, nullable=True)
    last_checked_at = Column(DateTime, nullable=True)
    period_start = Column(DateTime, nullable=True)
    period_end = Column(DateTime, nullable=True)
    previous_period_start = Column(DateTime, nullable=True)
    previous_period_end = Column(DateTime, nullable=True)
    time_column = Column(String, nullable=True)
    dataset_version = Column(String, nullable=True)
    created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now, onupdate=now)
    # Scheduling & alert fields
    check_interval_hours = Column(Integer, default=24)
    last_status = Column(String, nullable=True)
    alert_sent_at = Column(DateTime, nullable=True)
    alert_count = Column(Integer, default=0)
    notify_email = Column(String, nullable=True)
    notify_slack_webhook = Column(String, nullable=True)
    notify_on_recovery = Column(Boolean, default=True)

    dataset = relationship("Dataset", back_populates="monitors")
    metric = relationship("Metric")
    user = relationship("User")

class ShareToken(Base):
    __tablename__ = "share_tokens"
    id = Column(String, primary_key=True, default=gen_uuid)
    resource_type = Column(String, nullable=False)  # report | analysis
    resource_id = Column(String, nullable=False, index=True)
    token = Column(String, unique=True, index=True, nullable=False)
    created_by = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role = Column(String, default="viewer")
    expires_at = Column(DateTime, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now)
    view_count = Column(Integer, default=0)

    creator = relationship("User")

class MonitorAlertLog(Base):
    __tablename__ = "monitor_alert_logs"
    id = Column(String, primary_key=True, default=gen_uuid)
    monitor_id = Column(String, ForeignKey("monitors.id", ondelete="CASCADE"), nullable=False, index=True)
    dataset_id = Column(String, ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    checked_at = Column(DateTime, default=now)
    status = Column(String, nullable=False)  # healthy | alert | error | recovery
    metric_value = Column(Float, nullable=True)
    threshold_value = Column(Float, nullable=True)
    alert_sent = Column(Boolean, default=False)
    alert_channels = Column(JSON, nullable=True)  # ["email","slack"]
    error_message = Column(Text, nullable=True)

# Extend Dataset relationships
Dataset.versions = relationship("DatasetVersion", back_populates="dataset", cascade="all, delete-orphan", order_by="DatasetVersion.version_number")
Dataset.transformations = relationship("Transformation", back_populates="dataset", cascade="all, delete-orphan", order_by="Transformation.created_at")
Dataset.metrics = relationship("Metric", back_populates="dataset", cascade="all, delete-orphan")
Dataset.monitors = relationship("Monitor", back_populates="dataset", cascade="all, delete-orphan")
