"""Exercise the installed propagator against GHSA-mf5v-w3w3-f6cg carriers."""

import subprocess
import sys
import textwrap


def test_traceparent_extraction_rejects_oversized_newline_carrier_promptly():
    # Bound a future vulnerable dependency's CPU use in a child process. JSON
    # metadata can preserve newlines even though HTTP headers cannot.
    subprocess.run(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                """
                import json
                from opentelemetry.trace import get_current_span
                from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

                propagator = TraceContextTextMapPropagator()
                valid = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
                context = propagator.extract({"traceparent": valid})
                span = get_current_span(context).get_span_context()
                assert span.is_valid
                assert span.trace_id == int("4bf92f3577b34da6a3ce929d0e0e4736", 16)

                for size in (1024, 100_000):
                    value = valid + " " * size + "\\n!"
                    carrier = json.loads(json.dumps({"traceparent": value}))
                    context = propagator.extract(carrier)
                    assert not get_current_span(context).get_span_context().is_valid
                """
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
