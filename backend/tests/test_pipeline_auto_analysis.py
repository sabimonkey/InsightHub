import uuid
from unittest.mock import MagicMock

from app.models.extraction import ExtractedDocument
from app.services.pipeline.auto_analysis import should_skip_auto_analysis


def test_skip_auto_analysis_when_active_run():
    doc = ExtractedDocument(id=uuid.uuid4(), source_item_id=uuid.uuid4(), plain_text="x")
    session = MagicMock()
    session.scalar = MagicMock(side_effect=[MagicMock(), None])
    assert should_skip_auto_analysis(session, doc.source_item_id, doc) == "ACTIVE_RUN"


def test_skip_auto_analysis_when_already_analyzed():
    doc = ExtractedDocument(id=uuid.uuid4(), source_item_id=uuid.uuid4(), plain_text="x")
    session = MagicMock()
    session.scalar = MagicMock(side_effect=[None, MagicMock()])
    assert should_skip_auto_analysis(session, doc.source_item_id, doc) == "ALREADY_ANALYZED"
