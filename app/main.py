from fastapi import FastAPI

from app.api.routes import router
from app.config import settings
from app.graph.workflow import graph
from app.integrations.produck.scheduler import build_produck_scheduler
from app.logging_config import configure_logging
from app.services.container import build_produck_client, build_services

configure_logging(settings.log_level)

app = FastAPI(title="AI Incident Resolution Agent", version="1.0.0")
app.include_router(router)


@app.on_event("startup")
async def start_produck_scheduler() -> None:
    if not settings.produck_poll_enabled:
        app.state.produck_scheduler = None
        return
    services = build_services()
    client = build_produck_client(settings, services.groq)
    scheduler = build_produck_scheduler(
        client=client,
        parcle=services.parcle,
        groq=services.groq,
        graph=graph,
        state_path=settings.produck_state_path,
        legacy_state_path=settings.produck_legacy_state_path,
        feedback_ids=settings.produck_feedback_ids,
        poll_interval_seconds=settings.produck_poll_interval_seconds,
        close_on_success=settings.produck_close_on_success,
    )
    app.state.produck_scheduler = scheduler
    scheduler.start()


@app.on_event("shutdown")
async def stop_produck_scheduler() -> None:
    scheduler = getattr(app.state, "produck_scheduler", None)
    if scheduler is not None:
        await scheduler.stop()


@app.get("/health", tags=["operations"])
def health() -> dict[str, str]:
    return {"status": "ok"}
