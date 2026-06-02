"""
OpenTelemetry tracing setup.

Uses a ConsoleSpanExporter (stdout) suitable for development and log-aggregation
pipelines (e.g. Datadog, GCP Cloud Logging).  Swap BatchSpanProcessor target for
an OTLP exporter to send traces to a collector in production.

The module-level `tracer` is used by Celery tasks to create spans for
long-running operations such as process_file.
"""

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, BatchSpanProcessor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor


def configure_tracing(app) -> None:
    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)


tracer = trace.get_tracer("geminirag")
