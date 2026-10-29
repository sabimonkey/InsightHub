import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LLMProviderCredential(Base):
    """Encrypted API key storage; plaintext never persisted."""

    __tablename__ = "llm_provider_credentials"

    provider_type: Mapped[str] = mapped_column(String(64), primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class LLMProviderConfig(Base):
    __tablename__ = "llm_provider_configs"
    __table_args__ = (Index("uq_llm_provider_configs_type", "provider_type", unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(64), nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(256), nullable=False)
    is_local: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    api_key_env: Mapped[str | None] = mapped_column(String(128), nullable=True)
    capabilities_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class LLMModelDeployment(Base):
    __tablename__ = "llm_model_deployments"
    __table_args__ = (Index("ix_llm_model_deployments_provider", "provider_config_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_config_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("llm_provider_configs.id", ondelete="CASCADE"), nullable=False)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    model_id: Mapped[str] = mapped_column(String(512), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    capabilities_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class LLMWorkflowRoute(Base):
    """One model deployment per workflow. The secret stays in the environment."""

    __tablename__ = "llm_workflow_routes"

    workflow: Mapped[str] = mapped_column(String(32), primary_key=True)
    deployment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("llm_model_deployments.id", ondelete="RESTRICT"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (
        Index("ix_analysis_runs_source_item_id", "source_item_id"),
        Index("uq_analysis_runs_current", "source_item_id", unique=True, postgresql_where=text("is_current")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("source_items.id", ondelete="RESTRICT"), nullable=False)
    extracted_document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("extracted_documents.id", ondelete="RESTRICT"), nullable=False)
    provider_config_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("llm_provider_configs.id", ondelete="RESTRICT"), nullable=True)
    provider_type: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(256), nullable=False)
    prompt_name: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    analysis_strategy: Mapped[str | None] = mapped_column(String(32), nullable=True)
    input_extraction_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("analysis_runs.id", ondelete="RESTRICT"), nullable=False, unique=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    raw_structured_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Claim(Base):
    __tablename__ = "claims"
    __table_args__ = (Index("ix_claims_analysis_result_id", "analysis_result_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_result_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("analysis_results.id", ondelete="RESTRICT"), nullable=False)
    claim_type: Mapped[str] = mapped_column(String(32), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    importance: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (Index("ix_evidence_claim_id", "claim_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False)
    content_chunk_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("content_chunks.id", ondelete="RESTRICT"), nullable=False)
    quote_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence_strength: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
