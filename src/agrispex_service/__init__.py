"""AgriSPEX Agrarian integration service.

A lightweight, deployable service that connects to the Agrarian PostgreSQL
(agrispex_db), maintains the AgriSPEX alert schema, and exposes a health endpoint
for the Agrarian Portal's Kubernetes pod monitoring. It is intentionally torch-free
so the image stays small and deployable; model inference remains a separate concern.

All credentials come from environment variables (never hardcoded) per the Agrarian
Database Guide.
"""

__version__ = "1.0.0"
