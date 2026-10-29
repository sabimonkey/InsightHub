import json
import uuid
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.models.analysis import AnalysisRun, Claim, Evidence, LLMModelDeployment, LLMProviderConfig, LLMWorkflowRoute
from app.models.extraction import ContentChunk
from app.models.organization import Category, SourceCategoryAssignment
from app.models.synthesis import Brief
from app.services.analysis.service import AnalysisService
from app.services.extraction.service import ExtractionService
from app.services.ingestion.service import IngestionService
from app.services.llm.fallback import select_fallback
from app.services.llm.probe import probe_provider
from app.services.llm.provider import FakeLLMProvider, OpenAICompatibleProvider
from app.services.llm.deployments import sync_deployments
from app.services.llm.registry import build_provider, sync_provider_rows
from app.services.llm.routing import WORKFLOWS, RoutingError, resolve_workflow, set_provider_enabled, update_routes
from app.services.llm.types import LLMError, LLMRequest
from app.services.retrieval.ask import AskService
from app.services.retrieval.search import SearchService
from app.services.synthesis.service import SynthesisService
from app.api.analysis import list_providers
from app.api.analysis import test_provider as run_provider_test
from tests.llm_routing_helpers import ensure_deployment_disabled, ensure_deployment_enabled


SENTINEL = "test-credential"


def _settings(**kwargs) -> Settings:
    values = dict(
        llm_enable_fake=False,
        llm_default_provider="",
        llm_timeout_seconds=1,
        llm_max_retries=0,
        lmstudio_base_url="http://127.0.0.1:1234/v1",
        lmstudio_model="",
        deepseek_base_url="",
        deepseek_model="",
        deepseek_api_key="",
        siliconflow_base_url="",
        siliconflow_model="",
        siliconflow_api_key="",
        zai_base_url="https://open.bigmodel.cn/api/paas/v4",
        zai_model="glm-5.3-flash",
        zai_api_key="",
        default_llm_context_window=8000,
        analysis_max_output_tokens=400,
        brief_inline=True,
    )
    values.update(kwargs)
    return Settings(**values)


def _cloud_settings(**kwargs) -> Settings:
    values = dict(
        deepseek_base_url="https://api.deepseek.com/v1",
        deepseek_model="deepseek-chat",
        deepseek_api_key=SENTINEL,
        siliconflow_base_url="https://api.siliconflow.cn/v1",
        siliconflow_model="sf-model",
        siliconflow_api_key=SENTINEL,
        zai_base_url="https://open.bigmodel.cn/api/paas/v4",
        zai_model="glm-5.3-flash",
        zai_api_key=SENTINEL,
    )
    values.update(kwargs)
    return _settings(**values)


def _deployment_for(db_session, settings, provider_type: str) -> LLMModelDeployment:
    sync_deployments(db_session, settings)
    provider = db_session.scalar(select(LLMProviderConfig).where(LLMProviderConfig.provider_type == provider_type))
    assert provider is not None
    deployment = db_session.scalar(
        select(LLMModelDeployment).where(LLMModelDeployment.provider_config_id == provider.id, LLMModelDeployment.archived_at.is_(None)).order_by(LLMModelDeployment.created_at.asc())
    )
    assert deployment is not None
    return deployment


def _routes(provider_type: str, db_session, settings) -> dict[str, str]:
    dep = _deployment_for(db_session, settings, provider_type)
    dep_id = str(dep.id)
    return {name: dep_id for name in WORKFLOWS}


def _routes_mixed(db_session, settings, mapping: dict[str, str], *, default_provider: str = "DEEPSEEK") -> dict[str, str]:
    out: dict[str, str] = {}
    for workflow, provider_type in mapping.items():
        out[workflow] = str(_deployment_for(db_session, settings, provider_type).id)
    for name in WORKFLOWS:
        out.setdefault(name, str(_deployment_for(db_session, settings, default_provider).id))
    return out


def _text_source(db_session, raw_root, tmp_path, text: str):
    created = IngestionService(db_session, raw_root, max_upload_size_bytes=200_000).ingest_text(text)
    ExtractionService(
        db_session,
        raw_root,
        tmp_path / "extracted",
        inline=True,
        chunk_max_chars=500,
        chunk_overlap_chars=0,
        max_pdf_pages=1,
        web_timeout=1,
        web_max_bytes=1000,
        web_max_redirects=1,
    ).schedule(created.source_item.id, "MANUAL", force=True)
    return created.source_item


def test_fake_test_mode_does_not_call_configured_local(db_session):
    settings = _settings(llm_enable_fake=True, llm_default_provider="FAKE", lmstudio_model="qwen2.5-14b-instruct")
    spec = resolve_workflow(db_session, settings, "ANALYSIS", None)
    assert spec.provider_type == "FAKE"


def test_local_route_uses_openai_compatible_transport(db_session):
    settings = _settings(lmstudio_model="qwen2.5-14b-instruct")
    ensure_deployment_enabled(db_session, settings, "LOCAL_OPENAI_COMPATIBLE")
    update_routes(db_session, settings, _routes("LOCAL_OPENAI_COMPATIBLE", db_session, settings))
    spec = resolve_workflow(db_session, settings, "ANALYSIS", None)
    assert spec.provider_type == "LOCAL_OPENAI_COMPATIBLE"
    assert spec.is_local is True

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        assert request.headers.get("authorization") in {None, ""}
        fmt = (payload.get("response_format") or {}).get("type")
        if payload.get("stream"):
            return httpx.Response(
                200,
                content='data: {"choices":[{"delta":{"content":"O"}}]}\n\ndata: [DONE]\n\n',
                headers={"content-type": "text/event-stream"},
            )
        content = "OK"
        messages = payload.get("messages") or []
        if fmt == "json_object" and any("你好" in (item.get("content") or "") for item in messages):
            content = '{"text":"你好，世界"}'
        elif any("连接正常" in (item.get("content") or "") for item in messages):
            content = "连接正常"
        elif fmt == "json_schema":
            content = '{"ok": true}'
        elif fmt == "json_object":
            content = '{"ok": true}'
        return httpx.Response(200, json={"choices": [{"message": {"content": content}, "finish_reason": "stop"}], "usage": {}, "model": spec.model})

    provider = build_provider(spec, settings, client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = probe_provider(provider)
    assert result["ok"] is True
    assert result["chinese_ok"] is True
    assert result["probes"]["json_schema"]["status"] == "SUPPORTED"
    assert result["structured_strategy"] == "JSON_SCHEMA"
    assert result["is_local"] is True


def test_analysis_execute_uses_routed_deployment_model_not_empty_env(db_session, raw_root, tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", SENTINEL)
    settings = _cloud_settings(deepseek_model="")
    ensure_deployment_enabled(db_session, settings, "DEEPSEEK")
    update_routes(db_session, settings, _routes("DEEPSEEK", db_session, settings))
    source = _text_source(db_session, raw_root, tmp_path, "routed deployment model id must be used at execute time")
    fake = FakeLLMProvider(model="deepseek-v4-pro")
    fake.provider_type = "DEEPSEEK"
    fake.is_local = False
    run = AnalysisService(db_session, inline=True, settings=settings, providers={"DEEPSEEK": fake}).start(source.id)
    assert run.status in {"SUCCEEDED", "PARTIAL"}
    assert fake.calls
    assert run.model_name == "deepseek-v4-pro"


def test_analysis_route_uses_cloud_deployment(db_session, raw_root, tmp_path, monkeypatch):
    monkeypatch.setenv("SILICONFLOW_API_KEY", SENTINEL)
    settings = _cloud_settings(siliconflow_model="zai-org/GLM-5.3-Flash")
    ensure_deployment_enabled(db_session, settings, "SILICONFLOW")
    update_routes(db_session, settings, _routes("SILICONFLOW", db_session, settings))
    source = _text_source(db_session, raw_root, tmp_path, "cloud routing keeps this recorded fact sentence")
    fake = FakeLLMProvider(model="zai-org/GLM-5.3-Flash")
    fake.provider_type = "SILICONFLOW"
    fake.is_local = False
    run = AnalysisService(db_session, inline=True, settings=settings, providers={"SILICONFLOW": fake}).start(source.id)
    assert run.status in {"SUCCEEDED", "PARTIAL"}
    assert run.provider_type == "SILICONFLOW"
    assert run.model_name == "zai-org/GLM-5.3-Flash"
    assert run.metadata_json["is_local"] is False
    assert fake.calls
    assert SENTINEL not in json.dumps(run.metadata_json)


def test_ask_planner_and_answer_use_different_routes(db_session, raw_root, tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", SENTINEL)
    settings = _cloud_settings(lmstudio_model="qwen2.5-14b-instruct")
    ensure_deployment_enabled(db_session, settings, "LOCAL_OPENAI_COMPATIBLE")
    ensure_deployment_enabled(db_session, settings, "DEEPSEEK")
    routes = _routes_mixed(db_session, settings, {"ASK_PLANNER": "LOCAL_OPENAI_COMPATIBLE", "ASK_ANSWER": "DEEPSEEK"}, default_provider="DEEPSEEK")
    update_routes(db_session, settings, routes)
    source = _text_source(db_session, raw_root, tmp_path, "planner stays local while the answer names this sandbox sentence")
    chunk = db_session.scalar(select(ContentChunk).join(ContentChunk.document).where(ContentChunk.document.has(source_item_id=source.id)))
    made: dict[str, FakeLLMProvider] = {}

    def build(spec, settings, client=None, fake=None, session=None):
        provider = FakeLLMProvider(model=spec.model)
        provider.provider_type = spec.provider_type
        provider.is_local = spec.is_local
        provider.supports_json_schema = bool(spec.capabilities.get("supports_json_schema"))
        made[spec.provider_type] = provider
        return provider

    monkeypatch.setattr("app.services.retrieval.ask.build_provider", build)
    monkeypatch.setattr(
        SearchService,
        "search",
        lambda self, query, filters=None, mode="hybrid", limit=None: {
            "results": [{"chunk_id": chunk.id, "source_id": str(source.id), "score": 0.9, "privacy_level": "PRIVATE", "retrieval_reason": "RELEVANCE"}]
        },
    )
    ask = AskService(db_session, settings, inline=True)
    session = ask.create_session("routing")
    turn = ask.start_turn(session.id, "what does the sandbox sentence say")
    assert made["LOCAL_OPENAI_COMPATIBLE"].calls
    assert made["DEEPSEEK"].calls
    assert made["LOCAL_OPENAI_COMPATIBLE"].calls[0].metadata["purpose"] == "ask_plan"
    assert made["DEEPSEEK"].calls[0].metadata["purpose"] == "ask_answer"
    assert turn.provider_type == "DEEPSEEK"
    assert turn.filters_json["retrieval"]["planner_provider_type"] == "LOCAL_OPENAI_COMPATIBLE"
    assert turn.filters_json["retrieval"]["answer_is_local"] is False


def test_brief_route_uses_cloud_deployment(db_session, raw_root, tmp_path, monkeypatch):
    monkeypatch.setenv("SILICONFLOW_API_KEY", SENTINEL)
    settings = _cloud_settings(siliconflow_model="zai-org/GLM-5.3-Flash")
    ensure_deployment_enabled(db_session, settings, "SILICONFLOW")
    update_routes(db_session, settings, _routes("SILICONFLOW", db_session, settings))
    source = _text_source(db_session, raw_root, tmp_path, "brief routing uses the cloud deployment for this fact")
    chunk = db_session.scalar(select(ContentChunk).join(ContentChunk.document).where(ContentChunk.document.has(source_item_id=source.id)))
    run = AnalysisRun(
        id=uuid.uuid4(),
        source_item_id=source.id,
        extracted_document_id=chunk.extracted_document_id,
        provider_type="LOCAL_OPENAI_COMPATIBLE",
        model_name="qwen2.5-14b-instruct",
        prompt_name="source_analysis",
        prompt_version="1.1.0",
        status="SUCCEEDED",
        is_current=True,
        metadata_json={},
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(run)
    db_session.flush()
    result_id = uuid.uuid4()
    from app.models.analysis import AnalysisResult

    db_session.add(AnalysisResult(id=result_id, analysis_run_id=run.id, summary="摘要", raw_structured_json={}, created_at=datetime.now(timezone.utc)))
    db_session.flush()
    claim = Claim(id=uuid.uuid4(), analysis_result_id=result_id, claim_type="FACT", text=chunk.content[:80], confidence=0.9, importance=3, sequence=1, created_at=datetime.now(timezone.utc))
    db_session.add(claim)
    db_session.flush()
    db_session.add(Evidence(id=uuid.uuid4(), claim_id=claim.id, content_chunk_id=chunk.id, quote_text=chunk.content[:80], created_at=datetime.now(timezone.utc)))
    category = db_session.scalar(select(Category).where(Category.slug == "knowledge"))
    db_session.add(
        SourceCategoryAssignment(
            id=uuid.uuid4(),
            source_item_id=source.id,
            category_id=category.id,
            origin="USER",
            status="ACTIVE",
            is_primary=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()
    seen: list[str] = []

    def build(spec, settings, client=None, fake=None, session=None):
        seen.append(spec.provider_type)
        provider = FakeLLMProvider(model=spec.model)
        provider.provider_type = spec.provider_type
        provider.is_local = spec.is_local
        return provider

    monkeypatch.setattr("app.services.synthesis.service.build_provider", build)
    today = datetime.now(timezone.utc).date().isoformat()
    brief = SynthesisService(db_session, settings, inline=True).create_brief(
        {"start_date": today, "end_date": today, "date_basis": "COLLECTED_AT", "detail_level": "STANDARD", "category_slugs": ["knowledge"]}
    )
    assert isinstance(brief, Brief)
    assert seen[0] == "SILICONFLOW"
    assert brief.provider_type == "SILICONFLOW"
    assert brief.filters_json["is_local"] is False
    assert SENTINEL not in json.dumps(brief.filters_json, default=str)


def test_disabled_provider_cannot_be_routed(db_session, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", SENTINEL)
    settings = _cloud_settings(lmstudio_model="qwen2.5-14b-instruct")
    ensure_deployment_enabled(db_session, settings, "DEEPSEEK")
    rows = sync_provider_rows(db_session, settings)
    deepseek = next(row for row in rows if row.provider_type == "DEEPSEEK")
    deepseek.enabled = False
    db_session.commit()
    with pytest.raises(RoutingError) as exc:
        update_routes(db_session, settings, _routes("DEEPSEEK", db_session, settings))
    assert exc.value.code == "PROVIDER_DISABLED"
    local = next(row for row in rows if row.provider_type == "LOCAL_OPENAI_COMPATIBLE")
    with pytest.raises(RoutingError) as local_exc:
        set_provider_enabled(db_session, settings, local.id, False)
    assert local_exc.value.code == "LOCAL_PROVIDER_REQUIRED"


def test_missing_api_key_test_connection_is_not_configured(db_session, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    from app.services.llm.credential_resolver import ResolvedApiKey

    monkeypatch.setattr(
        "app.services.llm.registry.resolve_api_key",
        lambda *_args, **_kwargs: ResolvedApiKey("", "none"),
    )
    settings = _settings(deepseek_base_url="https://api.deepseek.com/v1", deepseek_model="deepseek-chat")
    service = AnalysisService(db_session, inline=True, settings=settings)
    rows = sync_provider_rows(db_session, settings)
    row = next(item for item in rows if item.provider_type == "DEEPSEEK")
    result = run_provider_test(row.id, service)
    assert result["ok"] is False
    assert result["code"] == "NOT_CONFIGURED"


def test_secret_stays_out_of_api_logs_and_database(db_session, monkeypatch, caplog):
    monkeypatch.setenv("DEEPSEEK_API_KEY", SENTINEL)
    settings = _cloud_settings()
    service = AnalysisService(db_session, inline=True, settings=settings)
    rows = sync_provider_rows(db_session, settings)
    stored = json.dumps(
        [
            {"type": row.provider_type, "env": row.api_key_env, "url": row.base_url, "model": row.model, "capabilities": row.capabilities_json}
            for row in rows
        ],
        default=str,
    )
    assert SENTINEL not in stored
    assert "api_key" not in stored
    views = list_providers(service)
    payload = json.dumps([item.model_dump(mode="json") for item in views], default=str)
    assert SENTINEL not in payload
    assert "sk-" not in payload
    with caplog.at_level("ERROR"):
        try:
            raise LLMError("PROVIDER_UNAVAILABLE", type(RuntimeError("authorization " + SENTINEL)).__name__)
        except LLMError as exc:
            assert SENTINEL not in exc.message
    assert SENTINEL not in caplog.text
    row = db_session.scalar(select(LLMProviderConfig).where(LLMProviderConfig.provider_type == "DEEPSEEK"))
    assert row.api_key_env == "DEEPSEEK_API_KEY"
    assert SENTINEL not in (row.api_key_env or "")


def test_local_failure_does_not_fail_over_to_cloud(db_session, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", SENTINEL)
    settings = _cloud_settings(
        lmstudio_model="qwen2.5-14b-instruct",
        llm_provider_fallback_enabled=True,
        llm_fallback_provider="DEEPSEEK",
    )
    assert select_fallback(settings, "LOCAL_OPENAI_COMPATIBLE", "PUBLIC") is None
    service = AnalysisService(db_session, inline=True, settings=settings)
    local = FakeLLMProvider(fail="PROVIDER_UNAVAILABLE")
    local.provider_type = "LOCAL_OPENAI_COMPATIBLE"
    local.is_local = True
    with pytest.raises(LLMError) as exc:
        service._complete(local, "system", "<source_content>user content</source_content>", None, {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "latency_ms": 0, "calls": 0}, "PUBLIC")
    assert exc.value.code == "PROVIDER_UNAVAILABLE"


def test_cloud_failure_does_not_switch_cloud_unless_explicit(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", SENTINEL)
    monkeypatch.setenv("SILICONFLOW_API_KEY", SENTINEL)
    silent = _cloud_settings(llm_provider_fallback_enabled=True, llm_fallback_provider="")
    assert select_fallback(silent, "DEEPSEEK", "PUBLIC") is None
    explicit = _cloud_settings(llm_provider_fallback_enabled=True, llm_fallback_provider="SILICONFLOW")
    assert select_fallback(explicit, "DEEPSEEK", "PUBLIC").provider_type == "SILICONFLOW"


def test_json_object_path_is_recorded_when_schema_is_unsupported():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}], "usage": {}, "model": "cloud-model"})

    provider = OpenAICompatibleProvider(
        provider_type="DEEPSEEK",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-chat",
        api_key=SENTINEL,
        is_local=False,
        timeout=1,
        max_retries=0,
        supports_json_schema=False,
        supports_json_object=True,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    response = provider.complete(LLMRequest("system", "user", {"type": "object"}, 0, 16, {"purpose": "analysis", "schema_name": "source_analysis"}))
    assert seen["payload"]["response_format"]["type"] == "json_object"
    assert seen["payload"]["thinking"] == {"type": "disabled"}
    assert response.raw_response_metadata["strategy"] == "JSON_OBJECT"
    assert SENTINEL not in json.dumps(response.raw_response_metadata)


def test_deepseek_without_recorded_context_uses_the_model_window():
    from app.services.llm.registry import ProviderSpec

    spec = ProviderSpec("DEEPSEEK", "DeepSeek", "https://api.deepseek.com/v1", "deepseek-v4-pro", False, "DEEPSEEK_API_KEY", True, {})
    provider = build_provider(spec, Settings(deepseek_api_key="test-key", llm_timeout_seconds=1, llm_max_retries=0))
    assert provider.context_window == 1_000_000


def test_unconfigured_cloud_route_does_not_fall_back_to_local(db_session, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    from app.services.llm.credential_resolver import ResolvedApiKey

    monkeypatch.setattr(
        "app.services.llm.registry.resolve_api_key",
        lambda *_args, **_kwargs: ResolvedApiKey("", "none"),
    )
    settings = _settings(lmstudio_model="qwen2.5-14b-instruct", deepseek_base_url="https://api.deepseek.com/v1", deepseek_model="deepseek-chat")
    ensure_deployment_enabled(db_session, settings, "DEEPSEEK")
    deepseek = _deployment_for(db_session, settings, "DEEPSEEK")
    route = db_session.get(LLMWorkflowRoute, "ANALYSIS")
    route.deployment_id = deepseek.id
    db_session.commit()
    with pytest.raises(RoutingError) as exc:
        resolve_workflow(db_session, settings, "ANALYSIS", None)
    assert exc.value.code == "CONFIGURATION_REQUIRED"


def test_one_provider_supports_multiple_deployments(db_session, monkeypatch):
    monkeypatch.setenv("SILICONFLOW_API_KEY", SENTINEL)
    settings = _cloud_settings(siliconflow_model="model-a")
    from app.services.llm.deployments import create_deployment

    sync_deployments(db_session, settings)
    provider = db_session.scalar(select(LLMProviderConfig).where(LLMProviderConfig.provider_type == "SILICONFLOW"))
    create_deployment(db_session, provider.id, display_name="Model B", model_id="vendor/model-b", capabilities={"supports_json_object": True})
    deployments = list(db_session.scalars(select(LLMModelDeployment).where(LLMModelDeployment.provider_config_id == provider.id)))
    assert len(deployments) >= 2
    assert "vendor/model-b" in {item.model_id for item in deployments}


def test_workflows_route_to_different_deployments(db_session, monkeypatch):
    monkeypatch.setenv("SILICONFLOW_API_KEY", SENTINEL)
    monkeypatch.setenv("DEEPSEEK_API_KEY", SENTINEL)
    settings = _cloud_settings()
    ensure_deployment_enabled(db_session, settings, "DEEPSEEK")
    ensure_deployment_enabled(db_session, settings, "SILICONFLOW")
    from app.services.llm.deployments import create_deployment

    provider = db_session.scalar(select(LLMProviderConfig).where(LLMProviderConfig.provider_type == "SILICONFLOW"))
    planner = create_deployment(
        db_session,
        provider.id,
        display_name="Planner",
        model_id="planner-model",
        capabilities={"supports_json_object": True},
    )
    answer = create_deployment(db_session, provider.id, display_name="Answer", model_id="answer-model", capabilities={"supports_json_object": False})
    mapping = _routes_mixed(db_session, settings, {}, default_provider="DEEPSEEK")
    mapping["ASK_PLANNER"] = str(planner.id)
    mapping["ASK_ANSWER"] = str(answer.id)
    update_routes(db_session, settings, mapping)
    assert db_session.get(LLMWorkflowRoute, "ASK_PLANNER").deployment_id == planner.id
    assert db_session.get(LLMWorkflowRoute, "ASK_ANSWER").deployment_id == answer.id


def test_disabled_deployment_cannot_be_routed(db_session, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", SENTINEL)
    settings = _cloud_settings(lmstudio_model="qwen2.5-14b-instruct")
    ensure_deployment_enabled(db_session, settings, "LOCAL_OPENAI_COMPATIBLE")
    ensure_deployment_enabled(db_session, settings, "DEEPSEEK")
    dep = _deployment_for(db_session, settings, "DEEPSEEK")
    dep.enabled = False
    db_session.commit()
    body = _routes("LOCAL_OPENAI_COMPATIBLE", db_session, settings)
    body["ANALYSIS"] = str(dep.id)
    with pytest.raises(RoutingError) as exc:
        update_routes(db_session, settings, body)
    assert exc.value.code == "PROVIDER_DISABLED"


def test_cloud_secret_missing_blocks_route_activation(db_session, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    from app.services.llm.credential_resolver import ResolvedApiKey

    monkeypatch.setattr(
        "app.services.llm.registry.resolve_api_key",
        lambda *_args, **_kwargs: ResolvedApiKey("", "none"),
    )
    settings = _settings(lmstudio_model="qwen2.5-14b-instruct", deepseek_base_url="https://api.deepseek.com/v1", deepseek_model="deepseek-chat")
    ensure_deployment_enabled(db_session, settings, "LOCAL_OPENAI_COMPATIBLE")
    ensure_deployment_enabled(db_session, settings, "DEEPSEEK")
    dep = _deployment_for(db_session, settings, "DEEPSEEK")
    body = _routes("LOCAL_OPENAI_COMPATIBLE", db_session, settings)
    body["BRIEF"] = str(dep.id)
    with pytest.raises(RoutingError) as exc:
        update_routes(db_session, settings, body)
    assert exc.value.code == "CONFIGURATION_REQUIRED"


def test_workflow_routes_cloud_default(db_session, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", SENTINEL)
    monkeypatch.setenv("SILICONFLOW_API_KEY", SENTINEL)
    settings = _cloud_settings(deepseek_model="deepseek-v4-pro", siliconflow_model="zai-org/GLM-5.3-Flash")
    from app.services.llm.cloud_defaults import CLOUD_DEFAULT_ROUTE_TARGETS, apply_cloud_default_routes

    apply_cloud_default_routes(db_session, settings)
    # Stage A routes point at inactive ZAI deployments until the user enables them.
    for route in db_session.scalars(select(LLMWorkflowRoute)):
        deployment = db_session.get(LLMModelDeployment, route.deployment_id)
        deployment.enabled = True
    db_session.flush()
    for workflow, (provider_type, model_id) in CLOUD_DEFAULT_ROUTE_TARGETS.items():
        spec = resolve_workflow(db_session, settings, workflow, None)
        assert spec.provider_type == provider_type
        assert spec.model == model_id


def test_readiness_does_not_require_lm_studio_when_cloud_routes_active(db_session, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", SENTINEL)
    monkeypatch.setenv("SILICONFLOW_API_KEY", SENTINEL)
    settings = _cloud_settings(deepseek_model="deepseek-v4-pro", siliconflow_model="zai-org/GLM-5.3-Flash")
    from app.services.llm.cloud_defaults import apply_cloud_default_routes
    from app.services.maintenance.system import readiness

    apply_cloud_default_routes(db_session, settings)
    ready = readiness(db_session, settings)
    assert ready["ready"] is True


def test_local_route_activation_stays_configured_without_cloud_keys(db_session, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", SENTINEL)
    settings = _cloud_settings(lmstudio_model="qwen2.5-14b-instruct")
    ensure_deployment_enabled(db_session, settings, "LOCAL_OPENAI_COMPATIBLE")
    ensure_deployment_enabled(db_session, settings, "DEEPSEEK")
    local = _deployment_for(db_session, settings, "LOCAL_OPENAI_COMPATIBLE")
    mapping = _routes_mixed(db_session, settings, {"ANALYSIS": "LOCAL_OPENAI_COMPATIBLE"}, default_provider="DEEPSEEK")
    update_routes(db_session, settings, mapping)
    assert db_session.get(LLMWorkflowRoute, "ANALYSIS").deployment_id == local.id
    spec = resolve_workflow(db_session, settings, "ANALYSIS", None)
    assert spec.provider_type == "LOCAL_OPENAI_COMPATIBLE"


def test_schema_http_400_retries_json_object_before_prompt_fallback():
    attempts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        fmt = (payload.get("response_format") or {}).get("type")
        attempts.append(fmt or "none")
        if fmt == "json_schema":
            return httpx.Response(400, text="response_format json_schema is not supported")
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}], "usage": {}, "model": "cloud-model"})

    provider = OpenAICompatibleProvider(
        provider_type="DEEPSEEK",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-chat",
        api_key=SENTINEL,
        is_local=False,
        timeout=1,
        max_retries=0,
        supports_json_schema=True,
        supports_json_object=True,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    response = provider.complete(LLMRequest("system", "user", {"type": "object"}, 0, 16, {"purpose": "analysis", "schema_name": "source_analysis"}))
    assert attempts == ["json_schema", "json_object"]
    assert response.raw_response_metadata["strategy"] == "JSON_OBJECT"


def test_runtime_uses_deployment_model_id(db_session, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", SENTINEL)
    settings = _cloud_settings()
    ensure_deployment_enabled(db_session, settings, "DEEPSEEK")
    dep = _deployment_for(db_session, settings, "DEEPSEEK")
    update_routes(db_session, settings, _routes("DEEPSEEK", db_session, settings))
    spec = resolve_workflow(db_session, settings, "ANALYSIS", None)
    assert spec.deployment_id == dep.id
    assert spec.model == dep.model_id


def test_cloud_routes_resolve_when_local_deployment_disabled(db_session, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", SENTINEL)
    monkeypatch.setenv("SILICONFLOW_API_KEY", SENTINEL)
    settings = _cloud_settings(deepseek_model="deepseek-v4-pro", siliconflow_model="zai-org/GLM-5.3-Flash")
    ensure_deployment_disabled(db_session, settings, "LOCAL_OPENAI_COMPATIBLE")
    ensure_deployment_enabled(db_session, settings, "DEEPSEEK")
    ensure_deployment_enabled(db_session, settings, "SILICONFLOW")
    update_routes(
        db_session,
        settings,
        _routes_mixed(
            db_session,
            settings,
            {"ASK_ANSWER": "SILICONFLOW"},
            default_provider="DEEPSEEK",
        ),
    )
    assert resolve_workflow(db_session, settings, "ANALYSIS", None).provider_type == "DEEPSEEK"
    assert resolve_workflow(db_session, settings, "ASK_ANSWER", None).provider_type == "SILICONFLOW"


def test_explicit_local_route_unavailable_when_local_deployment_disabled(db_session, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", SENTINEL)
    settings = _cloud_settings(lmstudio_model="qwen2.5-14b-instruct")
    local = ensure_deployment_disabled(db_session, settings, "LOCAL_OPENAI_COMPATIBLE")
    ensure_deployment_enabled(db_session, settings, "DEEPSEEK")
    update_routes(db_session, settings, _routes("DEEPSEEK", db_session, settings))
    route = db_session.get(LLMWorkflowRoute, "ASK_PLANNER")
    route.deployment_id = local.id
    db_session.commit()
    with pytest.raises(RoutingError) as exc:
        resolve_workflow(db_session, settings, "ASK_PLANNER", None)
    assert exc.value.code == "PROVIDER_DISABLED"


def test_analysis_execute_honors_provider_override(db_session, raw_root, tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", SENTINEL)
    monkeypatch.setenv("SILICONFLOW_API_KEY", SENTINEL)
    settings = _cloud_settings(analysis_max_output_tokens=400)
    ensure_deployment_enabled(db_session, settings, "DEEPSEEK")
    ensure_deployment_enabled(db_session, settings, "SILICONFLOW")
    update_routes(
        db_session,
        settings,
        _routes_mixed(
            db_session,
            settings,
            {"ANALYSIS": "DEEPSEEK", "ASK_PLANNER": "SILICONFLOW", "ASK_ANSWER": "DEEPSEEK", "BRIEF": "DEEPSEEK"},
        ),
    )
    deepseek = FakeLLMProvider(model="deepseek-fake")
    deepseek.provider_type = "DEEPSEEK"
    glm = FakeLLMProvider(model="glm-fake")
    glm.provider_type = "SILICONFLOW"
    created = _text_source(db_session, raw_root, tmp_path, "recorded fact sentence for analysis override test")
    service = AnalysisService(
        db_session,
        inline=True,
        settings=settings,
        providers={"DEEPSEEK": deepseek, "SILICONFLOW": glm},
    )
    run = service.start(created.id, "SILICONFLOW")
    assert run.status in {"SUCCEEDED", "PARTIAL"}
    assert run.provider_type == "SILICONFLOW"
    assert glm.calls
    assert not deepseek.calls
