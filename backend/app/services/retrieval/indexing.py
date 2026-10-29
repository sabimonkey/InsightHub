import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.extraction import ContentChunk, ExtractedDocument, ExtractionRun
from app.models.retrieval import ChunkEmbedding, EmbeddingProfile, EmbeddingProviderConfig, IndexingRun
from app.models.source_item import SourceItem
from app.services.retrieval.constants import EMBEDDING_DIMENSIONS
from app.services.retrieval.embedding import EmbeddingError, EmbeddingProvider, provider_from_settings


class IndexingService:
    def __init__(self, session: Session, settings: Settings | None = None, provider: EmbeddingProvider | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.provider = provider if provider is not None else provider_from_settings(self.settings)

    def configured(self) -> bool:
        return self.provider is not None and self.settings.embedding_dimensions == EMBEDDING_DIMENSIONS

    def ensure_profile(self) -> EmbeddingProfile | None:
        if not self.configured() or self.provider is None:
            return None
        provider = self.provider
        row = self.session.scalar(select(EmbeddingProviderConfig).where(EmbeddingProviderConfig.provider_type == provider.provider_type))
        now = datetime.now(timezone.utc)
        env_name = None if provider.is_local or provider.provider_type == "FAKE" else f"{provider.provider_type}_EMBEDDING_API_KEY"
        if row is None:
            row = EmbeddingProviderConfig(
                id=uuid.uuid4(),
                name=provider.provider_type,
                provider_type=provider.provider_type,
                base_url=getattr(provider, "base_url", ""),
                model=provider.model,
                dimensions=EMBEDDING_DIMENSIONS,
                is_local=provider.is_local,
                api_key_env=env_name,
                enabled=True,
                created_at=now,
                updated_at=now,
            )
            self.session.add(row)
            self.session.flush()
        profile = self.session.scalar(select(EmbeddingProfile).where(EmbeddingProfile.is_active.is_(True)))
        if profile is not None:
            config = self.session.get(EmbeddingProviderConfig, profile.provider_config_id)
            mismatched = profile.dimensions != EMBEDDING_DIMENSIONS or profile.model != provider.model or config is None or config.provider_type != provider.provider_type
            if mismatched and provider.provider_type == "FAKE" and config is not None and config.provider_type != "FAKE":
                return self._inactive_profile(row, provider.model, now)
            if mismatched:
                profile.is_active = False
                self.session.flush()
                profile = None
        if profile is None:
            profile = EmbeddingProfile(
                id=uuid.uuid4(),
                provider_config_id=row.id,
                model=provider.model,
                dimensions=EMBEDDING_DIMENSIONS,
                is_active=True,
                created_at=now,
            )
            self.session.add(profile)
            self.session.flush()
        return profile

    def _inactive_profile(self, config: EmbeddingProviderConfig, model: str, now: datetime) -> EmbeddingProfile:
        existing = self.session.scalar(
            select(EmbeddingProfile).where(
                EmbeddingProfile.provider_config_id == config.id,
                EmbeddingProfile.model == model,
                EmbeddingProfile.dimensions == EMBEDDING_DIMENSIONS,
                EmbeddingProfile.is_active.is_(False),
            )
        )
        if existing is not None:
            return existing
        created = EmbeddingProfile(
            id=uuid.uuid4(),
            provider_config_id=config.id,
            model=model,
            dimensions=EMBEDDING_DIMENSIONS,
            is_active=False,
            created_at=now,
        )
        self.session.add(created)
        self.session.flush()
        return created

    def index_source(self, source_id: uuid.UUID) -> IndexingRun | None:
        profile = self.ensure_profile()
        if profile is None:
            return None
        chunks = self._current_chunks(source_id)
        return self._index(profile, chunks, source_id)

    def backfill(self) -> IndexingRun | None:
        profile = self.ensure_profile()
        if profile is None:
            return None
        chunks = self._current_chunks(None)
        missing = []
        for chunk in chunks:
            digest = hashlib.sha256(chunk.content.encode("utf-8")).hexdigest()
            existing = self.session.scalar(
                select(ChunkEmbedding).where(ChunkEmbedding.content_chunk_id == chunk.id, ChunkEmbedding.embedding_profile_id == profile.id, ChunkEmbedding.content_hash == digest)
            )
            if existing is None:
                missing.append(chunk)
        return self._index(profile, missing, None)

    def status(self) -> dict:
        profile = self.session.scalar(select(EmbeddingProfile).where(EmbeddingProfile.is_active.is_(True)))
        total = len(self._current_chunks(None))
        indexed = 0
        if profile is not None:
            indexed = len(list(self.session.scalars(select(ChunkEmbedding).where(ChunkEmbedding.embedding_profile_id == profile.id))))
        latest = self.session.scalar(select(IndexingRun).order_by(IndexingRun.created_at.desc()))
        return {
            "configured": self.configured(),
            "semantic_available": profile is not None,
            "profile_id": None if profile is None else profile.id,
            "dimensions": EMBEDDING_DIMENSIONS,
            "indexed_chunks": indexed,
            "total_current_chunks": total,
            "backfill_status": None if latest is None else latest.status,
        }

    def _index(self, profile: EmbeddingProfile, chunks: list[ContentChunk], source_id: uuid.UUID | None) -> IndexingRun:
        now = datetime.now(timezone.utc)
        run = IndexingRun(
            id=uuid.uuid4(),
            source_item_id=source_id,
            embedding_profile_id=profile.id,
            status="RUNNING",
            total_chunks=len(chunks),
            processed_chunks=0,
            failed_chunks=0,
            started_at=now,
            created_at=now,
        )
        self.session.add(run)
        self.session.flush()
        provider = self.provider
        batch_size = max(1, self.settings.embedding_batch_size)
        pending: list[ContentChunk] = []
        for chunk in chunks:
            source = self._source_for_chunk(chunk)
            if source is not None and source.privacy_level == "SENSITIVE" and provider is not None and not provider.is_local:
                run.failed_chunks += 1
                run.error_code = "PRIVACY_PROVIDER_NOT_ALLOWED"
                continue
            digest = hashlib.sha256(chunk.content.encode("utf-8")).hexdigest()
            existing = self.session.scalar(
                select(ChunkEmbedding).where(ChunkEmbedding.content_chunk_id == chunk.id, ChunkEmbedding.embedding_profile_id == profile.id, ChunkEmbedding.content_hash == digest)
            )
            if existing is not None:
                run.processed_chunks += 1
                continue
            pending.append(chunk)
            if len(pending) >= batch_size:
                self._flush_batch(profile, pending, run)
                pending = []
        if pending:
            self._flush_batch(profile, pending, run)
        run.status = "PARTIAL" if run.failed_chunks else "SUCCEEDED"
        run.completed_at = datetime.now(timezone.utc)
        self.session.commit()
        return run

    def _flush_batch(self, profile: EmbeddingProfile, chunks: list[ContentChunk], run: IndexingRun) -> None:
        provider = self.provider
        if provider is None:
            return
        try:
            vectors, tokens = provider.embed_documents([chunk.content for chunk in chunks])
        except EmbeddingError as exc:
            run.failed_chunks += len(chunks)
            run.error_code = exc.code
            run.error_message = exc.message
            return
        for chunk, vector in zip(chunks, vectors, strict=False):
            if len(vector) != profile.dimensions or len(vector) != EMBEDDING_DIMENSIONS:
                run.failed_chunks += 1
                run.error_code = "EMBEDDING_DIMENSION_MISMATCH"
                continue
            self.session.add(
                ChunkEmbedding(
                    id=uuid.uuid4(),
                    content_chunk_id=chunk.id,
                    embedding_profile_id=profile.id,
                    provider_type=provider.provider_type,
                    model_name=provider.model,
                    dimensions=len(vector),
                    embedding=vector,
                    content_hash=hashlib.sha256(chunk.content.encode("utf-8")).hexdigest(),
                    input_tokens=tokens,
                    created_at=datetime.now(timezone.utc),
                )
            )
            run.processed_chunks += 1
        self.session.flush()

    def _current_chunks(self, source_id: uuid.UUID | None) -> list[ContentChunk]:
        query = (
            select(ContentChunk)
            .join(ExtractedDocument, ExtractedDocument.id == ContentChunk.extracted_document_id)
            .join(ExtractionRun, ExtractionRun.id == ExtractedDocument.extraction_run_id)
            .where(ExtractionRun.is_current.is_(True), ExtractionRun.status.in_(("SUCCEEDED", "PARTIAL")))
        )
        if source_id is not None:
            query = query.where(ExtractedDocument.source_item_id == source_id)
        return list(self.session.scalars(query.order_by(ContentChunk.sequence)).all())

    def _source_for_chunk(self, chunk: ContentChunk) -> SourceItem | None:
        document = self.session.get(ExtractedDocument, chunk.extracted_document_id)
        if document is None:
            return None
        return self.session.get(SourceItem, document.source_item_id)
