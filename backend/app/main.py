from __future__ import annotations

import asyncio
import traceback
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from app.core.settings import get_settings
from app.collaboration.rbac import analysis_editor, current_member, require_admin, require_editor
from app.collaboration.store import TeamStore, get_team_store
from app.history.store import HistoryStore
from app.monitoring.dashboard import DashboardService, get_dashboard
from app.monitoring.middleware import ObservabilityMiddleware
from app.monitoring.telemetry import get_telemetry
from app.orchestrator import AetherOrchestrator
from app.prompts.ops import deploy_version, get_prompt_ops_store, prompt_catalog
from app.reporting.emailer import send_report_email
from app.reporting.exporters import SUPPORTED_FORMATS, build_export
from app.schemas.context import ReasoningContext
from app.schemas.factor import Factor
from app.schemas.factor_advisor import FactorAdviseRequest
from app.utils.llm_client import LLMClient
from app.utils.pdf_parser import extract_metadata_and_text
from app.utils.resilient_llm import LLMUnavailableError
from app.webhooks.service import WebhookService

settings = get_settings()
telemetry = get_telemetry()

API_TAGS = [
    {
        "name": "Analysis",
        "description": "Synchronous analysis endpoints. Send a reasoning context (or PDF) and receive a full factor-by-factor debate with a synthesized conclusion, confidence score, and explainability traces.",
    },
    {
        "name": "Factor Advice",
        "description": "Two-phase workflow support. `POST /factors/advise` proposes a ranked set of factors from a context; pass the returned `context` plus selected factors to `POST /analyze-with-factors`.",
    },
    {
        "name": "Webhooks",
        "description": "Asynchronous analysis and delivery. Register an endpoint, submit an analysis job with `POST /webhooks/analyze`, poll `GET /webhooks/jobs/{job_id}`, and receive signed `analysis.completed` events on success.",
    },
    {
        "name": "History",
        "description": "Persisted analysis records, per-factor scores, comparisons, timelines, and consistently important factor trends.",
    },
    {
        "name": "Dashboard",
        "description": "Operational metrics: API call volume, estimated LLM cost breakdown, most expensive analyses, cost trends, and budget alerts.",
    },
    {
        "name": "Prompts",
        "description": "Prompt versioning and experiment workflow: browse versions, view live quality metrics from real runs, vote on the best version, and deploy the winner (admin).",
    },
    {
        "name": "Team",
        "description": "Multi-user collaboration: team members with viewer/editor/admin roles, per-analysis sharing, and role enforcement on comments and annotations.",
    },
    {
        "name": "Operations",
        "description": "Health, status, metrics, report export, and email delivery.",
    },
]

API_DESCRIPTION = """
Project AETHER performs **AI-driven analysis and debate** on a reasoning context
(narrative text, extracted facts, metrics) or a PDF document. For every factor it
stages a structured support/opposition debate, synthesizes a conclusion with a
confidence score, and exposes full explainability traces.

## Two-phase workflow

1. **Suggest** — `POST /factors/advise` (or `/factors/advise-pdf`) returns a ranked
   `factor_plan` plus a reusable `context` in `FactorAdviseResponse`.
2. **Analyze** — `POST /analyze-with-factors` with the normalized `context` and the
   selected `factors` produces the final `FinalReport` and debate logs.

## Async + webhooks

`POST /webhooks/analyze` returns immediately with a `job_id` (`202 Accepted`).
When the analysis finishes, the result is delivered to your endpoint as a signed
`analysis.completed` event. Poll `GET /webhooks/jobs/{job_id}` or read the result
from the webhook body.

## Error handling

All errors return the JSON envelope:

```json
{"detail": {"message": "...", "request_id": "...", "trace_id": "..."}}
```

| HTTP | Error code | Meaning |
|------|-----------|---------|
| 400 | `invalid_input` | Malformed body, unsupported file type or format |
| 404 | `not_found` | Unknown analysis id, webhook id, or job id |
| 500 | `internal_error` | Unexpected server failure |
| 503 | `llm_unavailable` | The language model provider is unavailable |

See `docs/API.md` for example requests/responses and the SDK packages under `sdk/`.
"""

app = FastAPI(
    title="Project AETHER",
    version="1.0.0",
    description=API_DESCRIPTION,
    openapi_tags=API_TAGS,
    contact={
        "name": "Project AETHER",
        "url": "https://github.com/anomalyco/opencode",
    },
    license_info={"name": "MIT"},
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(ObservabilityMiddleware)

orchestrator = AetherOrchestrator()
history_store = HistoryStore(
    db_path=settings.history_db_path or None,
    enabled=settings.history_enabled,
)
webhook_service = WebhookService(orchestrator=orchestrator)
dashboard_service: DashboardService = get_dashboard(telemetry=telemetry)
prompt_ops_store = get_prompt_ops_store(db_path=settings.prompt_db_path or None)
team_store = get_team_store(db_path=settings.team_db_path or None)
ACTIVE_VERSIONS_FILE = Path(__file__).resolve().parent / "prompts" / "active_versions.json"


class EmailReportRequest(BaseModel):
    email: str
    format: str = "pdf"


class AnalyzeFactorsRequest(BaseModel):
    context: ReasoningContext
    factors: list[Factor]


class CompareRequest(BaseModel):
    ids: list[str]


class WebhookRegisterRequest(BaseModel):
    url: str
    secret: str = "auto"
    description: str = ""
    events: Optional[List[str]] = None


class WebhookTestRequest(BaseModel):
    webhook_id: str


class WebhookAnalyzeRequest(BaseModel):
    context: ReasoningContext
    webhook_id: str = ""
    webhook_url: str = ""
    webhook_secret: str = ""
    factors: Optional[List[Factor]] = None
    input_type: str = "text"
    max_attempts: Optional[int] = None


class PromptDeployRequest(BaseModel):
    version: str
    reason: str = ""


class PromptVoteRequest(BaseModel):
    version: str
    score: int = 1


class PromptCompareRequest(BaseModel):
    name: str
    versions: List[str]


class MemberCreateRequest(BaseModel):
    name: str
    email: str
    role: str = "viewer"


class MemberRoleRequest(BaseModel):
    role: str


class IdentityRequest(BaseModel):
    email: str
    name: str = ""


class ShareRequest(BaseModel):
    member_email: str
    role: str = "viewer"


class ShareRoleRequest(BaseModel):
    role: str


class CommentCreateRequest(BaseModel):
    anchor: str = ""
    body: str
    parent_id: str = ""


class CommentResolveRequest(BaseModel):
    resolved: bool = True


class AnnotationCreateRequest(BaseModel):
    anchor: str = ""
    content: str


class AnnotationUpdateRequest(BaseModel):
    content: str


@app.on_event("startup")
async def _recover_webhook_jobs() -> None:
    recovered = await asyncio.to_thread(webhook_service.store.recover_stale_running_jobs)
    if recovered:
        print(f"[WEBHOOKS] Marked {recovered} stale job(s) as failed after restart")


def _validate_export_format(fmt: str) -> str:
    normalized = fmt.strip().lower()
    if normalized == "md":
        normalized = "markdown"
    if normalized not in SUPPORTED_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported export format: {fmt}",
        )
    return normalized


def _report_response(
    result: dict,
    input_text: str,
    fmt: str,
    *,
    default_filename: str | None = None,
) -> Response:
    fmt = _validate_export_format(fmt)
    data, media_type, filename = build_export(result, input_text, fmt)
    if default_filename and fmt == "pdf":
        filename = default_filename
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def _request_meta(request: Request | None = None) -> dict[str, str]:
    request_id = getattr(getattr(request, "state", None), "request_id", None) if request else None
    trace_id = getattr(getattr(request, "state", None), "trace_id", None) if request else None
    return {
        "request_id": request_id or uuid.uuid4().hex,
        "trace_id": trace_id or uuid.uuid4().hex,
    }


def _sanitized_message(detail: str, *, request_id: str, trace_id: str) -> dict[str, str]:
    return {
        "message": detail,
        "request_id": request_id,
        "trace_id": trace_id,
    }


@app.exception_handler(LLMUnavailableError)
async def llm_unavailable_handler(request: Request, exc: LLMUnavailableError):
    meta = _request_meta(request)
    return JSONResponse(
        content={
            "detail": {
                "message": exc.user_message,
                "request_id": meta["request_id"],
                "trace_id": meta["trace_id"],
            }
        },
        status_code=503,
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        raise exc
    meta = _request_meta(request)
    traceback.print_exc()
    return JSONResponse(
        content={
            "detail": {
                "message": "The service encountered an unexpected error.",
                "request_id": meta["request_id"],
                "trace_id": meta["trace_id"],
            }
        },
        status_code=500,
    )


@app.post("/analyze", tags=["Analysis"])
async def analyze(context: ReasoningContext, request: Request):
    try:
        return await orchestrator.analyze(context)
    except HTTPException:
        raise
    except Exception as exc:
        traceback.print_exc()
        meta = _request_meta(request)
        raise HTTPException(
            status_code=500,
            detail=_sanitized_message("Analysis failed.", request_id=meta["request_id"], trace_id=meta["trace_id"]),
        ) from exc


@app.post("/analyze-pdf", tags=["Analysis"])
async def analyze_pdf(file: UploadFile = File(...)):
    try:
        if not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Only PDF files are supported")

        file_bytes = await file.read()
        pdf_data = await asyncio.to_thread(extract_metadata_and_text, file_bytes)

        context = ReasoningContext(
            narrative=pdf_data["text"],
            extracted_facts=[],
            metrics=pdf_data.get("metrics", []),
            assumptions=[],
            limitations=[],
        )
        return await orchestrator.analyze(context, source_document=pdf_data, input_type="pdf")
    except HTTPException:
        raise
    except Exception as exc:
        traceback.print_exc()
        meta = _request_meta(request)
        raise HTTPException(
            status_code=500,
            detail=_sanitized_message("PDF analysis failed.", request_id=meta["request_id"], trace_id=meta["trace_id"]),
        ) from exc


@app.post("/factors/advise", tags=["Factor Advice"])
async def factors_advise(request: FactorAdviseRequest, req: Request):
    try:
        return await orchestrator.advise(request.context, custom_factors=request.custom_factors)
    except HTTPException:
        raise
    except Exception as exc:
        traceback.print_exc()
        meta = _request_meta(req)
        raise HTTPException(
            status_code=500,
            detail=_sanitized_message("Factor analysis failed.", request_id=meta["request_id"], trace_id=meta["trace_id"]),
        ) from exc


@app.post("/factors/advise-pdf", tags=["Factor Advice"])
async def factors_advise_pdf(file: UploadFile = File(...)):
    try:
        if not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Only PDF files are supported")

        file_bytes = await file.read()
        pdf_data = await asyncio.to_thread(extract_metadata_and_text, file_bytes)

        context = ReasoningContext(
            narrative=pdf_data["text"],
            extracted_facts=[],
            metrics=pdf_data.get("metrics", []),
            assumptions=[],
            limitations=[],
        )
        return await orchestrator.advise(context)
    except HTTPException:
        raise
    except Exception as exc:
        traceback.print_exc()
        meta = _request_meta()
        raise HTTPException(
            status_code=500,
            detail=_sanitized_message("PDF factor analysis failed.", request_id=meta["request_id"], trace_id=meta["trace_id"]),
        ) from exc


@app.post("/analyze-with-factors", tags=["Analysis"])
async def analyze_with_factors(request: AnalyzeFactorsRequest, req: Request):
    try:
        return await orchestrator.analyze(
            request.context,
            factors=request.factors,
            input_type="text",
        )
    except HTTPException:
        raise
    except Exception as exc:
        traceback.print_exc()
        meta = _request_meta(req)
        raise HTTPException(
            status_code=500,
            detail=_sanitized_message("Analysis failed.", request_id=meta["request_id"], trace_id=meta["trace_id"]),
        ) from exc


@app.get("/", tags=["Operations"])
async def root(request: Request):
    meta = _request_meta(request)
    return {
        "service": "Project AETHER",
        "status": "ok",
        "environment": settings.environment,
        **meta,
    }


@app.get("/status", tags=["Operations"])
async def status():
    return orchestrator.status


@app.get("/health", tags=["Operations"])
async def health():
    health_state = telemetry.health()
    health_state["service"] = "Project AETHER"
    health_state["telemetry"] = telemetry.snapshot().to_dict()
    return health_state


@app.get("/health/groq", tags=["Operations"])
async def groq_health(deep: bool = False):
    checks: list[dict[str, object]] = []
    llm = orchestrator.llm.primary if hasattr(orchestrator.llm, "primary") else orchestrator.llm
    models = [getattr(llm, "model", None) or settings.profile_for().synthesis]
    if deep:
        models = list(dict.fromkeys([
            settings.profile_for().factor_extractor,
            settings.profile_for().support,
            settings.profile_for().opposition,
            settings.profile_for().synthesis,
        ]))

    for model in models:
        if not model:
            continue
        try:
            probe = LLMClient(model=model)
            await asyncio.wait_for(
                probe.acompletion(
                    "Return OK.",
                    system="You are a health check. Respond with OK only.",
                    json_mode=False,
                    config={"max_completion_tokens": 1, "temperature": 0},
                    agent_name="health_check",
                ),
                timeout=settings.groq_timeout_seconds,
            )
            checks.append({"model": model, "status": "ok"})
        except Exception as exc:
            checks.append({
                "model": model,
                "status": "degraded",
                "error_type": type(exc).__name__,
                "message": "The model is temporarily unavailable.",
            })

    snapshot = telemetry.snapshot()
    status = "ok" if all(check["status"] == "ok" for check in checks) and not snapshot.alerts else "degraded"
    return {
        "status": status,
        "checks": checks,
        "limits": {
            "rpm": settings.request_rate_limit_rpm,
            "alert_threshold": settings.request_rate_limit_alert_threshold,
            "error_rate_threshold": settings.error_rate_alert_threshold,
        },
        "telemetry": snapshot.to_dict(),
    }


@app.get("/metrics", tags=["Operations"])
async def metrics():
    snapshot = telemetry.snapshot()
    return snapshot.to_dict()


@app.post("/analyze-report", tags=["Analysis"])
async def analyze_report(context: ReasoningContext, request: Request, format: str = "pdf"):
    try:
        result = await orchestrator.analyze(context)
        return _report_response(result, context.narrative, format)
    except HTTPException:
        raise
    except Exception as exc:
        traceback.print_exc()
        meta = _request_meta(request)
        raise HTTPException(
            status_code=500,
            detail=_sanitized_message("Report generation failed.", request_id=meta["request_id"], trace_id=meta["trace_id"]),
        ) from exc


@app.post("/analyze-pdf-report", tags=["Analysis"])
async def analyze_pdf_report(
    file: UploadFile = File(...),
    format: str = "pdf",
):
    try:
        if not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Only PDF files are supported")

        file_bytes = await file.read()
        pdf_data = await asyncio.to_thread(extract_metadata_and_text, file_bytes)

        context = ReasoningContext(
            narrative=pdf_data["text"],
            extracted_facts=[],
            metrics=pdf_data.get("metrics", []),
            assumptions=[],
            limitations=[],
        )
        result = await orchestrator.analyze(context, source_document=pdf_data, input_type="pdf")
        return _report_response(
            result,
            pdf_data["text"],
            format,
            default_filename="PDF_Analysis_Report.pdf",
        )
    except HTTPException:
        raise
    except Exception as exc:
        traceback.print_exc()
        meta = _request_meta(request)
        raise HTTPException(
            status_code=500,
            detail=_sanitized_message("Report generation failed.", request_id=meta["request_id"], trace_id=meta["trace_id"]),
        ) from exc


@app.get("/download-report", tags=["Operations"])
async def download_report(request: Request, format: str = "pdf"):
    try:
        if not orchestrator.last_result or not orchestrator.last_narrative:
            raise HTTPException(status_code=400, detail="No analysis available for report download")

        return _report_response(orchestrator.last_result, orchestrator.last_narrative, format)
    except HTTPException:
        raise
    except Exception as exc:
        traceback.print_exc()
        meta = _request_meta(request)
        raise HTTPException(
            status_code=500,
            detail=_sanitized_message("Report download failed.", request_id=meta["request_id"], trace_id=meta["trace_id"]),
        ) from exc


@app.post("/send-report", tags=["Operations"])
async def send_report(request: EmailReportRequest, req: Request):
    try:
        if not orchestrator.last_result:
            raise HTTPException(status_code=400, detail="No analysis available to send")

        fmt = _validate_export_format(request.format)
        outcome = await asyncio.to_thread(
            send_report_email,
            request.email,
            orchestrator.last_result,
            orchestrator.last_narrative or "",
            fmt,
        )
        status_code = outcome.pop("status_code", 200)
        if status_code >= 400:
            raise HTTPException(status_code=status_code, detail=outcome.get("message"))
        return JSONResponse(outcome, status_code=status_code)
    except HTTPException:
        raise
    except Exception as exc:
        traceback.print_exc()
        meta = _request_meta(req)
        raise HTTPException(
            status_code=500,
            detail=_sanitized_message("Failed to send report.", request_id=meta["request_id"], trace_id=meta["trace_id"]),
        ) from exc


@app.get("/history", tags=["History"])
async def list_history(limit: int = 50, offset: int = 0):
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    return await asyncio.to_thread(history_store.list_analyses, limit=limit, offset=offset)


@app.get("/history/trends/timeline", tags=["History"])
async def history_timeline(limit: int = 100):
    return {"timeline": await asyncio.to_thread(history_store.timeline, limit=limit)}


@app.get("/history/trends/factors", tags=["History"])
async def history_consistent_factors(min_occurrences: int = 2):
    return {
        "factors": await asyncio.to_thread(
            history_store.consistent_factors,
            min_occurrences=min_occurrences,
        )
    }


@app.post("/history/compare", tags=["History"])
async def compare_history(request: CompareRequest):
    ids = [analysis_id for analysis_id in request.ids if analysis_id]
    if not ids:
        raise HTTPException(status_code=400, detail="At least one analysis id is required")
    analyses = await asyncio.to_thread(history_store.compare_analyses, ids)
    return {"analyses": analyses}


@app.get("/history/{analysis_id}", tags=["History"])
async def get_history(analysis_id: str):
    record = await asyncio.to_thread(history_store.get_analysis, analysis_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return record


@app.delete("/history/{analysis_id}", tags=["History"])
async def delete_history(analysis_id: str):
    deleted = await asyncio.to_thread(history_store.delete_analysis, analysis_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return {"deleted": True, "analysis_id": analysis_id}


# ---------------------------------------------------------------------------
# Webhooks (async analysis + delivery)
# ---------------------------------------------------------------------------


@app.post("/webhooks/endpoints", tags=["Webhooks"])
async def register_webhook(request: WebhookRegisterRequest, req: Request):
    try:
        endpoint = await asyncio.to_thread(
            webhook_service.register_endpoint,
            url=request.url,
            description=request.description,
            secret=request.secret,
            events=request.events,
        )
        return JSONResponse(endpoint, status_code=201)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        traceback.print_exc()
        meta = _request_meta(req)
        raise HTTPException(
            status_code=500,
            detail=_sanitized_message("Failed to register webhook.", request_id=meta["request_id"], trace_id=meta["trace_id"]),
        ) from exc


@app.get("/webhooks/endpoints", tags=["Webhooks"])
async def list_webhook_endpoints():
    return {"endpoints": await asyncio.to_thread(webhook_service.store.list_endpoints)}


@app.post("/webhooks/endpoints/test", tags=["Webhooks"])
async def test_webhook(request: WebhookTestRequest, req: Request):
    try:
        outcome = await webhook_service.test_ping(request.webhook_id)
        return {"webhook_id": request.webhook_id, "ping": outcome}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        traceback.print_exc()
        meta = _request_meta(req)
        raise HTTPException(
            status_code=500,
            detail=_sanitized_message("Webhook ping failed.", request_id=meta["request_id"], trace_id=meta["trace_id"]),
        ) from exc


@app.delete("/webhooks/endpoints/{webhook_id}", tags=["Webhooks"])
async def delete_webhook(webhook_id: str):
    deleted = await asyncio.to_thread(webhook_service.delete_endpoint, webhook_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found")
    return {"deleted": True, "webhook_id": webhook_id}


@app.post("/webhooks/analyze", tags=["Webhooks"])
async def webhook_analyze(request: WebhookAnalyzeRequest, req: Request):
    try:
        job = await webhook_service.submit_analysis(
            context=request.context,
            webhook_id=request.webhook_id,
            webhook_url=request.webhook_url,
            webhook_secret=request.webhook_secret,
            factors=request.factors,
            input_type=request.input_type,
            max_attempts=request.max_attempts,
        )
        return JSONResponse(
            {
                "job_id": job["job_id"],
                "webhook_id": job["webhook_id"],
                "status": "queued",
                "result_url": f"/webhooks/jobs/{job['job_id']}",
            },
            status_code=202,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        traceback.print_exc()
        meta = _request_meta(req)
        raise HTTPException(
            status_code=500,
            detail=_sanitized_message("Failed to queue webhook analysis.", request_id=meta["request_id"], trace_id=meta["trace_id"]),
        ) from exc


@app.get("/webhooks/jobs", tags=["Webhooks"])
async def list_webhook_jobs(webhook_id: str = "", status: str = "", limit: int = 50):
    limit = max(1, min(limit, 200))
    return await asyncio.to_thread(
        webhook_service.list_jobs,
        webhook_id=webhook_id,
        status=status,
        limit=limit,
    )


@app.get("/webhooks/jobs/{job_id}", tags=["Webhooks"])
async def get_webhook_job(job_id: str):
    job = await asyncio.to_thread(webhook_service.get_job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Webhook job not found")
    return job


# ---------------------------------------------------------------------------
# Dashboard (usage, cost, budget)
# ---------------------------------------------------------------------------


@app.get("/dashboard", tags=["Dashboard"])
async def dashboard():
    return await asyncio.to_thread(dashboard_service.full_report)


@app.get("/dashboard/costs", tags=["Dashboard"])
async def dashboard_costs():
    report = await asyncio.to_thread(dashboard_service.full_report)
    return {"costs": report["costs"], "usage": report["usage"]}


@app.get("/dashboard/budget", tags=["Dashboard"])
async def dashboard_budget():
    report = await asyncio.to_thread(dashboard_service.full_report)
    return {"budget": report["budget"], "alerts": report["alerts"]}


@app.get("/dashboard/cost-trend", tags=["Dashboard"])
async def dashboard_cost_trend(days: int = 30):
    days = max(1, min(days, 90))
    report = await asyncio.to_thread(dashboard_service.full_report)
    return {"trend": report["cost_trend"][-days:]}


@app.get("/dashboard/expensive-analyses", tags=["Dashboard"])
async def dashboard_expensive(limit: int = 10):
    limit = max(1, min(limit, 50))
    report = await asyncio.to_thread(dashboard_service.full_report)
    return {"analyses": report["expensive_analyses"][:limit]}


# ---------------------------------------------------------------------------
# Prompts (versioning, metrics, voting, deploy)
# ---------------------------------------------------------------------------


@app.get("/prompts", tags=["Prompts"])
async def list_prompts(member: Optional[Dict[str, Any]] = Depends(current_member)):
    catalog = await asyncio.to_thread(
        prompt_catalog,
        registry=orchestrator.prompt_registry,
        tracker=orchestrator.prompt_tracker,
        ops_store=prompt_ops_store,
        member_email=(member or {}).get("email", ""),
    )
    return {"prompts": catalog}


@app.get("/prompts/{name}", tags=["Prompts"])
async def get_prompt(name: str, member: Optional[Dict[str, Any]] = Depends(current_member)):
    catalog = await asyncio.to_thread(
        prompt_catalog,
        registry=orchestrator.prompt_registry,
        tracker=orchestrator.prompt_tracker,
        ops_store=prompt_ops_store,
        member_email=(member or {}).get("email", ""),
    )
    entry = next((p for p in catalog if p["name"] == name), None)
    if entry is None:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return entry


@app.get("/prompts/{name}/versions/{version}", tags=["Prompts"])
async def get_prompt_version(name: str, version: str):
    try:
        template = orchestrator.prompt_registry.get(name, version=version)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return template.model_dump(mode="json")


@app.get("/prompts/{name}/compare", tags=["Prompts"])
async def compare_prompt_versions(name: str, versions: str = ""):
    wanted = [v.strip() for v in versions.split(",") if v.strip()]
    if not wanted:
        raise HTTPException(status_code=400, detail="Provide at least one version via ?versions=v1,v2")
    registry = orchestrator.prompt_registry
    runs = orchestrator.prompt_tracker.load_runs(name)
    from app.prompts.ops import aggregate_metrics

    metrics = aggregate_metrics(runs)
    votes = {v["version"]: v for v in prompt_ops_store.votes(name)}

    compared = []
    for version in wanted:
        try:
            template = registry.get(name, version=version)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        compared.append(
            {
                "version": template.version,
                "status": template.status,
                "description": template.description,
                "role": template.role,
                "task_definition": template.task_definition,
                "rules": template.rules,
                "output_format_spec": template.output_format_spec,
                "few_shot_example_count": {
                    domain: len(examples) for domain, examples in template.few_shot_examples.items()
                },
                "metrics": metrics.get(template.version, {}),
                "votes": votes.get(template.version, {"count": 0, "score": 0}),
            }
        )
    return {"name": name, "versions": compared}


@app.post("/prompts/{name}/deploy", tags=["Prompts"])
async def deploy_prompt(name: str, request: PromptDeployRequest, admin: Dict[str, Any] = Depends(require_admin)):
    try:
        outcome = await asyncio.to_thread(
            deploy_version,
            registry=orchestrator.prompt_registry,
            ops_store=prompt_ops_store,
            active_versions_file=ACTIVE_VERSIONS_FILE,
            name=name,
            version=request.version,
            member_email=admin["email"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    orchestrator.refresh_prompt_registry()
    return {**outcome, "deployed": True, "reason": request.reason}


@app.post("/prompts/{name}/vote", tags=["Prompts"])
async def vote_prompt(name: str, request: PromptVoteRequest, editor: Dict[str, Any] = Depends(require_editor)):
    try:
        orchestrator.prompt_registry.get(name, version=request.version)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    score = max(-1, min(1, request.score))
    if score == 0:
        raise HTTPException(status_code=400, detail="score must be -1 or 1")
    vote = await asyncio.to_thread(
        prompt_ops_store.vote,
        prompt_name=name,
        version=request.version,
        member_email=editor["email"],
        score=score,
    )
    return vote


# ---------------------------------------------------------------------------
# Team (members, roles, sharing, comments, annotations)
# ---------------------------------------------------------------------------


@app.get("/team/members", tags=["Team"])
async def list_team_members():
    return {"members": await asyncio.to_thread(team_store.list_members)}


@app.post("/team/identity", tags=["Team"])
async def adopt_identity(request: IdentityRequest):
    """Self-register (or re-adopt) an identity. New members start as viewers."""
    member = await asyncio.to_thread(
        team_store.add_member,
        name=request.name.strip() or request.email.split("@")[0],
        email=request.email,
        role="viewer",
    )
    return member


@app.post("/team/members", tags=["Team"])
async def add_team_member(request: MemberCreateRequest, admin: Dict[str, Any] = Depends(require_admin)):
    try:
        member = await asyncio.to_thread(
            team_store.add_member,
            name=request.name.strip(),
            email=request.email,
            role=request.role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return member


@app.patch("/team/members/{member_id}", tags=["Team"])
async def update_team_member(member_id: str, request: MemberRoleRequest, admin: Dict[str, Any] = Depends(require_admin)):
    try:
        member = await asyncio.to_thread(team_store.update_role, member_id, request.role)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")
    return member


@app.delete("/team/members/{member_id}", tags=["Team"])
async def remove_team_member(member_id: str, admin: Dict[str, Any] = Depends(require_admin)):
    removed = await asyncio.to_thread(team_store.remove_member, member_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Member not found")
    return {"deleted": True, "member_id": member_id}


@app.get("/analyses/{analysis_id}/shares", tags=["Team"])
async def list_shares(analysis_id: str):
    return {"shares": await asyncio.to_thread(team_store.list_shares, analysis_id)}


@app.post("/analyses/{analysis_id}/shares", tags=["Team"])
async def share_analysis(
    analysis_id: str,
    request: ShareRequest,
    editor: Dict[str, Any] = Depends(analysis_editor),
):
    target = await asyncio.to_thread(team_store.get_member_by_email, request.member_email)
    if target is None:
        raise HTTPException(status_code=404, detail="Member not found")
    share = await asyncio.to_thread(
        team_store.share_analysis,
        analysis_id=analysis_id,
        member_id=target["member_id"],
        role=request.role,
    )
    return share


@app.patch("/analyses/{analysis_id}/shares/{member_id}", tags=["Team"])
async def update_share(
    analysis_id: str,
    member_id: str,
    request: ShareRoleRequest,
    editor: Dict[str, Any] = Depends(analysis_editor),
):
    try:
        updated = await asyncio.to_thread(
            team_store.update_share, analysis_id, member_id, request.role
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=404, detail="Share not found")
    return {"analysis_id": analysis_id, "member_id": member_id, "role": request.role}


@app.delete("/analyses/{analysis_id}/shares/{member_id}", tags=["Team"])
async def remove_share(
    analysis_id: str,
    member_id: str,
    editor: Dict[str, Any] = Depends(analysis_editor),
):
    removed = await asyncio.to_thread(team_store.remove_share, analysis_id, member_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Share not found")
    return {"deleted": True, "analysis_id": analysis_id, "member_id": member_id}


@app.get("/analyses/{analysis_id}/comments", tags=["Team"])
async def list_comments(analysis_id: str):
    return {"comments": await asyncio.to_thread(team_store.list_comments, analysis_id)}


@app.post("/analyses/{analysis_id}/comments", tags=["Team"])
async def add_comment(
    analysis_id: str,
    request: CommentCreateRequest,
    editor: Dict[str, Any] = Depends(analysis_editor),
):
    if not request.body.strip():
        raise HTTPException(status_code=400, detail="Comment body is required")
    comment = await asyncio.to_thread(
        team_store.add_comment,
        analysis_id=analysis_id,
        anchor=request.anchor,
        body=request.body,
        member_id=editor["member_id"],
        parent_id=request.parent_id,
    )
    return comment


@app.patch("/comments/{comment_id}", tags=["Team"])
async def resolve_comment(
    comment_id: str,
    request: CommentResolveRequest,
    member: Optional[Dict[str, Any]] = Depends(current_member),
):
    comment = await asyncio.to_thread(team_store.get_comment, comment_id)
    if comment is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    if member is None:
        raise HTTPException(status_code=403, detail="authentication required")
    allowed = member["role"] == "admin"
    share_role = await asyncio.to_thread(
        team_store.get_share_role, comment["analysis_id"], member["member_id"]
    )
    if share_role == "editor":
        allowed = True
    elif member["role"] == "editor" and share_role != "viewer":
        allowed = True
    if not allowed:
        raise HTTPException(status_code=403, detail="editor access required on this analysis")
    updated = await asyncio.to_thread(
        team_store.set_comment_resolved, comment_id, request.resolved
    )
    return updated


@app.delete("/comments/{comment_id}", tags=["Team"])
async def delete_comment(
    comment_id: str,
    member: Optional[Dict[str, Any]] = Depends(current_member),
):
    comment = await asyncio.to_thread(team_store.get_comment, comment_id)
    if comment is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    if member is None:
        raise HTTPException(status_code=403, detail="authentication required")
    share_role = await asyncio.to_thread(
        team_store.get_share_role, comment["analysis_id"], member["member_id"]
    )
    allowed = member["role"] == "admin" or (
        member["role"] == "editor" and share_role != "viewer"
    ) or share_role == "editor"
    if not allowed:
        raise HTTPException(status_code=403, detail="editor access required on this analysis")
    removed = await asyncio.to_thread(team_store.delete_comment, comment_id)
    return {"deleted": True, "comment_id": comment_id}


@app.get("/analyses/{analysis_id}/annotations", tags=["Team"])
async def list_annotations(analysis_id: str):
    return {"annotations": await asyncio.to_thread(team_store.list_annotations, analysis_id)}


@app.post("/analyses/{analysis_id}/annotations", tags=["Team"])
async def add_annotation(
    analysis_id: str,
    request: AnnotationCreateRequest,
    editor: Dict[str, Any] = Depends(analysis_editor),
):
    if not request.content.strip():
        raise HTTPException(status_code=400, detail="Annotation content is required")
    annotation = await asyncio.to_thread(
        team_store.add_annotation,
        analysis_id=analysis_id,
        anchor=request.anchor,
        content=request.content,
        member_id=editor["member_id"],
    )
    return annotation


@app.patch("/annotations/{annotation_id}", tags=["Team"])
async def update_annotation(
    annotation_id: str,
    request: AnnotationUpdateRequest,
    member: Optional[Dict[str, Any]] = Depends(current_member),
):
    annotation = await asyncio.to_thread(team_store.get_annotation, annotation_id)
    if annotation is None:
        raise HTTPException(status_code=404, detail="Annotation not found")
    if member is None:
        raise HTTPException(status_code=403, detail="authentication required")
    share_role = await asyncio.to_thread(
        team_store.get_share_role, annotation["analysis_id"], member["member_id"]
    )
    allowed = member["role"] == "admin" or (
        member["role"] == "editor" and share_role != "viewer"
    ) or share_role == "editor"
    if not allowed:
        raise HTTPException(status_code=403, detail="editor access required on this analysis")
    updated = await asyncio.to_thread(team_store.update_annotation, annotation_id, request.content)
    return updated


@app.delete("/annotations/{annotation_id}", tags=["Team"])
async def delete_annotation(
    annotation_id: str,
    member: Optional[Dict[str, Any]] = Depends(current_member),
):
    annotation = await asyncio.to_thread(team_store.get_annotation, annotation_id)
    if annotation is None:
        raise HTTPException(status_code=404, detail="Annotation not found")
    if member is None:
        raise HTTPException(status_code=403, detail="authentication required")
    share_role = await asyncio.to_thread(
        team_store.get_share_role, annotation["analysis_id"], member["member_id"]
    )
    allowed = member["role"] == "admin" or (
        member["role"] == "editor" and share_role != "viewer"
    ) or share_role == "editor"
    if not allowed:
        raise HTTPException(status_code=403, detail="editor access required on this analysis")
    removed = await asyncio.to_thread(team_store.delete_annotation, annotation_id)
    return {"deleted": True, "annotation_id": annotation_id}


@app.get("/analyses/{analysis_id}/collab", tags=["Team"])
async def collab_bundle(analysis_id: str):
    shares, comments, annotations = await asyncio.gather(
        asyncio.to_thread(team_store.list_shares, analysis_id),
        asyncio.to_thread(team_store.list_comments, analysis_id),
        asyncio.to_thread(team_store.list_annotations, analysis_id),
    )
    return {"shares": shares, "comments": comments, "annotations": annotations}
