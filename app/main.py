from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.agent.graph import ConsultationEngine
from app.agent.service import get_consultation_engine
from app.config import ROOT, get_settings
from app.consultation_contract import ConsultationRequest, ConsultationResponse
from app.schemas import HealthResponse, OrderId, OrderLookupResult
from app.tools.orders import lookup_order_result
from scripts.init_orders_db import verify_database

FRONTEND_DIST = ROOT / "frontend/dist"
STATIC_DIR = ROOT / "app/static"


@asynccontextmanager
async def lifespan(application: FastAPI):
    verify_database(get_settings().db_path)
    yield


app = FastAPI(title="CS Pilot", version="0.1.0", lifespan=lifespan)


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        ai_enabled=settings.agent_allow_api
        and bool(settings.openai_api_key.get_secret_value().strip())
    )


@app.get("/api/orders/{order_id}", response_model=OrderLookupResult)
def get_order(order_id: OrderId) -> OrderLookupResult:
    return lookup_order_result(order_id)


@app.post(
    "/api/consultations",
    response_model=ConsultationResponse,
)
def create_consultation(
    request: ConsultationRequest,
    engine: Annotated[ConsultationEngine, Depends(get_consultation_engine)],
) -> ConsultationResponse:
    return engine.run(request)


# One screen only: do not swallow unknown API paths with an SPA catch-all.
dist = STATIC_DIR if (STATIC_DIR / "index.html").exists() else FRONTEND_DIST
if (dist / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(dist / "index.html")
