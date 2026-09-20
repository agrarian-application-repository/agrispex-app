"""Database layer for the AgriSPEX Agrarian integration service.

Connects to the provisioned Agrarian PostgreSQL using SQLAlchemy + psycopg (v3),
with connection pooling (per the Agrarian Database Guide best practices). All
secrets are read from environment variables; nothing is hardcoded.

Environment variables (see .env.example):
    DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, DB_SCHEMA (default public)
    ALERTS_TABLE (default agrispex_alerts)
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader (no extra dependency). Existing env vars win."""

    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _safe_identifier(value: str) -> str:
    if not SAFE_IDENTIFIER.fullmatch(value):
        raise ValueError(f"unsafe SQL identifier: {value!r}")
    return value


def settings() -> Dict[str, Any]:
    return {
        "host": os.getenv("DB_HOST", "10.160.101.65"),
        "port": os.getenv("DB_PORT", "5432"),
        "name": os.getenv("DB_NAME", "agrispex_db"),
        "user": os.getenv("DB_USER", "agrispex"),
        "password": os.getenv("DB_PASSWORD", ""),
        "schema": _safe_identifier(os.getenv("DB_SCHEMA", "public")),
        "table": _safe_identifier(os.getenv("ALERTS_TABLE", "agrispex_alerts")),
    }


def make_engine() -> Engine:
    s = settings()
    if not s["password"]:
        raise RuntimeError("DB_PASSWORD is not set (configure environment variables / .env)")
    uri = (
        f"postgresql+psycopg://{s['user']}:{s['password']}"
        f"@{s['host']}:{s['port']}/{s['name']}"
    )
    # Pooling per the Agrarian Database Guide; pre_ping survives idle drops.
    return create_engine(uri, pool_pre_ping=True, pool_size=5, max_overflow=5, pool_recycle=1800, future=True)


def qualified_table(s: Dict[str, Any]) -> str:
    return f'"{s["schema"]}"."{s["table"]}"'


def ensure_schema(engine: Engine) -> None:
    """Create the AgriSPEX alert table + indexes (developer owns the schema)."""

    s = settings()
    q = qualified_table(s)
    ddl = f"""
    CREATE TABLE IF NOT EXISTS {q} (
        alert_id BIGINT PRIMARY KEY,
        captured_at TIMESTAMPTZ NOT NULL,
        parcel_id TEXT NOT NULL,
        geocell_row INTEGER,
        geocell_col INTEGER,
        stress_class SMALLINT NOT NULL,
        confidence DOUBLE PRECISION,
        stress_type SMALLINT,
        cause_class SMALLINT,
        rationale_code SMALLINT,
        rationale_text TEXT,
        soil_moisture_pct DOUBLE PRECISION,
        temperature_c DOUBLE PRECISION,
        humidity_pct DOUBLE PRECISION,
        ndvi DOUBLE PRECISION,
        ndre DOUBLE PRECISION,
        ndwi DOUBLE PRECISION,
        model_version TEXT,
        explanation_method TEXT,
        overlay_ref BIGINT,
        payload JSONB NOT NULL,
        received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """
    idx1 = f'CREATE INDEX IF NOT EXISTS idx_{s["table"]}_parcel ON {q} (parcel_id);'
    idx2 = f'CREATE INDEX IF NOT EXISTS idx_{s["table"]}_captured ON {q} (captured_at DESC);'
    with engine.begin() as conn:
        conn.execute(text(ddl))
        conn.execute(text(idx1))
        conn.execute(text(idx2))


def insert_alert(engine: Engine, record: Dict[str, Any]) -> int:
    """Upsert one alert record. Returns affected row count."""

    s = settings()
    q = qualified_table(s)
    cols = [
        "alert_id", "captured_at", "parcel_id", "geocell_row", "geocell_col",
        "stress_class", "confidence", "stress_type", "cause_class", "rationale_code",
        "rationale_text", "soil_moisture_pct", "temperature_c", "humidity_pct",
        "ndvi", "ndre", "ndwi", "model_version", "explanation_method", "overlay_ref",
    ]
    params = {c: record.get(c) for c in cols}
    params["payload"] = json.dumps(record.get("payload", record), default=str)
    placeholders = ", ".join(f":{c}" for c in cols) + ", CAST(:payload AS JSONB)"
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != "alert_id")
    sql = text(
        f"""
        INSERT INTO {q} ({", ".join(cols)}, payload)
        VALUES ({placeholders})
        ON CONFLICT (alert_id) DO UPDATE SET
            {updates}, payload = EXCLUDED.payload, received_at = NOW()
        """
    )
    with engine.begin() as conn:
        result = conn.execute(sql, params)
    return max(int(result.rowcount or 0), 0)


def recent_alerts(engine: Engine, limit: int = 20) -> List[Dict[str, Any]]:
    s = settings()
    q = qualified_table(s)
    sql = text(
        f"SELECT alert_id, captured_at, parcel_id, stress_class, confidence, "
        f"rationale_text, model_version, received_at FROM {q} "
        f"ORDER BY received_at DESC LIMIT :limit"
    )
    with engine.begin() as conn:
        rows = conn.execute(sql, {"limit": int(limit)}).mappings().all()
    out = []
    for r in rows:
        d = dict(r)
        for k, v in d.items():
            if isinstance(v, datetime):
                d[k] = v.astimezone(timezone.utc).isoformat()
        out.append(d)
    return out


def health(engine: Engine) -> Dict[str, Any]:
    s = settings()
    info = {
        "database": s["name"], "host": s["host"], "port": s["port"],
        "schema": s["schema"], "table": s["table"],
    }
    try:
        with engine.begin() as conn:
            conn.execute(text("SELECT 1"))
            exists = conn.execute(text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = :sch AND table_name = :tbl)"
            ), {"sch": s["schema"], "tbl": s["table"]}).scalar()
        return {"status": "ok", "db_connected": True, "table_ready": bool(exists), **info}
    except Exception as exc:  # noqa: BLE001
        return {"status": "degraded", "db_connected": False, "error": f"{type(exc).__name__}: {exc}", **info}
