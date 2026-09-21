## AgriSPEX - AGRARIAN Project

## Overview
AgriSPEX detects early crop stress in kiwifruit orchards by fusing Copernicus Sentinel-2
multispectral imagery with FARM5.0 ground IoT measurements. A quantised TinyViT runs on the
satellite edge coprocessor and only a 50-byte explainable alert crosses the narrowband link.
This repository contains the AGRARIAN-facing service that ingests those alerts into the
AGRARIAN data storage and serves them for ADSS rendering.

## 1. Testbed
Testbed 3 - LEO NB-IoT with onboard AI (Sateliot constellation + Ubotica CogniSAT-XE2).

- **Dataset:** Copernicus Sentinel-2 Level-2A over the Arta pilot region, Epirus, Greece
  (~28 GB, 30 scenes, February-May 2026), tiled into 1,418 patches of 224x224 with 13
  channels (bands B02-B08, B8A, B11, B12 plus NDVI, NDRE, NDWI). Ground context comes from
  FARM5.0 IoT nodes (soil moisture, air temperature, relative humidity) temporally aligned
  to each Sentinel-2 acquisition. Alerts written by this service are stored in the AGRARIAN
  PostgreSQL database `agrispex_db`, table `public.agrispex_alerts`.

## 2. Node Type
Cloud - this container runs on the AGRARIAN Portal / K3s orchestrator and writes to the
AGRARIAN PostgreSQL data storage.

The other two AgriSPEX components deploy elsewhere and are not part of this image: the
TinyViT backbone runs on the **satellite** node (Ubotica CogniSAT-XE2, deployed via Ubotica's
Rupia application as a compiled Myriad-X `.unn`), and the compact NB-IoT alerts are uplinked
from the Sateliot **edge** UE (Raspberry Pi + nRF9151).

## 3. Application Name
AgriSPEX

## 4. Application Objective
Persist every AgriSPEX crop-stress alert into the AGRARIAN data storage with a stable,
queryable schema, and serve it back for downstream decision support.

- Maintains the `agrispex_alerts` table, created automatically on first start.
- `POST /alerts` upserts one alert: stress classification, confidence, cause class, textual
  rationale, affected geocell bitmap, IoT context, spectral indices and model version. The
  complete alert JSON is retained verbatim in a `JSONB` payload column so nothing is lost.
- `GET /alerts/recent` reads alerts back, newest first, for ADSS and dashboard consumption.
- `GET /iot/simulate` returns an on-demand synthetic IoT context vector for runs where no
  live sensor feed is attached. Responses are always flagged `source: "synthetic"` so
  simulated values can never be mistaken for field measurements.
- `GET /health` and `GET /ready` provide pod monitoring for the orchestrator.

## 5. Use Case Description
Water deficit and humidity-driven fungal risk in orchards are spatially heterogeneous and
usually go unnoticed until damage has spread. AgriSPEX classifies stress with a TinyViT-5M
model that fuses the ground IoT vector at its classification head. Because inference happens
on the satellite edge coprocessor, only a 50-byte CRC-protected alert is transmitted instead
of a 2.6 MB raw patch - a 99.998% reduction, well inside the 200-byte NB-IoT message budget
of Testbed 3.

Every alert carries an explanation: a gradient-weighted attention-rollout overlay, a
bit-packed mask of the affected parcel cells, and a rationale under 40 words, for example
*"Stress in 8 cells from spectral indices; synchronised IoT context incomplete. Recommend
ground verification."* This service is the landing point for those alerts inside AGRARIAN,
making them queryable so an advisor can act on irrigation or scouting decisions.

## 6. Organization
YTHION OÜ

## 7. Use Instructions

### Required Inputs / Configuration
All configuration is by environment variable. From 0.1.2 the connection settings are
baked into the image at build time: the AGRARIAN Portal's deploy dialog exposes only
namespace, image tag, target node and replica count, so there is no deploy-time
mechanism to attach a Secret or set environment variables. Every value below can still
be overridden at runtime by the orchestrator if one becomes available.

The credentials are embedded in the image on the instruction of the AGRARIAN Portal
team, since the Portal provides no way to supply them at deploy time.

| Variable | Required | Default | Description |
|---|---|---|---|
| `DB_HOST` | yes | `10.160.101.65` | AGRARIAN PostgreSQL host |
| `DB_PORT` | yes | `5432` | PostgreSQL port |
| `DB_NAME` | yes | `agrispex_db` | Project database, from the onboarding email |
| `DB_USER` | yes | `agrispex` | Project username, from the onboarding email |
| `DB_PASSWORD` | yes | - | 16-character password from the onboarding email |
| `DB_SCHEMA` | no | `public` | Target schema |
| `ALERTS_TABLE` | no | `agrispex_alerts` | Target table |
| `PORT` | no | `80` | HTTP listen port |

Deploy-time overrides are not currently available on the Portal; see above.

### Running

```bash
docker build -t agrispex-app:0.1.2 .
docker run --rm -p 8080:80 agrispex-app:0.1.2
curl http://localhost:8080/health
```

On the Portal: select the application on the Dashboard, choose the namespace, set
`replicas: 1` and the image tag, then deploy. The published image is
`ghcr.io/agrarian-application-repository/agrispex-app`.

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Service identity and version |
| GET | `/health` | Liveness - always 200 while the process is alive; body reports database state |
| GET | `/ready` | Readiness - 200 only when the database is connected and the table exists |
| POST | `/alerts` | Upsert one alert record |
| GET | `/alerts/recent?limit=20` | Most recent alerts |
| GET | `/iot/simulate?at=<ISO8601>` | Synthetic IoT context vector, always flagged |

Example alert ingestion:

```bash
curl -X POST http://localhost:8080/alerts -H 'Content-Type: application/json' -d '{
  "alert_id": 1100001,
  "captured_at": "2026-05-12T09:20:31+00:00",
  "parcel_id": "S2C_MSIL2A_20260512T092031_T34SDJ_y672_x672",
  "stress_class": 1, "confidence": 0.9999, "cause_class": 3,
  "rationale_code": 4,
  "rationale_text": "Stress in 8 cells from spectral indices; synchronised IoT context incomplete. Recommend ground verification.",
  "ndvi": 0.2048, "ndre": 0.1356, "ndwi": -0.1319,
  "model_version": "tinyvit_best-be7f9727dca7"
}'
```

### Expected Outputs
One row per alert in `public.agrispex_alerts`, keyed on `alert_id`, with the full
`agrispex.alert.v1` record in the `payload` JSONB column and indexes on `parcel_id` and
`captured_at`. The service writes no files and holds no local state, so it can be scaled or
restarted freely. One log line per request goes to stdout for collection by the orchestrator.

### Contact
`projects@ythion.eu`
