from __future__ import annotations

import asyncio
import copy
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from src.observability.bus import EventBus

_STATIC = Path(__file__).parent / "static"


# ---------------------------------------------------------------------------
# In-memory state tracker — subscribes to EventBus, builds REST-queryable state
# ---------------------------------------------------------------------------

class PipelineStateTracker:
    """Builds a queryable run state from pipeline events."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: Dict[str, Any] = self._blank_state()
        self._current_gen: Optional[Dict] = None

    @staticmethod
    def _blank_state() -> dict:
        return {
            "status": "idle",
            "task": "",
            "objective": "",
            "harness_id": "",
            "max_generations": 0,
            "current_generation": 0,
            "initial_score": None,
            "final_score": None,
            "generations": [],
            "harness_snapshots": {},
        }

    def reset(self, task: str = "", max_generations: int = 3) -> None:
        with self._lock:
            self._state = self._blank_state()
            self._state["status"] = "running"
            self._state["task"] = task
            self._state["max_generations"] = max_generations
            self._current_gen = None

    def on_event(self, event) -> None:
        with self._lock:
            self._handle(event)

    def _handle(self, event) -> None:
        d = event.data
        t = event.type
        g = event.generation

        if t == "evolution_start":
            self._state["objective"] = d.get("objective", "")
            self._state["harness_id"] = d.get("harness_id", "")
            self._state["max_generations"] = d.get("max_generations", 0)
            self._state["status"] = "running"
            if not self._state["task"]:
                self._state["task"] = d.get("objective", "")

        elif t == "generation_start":
            self._state["current_generation"] = g
            agents_by_id = {}
            for a in d.get("agents", []):
                agents_by_id[a["id"]] = {
                    "id": a["id"],
                    "name": a.get("name", ""),
                    "role": a.get("role", ""),
                    "tool_calls": 0,
                    "artifacts": [],
                    "status": "pending",
                    "tools_used": [],
                }
            self._current_gen = {
                "generation": g,
                "harness_id": d.get("harness_id", ""),
                "score": 0.0,
                "passed": False,
                "tool_calls": 0,
                "elapsed": 0.0,
                "agents": agents_by_id,
                "mutations": [],
                "signatures": [],
                "metric_scores": {},
            }

        elif t == "agent_start" and self._current_gen:
            aid = d.get("agent_id", "")
            if aid not in self._current_gen["agents"]:
                self._current_gen["agents"][aid] = {
                    "id": aid, "name": d.get("agent_name", ""),
                    "role": d.get("role", ""), "tool_calls": 0,
                    "artifacts": [], "status": "pending", "tools_used": [],
                }
            self._current_gen["agents"][aid]["status"] = "running"

        elif t == "agent_tool_call" and self._current_gen:
            aid = d.get("agent_id", "")
            tool = d.get("tool", "")
            ag = self._current_gen["agents"].get(aid)
            if ag:
                ag["tool_calls"] += 1
                if tool and tool not in ag["tools_used"]:
                    ag["tools_used"].append(tool)

        elif t == "agent_finish" and self._current_gen:
            aid = d.get("agent_id", "")
            ag = self._current_gen["agents"].get(aid)
            if ag:
                ag["status"] = "done" if d.get("success") else "error"
                ag["artifacts"] = d.get("artifacts", [])

        elif t == "run_complete" and self._current_gen:
            self._current_gen["tool_calls"] = d.get("total_tool_calls", 0)
            self._current_gen["elapsed"] = d.get("elapsed", 0.0)

        elif t == "evaluation_complete" and self._current_gen:
            self._current_gen["score"] = d.get("score", 0.0)
            self._current_gen["passed"] = d.get("passed", False)
            self._current_gen["metric_scores"] = d.get("metrics", {})
            if self._state["initial_score"] is None:
                self._state["initial_score"] = d.get("score", 0.0)

        elif t == "weakness_mined" and self._current_gen:
            self._current_gen["signatures"] = d.get("signatures", [])

        elif t == "mutation_proposed" and self._current_gen:
            existing = next(
                (m for m in self._current_gen["mutations"]
                 if m["type"] == d.get("mutation_type", "")),
                None,
            )
            if not existing:
                self._current_gen["mutations"].append({
                    "type": d.get("mutation_type", ""),
                    "effect": d.get("effect", ""),
                    "accepted": None,
                    "reason": "",
                })

        elif t == "gate_decision" and self._current_gen:
            mut_type = d.get("mutation_type", "")
            for m in self._current_gen["mutations"]:
                if m["type"] == mut_type:
                    m["accepted"] = d.get("accepted", False)
                    m["reason"] = d.get("reason", "")
                    break

        elif t == "harness_snapshot":
            self._state["harness_snapshots"][g] = copy.deepcopy(d)
            if self._current_gen:
                self._current_gen["harness_snapshot"] = copy.deepcopy(d)

        elif t == "generation_finish" and self._current_gen:
            self._state["final_score"] = self._current_gen["score"]
            self._state["generations"].append(copy.deepcopy(self._current_gen))
            self._current_gen = None

        elif t == "evolution_complete":
            self._state["status"] = "done"
            self._state["final_score"] = d.get("final_score")
            if self._state["initial_score"] is None:
                self._state["initial_score"] = d.get("initial_score")

    def get_state(self) -> dict:
        with self._lock:
            s = copy.deepcopy(self._state)
            if self._current_gen:
                # include in-progress generation
                s["in_progress_gen"] = copy.deepcopy(self._current_gen)
            return s


# ---------------------------------------------------------------------------
# Pydantic schema for POST /api/run
# ---------------------------------------------------------------------------

class RunRequest(BaseModel):
    task: str
    domain: str = "general"
    constraints: List[str] = []
    max_generations: int = 3
    use_gemini: bool = False
    project_id: str = "ai-hack-sf26sfo-7208"
    model_id: str = "gemini-2.5-flash"
    num_agents: Optional[int] = None
    # Per-agent prompt detail level: "brief" | "detailed" | "exhaustive".
    prompt_detail: str = "detailed"
    # When True, the evolution engine explores the Gemini model pool per agent.
    optimize_models: bool = True


class FeedbackRequest(BaseModel):
    feedback: str
    generations: int = 2


# ---------------------------------------------------------------------------
# FastAPI app factory
# ---------------------------------------------------------------------------

def create_app(
    bus: EventBus,
    tracker: Optional[PipelineStateTracker] = None,
    run_callback: Optional[Callable[[RunRequest], None]] = None,
) -> FastAPI:
    app = FastAPI(title="Harness Evolution Monitor", docs_url=None, redoc_url=None)

    _tracker = tracker or PipelineStateTracker()
    _running = threading.Event()   # set while a pipeline run is active
    _stop_req = threading.Event()  # set to request the running pipeline to abort

    @app.on_event("startup")
    async def _capture_loop():
        bus.set_loop(asyncio.get_event_loop())

    # ── HTML dashboard ────────────────────────────────────────
    @app.get("/", response_class=HTMLResponse)
    async def dashboard():
        return (_STATIC / "index.html").read_text()

    # ── SSE stream ────────────────────────────────────────────
    @app.get("/events")
    async def sse():
        q: asyncio.Queue = asyncio.Queue(maxsize=512)
        bus.add_sse_queue(q)

        async def stream():
            try:
                while True:
                    try:
                        event = await asyncio.wait_for(q.get(), timeout=25)
                        payload = json.dumps(event.to_dict())
                        yield f"data: {payload}\n\n"
                    except asyncio.TimeoutError:
                        yield 'data: {"type":"ping"}\n\n'
            except asyncio.CancelledError:
                pass
            finally:
                bus.remove_sse_queue(q)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    # ── State REST endpoint ───────────────────────────────────
    @app.get("/api/state")
    async def get_state():
        return _tracker.get_state()

    # ── Workflow snapshots ────────────────────────────────────
    @app.get("/api/workflow")
    async def get_workflow():
        state = _tracker.get_state()
        snapshots = state.get("harness_snapshots", {})
        generations = state.get("generations", [])
        result = []
        for g in generations:
            gen_num = g["generation"]
            snap = snapshots.get(gen_num, snapshots.get(str(gen_num), {}))
            result.append({
                "generation": gen_num,
                "score": g.get("score", 0.0),
                "passed": g.get("passed", False),
                "tool_calls": g.get("tool_calls", 0),
                "harness_id": g.get("harness_id", ""),
                "agents": snap.get("agents", []),
                "phases": snap.get("phases", []),
                "edges": snap.get("edges", []),
            })
        return result

    @app.get("/api/workflow/latest")
    async def get_latest_workflow():
        state = _tracker.get_state()
        snapshots = state.get("harness_snapshots", {})
        if not snapshots:
            return {}
        latest_gen = max(int(k) for k in snapshots.keys())
        snap = snapshots[latest_gen]
        generations = state.get("generations", [])
        g_meta = next((g for g in generations if g.get("generation") == latest_gen), {})
        return {
            "generation": latest_gen,
            "score": g_meta.get("score", 0.0),
            "passed": g_meta.get("passed", False),
            "tool_calls": g_meta.get("tool_calls", 0),
            "harness_id": snap.get("harness_id", ""),
            "agents": snap.get("agents", []),
            "phases": snap.get("phases", []),
            "edges": snap.get("edges", []),
        }

    # ── Feedback continuation ─────────────────────────────────
    @app.post("/api/feedback")
    async def continue_with_feedback(req: FeedbackRequest):
        if _running.is_set():
            return {"status": "error", "message": "A run is already in progress."}
        if run_callback is None:
            return {"status": "error", "message": "No run callback registered."}

        state = _tracker.get_state()
        current_task = state.get("task", "")
        if not current_task:
            return {"status": "error", "message": "No prior run to continue from."}

        feedback_req = RunRequest(
            task=current_task + f"\n\nUser feedback: {req.feedback}",
            domain="software_engineering",
            max_generations=req.generations,
            use_gemini=True,
        )

        _tracker.reset(task=feedback_req.task, max_generations=req.generations)
        _stop_req.clear()
        _running.set()
        feedback_req._stop_event = _stop_req  # allow stopping between generations

        def _go():
            try:
                run_callback(feedback_req)
            finally:
                _running.clear()

        threading.Thread(target=_go, daemon=True).start()
        return {"status": "started"}

    # ── Stop running pipeline ─────────────────────────────────
    @app.post("/api/stop")
    async def stop_run():
        if not _running.is_set():
            return {"status": "idle"}
        _stop_req.set()
        # Wait up to 8 s for the pipeline thread to honour the stop signal
        for _ in range(80):
            await asyncio.sleep(0.1)
            if not _running.is_set():
                _stop_req.clear()
                return {"status": "stopped"}
        # Timed out — clear flag anyway; the thread will finish eventually
        _stop_req.clear()
        return {"status": "timeout"}

    # ── Run trigger ───────────────────────────────────────────
    @app.post("/api/run")
    async def start_run(req: RunRequest):
        if _running.is_set():
            return {"status": "error", "message": "A run is already in progress."}
        if run_callback is None:
            return {"status": "error", "message": "No run callback registered on this server."}

        _tracker.reset(task=req.task, max_generations=req.max_generations)
        _stop_req.clear()
        _running.set()
        req._stop_event = _stop_req  # pipeline checks this between generations

        def _go():
            try:
                run_callback(req)
            finally:
                _running.clear()

        threading.Thread(target=_go, daemon=True).start()
        return {"status": "started"}

    return app


# ---------------------------------------------------------------------------
# Blocking entry point (called from a daemon thread in cli.py)
# ---------------------------------------------------------------------------

def start_server(
    bus: EventBus,
    host: str = "127.0.0.1",
    port: int = 8765,
    tracker: Optional[PipelineStateTracker] = None,
    run_callback: Optional[Callable] = None,
) -> None:
    import uvicorn
    app = create_app(bus, tracker=tracker, run_callback=run_callback)
    uvicorn.run(app, host=host, port=port, log_level="error")
