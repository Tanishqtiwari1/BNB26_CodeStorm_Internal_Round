"""REST API + static frontend.

    uvicorn blackbox.api:app --port 8000
"""
import os
from typing import Any, Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .agents import ReplayUnsupported
from .llm import LLMError
from .service import Service

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
app = FastAPI(title="Black Box API", version="1.0",
              description="AI agent flight recorder: traces, root-cause diagnosis, checkpointed replay.")
svc = Service(db=os.environ.get("BLACKBOX_DB", "data/blackbox.db"),
              model_path=os.environ.get("BLACKBOX_MODEL", "data/model_v2.joblib" if os.path.exists("data/model_v2.joblib") else "data/model.joblib"),
              metrics_path=os.environ.get("BLACKBOX_METRICS", "data/metrics.json"),
              background=os.environ.get("BLACKBOX_BACKGROUND", "1") == "1")


def _call(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except KeyError as e:
        raise HTTPException(404, f"not found: {e.args[0] if e.args else ''}")
    except ReplayUnsupported as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))
    except LLMError as e:
        raise HTTPException(502, f"LLM call failed: {e}")


class ReplayReq(BaseModel):
    sid: str
    mode: Literal["repair", "patch_output", "patch_args"] = "repair"
    patch: Optional[dict[str, Any]] = None


class AgentReq(BaseModel):
    agent: Literal["react-slm", "react-sim", "travel-llm", "travel-sim"] = "react-slm"
    seed: Optional[int] = None
    fault_type: Optional[str] = None


@app.get("/api/info")
def info():
    return svc.info()


@app.get("/api/stats")
def stats():
    return _call(svc.stats)


@app.get("/api/runs")
def list_runs(status: Optional[Literal["passed", "failed"]] = None, split: Optional[str] = None,
              agent: Optional[str] = None, q: Optional[str] = None,
              limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    return svc.list_runs(status=status, split=split, agent=agent, q=q, limit=limit, offset=offset)


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    return _call(svc.get_run, run_id)


@app.get("/api/runs/{run_id}/trace")
def get_trace(run_id: str):
    return {"run_id": run_id, "steps": _call(svc.get_run, run_id)["steps"]}


@app.get("/api/runs/{run_id}/diagnosis")
def diagnose(run_id: str):
    return _call(svc.analysis, run_id)


@app.get("/api/runs/{run_id}/steps/{sid}/explanation")
def explanation(run_id: str, sid: str):
    return _call(svc.explanation, run_id, sid)


@app.post("/api/runs/{run_id}/replay")
def replay(run_id: str, req: ReplayReq):
    return _call(svc.replay, run_id, req.sid, req.mode, req.patch)


@app.get("/api/runs/{run_id}/forks")
def forks(run_id: str):
    return svc.forks(run_id)


@app.get("/api/replays")
def replays(limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    return svc.replays(limit, offset)


@app.get("/api/demo/patch/{run_id}")
def demo_patch(run_id: str):
    return _call(svc.demo_patch, run_id)


@app.post("/api/otlp/v1/traces")
def otlp_ingest(payload: dict, success: Optional[bool] = None):
    """OTLP/HTTP JSON ingestion: point any OpenTelemetry exporter here."""
    return _call(svc.ingest_otlp, payload, success)


@app.get("/api/compare")
def compare(a: str, b: str):
    return _call(svc.compare, a, b)


@app.get("/api/metrics")
def metrics():
    return _call(svc.metrics)


@app.post("/api/agent/run")
def run_agent(req: AgentReq):
    return _call(svc.run_agent, req.agent, req.seed, req.fault_type)


class SampleReq(BaseModel):
    strategy: str = "plan_first"
    bug: str = "none"
    seed: Optional[int] = None


@app.get("/api/connect/options")
def sample_options():
    return _call(svc.sample_options)


@app.post("/api/connect/sample")
def sample_agent(req: SampleReq):
    """Run the bundled sample agent (a different agent from the built-in one) and ingest its OTel trace."""
    return _call(svc.sample_agent, req.strategy, req.bug, req.seed)


@app.post("/api/traces")
def upload_trace(payload: dict):
    """Upload a trace: OTLP/HTTP JSON (`resourceSpans`) or Black Box's simple format (`steps`)."""
    if "resourceSpans" in payload:
        return _call(svc.ingest_otlp, payload, payload.get("success"))
    return _call(svc.ingest_simple, payload)


@app.post("/api/demo/killer")
def killer():
    return _call(svc.killer_demo)


if os.path.isdir(WEB):
    app.mount("/static", StaticFiles(directory=WEB), name="static")

    from fastapi.responses import HTMLResponse
    import hashlib

    def _ver(name):
        with open(os.path.join(WEB, name), "rb") as f:
            return hashlib.md5(f.read()).hexdigest()[:10]

    @app.middleware("http")
    async def _no_stale_assets(request, call_next):
        # Browsers must revalidate the frontend on every load, so a deploy never
        # mixes a new index.html with a cached old app.js / style.css.
        resp = await call_next(request)
        if request.url.path in ("/", "/app") or request.url.path.startswith("/static/"):
            resp.headers["Cache-Control"] = "no-cache"
        return resp

    def _page(name, assets):
        with open(os.path.join(WEB, name), encoding="utf-8") as f:
            html = f.read()
        for a in assets:
            html = html.replace(f"/static/{a}", f"/static/{a}?v={_ver(a)}")
        return HTMLResponse(html)

    @app.get("/")
    def landing():
        return _page("landing.html", ("landing.css", "landing.js"))

    @app.get("/app")
    def index():
        return _page("index.html", ("style.css", "app.js"))
