"""
Minimal evaluation dashboard.

FastAPI app on port 8081. Queries the five RisingWave materialized views
and renders a single-page HTML report. Designed for the interview demo:
it shows current-window quality metrics without requiring a frontend build.

Routes:
    GET /         -> HTML dashboard (latest window snapshot)
    GET /metrics  -> JSON payload (same data, machine-readable)
    GET /health   -> {"status": "ok"}

Environment variables:
    RISINGWAVE_HOST   (default: localhost)
    RISINGWAVE_PORT   (default: 4566)
    RISINGWAVE_USER   (default: root)
    RISINGWAVE_DB     (default: dev)
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Database connection pool
# ---------------------------------------------------------------------------

_pool: Any = None


def _rw_dsn() -> str:
    host = os.getenv("RISINGWAVE_HOST", "localhost")
    port = os.getenv("RISINGWAVE_PORT", "4566")
    user = os.getenv("RISINGWAVE_USER", "root")
    db = os.getenv("RISINGWAVE_DB", "dev")
    return f"postgresql://{user}@{host}:{port}/{db}"


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    global _pool
    try:
        import asyncpg  # type: ignore[import-untyped]

        _pool = await asyncpg.create_pool(_rw_dsn(), min_size=1, max_size=3)
        log.info("Dashboard connected to RisingWave")
    except Exception as exc:
        log.warning("Dashboard: could not connect to RisingWave — %s (running in offline mode)", exc)
        _pool = None
    yield
    if _pool is not None:
        await _pool.close()


app = FastAPI(title="FinSentry Evaluation Dashboard", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------


async def _fetch_one(sql: str) -> dict[str, Any] | None:
    if _pool is None:
        return None
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(sql)
            return dict(row) if row else None
    except Exception:
        log.exception("Dashboard query failed: %s", sql[:80])
        return None


async def _fetch_metrics() -> dict[str, Any]:
    throughput = await _fetch_one(
        """
        SELECT total_requests, success_count, blocked_count, error_count,
               ROUND(avg_latency_ms::numeric, 1) AS avg_latency_ms,
               ROUND(p95_latency_ms::numeric, 1) AS p95_latency_ms,
               window_start, window_end
        FROM mv_request_throughput_1m
        ORDER BY window_end DESC
        LIMIT 1
        """
    )

    faithfulness = await _fetch_one(
        """
        SELECT verdicts_count, ROUND(avg_faithfulness::numeric, 3) AS avg_faithfulness,
               complete_count, skipped_count, window_start, window_end
        FROM mv_faithfulness_5m
        ORDER BY window_end DESC
        LIMIT 1
        """
    )

    relevance = await _fetch_one(
        """
        SELECT verdicts_count,
               ROUND(avg_answer_relevance::numeric, 3) AS avg_answer_relevance,
               ROUND(avg_context_relevance::numeric, 3) AS avg_context_relevance,
               window_start, window_end
        FROM mv_relevance_5m
        ORDER BY window_end DESC
        LIMIT 1
        """
    )

    tokens = await _fetch_one(
        """
        SELECT input_tokens_total, output_tokens_total, thoughts_tokens_total,
               gemini_calls_total, window_start, window_end
        FROM mv_token_usage_5m
        ORDER BY window_end DESC
        LIMIT 1
        """
    )

    return {
        "throughput": throughput,
        "faithfulness": faithfulness,
        "relevance": relevance,
        "tokens": tokens,
        "risingwave_connected": _pool is not None,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
async def metrics() -> JSONResponse:
    data = await _fetch_metrics()
    return JSONResponse(content=data)


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    data = await _fetch_metrics()
    return HTMLResponse(content=_render_html(data))


# ---------------------------------------------------------------------------
# HTML renderer
# ---------------------------------------------------------------------------


def _fmt(value: Any, suffix: str = "", na: str = "—") -> str:
    if value is None:
        return na
    return f"{value}{suffix}"


def _render_html(data: dict[str, Any]) -> str:
    tp = data.get("throughput") or {}
    fa = data.get("faithfulness") or {}
    re = data.get("relevance") or {}
    tok = data.get("tokens") or {}
    connected = data.get("risingwave_connected", False)

    connection_badge = (
        '<span style="color:#22c55e">&#9679; RisingWave connected</span>'
        if connected
        else '<span style="color:#ef4444">&#9679; RisingWave offline (static demo)</span>'
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>FinSentry Dashboard</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: system-ui, sans-serif; background: #0f172a; color: #e2e8f0;
            padding: 2rem; max-width: 1100px; margin: 0 auto; }}
    h1 {{ font-size: 1.5rem; font-weight: 700; margin-bottom: 0.25rem; }}
    .subtitle {{ color: #94a3b8; font-size: 0.875rem; margin-bottom: 2rem; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
             gap: 1rem; margin-bottom: 2rem; }}
    .card {{ background: #1e293b; border-radius: 0.75rem; padding: 1.25rem;
             border: 1px solid #334155; }}
    .card-label {{ color: #94a3b8; font-size: 0.75rem; text-transform: uppercase;
                   letter-spacing: 0.05em; margin-bottom: 0.5rem; }}
    .card-value {{ font-size: 1.75rem; font-weight: 700; color: #f1f5f9; }}
    .card-sub {{ color: #64748b; font-size: 0.75rem; margin-top: 0.25rem; }}
    table {{ width: 100%; border-collapse: collapse; background: #1e293b;
             border-radius: 0.75rem; overflow: hidden; border: 1px solid #334155; }}
    th {{ text-align: left; padding: 0.75rem 1rem; color: #94a3b8;
          font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em;
          border-bottom: 1px solid #334155; }}
    td {{ padding: 0.75rem 1rem; font-size: 0.875rem; border-bottom: 1px solid #1e293b; }}
    tr:last-child td {{ border-bottom: none; }}
    .section-title {{ font-size: 1rem; font-weight: 600; margin: 1.5rem 0 0.75rem; }}
  </style>
</head>
<body>
  <h1>FinSentry Evaluation Dashboard</h1>
  <p class="subtitle">{connection_badge} &nbsp;&bull;&nbsp; Real-time quality metrics from RisingWave</p>

  <p class="section-title">Request Throughput (last 1-minute window)</p>
  <div class="grid">
    <div class="card">
      <div class="card-label">Total Requests</div>
      <div class="card-value">{_fmt(tp.get('total_requests'))}</div>
    </div>
    <div class="card">
      <div class="card-label">Success Rate</div>
      <div class="card-value">{_success_rate(tp)}</div>
    </div>
    <div class="card">
      <div class="card-label">Avg Latency</div>
      <div class="card-value">{_fmt(tp.get('avg_latency_ms'), ' ms')}</div>
    </div>
    <div class="card">
      <div class="card-label">p95 Latency</div>
      <div class="card-value">{_fmt(tp.get('p95_latency_ms'), ' ms')}</div>
    </div>
  </div>

  <p class="section-title">Quality Scores (last 5-minute window)</p>
  <div class="grid">
    <div class="card">
      <div class="card-label">Faithfulness</div>
      <div class="card-value">{_fmt(fa.get('avg_faithfulness'))}</div>
      <div class="card-sub">{_fmt(fa.get('verdicts_count'))} verdicts</div>
    </div>
    <div class="card">
      <div class="card-label">Answer Relevance</div>
      <div class="card-value">{_fmt(re.get('avg_answer_relevance'))}</div>
    </div>
    <div class="card">
      <div class="card-label">Context Relevance</div>
      <div class="card-value">{_fmt(re.get('avg_context_relevance'))}</div>
    </div>
    <div class="card">
      <div class="card-label">Faithfulness Skip Rate</div>
      <div class="card-value">{_skip_rate(fa)}</div>
      <div class="card-sub">of {_fmt(fa.get('verdicts_count'))} verdicts</div>
    </div>
  </div>

  <p class="section-title">Gemini Token Usage (last 5-minute window)</p>
  <div class="grid">
    <div class="card">
      <div class="card-label">Input Tokens</div>
      <div class="card-value">{_fmt(tok.get('input_tokens_total'))}</div>
    </div>
    <div class="card">
      <div class="card-label">Output Tokens</div>
      <div class="card-value">{_fmt(tok.get('output_tokens_total'))}</div>
    </div>
    <div class="card">
      <div class="card-label">Thoughts Tokens</div>
      <div class="card-value">{_fmt(tok.get('thoughts_tokens_total'))}</div>
    </div>
    <div class="card">
      <div class="card-label">Gemini Calls</div>
      <div class="card-value">{_fmt(tok.get('gemini_calls_total'))}</div>
    </div>
  </div>
</body>
</html>"""


def _success_rate(tp: dict[str, Any]) -> str:
    total = tp.get("total_requests")
    success = tp.get("success_count")
    if total is None or success is None or total == 0:
        return "—"
    return f"{100 * success / total:.1f}%"


def _skip_rate(fa: dict[str, Any]) -> str:
    skipped = fa.get("skipped_count")
    total = fa.get("verdicts_count")
    if skipped is None or total is None or total == 0:
        return "—"
    return f"{100 * skipped / total:.1f}%"
