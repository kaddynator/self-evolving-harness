#!/usr/bin/env python3
"""Evolutionary AI Harness CLI.

Commands:
  compile   Synthesize a new harness from a natural language task description.
  run       Load a harness YAML and run one execution cycle (no evolution).
  evolve    Run the full evolution loop (run → evaluate → mine → propose → gate → next gen).
  summary   Print the MongoDB run summary for a harness ID.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import mongomock
import yaml

try:
    from dotenv import load_dotenv

    load_dotenv()  # load MONGO_URI / GEMINI_API_KEY from .env if present
except ImportError:
    pass

from src.ir.loader import load_harness
from src.memory.store import MongoMemoryStore
from src.pipeline import EvolutionPipeline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store(mongo_uri: str | None) -> MongoMemoryStore:
    if mongo_uri:
        return MongoMemoryStore(uri=mongo_uri)
    # Default: in-process mongomock (no real MongoDB needed for demo)
    client = mongomock.MongoClient()
    return MongoMemoryStore(db=client["harness_demo"])


def _make_bus(terminal: bool = True):
    """Create an EventBus, optionally subscribing the rich terminal observer."""
    from src.observability.bus import EventBus
    from src.observability.terminal import RichTerminalObserver
    bus = EventBus()
    if terminal:
        obs = RichTerminalObserver()
        bus.subscribe(obs.on_event)
    return bus


def _make_pipeline(args, store: MongoMemoryStore, event_bus=None) -> EvolutionPipeline:
    agent_runner = None
    if getattr(args, "gemini", False):
        from src.gemini.client import GeminiClient
        from src.gemini.agent_runner import make_gemini_runner
        project_id = getattr(args, "project", None) or "ai-hack-sf26sfo-7208"
        model_id = getattr(args, "model", None) or "gemini-2.5-flash"
        client = GeminiClient(project_id=project_id, model_id=model_id)
        shared_memory: dict = {}
        agent_runner = make_gemini_runner(client, shared_memory_ref=shared_memory)
        print(f"[gemini] Using model {model_id} on project {project_id}")
    return EvolutionPipeline(store, agent_runner=agent_runner, event_bus=event_bus)


def _print_cycle(result, generation: int = 1) -> None:
    ev = result.evaluation
    run = result.run
    print(f"\n{'='*60}")
    print(f"  Generation {generation}  |  {result.harness.organization.id}")
    print(f"{'='*60}")
    print(f"  Run ID         : {run.run_id[:8]}...")
    print(f"  Success        : {run.success}")
    print(f"  Stop reason    : {run.stop_reason}")
    print(f"  Total tool calls: {run.total_tool_calls}")
    print(f"  Elapsed (s)    : {run.elapsed_seconds:.3f}")
    print(f"\n  Score          : {ev.total_score:.1f}  (threshold {ev.success_threshold})")
    print(f"  Passed         : {ev.passed_threshold}")
    print(f"\n  Metric scores:")
    for name, score in ev.metric_scores.items():
        print(f"    {name:<30} {score:+.1f}")
    print(f"\n  Binary checks:")
    for bc in ev.binary_check_results:
        status = "PASS" if bc.passed else "FAIL"
        print(f"    [{status}] {bc.check_id}  ({bc.detail})")

    if result.signatures:
        print(f"\n  Failure signatures ({len(result.signatures)}):")
        for sig in result.signatures:
            print(f"    - {sig.mechanism}: {sig.agent_behavior}")

    if result.proposals:
        print(f"\n  Proposals ({len(result.proposals)}):")
        for (proposal, _), decision in zip(result.proposals, result.gate_decisions):
            verdict = "ACCEPTED" if decision.accepted else "rejected"
            print(f"    [{verdict}] {proposal.mutation_type} — {proposal.expected_effect}")
            if not decision.accepted:
                print(f"             reason: {decision.reason}")

    if result.accepted_candidate:
        print(f"\n  => Accepted candidate: {result.accepted_candidate.organization.id}")
    else:
        print(f"\n  => No accepted candidate this generation.")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_compile(args, store: MongoMemoryStore) -> int:
    from src.compiler.compiler import HarnessCompiler, CompilationError

    gemini_client = None
    if getattr(args, "gemini", False):
        from src.gemini.client import GeminiClient
        project_id = getattr(args, "project", None) or "ai-hack-sf26sfo-7208"
        model_id = getattr(args, "model", None) or "gemini-2.5-flash"
        gemini_client = GeminiClient(project_id=project_id, model_id=model_id)
        print(f"[compiler] Using Gemini {model_id} on project {project_id}")
    else:
        print("[compiler] Using mock compiler (pass --gemini for live synthesis)")

    constraints = args.constraint or []

    # Optionally load prior lessons from memory
    prior_lessons = []
    if args.harness_id:
        summary = store.run_summary(args.harness_id)
        prior_lessons = summary.get("failure_signatures", [])

    compiler = HarnessCompiler(client=gemini_client)

    try:
        harness = compiler.compile(
            task_description=args.task,
            constraints=constraints,
            domain=args.domain,
            prior_lessons=prior_lessons if prior_lessons else None,
        )
    except CompilationError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Serialize and save
    out_path = Path(args.output) if args.output else None
    harness_dict = harness.model_dump(by_alias=True, mode="python")
    harness_yaml = yaml.dump(harness_dict, sort_keys=False, allow_unicode=True)

    if out_path:
        out_path.write_text(harness_yaml)
        print(f"\nHarness saved to: {out_path}")
    else:
        print("\n" + harness_yaml)

    print(f"\nCompiled harness: {harness.organization.id}")
    print(f"Agents          : {len(harness.agents)}")
    print(f"Edges           : {len(harness.communication.edges)}")
    print(f"Objective       : {harness.organization.objective[:80]}")

    if args.evolve:
        print(f"\nStarting evolution: {harness.organization.id}")
        bus = _make_bus(terminal=True)
        pipeline = _make_pipeline(args, store, event_bus=bus)
        results = pipeline.run_evolution(harness, max_generations=args.generations)
        for i, result in enumerate(results, start=1):
            _print_cycle(result, generation=i)
        if len(results) > 1:
            first_score = results[0].evaluation.total_score
            last_score = results[-1].evaluation.total_score
            print(f"\nEvolution summary: {len(results)} gen(s) | score {first_score:.1f} → {last_score:.1f}")

    return 0


def cmd_serve(args, store: MongoMemoryStore) -> int:
    """Start the web UI and run the pipeline, streaming events to the browser."""
    import threading
    import webbrowser
    import time as _time

    from src.observability.server import PipelineStateTracker, RunRequest, start_server

    bus = _make_bus(terminal=True)
    tracker = PipelineStateTracker()
    bus.subscribe(tracker.on_event)

    host, port = os.environ.get("SERVE_HOST", "127.0.0.1"), getattr(args, "port", 8765)
    url = f"http://{host}:{port}"

    # ── Run callback (called from POST /api/run in the web UI) ──
    def _web_run_callback(req: RunRequest) -> None:
        """Start a fresh pipeline from a web-submitted config.

        Attempts a real Gemini run when use_gemini is set, but gracefully
        falls back to the deterministic mock agents if Gemini is unavailable
        (auth, quota, or an unparseable response) so the UI never dead-ends
        on a 0-generation failure.
        """
        from src.compiler.compiler import HarnessCompiler, CompilationError
        from src.observability.events import PipelineEvent

        # Clear all prior run state up-front so a new evolution starts clean.
        bus.clear_history()

        # Real-model path: Gemini designs the workflow (compilation) AND executes
        # every agent via a function-calling tool loop against a sandbox, with an
        # LLM-as-judge for scoring and Gemini-driven prompt growth during
        # evolution. If Gemini is unavailable we gracefully fall back to the
        # deterministic mock so the UI never dead-ends.
        exec_client = None
        fallback_note = ""

        if req.use_gemini:
            try:
                from src.gemini.client import GeminiClient
                exec_client = GeminiClient(
                    project_id=req.project_id, model_id=req.model_id
                )
            except Exception as exc:  # auth / import / network at construction
                fallback_note = f"Gemini unavailable ({type(exc).__name__}); using mock engine."
                exec_client = None

        compiler = HarnessCompiler(client=exec_client)
        harness = None
        gemini_exec = exec_client is not None
        try:
            harness = compiler.compile(
                req.task,
                constraints=req.constraints or [],
                domain=req.domain,
                num_agents=req.num_agents,
                prompt_detail=getattr(req, "prompt_detail", "detailed"),
                optimize_models=getattr(req, "optimize_models", True),
            )
        except Exception as exc:  # CompilationError, RuntimeError (quota), etc.
            # Gemini compile failed — retry once with the deterministic mock
            # compiler, and drop to mock execution too.
            if exec_client is not None:
                fallback_note = f"Gemini compile failed ({type(exc).__name__}); using mock engine."
                gemini_exec = False
                try:
                    harness = HarnessCompiler(client=None).compile(
                        req.task,
                        constraints=req.constraints or [],
                        domain=req.domain,
                        num_agents=req.num_agents,
                        prompt_detail=getattr(req, "prompt_detail", "detailed"),
                        optimize_models=getattr(req, "optimize_models", True),
                    )
                except Exception as exc2:
                    harness = None
                    fallback_note = f"Compilation failed: {exc2}"
            else:
                fallback_note = f"Compilation failed: {exc}"

        if harness is None:
            bus.publish(PipelineEvent(
                type="evolution_complete",
                data={"error": fallback_note or "Compilation failed.",
                      "generations": 0,
                      "initial_score": 0.0, "final_score": 0.0},
            ))
            return

        if fallback_note:
            print(f"[web] {fallback_note}")

        # Build the real-model execution stack when Gemini is available.
        agent_runner = None
        judge = None
        mutation_client = None
        if gemini_exec:
            from src.gemini.agent_runner import make_gemini_tool_runner
            from src.evaluation.judge import GeminiJudge
            agent_runner = make_gemini_tool_runner(exec_client, task=harness.task)
            judge = GeminiJudge(exec_client)
            mutation_client = exec_client
            print("[web] Running with real Gemini execution (tools + judge + prompt growth).")

        pipeline = EvolutionPipeline(
            store,
            agent_runner=agent_runner,
            event_bus=bus,
            judge=judge,
            mutation_client=mutation_client,
            optimize_models=getattr(req, "optimize_models", True),
        )
        stop_ev = getattr(req, '_stop_event', None)
        pipeline.run_evolution(harness, max_generations=req.max_generations, stop_event=stop_ev)

    # ── FastAPI server in daemon thread ──────────────────────
    server_thread = threading.Thread(
        target=start_server,
        kwargs={
            "bus": bus, "host": host, "port": port,
            "tracker": tracker, "run_callback": _web_run_callback,
        },
        daemon=True,
    )
    server_thread.start()
    _time.sleep(0.8)

    print(f"\n[serve] Web dashboard: {url}")
    print("[serve] Press Ctrl+C to stop.\n")
    webbrowser.open(url)

    # ── Optional: auto-start from CLI argument ────────────────
    src_arg = getattr(args, "source", None)
    if src_arg:
        src_path = Path(src_arg)
        if src_path.exists():
            harness = load_harness(src_path)
            pipeline = _make_pipeline(args, store, event_bus=bus)
            generations = getattr(args, "generations", 3)
            try:
                pipeline.run_evolution(harness, max_generations=generations)
            except KeyboardInterrupt:
                pass
        else:
            # task description → compile + evolve
            from src.compiler.compiler import HarnessCompiler, CompilationError
            gemini_client = None
            if getattr(args, "gemini", False):
                from src.gemini.client import GeminiClient
                project_id = getattr(args, "project", None) or "ai-hack-sf26sfo-7208"
                model_id = getattr(args, "model", None) or "gemini-2.5-flash"
                gemini_client = GeminiClient(project_id=project_id, model_id=model_id)
            compiler = HarnessCompiler(client=gemini_client)
            try:
                harness = compiler.compile(src_arg, domain=getattr(args, "domain", "general"))
            except CompilationError as e:
                print(f"Error: {e}", file=sys.stderr)
                return 1
            pipeline = _make_pipeline(args, store, event_bus=bus)
            generations = getattr(args, "generations", 3)
            try:
                pipeline.run_evolution(harness, max_generations=generations)
            except KeyboardInterrupt:
                pass

    print(f"\n[serve] Dashboard live at {url}  (Ctrl+C to stop)")
    try:
        while True:
            _time.sleep(1)
    except KeyboardInterrupt:
        pass
    return 0


def cmd_run(args, store: MongoMemoryStore) -> int:
    harness_path = Path(args.harness)
    if not harness_path.exists():
        print(f"Error: harness file not found: {harness_path}", file=sys.stderr)
        return 1

    harness = load_harness(harness_path)
    print(f"Loaded harness: {harness.organization.id} (v{harness.organization.version})")
    print(f"Objective: {harness.organization.objective}")

    bus = _make_bus(terminal=True)
    pipeline = _make_pipeline(args, store, event_bus=bus)
    result = pipeline.run_cycle(harness, generation=1)
    _print_cycle(result, generation=1)
    return 0


def cmd_evolve(args, store: MongoMemoryStore) -> int:
    harness_path = Path(args.harness)
    if not harness_path.exists():
        print(f"Error: harness file not found: {harness_path}", file=sys.stderr)
        return 1

    harness = load_harness(harness_path)
    generations = args.generations

    bus = _make_bus(terminal=True)
    pipeline = _make_pipeline(args, store, event_bus=bus)
    results = pipeline.run_evolution(harness, max_generations=generations)

    for i, result in enumerate(results, start=1):
        _print_cycle(result, generation=i)

    # Final comparison
    if len(results) > 1:
        first_score = results[0].evaluation.total_score
        last_score = results[-1].evaluation.total_score
        delta = last_score - first_score
        print(f"\n{'='*60}")
        print(f"  Evolution summary: {len(results)} generation(s)")
        print(f"  Score V1         : {first_score:.1f}")
        print(f"  Score final      : {last_score:.1f}  ({delta:+.1f})")
        print(f"{'='*60}\n")

    # MongoDB summary
    summary = store.run_summary(harness.organization.id)
    print(f"MongoDB memory — {harness.organization.id}:")
    print(json.dumps(summary, indent=2, default=str))
    return 0


def cmd_summary(args, store: MongoMemoryStore) -> int:
    summary = store.run_summary(args.harness_id)
    print(json.dumps(summary, indent=2, default=str))
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="harness",
        description="Evolutionary AI Organization Harness CLI",
    )
    parser.add_argument(
        "--mongo-uri",
        default=os.environ.get("MONGO_URI"),
        help="MongoDB URI (defaults to $MONGO_URI from .env; omit both to use in-memory mock)",
    )
    parser.add_argument(
        "--gemini",
        action="store_true",
        default=False,
        help="Use live Gemini agents instead of mock (requires gcloud ADC)",
    )
    parser.add_argument(
        "--project",
        default="ai-hack-sf26sfo-7208",
        help="Google Cloud project ID (default: ai-hack-sf26sfo-7208)",
    )
    parser.add_argument(
        "--model",
        default="gemini-2.5-flash",
        help="Gemini model ID (default: gemini-2.5-flash)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # serve
    p_serve = sub.add_parser(
        "serve",
        help="Start the web UI and run the evolution pipeline, streaming events to the browser",
    )
    p_serve.add_argument(
        "source", nargs="?", default=None,
        help="Optional: path to a harness YAML or a quoted task description (auto-starts the run). "
             "Omit to open the UI and submit a task from the Configure tab.",
    )
    p_serve.add_argument(
        "--domain", default="general",
        help="Domain hint when task description is given (default: general)",
    )
    p_serve.add_argument(
        "--generations", type=int, default=3,
        help="Evolution generations (default: 3)",
    )
    p_serve.add_argument(
        "--port", type=int, default=8765,
        help="Port for the web dashboard (default: 8765)",
    )

    # compile
    p_compile = sub.add_parser(
        "compile",
        help="Synthesize a new harness YAML from a natural language task description",
    )
    p_compile.add_argument("task", help="Natural language task description (quote it)")
    p_compile.add_argument(
        "--domain", default="general",
        help="Task domain: software_engineering | research | data_pipeline | general (default: general)",
    )
    p_compile.add_argument(
        "--constraint", action="append", default=[],
        metavar="CONSTRAINT",
        help="Add a hard constraint (repeatable: --constraint 'No API changes' --constraint 'Keep tests passing')",
    )
    p_compile.add_argument(
        "--output", "-o", default=None,
        metavar="FILE",
        help="Write the compiled harness YAML to this file (default: print to stdout)",
    )
    p_compile.add_argument(
        "--harness-id", default=None,
        metavar="HARNESS_ID",
        help="Load prior lessons from memory for this harness ID",
    )
    p_compile.add_argument(
        "--evolve", action="store_true", default=False,
        help="Immediately run the evolution loop on the compiled harness",
    )
    p_compile.add_argument(
        "--generations", type=int, default=3,
        help="Evolution generations when --evolve is set (default: 3)",
    )

    # run
    p_run = sub.add_parser("run", help="Execute one harness cycle")
    p_run.add_argument("harness", help="Path to harness YAML")

    # evolve
    p_evolve = sub.add_parser("evolve", help="Run full evolution loop")
    p_evolve.add_argument("harness", help="Path to harness YAML")
    p_evolve.add_argument(
        "--generations", type=int, default=3,
        help="Maximum number of evolution generations (default: 3)",
    )

    # summary
    p_summary = sub.add_parser("summary", help="Show MongoDB summary for a harness ID")
    p_summary.add_argument("harness_id", help="Organization harness ID")

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    store = _make_store(args.mongo_uri)

    if args.command == "serve":
        return cmd_serve(args, store)
    elif args.command == "compile":
        return cmd_compile(args, store)
    elif args.command == "run":
        return cmd_run(args, store)
    elif args.command == "evolve":
        return cmd_evolve(args, store)
    elif args.command == "summary":
        return cmd_summary(args, store)
    return 0


if __name__ == "__main__":
    sys.exit(main())
