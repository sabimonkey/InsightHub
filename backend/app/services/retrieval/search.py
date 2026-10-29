import re
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.extraction import ContentChunk, ExtractedDocument
from app.models.retrieval import EmbeddingProfile
from app.models.source_item import SourceItem
from app.services.retrieval.constants import EMBEDDING_DIMENSIONS
from app.services.system_scope import AUTOMATION_TEST_SCOPE, creation_scope_from_settings
from app.services.retrieval.coverage import allocate_coverage, coverage_slots, representative_utility, select_fallback_candidates
from app.services.retrieval.embedding import provider_from_settings
from sqlalchemy import select


def contains_cjk(value: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", value or ""))


class SearchService:
    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()

    def search(self, query: str, filters: dict | None = None, mode: str = "hybrid", limit: int | None = None) -> dict:
        filters = self._canonical_filters(filters or {})
        limit = limit or self.settings.hybrid_top_k
        profile = self.session.scalar(select(EmbeddingProfile).where(EmbeddingProfile.is_active.is_(True)))
        provider = provider_from_settings(self.settings)
        profile_ok = profile is not None and profile.dimensions == EMBEDDING_DIMENSIONS and self.settings.embedding_dimensions == EMBEDDING_DIMENSIONS
        semantic = provider is not None and profile_ok and mode != "keyword"
        lexical_hits = self._lexical(query, filters, self.settings.lexical_top_k)
        vector_hits = self._vector(query, filters, self.settings.vector_top_k) if semantic else []
        fused = self._rrf(lexical_hits, vector_hits)
        diversified = self._diversify(fused, limit)
        results = [self._present(item) for item in diversified]
        return {
            "mode": "hybrid" if semantic and mode != "keyword" else "keyword",
            "semantic_available": semantic or (profile_ok and provider is not None),
            "results": results,
        }

    def cover(self, query: str, filters: dict | None = None) -> dict:
        filters = self._canonical_filters(filters or {})
        eligible = self._scope_sources(filters)
        limit = max(1, self.settings.ask_max_coverage_sources)
        selected = eligible[:limit]
        raw_groups: list[list[dict]] = []
        missing: list[dict] = []
        fallback_used = False
        owners: list[dict] = []
        for source in selected:
            representatives = self._representatives(query, filters, source["id"])
            if not representatives:
                missing.append(source)
                continue
            raw_groups.append(representatives)
            owners.append(source)
        filtered = select_fallback_candidates(raw_groups, maximum=self.settings.max_chunks_per_source)
        if len(filtered) < len(owners):
            kept = {str(item.get("chunk_id")) for group in filtered for item in group}
            for source, group in zip(owners, raw_groups, strict=True):
                if not any(str(item.get("chunk_id")) in kept for item in group):
                    missing.append(source)
        groups: list[list[dict]] = []
        for representatives in filtered:
            presented = []
            for item in representatives:
                row = self._present(item)
                row["retrieval_reason"] = item.get("retrieval_reason") or "RELEVANCE"
                if item.get("distance") is not None:
                    row["distance"] = item["distance"]
                if row["retrieval_reason"] == "COVERAGE_FALLBACK":
                    fallback_used = True
                presented.append(row)
            if presented:
                groups.append(presented)
        slots = coverage_slots(len(groups), slot_budget=self.settings.ask_coverage_slots, per_source_cap=self.settings.max_chunks_per_source)
        hits = allocate_coverage(groups, slots=slots, minimum=1, maximum=self.settings.max_chunks_per_source)
        counts: dict[str, int] = {}
        reasons: dict[str, str] = {}
        for hit in hits:
            source_id = str(hit.get("source_id") or "")
            counts[source_id] = counts.get(source_id, 0) + 1
            reason = str(hit.get("retrieval_reason") or "RELEVANCE")
            if reason == "COVERAGE_FALLBACK" or source_id not in reasons:
                reasons[source_id] = reason
        retrieved_ids = [source_id for source_id in counts if source_id]
        limited = len(eligible) > limit
        missing_ids = [str(item["id"]) for item in missing]
        complete = not limited and not missing_ids and len(retrieved_ids) == len(eligible)
        return {
            "hits": hits,
            "eligible_source_count": len(eligible),
            "retrieved_source_count": len(retrieved_ids),
            "retrieved_source_ids": retrieved_ids,
            "missing_source_ids": missing_ids,
            "missing_titles": [str(item.get("title") or "Untitled Source") for item in missing],
            "coverage_complete": complete,
            "coverage_limited": limited,
            "coverage_limit": limit,
            "coverage_fallback_used": fallback_used,
            "chunks_per_source": counts,
            "retrieval_reasons": reasons,
        }

    def _scope_sources(self, filters: dict) -> list[dict]:
        where, params = self._filters(filters)
        rows = self.session.execute(
            text(
                f"""
                SELECT s.id,
                       COALESCE(NULLIF(s.display_name, ''), 'Untitled Source') AS title,
                       COALESCE(s.canonical_url, s.original_url) AS url,
                       s.privacy_level,
                       s.created_at,
                       (SELECT MAX(i.collected_at) FROM ingestion_records i WHERE i.source_item_id = s.id) AS collected_at
                FROM source_items s
                WHERE {self._scope_sql()}
                {where}
                ORDER BY collected_at DESC NULLS LAST, s.created_at DESC
                """
            ),
            params,
        ).mappings().all()
        return [dict(row) for row in rows]

    def _representatives(self, query: str, filters: dict, source_id) -> list[dict]:
        scoped = {**filters, "source_id": source_id}
        limit = max(1, self.settings.max_chunks_per_source)
        lexical = self._lexical(query, scoped, self.settings.lexical_top_k)
        vector = self._vector(query, scoped, self.settings.vector_top_k)
        if lexical or vector:
            fused = self._rrf(lexical, vector)[:limit]
            for item in fused:
                item["retrieval_reason"] = "RELEVANCE"
            return fused
        loose = self._vector(query, scoped, max(limit * 4, 16), apply_threshold=False)
        if loose:
            return self._score_loose(loose, limit)
        rows = self.session.execute(
            text(
                """
                SELECT c.id AS chunk_id, length(c.content) AS score
                FROM content_chunks c
                JOIN extracted_documents d ON d.id = c.extracted_document_id
                JOIN extraction_runs r ON r.id = d.extraction_run_id
                JOIN source_items s ON s.id = d.source_item_id
                WHERE r.is_current AND r.status IN ('SUCCEEDED', 'PARTIAL')
                  AND s.id = :rep_source_id
                  AND length(btrim(c.content)) > 0
                ORDER BY length(c.content) DESC, c.sequence ASC
                LIMIT :limit
                """
            ),
            {"rep_source_id": source_id, "limit": max(limit * 2, limit)},
        ).mappings().all()
        return self._with_text_keys(
            [
                {
                    "chunk_id": row["chunk_id"],
                    "methods": ["COVERAGE_FALLBACK"],
                    "score": float(row["score"] or 0),
                    "retrieval_reason": "COVERAGE_FALLBACK",
                }
                for row in rows
            ]
        )

    def _score_loose(self, loose: list[dict], limit: int) -> list[dict]:
        keyed = self._with_text_keys(loose)
        ranked = []
        for item in keyed:
            distance = float(item.get("distance") or 1.0)
            reason = "RELEVANCE" if distance <= self.settings.vector_max_distance else "COVERAGE_FALLBACK"
            text_length = int(item.get("text_length") or 0)
            if reason == "COVERAGE_FALLBACK" and text_length < 24:
                continue
            scored = dict(item)
            if reason == "COVERAGE_FALLBACK":
                scored["methods"] = list(dict.fromkeys([*item["methods"], "COVERAGE_FALLBACK"]))
                scored["score"] = representative_utility(distance, text_length)
            else:
                scored["score"] = 1.0 / (1.0 + distance)
            scored["retrieval_reason"] = reason
            scored["distance"] = distance
            ranked.append(scored)
        ranked.sort(key=lambda item: float(item["score"]), reverse=True)
        return ranked[: max(limit * 2, limit)]

    def _with_text_keys(self, items: list[dict]) -> list[dict]:
        ids = [item["chunk_id"] for item in items]
        chunks = {
            chunk.id: chunk
            for chunk in self.session.scalars(select(ContentChunk).where(ContentChunk.id.in_(ids)))
        } if ids else {}
        keyed = []
        for item in items:
            chunk = chunks.get(item["chunk_id"])
            text = "" if chunk is None else " ".join(chunk.content.split())
            keyed.append({**item, "text_key": text.casefold(), "text_length": len(text)})
        return keyed

    def _lexical(self, query: str, filters: dict, limit: int) -> list[dict]:
        if not query.strip():
            return []
        cjk = contains_cjk(query)
        where, params = self._filters(filters)
        params.update({"q": query, "limit": limit, "min_sim": self.settings.trigram_min_similarity})
        method_sql = """
            SELECT c.id AS chunk_id, ts_rank_cd(c.search_vector, plainto_tsquery('simple', :q)) AS score, 'FTS' AS method
            FROM content_chunks c
            JOIN extracted_documents d ON d.id = c.extracted_document_id
            JOIN extraction_runs r ON r.id = d.extraction_run_id
            JOIN source_items s ON s.id = d.source_item_id
            WHERE r.is_current AND r.status IN ('SUCCEEDED', 'PARTIAL')
              AND c.search_vector @@ plainto_tsquery('simple', :q)
        """
        trgm_sql = """
            SELECT c.id AS chunk_id, word_similarity(:q, c.content) AS score, 'TRIGRAM' AS method
            FROM content_chunks c
            JOIN extracted_documents d ON d.id = c.extracted_document_id
            JOIN extraction_runs r ON r.id = d.extraction_run_id
            JOIN source_items s ON s.id = d.source_item_id
            WHERE r.is_current AND r.status IN ('SUCCEEDED', 'PARTIAL')
              AND word_similarity(:q, c.content) >= :min_sim
        """
        parts = []
        if not cjk:
            parts.append(method_sql + where)
        parts.append(trgm_sql + where)
        if cjk:
            parts.append(method_sql + where)
        sql = " UNION ALL ".join(parts) + " ORDER BY score DESC LIMIT :limit"
        rows = self.session.execute(text(sql), params).mappings().all()
        merged: dict[str, dict] = {}
        for row in rows:
            key = str(row["chunk_id"])
            item = merged.setdefault(key, {"chunk_id": row["chunk_id"], "methods": [], "lexical_score": 0})
            if row["method"] not in item["methods"]:
                item["methods"].append(row["method"])
            item["lexical_score"] = max(item["lexical_score"], float(row["score"] or 0))
        return list(merged.values())

    def _vector(self, query: str, filters: dict, limit: int, *, apply_threshold: bool = True) -> list[dict]:
        provider = provider_from_settings(self.settings)
        profile = self.session.scalar(select(EmbeddingProfile).where(EmbeddingProfile.is_active.is_(True)))
        if provider is None or profile is None or not query.strip():
            return []
        vectors, _tokens = provider.embed_documents([query])
        if not vectors:
            return []
        where, params = self._filters(filters)
        params.update({"profile": profile.id, "limit": limit, "embedding": str(vectors[0])})
        distance_clause = ""
        if apply_threshold:
            params["max_distance"] = self.settings.vector_max_distance
            distance_clause = "AND (e.embedding <=> CAST(:embedding AS vector)) <= :max_distance"
        sql = f"""
            SELECT c.id AS chunk_id, (e.embedding <=> CAST(:embedding AS vector)) AS distance
            FROM chunk_embeddings e
            JOIN content_chunks c ON c.id = e.content_chunk_id
            JOIN extracted_documents d ON d.id = c.extracted_document_id
            JOIN extraction_runs r ON r.id = d.extraction_run_id
            JOIN source_items s ON s.id = d.source_item_id
            WHERE e.embedding_profile_id = :profile
              AND r.is_current AND r.status IN ('SUCCEEDED', 'PARTIAL')
              {distance_clause}
              {where}
            ORDER BY distance ASC
            LIMIT :limit
        """
        rows = self.session.execute(text(sql), params).mappings().all()
        return [{"chunk_id": row["chunk_id"], "methods": ["VECTOR"], "distance": float(row["distance"])} for row in rows]

    def _rrf(self, lexical: list[dict], vector: list[dict]) -> list[dict]:
        scores: dict[str, dict] = {}
        for rank, item in enumerate(lexical, start=1):
            key = str(item["chunk_id"])
            row = scores.setdefault(key, {"chunk_id": item["chunk_id"], "methods": [], "score": 0.0})
            row["methods"] = list(dict.fromkeys(row["methods"] + item["methods"]))
            row["score"] += 1 / (self.settings.rrf_k + rank)
        for rank, item in enumerate(vector, start=1):
            key = str(item["chunk_id"])
            row = scores.setdefault(key, {"chunk_id": item["chunk_id"], "methods": [], "score": 0.0})
            row["methods"] = list(dict.fromkeys(row["methods"] + item["methods"]))
            row["score"] += 1 / (self.settings.rrf_k + rank)
        return sorted(scores.values(), key=lambda item: item["score"], reverse=True)

    def _diversify(self, ranked: list[dict], limit: int) -> list[dict]:
        chosen = []
        counts: dict[str, int] = {}
        for item in ranked:
            chunk = self.session.get(ContentChunk, item["chunk_id"])
            document = None if chunk is None else self.session.get(ExtractedDocument, chunk.extracted_document_id)
            source_id = "" if document is None else str(document.source_item_id)
            if counts.get(source_id, 0) >= self.settings.max_chunks_per_source:
                continue
            counts[source_id] = counts.get(source_id, 0) + 1
            chosen.append(item)
            if len(chosen) >= limit:
                break
        return chosen

    def _scope_sql(self) -> str:
        if creation_scope_from_settings(self.settings) == AUTOMATION_TEST_SCOPE:
            return "s.system_scope = 'AUTOMATION_TEST' AND s.deleted_at IS NULL"
        return "(s.system_scope = 'USER' OR s.system_scope IS NULL) AND s.deleted_at IS NULL"

    def _filters(self, filters: dict) -> tuple[str, dict]:
        clauses = [self._scope_sql()]
        params: dict = {}
        scope = filters.get("scope") or "mine"
        if scope == "mine":
            clauses.append("EXISTS (SELECT 1 FROM ingestion_records i WHERE i.source_item_id = s.id AND i.origin = 'USER_COLLECTION' AND i.status = 'STORED')")
        elif scope == "discovered":
            clauses.append("EXISTS (SELECT 1 FROM ingestion_records i WHERE i.source_item_id = s.id AND i.origin = 'SYSTEM_DISCOVERY')")
            clauses.append("NOT EXISTS (SELECT 1 FROM ingestion_records i WHERE i.source_item_id = s.id AND i.origin = 'USER_COLLECTION')")
        if filters.get("source_type"):
            clauses.append("s.source_type = :source_type")
            params["source_type"] = filters["source_type"]
        if filters.get("privacy_level"):
            clauses.append("s.privacy_level = :privacy_level")
            params["privacy_level"] = filters["privacy_level"]
        if filters.get("category"):
            clauses.append(
                """EXISTS (
                    SELECT 1 FROM source_category_assignments a
                    JOIN categories cat ON cat.id = a.category_id
                    WHERE a.source_item_id = s.id AND a.status = 'ACTIVE' AND cat.is_active AND cat.slug = :category
                )"""
            )
            params["category"] = filters["category"]
        if filters.get("topic_id"):
            clauses.append("EXISTS (SELECT 1 FROM source_topic_assignments t WHERE t.source_item_id = s.id AND t.topic_id = :topic_id AND t.status = 'ACTIVE')")
            params["topic_id"] = uuid.UUID(str(filters["topic_id"]))
        if filters.get("entity_id"):
            clauses.append("EXISTS (SELECT 1 FROM entity_mentions m WHERE m.source_item_id = s.id AND m.entity_id = :entity_id)")
            params["entity_id"] = uuid.UUID(str(filters["entity_id"]))
        if filters.get("tag"):
            clauses.append(
                """EXISTS (
                    SELECT 1 FROM source_tags st JOIN tags tag ON tag.id = st.tag_id
                    WHERE st.source_item_id = s.id AND tag.normalized_name = :tag
                )"""
            )
            params["tag"] = str(filters["tag"]).casefold()
        if filters.get("collected_from"):
            clauses.append("EXISTS (SELECT 1 FROM ingestion_records i WHERE i.source_item_id = s.id AND i.origin = 'USER_COLLECTION' AND i.collected_at >= :collected_from)")
            params["collected_from"] = filters["collected_from"]
        if filters.get("collected_to"):
            clauses.append("EXISTS (SELECT 1 FROM ingestion_records i WHERE i.source_item_id = s.id AND i.origin = 'USER_COLLECTION' AND i.collected_at <= :collected_to)")
            params["collected_to"] = filters["collected_to"]
        if filters.get("source_id"):
            clauses.append("s.id = :only_source_id")
            params["only_source_id"] = uuid.UUID(str(filters["source_id"]))
        if filters.get("source_ids"):
            names = []
            for index, source_id in enumerate(filters["source_ids"]):
                key = f"source_id_{index}"
                names.append(f":{key}")
                params[key] = uuid.UUID(str(source_id))
            if names:
                clauses.append(f"s.id IN ({', '.join(names)})")
        if filters.get("eligible_privacy"):
            names = []
            for index, level in enumerate(filters["eligible_privacy"]):
                key = f"priv_{index}"
                names.append(f":{key}")
                params[key] = level
            clauses.append(f"s.privacy_level IN ({', '.join(names)})")
        sql = "".join(f" AND {clause}" for clause in clauses)
        return sql, params

    def _canonical_filters(self, filters: dict) -> dict:
        resolved = dict(filters)
        if resolved.get("topic_id"):
            topic_id = uuid.UUID(str(resolved["topic_id"]))
            row = self.session.execute(text("SELECT merged_into_topic_id FROM topics WHERE id = :id"), {"id": topic_id}).first()
            seen = {topic_id}
            while row is not None and row[0] is not None and row[0] not in seen:
                topic_id = row[0]
                seen.add(topic_id)
                row = self.session.execute(text("SELECT merged_into_topic_id FROM topics WHERE id = :id"), {"id": topic_id}).first()
            resolved["topic_id"] = topic_id
        if resolved.get("entity_id"):
            entity_id = uuid.UUID(str(resolved["entity_id"]))
            row = self.session.execute(text("SELECT merged_into_entity_id FROM entities WHERE id = :id"), {"id": entity_id}).first()
            seen = {entity_id}
            while row is not None and row[0] is not None and row[0] not in seen:
                entity_id = row[0]
                seen.add(entity_id)
                row = self.session.execute(text("SELECT merged_into_entity_id FROM entities WHERE id = :id"), {"id": entity_id}).first()
            resolved["entity_id"] = entity_id
        return resolved

    def _present(self, item: dict) -> dict:
        chunk = self.session.get(ContentChunk, item["chunk_id"])
        document = None if chunk is None else self.session.get(ExtractedDocument, chunk.extracted_document_id)
        source = None if document is None else self.session.get(SourceItem, document.source_item_id)
        return {
            "source_id": None if source is None else source.id,
            "chunk_id": None if chunk is None else chunk.id,
            "source_title": None if source is None else (source.display_name or "Untitled Source"),
            "source_type": None if source is None else source.source_type,
            "snippet": "" if chunk is None else chunk.content[:180],
            "score": item["score"],
            "retrieval_methods": item["methods"],
            "heading_path": None if chunk is None else chunk.heading_path,
            "page_number": None if chunk is None else (chunk.metadata_json or {}).get("page_number"),
            "original_url": None if source is None else source.original_url,
            "canonical_url": None if source is None else source.canonical_url,
            "original_filename": self._filename(source.id) if source is not None else None,
            "privacy_level": None if source is None else source.privacy_level,
            "category": self._labels(source.id, "category") if source is not None else [],
            "topics": self._labels(source.id, "topic") if source is not None else [],
            "entities": self._labels(source.id, "entity") if source is not None else [],
            "collection": self._collection(source.id) if source is not None else None,
        }

    def _filename(self, source_id: uuid.UUID) -> str | None:
        row = self.session.execute(text("SELECT original_filename FROM source_assets WHERE source_item_id = :id"), {"id": source_id}).first()
        return None if row is None else row[0]

    def _labels(self, source_id: uuid.UUID, kind: str) -> list[str]:
        if kind == "category":
            sql = """
                SELECT cat.name FROM source_category_assignments a
                JOIN categories cat ON cat.id = a.category_id
                WHERE a.source_item_id = :id AND a.status = 'ACTIVE' AND cat.is_active
            """
        elif kind == "topic":
            sql = """
                SELECT t.name FROM source_topic_assignments a
                JOIN topics t ON t.id = a.topic_id
                WHERE a.source_item_id = :id AND a.status = 'ACTIVE' AND t.merged_into_topic_id IS NULL
            """
        else:
            sql = """
                SELECT DISTINCT e.name FROM entity_mentions m
                JOIN entities e ON e.id = m.entity_id
                WHERE m.source_item_id = :id AND e.merged_into_entity_id IS NULL
            """
        return [row[0] for row in self.session.execute(text(sql), {"id": source_id})]

    def _collection(self, source_id: uuid.UUID) -> dict:
        row = self.session.execute(
            text(
                """
                SELECT MIN(collected_at), MAX(collected_at), COUNT(*)
                FROM ingestion_records
                WHERE source_item_id = :id AND origin = 'USER_COLLECTION' AND status = 'STORED'
                """
            ),
            {"id": source_id},
        ).one()
        return {"first_collected_at": row[0], "last_collected_at": row[1], "collection_count": row[2]}
