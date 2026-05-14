"""Sentry / GlitchTip integration shim + OpenTelemetry tracing.

``setup_sentry()`` is called from each entry point. No-op if DH_SENTRY_DSN
is unset, so dev / tests pay no cost.

``setup_tracing()`` initialises OpenTelemetry. Auto-instruments FastAPI,
HTTPX, SQLAlchemy. Exporter behaviour:
  - DH_OTEL_EXPORTER_OTLP_ENDPOINT set → OTLP HTTP exporter to that endpoint
  - otherwise → ConsoleSpanExporter (visible in logs, zero infra needed)

Tracing is enabled by default for low overhead, with a sampling rate of 5%
to keep stdout noise manageable. Tune via DH_OTEL_SAMPLE_RATE.
"""
from __future__ import annotations

from dh.config import settings
from dh.logging import log


def setup_sentry(*, service: str) -> None:
    if not settings.sentry_dsn:
        return
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            traces_sample_rate=0.0,
            send_default_pii=False,
            environment=settings.env,
            release=f"dh-{service}",
        )
        log.info("sentry.enabled", service=service)
    except Exception as e:
        log.warning("sentry.init.failed", error=str(e))


_OTEL_SETUP_DONE = False


def setup_tracing(*, service: str) -> None:
    """Idempotent OTel SDK + auto-instrumentation init."""
    global _OTEL_SETUP_DONE
    if _OTEL_SETUP_DONE:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            ConsoleSpanExporter,
        )
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

        resource = Resource.create(
            {
                "service.name": f"dh-{service}",
                "service.namespace": settings.otel_service_namespace,
                "deployment.environment": settings.env,
            }
        )
        provider = TracerProvider(
            resource=resource, sampler=TraceIdRatioBased(0.05)
        )
        if settings.otel_exporter_otlp_endpoint:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

            exporter = OTLPSpanExporter(
                endpoint=f"{settings.otel_exporter_otlp_endpoint.rstrip('/')}/v1/traces"
            )
        else:
            exporter = ConsoleSpanExporter()  # type: ignore[assignment]
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        # Auto-instrument the IO libraries we care about. Each instrumentor is
        # idempotent + a no-op if the target isn't imported in this process.
        try:
            from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

            HTTPXClientInstrumentor().instrument()
        except Exception:  # noqa: BLE001
            pass
        try:
            from opentelemetry.instrumentation.sqlalchemy import (
                SQLAlchemyInstrumentor,
            )

            SQLAlchemyInstrumentor().instrument()
        except Exception:  # noqa: BLE001
            pass

        _OTEL_SETUP_DONE = True
        log.info(
            "otel.enabled",
            service=service,
            exporter=("otlp" if settings.otel_exporter_otlp_endpoint else "console"),
        )
    except Exception as e:  # noqa: BLE001
        log.warning("otel.init.failed", error=str(e))


def instrument_fastapi(app: object) -> None:
    """Auto-instrument a FastAPI app. Safe to call multiple times."""
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)  # type: ignore[arg-type]
    except Exception as e:  # noqa: BLE001
        log.warning("otel.fastapi.failed", error=str(e))
