import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db, get_sessionmaker
from app.jobs.indexing import enqueue_ask_turn, enqueue_backfill, enqueue_index_source
from app.models.retrieval import AskSession, AskTurn, EmbeddingProfile, EmbeddingProviderConfig
from app.services.retrieval.ask import AskService
from app.services.retrieval.ask_events import iter_sse_events
from app.services.retrieval.ask_turn_view import build_ask_turn_view
from app.services.retrieval.embedding import provider_from_settings
from app.services.retrieval.indexing import IndexingService
from app.services.retrieval.search import SearchService
from sqlalchemy import select

router = APIRouter(prefix="/api", tags=["retrieval"])


class SearchRequest(BaseModel):
    query: str
    filters: dict = {}
    mode: str = "hybrid"
    limit: int | None = None


class AskSessionRequest(BaseModel):
    title: str | None = None


class AskTurnRequest(BaseModel):
    question: str
    filters: dict = {}
    provider_type: str | None = None


def _session(db: Session = Depends(get_db)) -> Session:
    return db


@router.get("/embedding/providers")
def embedding_providers(db: Session = Depends(_session)) -> dict:
    provider = provider_from_settings(get_settings())
    rows = list(db.scalars(select(EmbeddingProviderConfig)))
    if not rows and provider is not None:
        IndexingService(db).ensure_profile()
        db.commit()
        rows = list(db.scalars(select(EmbeddingProviderConfig)))
    return {
        "providers": [
            {
                "id": row.id,
                "name": row.name,
                "provider_type": row.provider_type,
                "model": row.model,
                "configured": True,
                "is_local": row.is_local,
            }
            for row in rows
        ]
    }


@router.get("/embedding/profiles")
def embedding_profiles(db: Session = Depends(_session)) -> dict:
    rows = list(db.scalars(select(EmbeddingProfile)))
    return {
        "profiles": [
            {"id": row.id, "model": row.model, "dimensions": row.dimensions, "is_active": row.is_active}
            for row in rows
        ]
    }


@router.post("/index/sources/{source_id}")
def index_source(source_id: uuid.UUID) -> dict:
    settings = get_settings()
    if settings.ask_inline:
        session = get_db_session_direct()
        try:
            run = IndexingService(session, settings).index_source(source_id)
        finally:
            session.close()
        return {"status": None if run is None else run.status, "run_id": None if run is None else run.id}
    enqueue_index_source(str(source_id))
    return {"status": "PENDING", "run_id": None}


@router.post("/index/backfill")
def index_backfill() -> dict:
    settings = get_settings()
    if settings.ask_inline:
        session = get_db_session_direct()
        try:
            run = IndexingService(session, settings).backfill()
        finally:
            session.close()
        return {"status": None if run is None else run.status, "run_id": None if run is None else run.id}
    enqueue_backfill()
    return {"status": "PENDING", "run_id": None}


@router.get("/index/status")
def index_status(db: Session = Depends(_session)) -> dict:
    return IndexingService(db).status()


@router.post("/search")
def search(body: SearchRequest, db: Session = Depends(_session)) -> dict:
    return SearchService(db).search(body.query, body.filters, body.mode, body.limit)


@router.post("/ask/sessions")
def create_ask_session(body: AskSessionRequest, db: Session = Depends(_session)) -> dict:
    row = AskService(db, enqueue=enqueue_ask_turn).create_session(body.title)
    return {"id": row.id, "title": row.title, "created_at": row.created_at}


@router.get("/ask/sessions")
def list_ask_sessions(db: Session = Depends(_session)) -> dict:
    from app.services.system_scope import api_visibility_filter

    rows = list(
        db.scalars(
            select(AskSession)
            .where(api_visibility_filter(AskSession.system_scope))
            .where(AskSession.deleted_at.is_(None))
            .order_by(AskSession.updated_at.desc())
        )
    )
    return {"sessions": [{"id": row.id, "title": row.title, "updated_at": row.updated_at} for row in rows]}


@router.get("/ask/sessions/{session_id}")
def get_ask_session(session_id: uuid.UUID, db: Session = Depends(_session)) -> dict:
    from app.services.system_scope import scope_visible_for_api

    row = db.get(AskSession, session_id)
    if row is None or row.deleted_at is not None or not scope_visible_for_api(row.system_scope):
        return {"session": None, "turns": []}
    turns = list(db.scalars(select(AskTurn).where(AskTurn.session_id == session_id).order_by(AskTurn.created_at)))
    return {"session": {"id": row.id, "title": row.title}, "turns": [_turn(db, turn) for turn in turns]}


@router.delete("/ask/sessions/{session_id}")
def delete_ask_session(session_id: uuid.UUID, db: Session = Depends(_session)) -> dict:
    service = AskService(db)
    try:
        service.soft_delete_session(session_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="ASK_SESSION_NOT_FOUND") from exc
    return {"ok": True}


@router.post("/ask/sessions/clear")
def clear_ask_sessions(db: Session = Depends(_session)) -> dict:
    count = AskService(db).clear_sessions()
    return {"ok": True, "deleted_count": count}


@router.post("/ask/sessions/{session_id}/turns")
def create_ask_turn(session_id: uuid.UUID, body: AskTurnRequest, db: Session = Depends(_session)) -> dict:
    settings = get_settings()
    from app.services.jobs.runtime_guard import WorkerNotAvailableError, ensure_async_worker

    try:
        ensure_async_worker(settings=settings, inline=settings.ask_inline)
    except WorkerNotAvailableError as exc:
        raise HTTPException(status_code=503, detail={"code": exc.code, "message": exc.message}) from exc
    service = AskService(db, settings, inline=settings.ask_inline, enqueue=enqueue_ask_turn)
    turn = service.start_turn(session_id, body.question, body.filters, body.provider_type)
    return _turn(db, turn)


@router.get("/ask/turns/{turn_id}")
def get_ask_turn(turn_id: uuid.UUID, db: Session = Depends(_session)) -> dict:
    turn = db.get(AskTurn, turn_id)
    if turn is None:
        return {"turn": None}
    from app.services.system_scope import scope_visible_for_api

    session_row = db.get(AskSession, turn.session_id)
    if session_row is None or not scope_visible_for_api(session_row.system_scope):
        raise HTTPException(status_code=404, detail="ASK_TURN_NOT_FOUND")
    return _turn(db, turn)


@router.get("/ask/turns/{turn_id}/events")
def ask_turn_events(turn_id: uuid.UUID, request: Request, db: Session = Depends(_session)) -> StreamingResponse:
    turn = db.get(AskTurn, turn_id)
    if turn is None:
        raise HTTPException(status_code=404, detail="ASK_TURN_NOT_FOUND")
    from app.services.system_scope import scope_visible_for_api

    session_row = db.get(AskSession, turn.session_id)
    if session_row is None or not scope_visible_for_api(session_row.system_scope):
        raise HTTPException(status_code=404, detail="ASK_TURN_NOT_FOUND")
    settings = get_settings()
    last_event_id = request.headers.get("Last-Event-ID")

    def event_stream():
        session_factory = get_sessionmaker()
        inner = session_factory()

        def status() -> str:
            row = inner.get(AskTurn, turn_id)
            return row.status if row is not None else "FAILED"

        saw_terminal_event = False
        try:
            for chunk in iter_sse_events(
                turn_id,
                last_event_id=last_event_id,
                settings=settings,
                get_turn_status=status,
            ):
                if chunk.startswith("event: final\n") or chunk.startswith("event: error\n"):
                    saw_terminal_event = True
                yield chunk
            if not saw_terminal_event:
                row = inner.get(AskTurn, turn_id)
                if row is not None and row.status in {"SUCCEEDED", "PARTIAL", "NO_EVIDENCE", "FAILED"}:
                    if row.status == "FAILED":
                        yield _format_terminal_sse(
                            "error",
                            {"code": row.error_code or "FAILED", "message": row.error_message or row.answer_markdown},
                        )
                    else:
                        from app.services.retrieval.ask_turn_view import build_ask_final_sse_payload

                        yield _format_terminal_sse("final", build_ask_final_sse_payload(inner, row))
        finally:
            inner.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


def _format_terminal_sse(event: str, payload: dict) -> str:
    import json

    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _turn(db: Session, turn: AskTurn) -> dict:
    return build_ask_turn_view(db, turn)


def get_db_session_direct() -> Session:
    return get_sessionmaker()()
