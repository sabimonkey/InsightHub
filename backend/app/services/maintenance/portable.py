import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.organization import Category, Entity, Project, Topic
from app.models.source_item import SourceItem
from app.models.synthesis import Brief
from app.version import APP_VERSION


def export_library(session: Session, destination: Path, *, include_raw_files: bool = False) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    sources = [
        {"id": str(row.id), "display_name": row.display_name, "source_type": row.source_type, "status": row.status}
        for row in session.scalars(select(SourceItem).order_by(SourceItem.created_at))
    ]
    (destination / "sources.json").write_text(json.dumps(sources, ensure_ascii=False, indent=2), encoding="utf-8")
    (destination / "categories.json").write_text(
        json.dumps([{"id": str(row.id), "name": row.name, "slug": row.slug} for row in session.scalars(select(Category))], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (destination / "topics.json").write_text(
        json.dumps([{"id": str(row.id), "name": row.name} for row in session.scalars(select(Topic))], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (destination / "entities.json").write_text(
        json.dumps([{"id": str(row.id), "name": row.name} for row in session.scalars(select(Entity))], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (destination / "projects.json").write_text(
        json.dumps([{"id": str(row.id), "name": row.name} for row in session.scalars(select(Project))], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    briefs = destination / "briefs"
    markdown = destination / "markdown"
    briefs.mkdir(exist_ok=True)
    markdown.mkdir(exist_ok=True)
    for brief in session.scalars(select(Brief)):
        payload = {
            "id": str(brief.id),
            "title": brief.title,
            "status": brief.status,
            "provider_type": brief.provider_type,
            "filters": brief.filters_json,
        }
        (briefs / f"{brief.id}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        (markdown / f"{brief.id}.md").write_text(brief.content_markdown or "", encoding="utf-8")
    manifest = {
        "kind": "portable_export",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "app_version": APP_VERSION,
        "include_raw_files": include_raw_files,
        "restorable": False,
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return destination
