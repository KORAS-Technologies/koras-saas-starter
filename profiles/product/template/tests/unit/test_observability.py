"""The span exporter is chosen by the protocol the endpoint speaks, or not at all."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ZITADEL_DOMAIN", "https://example.invalid")
os.environ.setdefault("ZITADEL_PROJECT_ID", "0")

from koras_api.core import observability  # noqa: E402


def test_no_endpoint_means_no_exporter() -> None:
    assert observability.span_exporter_for("", "grpc") is None
    assert observability.span_exporter_for("   ", "http/protobuf") is None


def test_a_hosted_gateway_gets_the_http_exporter_on_the_traces_path() -> None:
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    exporter = observability.span_exporter_for(
        "https://otlp-gateway-prod-us-east-3.grafana.net/otlp", "http/protobuf"
    )
    assert isinstance(exporter, OTLPSpanExporter)
    assert exporter._endpoint == "https://otlp-gateway-prod-us-east-3.grafana.net/otlp/v1/traces"


def test_the_traces_path_is_added_once() -> None:
    assert observability.traces_url("http://c/otlp/") == "http://c/otlp/v1/traces"
    assert observability.traces_url("http://c/otlp/v1/traces") == "http://c/otlp/v1/traces"


def test_the_local_collector_gets_the_grpc_exporter_by_default() -> None:
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

    assert isinstance(
        observability.span_exporter_for("http://localhost:4317", ""), OTLPSpanExporter
    )
    assert isinstance(
        observability.span_exporter_for("http://localhost:4317", "GRPC"), OTLPSpanExporter
    )


def test_an_unknown_protocol_is_refused_rather_than_guessed() -> None:
    with pytest.raises(ValueError, match="OTEL_EXPORTER_OTLP_PROTOCOL"):
        observability.span_exporter_for("http://localhost:4317", "carrier-pigeon")
