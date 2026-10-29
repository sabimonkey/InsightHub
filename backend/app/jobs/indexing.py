"""RQ jobs for embedding and ask."""

import uuid

from redis import Redis
from rq import Queue

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.services.retrieval.ask import AskService
from app.services.retrieval.indexing import IndexingService


def execute_index_source(source_id: str) -> str:
    session = get_sessionmaker()()
    try:
        IndexingService(session, get_settings()).index_source(uuid.UUID(source_id))
        return source_id
    finally:
        session.close()


def execute_backfill() -> str:
    session = get_sessionmaker()()
    try:
        run = IndexingService(session, get_settings()).backfill()
        return "" if run is None else str(run.id)
    finally:
        session.close()


def execute_ask_turn(turn_id: str) -> str:
    session = get_sessionmaker()()
    try:
        AskService(session, get_settings(), inline=True).execute(uuid.UUID(turn_id))
        return turn_id
    finally:
        session.close()


def enqueue_index_source(source_id: str) -> None:
    _queue().enqueue(execute_index_source, source_id)


def enqueue_backfill() -> None:
    _queue().enqueue(execute_backfill)


def enqueue_ask_turn(turn_id: str) -> None:
    _queue().enqueue(execute_ask_turn, turn_id)


def _queue() -> Queue:
    settings = get_settings()
    return Queue("insighthub", connection=Redis.from_url(settings.redis_url))
