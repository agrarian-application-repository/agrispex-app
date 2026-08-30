"""AgriSPEX <-> AGRARIAN integration service.

Deployed on the AGRARIAN Portal / K3s orchestrator. The container is stateless:
DB target and credentials arrive as environment variables injected from the
Kubernetes Secret ``agrispex-db``. Nothing is hardcoded.

Endpoints
    GET  /health         liveness  - always 200 while the process is alive
    GET  /ready          readiness - 200 only when the database is usable
    GET  /               service info
    POST /alerts         upsert one AgriSPEX alert record
    GET  /alerts/recent  read back recent alerts
    GET  /iot/simulate   on-demand synthetic IoT context vector (flagged)

The listening port comes from ``PORT`` (default 80, the AGRARIAN application
template convention) so the orchestrator can relocate the service without an
image rebuild.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agrispex_service import db

SERVICE_VERSION = "1.0.0"


class AlertIn(BaseModel):
    alert_id: int
    captured_at: str
    parcel_id: str
    stress_class: int
    geocell_row: Optional[int] = None
    geocell_col: Optional[int] = None
    confidence: Optional[float] = None
    stress_type: Optional[int] = None
    cause_class: Optional[int] = None
    rationale_code: Optional[int] = None
    rationale_text: Optional[str] = None
    soil_moisture_pct: Optional[float] = None
    temperature_c: Optional[float] = None
    humidity_pct: Optional[float] = None
    ndvi: Optional[float] = None
    ndre: Optional[float] = None
    ndwi: Optional[float] = None
    model_version: Optional[str] = None
    explanation_method: Optional[str] = None
    overlay_ref: Optional[int] = None
    payload: Optional[Dict[str, Any]] = Field(default=None, description="Full alert JSON; stored verbatim")


@lru_cache(maxsize=1)
def engine():
    return db.make_engine()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Best-effort schema creation. A DB outage must never stop the pod."""

    db.load_dotenv()
    try:
        db.ensure_schema(engine())
        print("[startup] agrispex_alerts schema ready")
    except Exception as exc:  # noqa: BLE001
        print(f"[startup] schema not ready yet (will retry on demand): {exc}")
    yield


app = FastAPI(
    title="AgriSPEX AGRARIAN Integration Service",
    version=SERVICE_VERSION,
    lifespan=lifespan,
)


@app.get("/health")
def health() -> Dict[str, Any]:
    """Liveness probe. Always 200 while the process is up.

    The DB state is reported in the body so the Portal can see it, but a
    database outage must not cause Kubernetes to restart a healthy pod.
    """

    try:
        info = db.health(engine())
    except Exception as exc:  # noqa: BLE001 - config errors must not 500 the probe
        info = {"status": "degraded", "db_connected": False, "error": f"{type(exc).__name__}: {exc}"}
    info["service"] = "agrispex-app"
    info["version"] = SERVICE_VERSION
    info["alive"] = True
    return info


@app.get("/ready")
def ready() -> JSONResponse:
    """Readiness probe. 200 only when the database is connected and the table exists."""

    try:
        info = db.health(engine())
    except Exception as exc:  # noqa: BLE001
        info = {"status": "degraded", "db_connected": False, "error": f"{type(exc).__name__}: {exc}"}
    ok = bool(info.get("db_connected")) and bool(info.get("table_ready"))
    return JSONResponse(status_code=200 if ok else 503, content={"ready": ok, **info})


@app.get("/")
def root() -> Dict[str, Any]:
    return {
        "name": "agrispex-app",
        "version": SERVICE_VERSION,
        "status": "running",
        "description": "AgriSPEX crop-stress alert ingestion for the AGRARIAN data storage (Testbed 3, UC3)",
        "owner": "YTHION OU",
        "endpoints": ["/health", "/ready", "/alerts (POST)", "/alerts/recent", "/iot/simulate"],
    }


@app.post("/alerts")
def post_alert(alert: AlertIn) -> Dict[str, Any]:
    record = alert.model_dump()
    if record.get("payload") is None:
        record["payload"] = record
    try:
        db.ensure_schema(engine())
        n = db.insert_alert(engine(), record)
        return {"status": "ok", "alert_id": alert.alert_id, "rows_affected": n}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc


@app.get("/alerts/recent")
def get_recent(limit: int = 20) -> Dict[str, Any]:
    try:
        return {"alerts": db.recent_alerts(engine(), limit=limit)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc


@app.get("/iot/simulate")
def iot_simulate(at: Optional[str] = None) -> Dict[str, Any]:
    """On-demand SYNTHETIC IoT context vector, for use when no live sensor feed
    is attached. The response is always flagged ``source = "synthetic"``."""

    from datetime import datetime, timezone

    from agrispex_sim import IoTSimulator

    when = datetime.now(timezone.utc)
    if at:
        when = datetime.fromisoformat(at.replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
    return IoTSimulator().vector_at(when)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "80")))
