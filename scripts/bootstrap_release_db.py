"""Safely prepare fresh/old schemas before applying the current release schema.

The historical workflow-route migration requires a provider row before it can
make deployment foreign keys non-null. Keep this credential-free seed in the
release layer rather than changing the existing application migration.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings

ROUTE_REVISION = "d1a3c5e70f28"


def _is_at_or_before_route(revision_id: str | None) -> bool:
    if revision_id is None:
        return True
    config = Config(str(BACKEND / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision(ROUTE_REVISION)
    while revision is not None:
        if revision.revision == revision_id:
            return True
        parent = revision.down_revision
        if isinstance(parent, tuple):
            if len(parent) != 1:
                return False
            parent = parent[0]
        revision = script.get_revision(parent) if parent else None
    return False


def _current_revision() -> str | None:
    engine = create_engine(get_settings().database_url)
    try:
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()


def _upgrade(revision: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=BACKEND,
        env=os.environ.copy(),
        check=True,
    )


def _seed_only_if_provider_table_is_empty() -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    capabilities = {
        "supports_json_schema": False,
        "supports_json_object": True,
        "supports_streaming": True,
        "supports_multimodal": True,
        "supports_vision": True,
        "supports_reasoning": True,
        "context_window": 1_000_000,
        "max_output_tokens": 128_000,
        "timeout_seconds": 180,
    }
    try:
        with factory.begin() as session:
            count = session.execute(text("SELECT count(*) FROM llm_provider_configs")).scalar_one()
            if count == 0:
                session.execute(
                    text(
                        """
                        INSERT INTO llm_provider_configs
                        (id, name, provider_type, base_url, model, is_local, enabled,
                         api_key_env, capabilities_json, is_default, created_at, updated_at)
                        VALUES (:id, :name, 'ZAI', :base_url, :model, false, true,
                                'ZAI_API_KEY', CAST(:capabilities AS jsonb), true, NOW(), NOW())
                        """
                    ),
                    {
                        "id": uuid.uuid4(),
                        "name": "智谱 GLM",
                        "base_url": "https://open.bigmodel.cn/api/paas/v4",
                        "model": "glm-5.3-flash",
                        "capabilities": json.dumps(capabilities),
                    },
                )
                session.execute(
                    text(
                        "UPDATE llm_workflow_routes "
                        "SET provider_type = 'ZAI' "
                        "WHERE provider_type = 'LOCAL_OPENAI_COMPATIBLE'"
                    )
                )
    finally:
        engine.dispose()


def main() -> int:
    if _is_at_or_before_route(_current_revision()):
        _upgrade(ROUTE_REVISION)
        _seed_only_if_provider_table_is_empty()
    _upgrade("head")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
