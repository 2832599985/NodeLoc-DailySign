from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from nodeloc_maintainer.application.checkin import CheckinService
from nodeloc_maintainer.application.maintainer import DailyMaintainer, delta_payload
from nodeloc_maintainer.application.reader import ReadingPlanner
from nodeloc_maintainer.application.reporting import ReportFormatter
from nodeloc_maintainer.application.stats import StatsService
from nodeloc_maintainer.application.tasks import TaskBusyError, TaskOptions, TaskSupervisor, serialize_event
from nodeloc_maintainer.application.topics import TopicDiscoveryService
from nodeloc_maintainer.domain.models import ReadingSessionResult, Settings
from nodeloc_maintainer.infrastructure.client_factory import NodeLocClientFactory
from nodeloc_maintainer.infrastructure.config import load_settings, validate_reading
from nodeloc_maintainer.infrastructure.config_writer import read_config_sanitized, save_config_with_backup
from nodeloc_maintainer.infrastructure.report_store import FileReportWriter
from nodeloc_maintainer.infrastructure.state import CompletionStateStore
from nodeloc_maintainer.infrastructure.time_provider import SystemDateProvider

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
CONSOLE_TEMPLATE_PATH = Path(__file__).with_name("web_console.html")


class JobRequest(BaseModel):
    mode: str = "dry_run"
    force_reading: bool = False
    max_accounts: int | None = None
    reading_minutes: float | None = None
    topics_per_account: int | None = None
    rounds: int = 1


class WebRuntime:
    def __init__(
        self,
        config_path: Path,
        state_file: Path,
        report_dir: Path,
        token: str | None,
    ):
        self.config_path = config_path
        self.state_file = state_file
        self.report_dir = report_dir
        self.token = token
        self.supervisor = TaskSupervisor()


def run_web_server(
    config_path: Path,
    state_file: Path,
    report_dir: Path,
    host: str,
    port: int,
    token: str | None = None,
) -> None:
    validate_web_security(host, token)
    runtime = WebRuntime(config_path=config_path, state_file=state_file, report_dir=report_dir, token=token)
    uvicorn.run(create_app(runtime), host=host, port=port, log_level="info")


def validate_web_security(host: str, token: str | None) -> None:
    if host not in LOCAL_HOSTS and not token:
        raise ValueError("Public Web mode requires --web-token or NODELOC_WEB_TOKEN.")


def read_console_html() -> str:
    return CONSOLE_TEMPLATE_PATH.read_text(encoding="utf-8")


def create_app(runtime: WebRuntime) -> FastAPI:
    app = FastAPI(title="NodeLoc Maintainer Console")

    def require_auth(authorization: str | None = Header(default=None)) -> None:
        if not runtime.token:
            return
        expected = f"Bearer {runtime.token}"
        if authorization != expected:
            raise HTTPException(status_code=401, detail="Unauthorized")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return read_console_html()

    @app.get("/api/status", dependencies=[Depends(require_auth)])
    def status() -> dict[str, Any]:
        settings = load_settings(runtime.config_path)
        return {
            "accounts": safe_account_summary(settings),
            "tasks": runtime.supervisor.status(),
            "reports": list_reports(runtime.report_dir),
        }

    @app.post("/api/jobs", dependencies=[Depends(require_auth)])
    def start_job(request: JobRequest) -> JSONResponse:
        options = TaskOptions(
            mode=request.mode,
            force_reading=request.force_reading,
            max_accounts=request.max_accounts,
            reading_minutes=request.reading_minutes,
            topics_per_account=request.topics_per_account,
            rounds=max(1, request.rounds),
        )
        try:
            task = runtime.supervisor.start(options, lambda task, emit: run_job(runtime, task, emit))
        except TaskBusyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return JSONResponse({"task": {"id": task.id, "status": task.status}})

    @app.get("/api/events")
    async def events(request: Request, last_event_id: int = 0, token: str | None = Query(default=None)):
        if runtime.token and token != runtime.token:
            raise HTTPException(status_code=401, detail="Unauthorized")

        async def stream():
            cursor = last_event_id
            while True:
                if await request.is_disconnected():
                    break
                events = runtime.supervisor.events_since(cursor)
                for event in events:
                    cursor = max(cursor, event.id)
                    yield f"id: {event.id}\n"
                    yield "event: task\n"
                    yield f"data: {json.dumps(serialize_event(event), ensure_ascii=False)}\n\n"
                await asyncio.sleep(0.8)

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/api/reports", dependencies=[Depends(require_auth)])
    def reports() -> list[dict[str, Any]]:
        return list_reports(runtime.report_dir)

    @app.get("/api/reports/{name}", dependencies=[Depends(require_auth)])
    def report_detail(name: str) -> PlainTextResponse:
        path = safe_report_path(runtime.report_dir, name)
        return PlainTextResponse(path.read_text(encoding="utf-8"))

    @app.get("/api/config", dependencies=[Depends(require_auth)])
    def get_config() -> dict[str, Any]:
        return read_config_sanitized(runtime.config_path)

    @app.put("/api/config", dependencies=[Depends(require_auth)])
    async def put_config(request: Request) -> dict[str, Any]:
        raw = await request.json()
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail="Config body must be an object.")
        try:
            backup_path = save_config_with_backup(runtime.config_path, raw)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "backup": str(backup_path), "config": read_config_sanitized(runtime.config_path)}

    return app


def run_job(runtime: WebRuntime, task, emit) -> str | None:
    settings = load_settings(runtime.config_path)
    dry_run = task.options.mode == "dry_run"
    force_reading = task.options.force_reading
    rounds = max(1, int(task.options.rounds or 1))

    if task.options.mode == "maintain_no_reading":
        settings = replace(settings, reading=replace(settings.reading, enabled=False))
    elif task.options.mode == "maintain_with_reading":
        settings = replace(settings, reading=replace(settings.reading, enabled=True))
    elif task.options.mode != "dry_run":
        raise ValueError(f"Unsupported job mode: {task.options.mode}")
    if task.options.reading_minutes is not None:
        settings = replace(settings, reading=replace(settings.reading, minutes_per_account=task.options.reading_minutes))
    if task.options.topics_per_account is not None:
        settings = replace(settings, reading=replace(settings.reading, topics_per_account=task.options.topics_per_account))

    validate_reading(settings.reading)
    report_parts: list[str] = []
    report_path: str | None = None
    for round_number in range(1, rounds + 1):
        emit("info", "round_start", None, f"round {round_number}/{rounds} started", {"round": round_number, "rounds": rounds})
        client_factory = NodeLocClientFactory(settings)
        maintainer = DailyMaintainer(
            settings=settings,
            state_store=CompletionStateStore(runtime.state_file),
            date_provider=SystemDateProvider(),
            checkin_service=CheckinService(settings, client_factory=client_factory),
            stats_service=StatsService(client_factory),
            topic_service=TopicDiscoveryService(client_factory),
            reading_planner=ReadingPlanner(),
            browser_reader=build_browser_reader(settings, dry_run=dry_run, force_reading=force_reading),
            event_sink=lambda event_type, message, account_name, data, round_number=round_number: emit(
                "info",
                event_type,
                account_name,
                message,
                {**data, "round": round_number, "rounds": rounds},
            ),
        )
        report = maintainer.run_once(
            dry_run=dry_run,
            skip_delays=True,
            force_checkin=False,
            force_reading=force_reading,
            max_accounts=task.options.max_accounts,
        )
        for result in report.results:
            if result.metrics_delta:
                emit(
                    "info",
                    "account_delta",
                    result.account_name,
                    "account metrics delta",
                    {**delta_payload(result.metrics_delta), "round": round_number, "rounds": rounds},
                )
        emit(
            "info",
            "round_complete",
            None,
            f"round {round_number}/{rounds} completed",
            {"round": round_number, "rounds": rounds, "accounts": len(report.results), "ok": report.ok},
        )
        report_parts.append(format_round_report(report, round_number, rounds))

    content = "\n\n".join(report_parts)
    report_path = FileReportWriter(runtime.report_dir).write(report.date_key, content)
    emit("info", "report_saved", None, "report saved", {"report_path": report_path})
    return report_path


def format_round_report(report, round_number: int, rounds: int) -> str:
    content = ReportFormatter().maintenance_report(report).rstrip()
    if rounds == 1:
        return content + "\n"
    return f"===== Round {round_number}/{rounds} =====\n{content}\n"


def build_browser_reader(settings: Settings, dry_run: bool, force_reading: bool):
    if dry_run or (not settings.reading.enabled and not force_reading):
        return DisabledBrowserReader()
    from nodeloc_maintainer.infrastructure.playwright_reader import PlaywrightBrowserReader

    return PlaywrightBrowserReader(timeout_ms=int(settings.timeout_seconds * 1000))


class DisabledBrowserReader:
    def run(self, account, topics, settings, target_seconds):
        return ReadingSessionResult(
            account_name=account.name,
            ok=False,
            message="browser reading is disabled for this run",
        )


def safe_account_summary(settings: Settings) -> list[dict[str, Any]]:
    return [{"name": account.name, "user_agent": account.user_agent} for account in settings.accounts]


def list_reports(report_dir: Path) -> list[dict[str, Any]]:
    if not report_dir.exists():
        return []
    reports = []
    for path in sorted(report_dir.glob("*.txt"), key=lambda item: item.stat().st_mtime, reverse=True)[:20]:
        reports.append(
            {
                "name": path.name,
                "size": path.stat().st_size,
                "modified": path.stat().st_mtime,
            }
        )
    return reports


def safe_report_path(report_dir: Path, name: str) -> Path:
    if "/" in name or "\\" in name or name in {"", ".", ".."} or not name.endswith(".txt"):
        raise HTTPException(status_code=404, detail="Report not found")
    root = report_dir.resolve()
    path = (root / name).resolve()
    if root not in path.parents or not path.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    return path
