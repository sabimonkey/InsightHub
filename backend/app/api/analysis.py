import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.jobs.analysis import enqueue_analysis
from app.services.jobs.runtime_guard import WorkerNotAvailableError, ensure_async_worker
from app.services.maintenance.pipeline_audit import audit_user_sources
from app.services.pipeline.analysis_batch import AnalysisBatchError, enqueue_analysis_backfill, preview_analysis_backfill
from app.services.pipeline.analysis_queue import analysis_queue_summary, list_analysis_jobs
from pydantic import BaseModel, Field

from app.api.deps import get_analysis_service
from app.models.analysis import AnalysisResult, AnalysisRun, Claim, Evidence, LLMModelDeployment, LLMProviderConfig
from app.services.analysis.service import AnalysisError, AnalysisService
from app.services.analysis.stages import read_stage, stage_label
from app.services.llm.deployments import archive_deployment, create_deployment, list_deployments_for_provider, routes_using_deployment, sync_deployments, update_deployment
from app.services.llm.capability_probe import apply_probe_capabilities, probe_deployment_capabilities
from app.services.llm.registry import ProviderSpec, build_provider, endpoint_configured, provider_specs, spec_from_deployment, sync_provider_rows
from app.services.llm.routing import RoutingError, list_route_options, list_routes, set_provider_enabled, update_routes

router = APIRouter(prefix="/api", tags=["analysis"])


class AnalyzeRequest(BaseModel):
    provider_type: str | None = None


class AnalysisBackfillBody(BaseModel):
    source_ids: list[uuid.UUID] | None = None
    confirm: bool = Field(default=False)
    include_partial: bool = Field(default=False)
    mode: str = Field(default="fresh")


class DeploymentView(BaseModel):
    id: uuid.UUID
    display_name: str
    model_id: str
    enabled: bool
    capabilities: dict
    route_ready: bool


class ProviderView(BaseModel):
    id: uuid.UUID
    name: str
    provider_type: str
    base_url: str
    model: str
    is_local: bool
    configured: bool
    is_default: bool
    api_key_state: str
    credential_source: str
    credential_manageable: bool
    enabled: bool
    capabilities: dict
    deployments: list[DeploymentView]


class ProviderCredentialUpdate(BaseModel):
    api_key: str = Field(min_length=1, max_length=4096)


class DeploymentCreate(BaseModel):
    display_name: str
    model_id: str
    enabled: bool = True
    capabilities: dict | None = None


class DeploymentUpdate(BaseModel):
    display_name: str | None = None
    model_id: str | None = None
    enabled: bool | None = None
    capabilities: dict | None = None


class RouteUpdate(BaseModel):
    ANALYSIS: str
    ASK_PLANNER: str
    ASK_ANSWER: str
    BRIEF: str


class ProviderEnabledUpdate(BaseModel):
    enabled: bool


class EvidenceView(BaseModel):
    id: uuid.UUID
    content_chunk_id: uuid.UUID
    quote_text: str | None
    page_number: int | None
    citation: int


class ClaimView(BaseModel):
    id: uuid.UUID
    claim_type: str
    text: str
    confidence: float | None
    importance: int | None
    evidence: list[EvidenceView]


class RunView(BaseModel):
    id: uuid.UUID
    status: str
    provider_type: str
    model_name: str
    is_simulated: bool = False
    prompt_name: str
    prompt_version: str
    is_current: bool
    analysis_strategy: str | None
    input_extraction_status: str | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    latency_ms: int | None
    error_code: str | None
    error_message: str | None
    created_at: str
    analysis_stage: str | None = None
    analysis_stage_label: str | None = None


class AnalysisView(BaseModel):
    run: RunView | None
    summary: str | None
    partial_warning: bool
    claims: list[ClaimView]
    category_candidates: list
    topic_candidates: list
    entities: list
    history: list[RunView]
    providers_configured: bool


def _run(row: AnalysisRun) -> RunView:
    stage = read_stage(row)
    return RunView(
        id=row.id,
        status=row.status,
        provider_type=row.provider_type,
        model_name=row.model_name,
        is_simulated=row.provider_type == "FAKE" or row.model_name == "fake-model",
        prompt_name=row.prompt_name,
        prompt_version=row.prompt_version,
        is_current=row.is_current,
        analysis_strategy=row.analysis_strategy,
        input_extraction_status=row.input_extraction_status,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        total_tokens=row.total_tokens,
        latency_ms=row.latency_ms,
        error_code=row.error_code,
        error_message=row.error_message,
        created_at=row.created_at.isoformat(),
        analysis_stage=stage,
        analysis_stage_label=stage_label(stage),
    )


def _view(run, result: AnalysisResult | None, claims: list[Claim], evidence: list[Evidence], history, configured: bool) -> AnalysisView:
    by_claim: dict[uuid.UUID, list[Evidence]] = {}
    for item in evidence:
        by_claim.setdefault(item.claim_id, []).append(item)
    citation = 1
    claim_views = []
    for claim in claims:
        rows = []
        for item in by_claim.get(claim.id, []):
            rows.append(EvidenceView(id=item.id, content_chunk_id=item.content_chunk_id, quote_text=item.quote_text, page_number=item.page_number, citation=citation))
            citation += 1
        claim_views.append(ClaimView(id=claim.id, claim_type=claim.claim_type, text=claim.text, confidence=claim.confidence, importance=claim.importance, evidence=rows))
    raw = result.raw_structured_json if result else {}
    return AnalysisView(
        run=_run(run) if run else None,
        summary=result.summary if result else None,
        partial_warning=bool(run and run.input_extraction_status == "PARTIAL"),
        claims=claim_views,
        category_candidates=raw.get("category_candidates") or [],
        topic_candidates=raw.get("topic_candidates") or [],
        entities=raw.get("entities") or [],
        history=[_run(item) for item in history],
        providers_configured=configured,
    )


@router.get("/llm/providers", response_model=list[ProviderView])
def list_providers(service: AnalysisService = Depends(get_analysis_service)) -> list[ProviderView]:
    from app.services.llm.credential_resolver import CREDENTIAL_MANAGED_PROVIDER_TYPES, resolve_api_key

    specs = {item.provider_type: item for item in provider_specs(service.settings, service.session)}
    rows = sync_provider_rows(service.session, service.settings)
    sync_deployments(service.session, service.settings)
    from app.services.system_scope import AUTOMATION_TEST_SCOPE, creation_scope_from_settings

    scope = creation_scope_from_settings(service.settings)
    views = []
    for row in rows:
        if row.provider_type == "FAKE":
            if scope != AUTOMATION_TEST_SCOPE or not service.settings.llm_enable_fake:
                continue
        if row.provider_type in {"LOCAL_OPENAI_COMPATIBLE", "DEEPSEEK", "SILICONFLOW", "GENERIC_OPENAI_COMPATIBLE"}:
            continue
        spec = specs.get(row.provider_type)
        if spec is None:
            spec = ProviderSpec(
                provider_type=row.provider_type,
                name=row.name,
                base_url=row.base_url,
                model=row.model,
                is_local=row.is_local,
                api_key_env=row.api_key_env,
                configured=False,
                capabilities=row.capabilities_json or {},
            )
        endpoint_ok = endpoint_configured(spec, service.settings, service.session)
        resolved = resolve_api_key(row.provider_type, spec.api_key_env, service.settings, service.session)
        if spec.api_key_env is None:
            key_state = "not_required" if spec.is_local or spec.provider_type == "FAKE" else "not_configured"
            cred_source = "none"
        else:
            key_state = "configured" if endpoint_ok else "not_configured"
            cred_source = resolved.source
        manageable = row.provider_type in CREDENTIAL_MANAGED_PROVIDER_TYPES and not row.is_local
        deployments = []
        primary_model = row.model
        for dep in list_deployments_for_provider(service.session, row.id):
            dep_spec = spec_from_deployment(row, dep, spec)
            from app.services.llm.deployments import deployment_route_ready

            ready = deployment_route_ready(dep, row, spec, service.settings, service.session)
            deployments.append(
                DeploymentView(
                    id=dep.id,
                    display_name=dep.display_name,
                    model_id=dep.model_id,
                    enabled=dep.enabled,
                    capabilities=dep.capabilities_json or {},
                    route_ready=ready,
                )
            )
            if not primary_model:
                primary_model = dep.model_id
        views.append(
            ProviderView(
                id=row.id,
                name=row.name,
                provider_type=row.provider_type,
                base_url=row.base_url,
                model=primary_model or "",
                is_local=row.is_local,
                configured=endpoint_ok,
                is_default=row.is_default,
                api_key_state=key_state,
                credential_source=cred_source,
                credential_manageable=manageable,
                enabled=row.enabled,
                capabilities=row.capabilities_json or {},
                deployments=deployments,
            )
        )
    return views


@router.post("/llm/providers/{provider_id}/deployments", response_model=DeploymentView)
def add_deployment(provider_id: uuid.UUID, body: DeploymentCreate, service: AnalysisService = Depends(get_analysis_service)) -> DeploymentView:
    try:
        row = create_deployment(
            service.session,
            provider_id,
            display_name=body.display_name,
            model_id=body.model_id,
            capabilities=body.capabilities,
            enabled=body.enabled,
        )
    except ValueError as exc:
        raise AnalysisError(409, str(exc), "无法创建模型部署。") from exc
    provider = service.session.get(LLMProviderConfig, provider_id)
    spec = next((item for item in provider_specs(service.settings, service.session) if item.provider_type == provider.provider_type), None)
    from app.services.llm.deployments import deployment_route_ready

    ready = bool(provider and spec and deployment_route_ready(row, provider, spec, service.settings, service.session))
    return DeploymentView(
        id=row.id,
        display_name=row.display_name,
        model_id=row.model_id,
        enabled=row.enabled,
        capabilities=row.capabilities_json or {},
        route_ready=ready,
    )


@router.patch("/llm/deployments/{deployment_id}", response_model=DeploymentView)
def patch_deployment(deployment_id: uuid.UUID, body: DeploymentUpdate, service: AnalysisService = Depends(get_analysis_service)) -> DeploymentView:
    fields = body.model_dump(exclude_unset=True)
    if "capabilities" in fields:
        fields["capabilities"] = fields.pop("capabilities")
    try:
        row = update_deployment(service.session, deployment_id, **fields)
    except ValueError as exc:
        code = str(exc)
        raise AnalysisError(409, code, "无法更新模型部署。") from exc
    provider = service.session.get(LLMProviderConfig, row.provider_config_id)
    spec = next((item for item in provider_specs(service.settings, service.session) if provider and item.provider_type == provider.provider_type), None)
    from app.services.llm.deployments import deployment_route_ready

    ready = bool(provider and spec and deployment_route_ready(row, provider, spec, service.settings, service.session))
    return DeploymentView(
        id=row.id,
        display_name=row.display_name,
        model_id=row.model_id,
        enabled=row.enabled,
        capabilities=row.capabilities_json or {},
        route_ready=ready,
    )


@router.post("/llm/providers/{provider_id}/test")
def test_provider(provider_id: uuid.UUID, service: AnalysisService = Depends(get_analysis_service)) -> dict:
    row = service.session.get(LLMProviderConfig, provider_id)
    if row is None:
        return {"ok": False, "code": "NOT_CONFIGURED"}
    deployments = list_deployments_for_provider(service.session, provider_id)
    if not deployments:
        return {"ok": False, "code": "NOT_CONFIGURED", "model": row.model, "is_local": row.is_local}
    return test_deployment(deployments[0].id, service)


@router.get("/llm/deployments/{deployment_id}/delete-preview")
def delete_deployment_preview(deployment_id: uuid.UUID, service: AnalysisService = Depends(get_analysis_service)) -> dict:
    deployment = service.session.get(LLMModelDeployment, deployment_id)
    if deployment is None or deployment.archived_at is not None:
        return {"ok": False, "code": "DEPLOYMENT_NOT_FOUND"}
    provider = service.session.get(LLMProviderConfig, deployment.provider_config_id)
    routes = routes_using_deployment(service.session, deployment.id)
    return {
        "ok": True,
        "provider_name": provider.name if provider else "",
        "provider_type": provider.provider_type if provider else "",
        "model_id": deployment.model_id,
        "display_name": deployment.display_name,
        "routes": routes,
        "can_delete": len(routes) == 0,
        "history_preserved": True,
    }


@router.delete("/llm/deployments/{deployment_id}")
def delete_deployment(deployment_id: uuid.UUID, service: AnalysisService = Depends(get_analysis_service)) -> dict:
    try:
        row = archive_deployment(service.session, deployment_id)
    except ValueError as exc:
        code = str(exc)
        status = 409 if code == "ROUTE_IN_USE" else 404
        raise AnalysisError(status, code, "无法删除模型部署。") from exc
    return {"ok": True, "id": str(row.id), "archived": True}


@router.post("/llm/deployments/{deployment_id}/test")
def test_deployment(
    deployment_id: uuid.UUID,
    service: AnalysisService = Depends(get_analysis_service),
    sample: bool = Query(default=False, description="真实 MiniMax 生图测试，可能产生费用"),
) -> dict:
    deployment = service.session.get(LLMModelDeployment, deployment_id)
    if deployment is None or deployment.archived_at is not None:
        return {"ok": False, "code": "NOT_CONFIGURED"}
    provider = service.session.get(LLMProviderConfig, deployment.provider_config_id)
    if provider is None:
        return {"ok": False, "code": "NOT_CONFIGURED"}
    if provider.provider_type == "MINIMAX_IMAGE" or (deployment.capabilities_json or {}).get("supports_image_generation"):
        from app.services.image.minimax import probe_image_config, probe_image_sample

        if sample:
            prompt = "A clean editorial cover illustration about research knowledge management."
            result = probe_image_sample(prompt, model=deployment.model_id, settings=service.settings, session=service.session)
        else:
            result = probe_image_config(service.settings, service.session)
        result["deployment_id"] = str(deployment.id)
        result["model"] = deployment.model_id
        return result
    endpoint = next((item for item in provider_specs(service.settings, service.session) if item.provider_type == provider.provider_type), None)
    if endpoint is None or not endpoint_configured(endpoint, service.settings, service.session):
        return {"ok": False, "code": "NOT_CONFIGURED", "model": deployment.model_id, "is_local": provider.is_local}
    spec = spec_from_deployment(provider, deployment, endpoint)
    runtime = service.providers.get(spec.provider_type) or build_provider(spec, service.settings, session=service.session)
    result = probe_deployment_capabilities(runtime)
    result["provider_type"] = provider.provider_type
    result["deployment_id"] = str(deployment.id)
    result["is_local"] = provider.is_local
    if result.get("overall_status") == "PASS" and result.get("probes"):
        from datetime import datetime, timezone

        deployment.capabilities_json = apply_probe_capabilities(deployment.capabilities_json, result["probes"])
        deployment.updated_at = datetime.now(timezone.utc)
        service.session.commit()
    return result


def _provider_credential_view(service: AnalysisService, row: LLMProviderConfig) -> dict:
    from app.services.llm.credential_resolver import CREDENTIAL_MANAGED_PROVIDER_TYPES, resolve_api_key

    spec = next((item for item in provider_specs(service.settings, service.session) if item.provider_type == row.provider_type), None)
    endpoint_ok = bool(spec and endpoint_configured(spec, service.settings, service.session))
    resolved = resolve_api_key(row.provider_type, row.api_key_env, service.settings, service.session)
    return {
        "ok": True,
        "provider_type": row.provider_type,
        "configured": endpoint_ok,
        "api_key_state": "configured" if endpoint_ok else "not_configured",
        "credential_source": resolved.source,
        "credential_manageable": row.provider_type in CREDENTIAL_MANAGED_PROVIDER_TYPES and not row.is_local,
    }


@router.put("/llm/providers/{provider_id}/credential")
def save_provider_credential(
    provider_id: uuid.UUID,
    body: ProviderCredentialUpdate,
    request: Request,
    service: AnalysisService = Depends(get_analysis_service),
) -> dict:
    from app.api.local_guard import require_local_settings_mutation
    from app.services.llm.credential_resolver import CREDENTIAL_MANAGED_PROVIDER_TYPES
    from app.services.secrets.vault import CredentialVaultError, write_vault_secret

    require_local_settings_mutation(request)
    row = service.session.get(LLMProviderConfig, provider_id)
    if row is None:
        raise AnalysisError(404, "PROVIDER_NOT_FOUND", "Provider 不存在。")
    if row.is_local or row.provider_type not in CREDENTIAL_MANAGED_PROVIDER_TYPES:
        raise AnalysisError(400, "CREDENTIAL_NOT_MANAGED", "该 Provider 不支持页面密钥配置。")
    try:
        write_vault_secret(service.session, row.provider_type, body.api_key)
    except CredentialVaultError as exc:
        raise AnalysisError(400, exc.code, exc.message) from exc
    return _provider_credential_view(service, row)


@router.delete("/llm/providers/{provider_id}/credential")
def clear_provider_credential(
    provider_id: uuid.UUID,
    request: Request,
    service: AnalysisService = Depends(get_analysis_service),
) -> dict:
    from app.api.local_guard import require_local_settings_mutation
    from app.services.llm.credential_resolver import CREDENTIAL_MANAGED_PROVIDER_TYPES
    from app.services.secrets.vault import clear_vault_secret

    require_local_settings_mutation(request)
    row = service.session.get(LLMProviderConfig, provider_id)
    if row is None:
        raise AnalysisError(404, "PROVIDER_NOT_FOUND", "Provider 不存在。")
    if row.is_local or row.provider_type not in CREDENTIAL_MANAGED_PROVIDER_TYPES:
        raise AnalysisError(400, "CREDENTIAL_NOT_MANAGED", "该 Provider 不支持页面密钥配置。")
    clear_vault_secret(service.session, row.provider_type)
    return _provider_credential_view(service, row)


@router.patch("/llm/providers/{provider_id}")
def update_provider_enabled(provider_id: uuid.UUID, body: ProviderEnabledUpdate, service: AnalysisService = Depends(get_analysis_service)) -> dict:
    try:
        row = set_provider_enabled(service.session, service.settings, provider_id, body.enabled)
    except RoutingError as exc:
        raise AnalysisError(409, exc.code, exc.message) from exc
    return {"id": row.id, "provider_type": row.provider_type, "enabled": row.enabled}


@router.post("/llm/providers/{provider_id}/retire")
def retire_provider(provider_id: uuid.UUID, request: Request, service: AnalysisService = Depends(get_analysis_service)) -> dict:
    """Retire a legacy provider without deleting identity referenced by historical runs."""
    from datetime import datetime, timezone

    from app.api.local_guard import require_local_settings_mutation
    from app.models.analysis import LLMWorkflowRoute
    from app.services.llm.credential_resolver import CREDENTIAL_MANAGED_PROVIDER_TYPES

    require_local_settings_mutation(request)
    row = service.session.get(LLMProviderConfig, provider_id)
    if row is None:
        raise AnalysisError(404, "PROVIDER_NOT_FOUND", "Provider 不存在。")
    if row.provider_type not in {"SILICONFLOW", "DEEPSEEK", "LOCAL_OPENAI_COMPATIBLE"}:
        raise AnalysisError(400, "PROVIDER_NOT_LEGACY", "仅可退役已停用的遗留 Provider。")
    deployments = list(service.session.scalars(select(LLMModelDeployment).where(LLMModelDeployment.provider_config_id == row.id)))
    deployment_ids = [deployment.id for deployment in deployments]
    routes = list(service.session.scalars(select(LLMWorkflowRoute.workflow).where(LLMWorkflowRoute.deployment_id.in_(deployment_ids)))) if deployment_ids else []
    if routes:
        raise AnalysisError(409, "ROUTE_IN_USE", f"请先迁移工作流路由：{', '.join(routes)}")
    active = service.session.scalar(select(AnalysisRun.id).where(
        AnalysisRun.provider_type == row.provider_type,
        AnalysisRun.status.in_(["PENDING", "RUNNING"]),
    ).limit(1))
    if active is not None:
        raise AnalysisError(409, "PROVIDER_HAS_ACTIVE_RUNS", "该 Provider 仍有进行中的分析任务。")

    now = datetime.now(timezone.utc)
    row.enabled = False
    row.is_default = False
    row.updated_at = now
    for deployment in deployments:
        deployment.enabled = False
        deployment.archived_at = deployment.archived_at or now
        deployment.updated_at = now
    credential_cleared = False
    if row.provider_type in CREDENTIAL_MANAGED_PROVIDER_TYPES:
        from app.services.secrets.vault import clear_vault_secret

        credential_cleared = clear_vault_secret(service.session, row.provider_type)
    service.session.commit()
    return {
        "id": str(row.id),
        "provider_type": row.provider_type,
        "retired": True,
        "history_preserved": True,
        "credential_cleared_from_vault": credential_cleared,
    }


@router.get("/llm/routes")
def get_workflow_routes(service: AnalysisService = Depends(get_analysis_service)) -> dict:
    return {"routes": list_routes(service.session, service.settings), "options": list_route_options(service.session, service.settings)}


@router.put("/llm/routes")
def put_workflow_routes(body: RouteUpdate, service: AnalysisService = Depends(get_analysis_service)) -> dict:
    try:
        routes = update_routes(service.session, service.settings, body.model_dump())
    except RoutingError as exc:
        raise AnalysisError(409, exc.code, exc.message) from exc
    return {"routes": routes, "options": list_route_options(service.session, service.settings)}


@router.post("/sources/{source_id}/analyze", response_model=RunView)
def analyze(source_id: uuid.UUID, body: AnalyzeRequest | None = None, service: AnalysisService = Depends(get_analysis_service)) -> RunView:
    try:
        ensure_async_worker(settings=service.settings, inline=service.inline)
    except WorkerNotAvailableError as exc:
        raise HTTPException(status_code=503, detail={"code": exc.code, "message": exc.message}) from exc
    run = service.start(source_id, body.provider_type if body else None)
    return _run(run)


@router.post("/sources/{source_id}/reanalyze", response_model=RunView)
def reanalyze(source_id: uuid.UUID, body: AnalyzeRequest | None = None, service: AnalysisService = Depends(get_analysis_service)) -> RunView:
    try:
        ensure_async_worker(settings=service.settings, inline=service.inline)
    except WorkerNotAvailableError as exc:
        raise HTTPException(status_code=503, detail={"code": exc.code, "message": exc.message}) from exc
    run = service.start(source_id, body.provider_type if body else None)
    return _run(run)


@router.get("/analysis/funnel")
def analysis_funnel(session: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    return {"ok": True, **audit_user_sources(session, settings)}


@router.get("/analysis/backfill/preview")
def analysis_backfill_preview(session: Session = Depends(get_db)) -> dict:
    return {"ok": True, **preview_analysis_backfill(session)}


@router.get("/analysis/queue")
def analysis_queue(session: Session = Depends(get_db), limit: int = Query(default=40, ge=1, le=100)) -> dict:
    return {"ok": True, "summary": analysis_queue_summary(session), "jobs": list_analysis_jobs(session, limit=limit)}


@router.post("/analysis/backfill")
def analysis_backfill(body: AnalysisBackfillBody, session: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    try:
        ensure_async_worker(settings=settings, inline=settings.analysis_inline)
    except WorkerNotAvailableError as exc:
        raise HTTPException(status_code=503, detail={"code": exc.code, "message": exc.message}) from exc
    try:
        mode = body.mode if body.mode in {"fresh", "retry_failed", "retry_partial"} else "fresh"
        result = enqueue_analysis_backfill(
            session,
            source_ids=body.source_ids,
            confirm=body.confirm,
            include_partial=body.include_partial,
            mode=mode,
            settings=settings,
            enqueue_analysis=enqueue_analysis,
        )
    except AnalysisBatchError as exc:
        return {"ok": False, "code": exc.code, "message": exc.message}
    return {"ok": True, **result}


@router.get("/sources/{source_id}/analysis", response_model=AnalysisView)
def get_analysis(source_id: uuid.UUID, run_id: uuid.UUID | None = None, service: AnalysisService = Depends(get_analysis_service)) -> AnalysisView:
    return _view(*service.view(source_id, run_id))


@router.get("/analysis-runs/{run_id}", response_model=AnalysisView)
def get_run(run_id: uuid.UUID, service: AnalysisService = Depends(get_analysis_service)) -> AnalysisView:
    run = service.session.get(AnalysisRun, run_id)
    if run is None:
        from app.services.analysis.service import AnalysisError

        raise AnalysisError(404, "ANALYSIS_NOT_FOUND", "找不到分析任务。")
    return _view(*service.view(run.source_item_id, run_id))
