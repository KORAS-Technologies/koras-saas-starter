"""Tracing: a span per request, exported when a collector is configured.

The exporter is chosen by `OTEL_EXPORTER_OTLP_PROTOCOL`, because the SDK does
not choose it: the environment variable selects a transport only when the
exporter is built from the environment, and this module builds it in code.
For eight days the dev API exported every batch over gRPC to Grafana Cloud's
HTTP gateway and logged "missing selected ALPN property" for each one, while
Doppler said `http/protobuf` the whole time.

An empty endpoint is a real answer -- no collector yet -- and gives no
exporter rather than a connection error a minute: spans are still created and
trace context still crosses the queue, only the export is off. A protocol
that is neither `grpc` nor `http/protobuf` is refused at startup, because a
misconfiguration reported as nothing-to-do is one nobody fixes.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter

from .settings import settings

_log = logging.getLogger(__name__)

GRPC = "grpc"
HTTP_PROTOBUF = "http/protobuf"


def traces_url(endpoint: str) -> str:
    """The traces path on an OTLP/HTTP endpoint, added once.

    Grafana Cloud hands out `https://.../otlp`; the spec says traces go to
    `/v1/traces` under it, and the HTTP exporter appends nothing when given
    an explicit endpoint.
    """
    base = endpoint.strip().rstrip("/")
    return base if base.endswith("/v1/traces") else f"{base}/v1/traces"


def span_exporter_for(endpoint: str, protocol: str) -> SpanExporter | None:
    """The exporter for this endpoint and transport, or None for no collector.

    The exporter classes are imported here rather than at the top so a
    service with no collector configured never loads grpc at all. Both read
    `OTEL_EXPORTER_OTLP_HEADERS` from the environment on their own, which is
    how a hosted collector's credential reaches them without code.
    """
    address = endpoint.strip()
    if not address:
        return None
    transport = protocol.strip().lower() or GRPC
    if transport == HTTP_PROTOBUF:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter as HttpExporter,
        )

        return HttpExporter(endpoint=traces_url(address))
    if transport == GRPC:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter as GrpcExporter,
        )

        return GrpcExporter(endpoint=address)
    raise ValueError(
        f"OTEL_EXPORTER_OTLP_PROTOCOL must be {GRPC!r} or {HTTP_PROTOBUF!r}, not {protocol!r}"
    )


def setup_telemetry(app: FastAPI, service_name: str) -> None:
    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: service_name}))
    exporter = span_exporter_for(
        settings.otel_exporter_otlp_endpoint, settings.otel_exporter_otlp_protocol
    )
    if exporter is None:
        _log.info("tracing: no OTLP endpoint configured; spans are created and not exported")
    else:
        provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
