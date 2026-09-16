from __future__ import annotations

import json
import logging
import os
import random
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode


logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("otel-demo")

resource = Resource.create(
    {
        "service.name": os.getenv("OTEL_SERVICE_NAME", "checkout-demo"),
        "service.version": os.getenv("SERVICE_VERSION", "1.0.0"),
        "deployment.environment.name": os.getenv("DEPLOYMENT_ENVIRONMENT", "lab"),
        "k8s.pod.uid": os.getenv("K8S_POD_UID", "unknown"),
    }
)

trace_provider = TracerProvider(resource=resource)
trace_provider.add_span_processor(
    BatchSpanProcessor(
        OTLPSpanExporter(
            endpoint=os.getenv(
                "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
                "http://otel-collector:4318/v1/traces",
            )
        )
    )
)
trace.set_tracer_provider(trace_provider)

metric_reader = PeriodicExportingMetricReader(
    OTLPMetricExporter(
        endpoint=os.getenv(
            "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
            "http://otel-collector:4318/v1/metrics",
        )
    ),
    export_interval_millis=5_000,
)
meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
metrics.set_meter_provider(meter_provider)

tracer = trace.get_tracer("aik8s.otel-demo")
meter = metrics.get_meter("aik8s.otel-demo")
request_counter = meter.create_counter(
    "demo.requests",
    description="Number of demo business requests",
)
latency_histogram = meter.create_histogram(
    "demo.request.duration",
    unit="ms",
    description="Demo business request duration",
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    trace_provider.force_flush()
    meter_provider.force_flush()
    trace_provider.shutdown()
    meter_provider.shutdown()


app = FastAPI(title="OpenTelemetry Kubernetes Demo", lifespan=lifespan)
FastAPIInstrumentor.instrument_app(
    app,
    tracer_provider=trace_provider,
    meter_provider=meter_provider,
    excluded_urls="/healthz",
    exclude_spans=["send", "receive"],
)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/work")
def work(mode: str = Query("ok", pattern="^(ok|slow|error)$")) -> dict:
    started = time.perf_counter()
    result = "ok"

    with tracer.start_as_current_span("validate-order") as span:
        span.set_attribute("demo.mode", mode)
        time.sleep(0.02)

    try:
        with tracer.start_as_current_span("inventory-call") as span:
            delay = 0.85 if mode == "slow" else random.uniform(0.05, 0.12)
            span.set_attribute("peer.service", "inventory")
            span.set_attribute("demo.delay_ms", round(delay * 1000, 1))
            time.sleep(delay)
            if mode == "error":
                raise RuntimeError("inventory demo failure")

        with tracer.start_as_current_span("format-response"):
            time.sleep(0.03)
            payload = {"status": "ok", "mode": mode, "inventory": "reserved"}
    except RuntimeError as exc:
        result = "error"
        current = trace.get_current_span()
        current.record_exception(exc)
        current.set_status(Status(StatusCode.ERROR, str(exc)))
        logger.error(json.dumps({"event": "work.failed", "mode": mode, "error": str(exc)}))
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        duration_ms = (time.perf_counter() - started) * 1000
        attributes = {"demo.mode": mode, "demo.result": result}
        request_counter.add(1, attributes)
        latency_histogram.record(duration_ms, attributes)
        logger.info(
            json.dumps(
                {
                    "event": "work.completed",
                    "mode": mode,
                    "result": result,
                    "duration_ms": round(duration_ms, 1),
                }
            )
        )

    return payload


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
