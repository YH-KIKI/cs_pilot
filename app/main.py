from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import ROOT, get_settings
from app.consultation_contract import ApiError, ConsultationRequest, ConsultationResponse
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
    return HealthResponse()


@app.get("/api/orders/{order_id}", response_model=OrderLookupResult)
def get_order(order_id: OrderId) -> OrderLookupResult:
    return lookup_order_result(order_id)


@app.post(
    "/api/consultations",
    response_model=ConsultationResponse,
    responses={501: {"model": ApiError, "description": "Contract defined; agent not implemented"}},
)
def create_consultation(request: ConsultationRequest):
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=501,
        content=ApiError(
            code="not_implemented",
            message=(
                "상담 API 계약만 정의된 단계입니다. "
                "RAG·에이전트 실행은 아직 연결되지 않았습니다."
            ),
        ).model_dump(),
    )


# One screen only: do not swallow unknown API paths with an SPA catch-all.
dist = STATIC_DIR if (STATIC_DIR / "index.html").exists() else FRONTEND_DIST
if (dist / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(dist / "index.html")
