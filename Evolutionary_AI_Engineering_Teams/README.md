# Evolutionary AI Engineering Teams

**Agent teams that design, run, evaluate, and improve themselves — from a plain-English task description.**

---

## The Problem

Today's AI agents are powerful — but most multi-agent systems remain fundamentally static. Developers predefine the agents, assign their responsibilities, and manually design how they collaborate. This works for predictable workflows, but breaks down when tasks are unfamiliar, evolve over time, or require expertise that was not anticipated during system design.

---

## What This System Does

Given a plain-English task, the system:

1. **Compiles** a multi-agent team (requirements → coder → tester → reviewer) with no manual design
2. **Executes** each agent against real tools, collecting a full execution trace
3. **Evaluates** output using a real LLM judge (Claude Sonnet 4.6 or Gemini 2.5 Flash)
4. **Mines** failure signatures from the trace — wrong tool, oversized patch, late testing, redundant agent
5. **Proposes mutations** — swap a model, tighten a budget, add a verifier, reorder the team
6. **Gates** each mutation: only candidates that improve without regressing are promoted
7. **Repeats** — generation after generation, the team adapts on its own

When the evolved workflow is still wrong, humans step in. They label what the correct output should have been. That feedback builds an evaluation set, and the system uses it to rebuild and re-evolve the workflow from the ground up.

---

## Architecture

```
Task Description (plain English)
        │
        ▼
  HarnessCompiler  ──Gemini/Claude──▶  OrganizationHarness IR (YAML)
        │
        ▼
  RuntimeExecutor  ──agents──▶  RunResult (trace + artifacts)
        │
        ▼
  Evaluator  ──LLM Judge──▶  EvaluationResult (score)
        │
        ▼
  WeaknessMiner  ──▶  FailureSignatures
        │
        ▼
  EvolutionEngine  ──▶  Candidate Harnessess (mutations)
        │
        ▼
  ValidationGate  ──▶  Accept / Reject each candidate
        │
        ▼
  MongoMemoryStore  ──▶  Persist all runs, evaluations, mutations, lessons
        │
        ▼  (loop)
  Next Generation
```

Full ASCII diagrams for every component: [`docs/architecture_diagrams.md`](docs/architecture_diagrams.md)

---

## Core Concepts

### Organization Harness IR
The central data structure — a fully executable YAML specification that defines:
- **Agents**: id, role, prompt, model, tools, budget, memory policy
- **Topology**: phases, edges (blocking / feedback / broadcast), shared memory
- **Evaluation**: metrics, binary checks, success threshold, validation gate
- **Mutation policy**: allowed operators, proposal width, protected components

Every generation produces a new harness version with `organization.version` incremented. The `id` stays constant so the entire lineage is traceable.

### Mutation Operators
| Operator | What it does |
|---|---|
| `modify_prompt` | Strengthen or expand an agent's instruction via LLM |
| `change_model` | Upgrade to the next model tier (e.g. flash → pro) |
| `add_agent` | Insert a verifier or specialist into the workflow |
| `remove_agent` | Prune a redundant non-core agent |
| `adjust_budget` | Tighten max tool calls to force focused execution |
| `modify_tools` | Grant a missing tool permission |
| `reorder_edges` | Enforce correct execution order |
| `modify_runtime_policy` | Prevent identical retries, require artifact before finish |

### Validation Gate
Each mutation candidate is run end-to-end and gated:
1. Runtime must not exceed budget
2. No regression on required metrics (e.g. `tests_pass`)
3. At least one improvement on tracked metrics (e.g. `total_score`, `tool_calls`)

Only accepted candidates advance to the next generation.

### Feedback Flywheel
```
Production failure
    → Sentiment sentinel captures EvalCase (status=needs_label)
    → Human labels expected_output (status=labeled)
    → Batch threshold triggers re-evolution against full labeled dataset
    → Reference grading: GeminiJudge.grade_against_expected()
    → Gate: no regression on full labeled set → redeploy
```

The sentinel lives outside the harness and cannot be evolved away.

---

## Tech Stack

| Layer | Technology |
|---|---|
| **LLM (agents + judge)** | Gemini 2.5 Flash (Vertex AI), Claude Sonnet 4.6 (Anthropic Vertex) |
| **State & memory** | MongoDB Atlas — organizations, runs, evaluations, mutations, lessons, eval_cases |
| **Task similarity** | Qdrant — vector search for warm-start topology retrieval |
| **Topology gene pool** | Kuzu — embedded graph DB, agent topology lineage |
| **Run history & scoring** | ClickHouse — 90-day TTL, time-decay scoring (quality / cost) |
| **Infrastructure** | DigitalOcean Droplets + Docker (Qdrant + ClickHouse on `147.182.239.133`) |
| **Web UI** | FastAPI + SSE + Remotion (React) |

---

## Project Structure

```
src/
├── compiler/          # Synthesizes OrganizationHarness IR from plain-English task
├── ir/                # Pydantic schema for the full harness IR
├── runtime/           # Executor: runs agents phase by phase, collects trace
│   └── tools.py       # Real tool sandbox (read/write/run_tests/git_diff/...)
├── evaluation/        # Scorer + LLM judge + validation gate
├── weakness/          # Rule-based failure signature mining
├── evolution/         # Mutation proposals + mutators (8 operators)
├── memory/            # MongoDB, Qdrant, Kuzu, ClickHouse stores
├── llm/               # Backend-neutral LLM client (Claude + Gemini)
├── observability/     # EventBus, SSE server, web UI, eval dataset API
├── eval_dataset/      # EvalCase model + production capture flow
└── pipeline.py        # Orchestrates the full compile→run→evaluate→evolve loop

demos/
└── harness-demo/      # Remotion + Kokoro TTS demo video pipeline

docs/
├── architecture_diagrams.md   # ASCII diagrams for every component
├── 14_feedback_flywheel.md    # Full flywheel design
└── narration-draft.md         # Demo video narration script

cli.py                 # CLI: compile / run / evolve / serve
```

---

## Quick Start

### Prerequisites
- Python 3.11+
- `gcloud auth application-default login` (for Gemini + Claude via Vertex AI)
- MongoDB Atlas URI (set in `.env`)
- DigitalOcean droplet with Qdrant + ClickHouse running (optional — gracefully skipped if absent)

### Setup

```bash
# Clone and enter the project
cd Evolutionary_AI_Engineering_Teams

# Create .env
cat > .env << 'EOF'
MONGODB_URI="mongodb+srv://<user>:<pass>@cluster0.xxx.mongodb.net"
DROPLET_IP="147.182.239.133"   # DigitalOcean droplet with Qdrant + ClickHouse
CH_USER="harness"
CH_PASSWORD="harness123"
CH_DB="harness"
KUZU_PATH="/tmp/kuzu_harness"
EOF

# Install dependencies
pip install -r requirements.txt
```

### Run the web UI

```bash
python cli.py serve
# Opens http://localhost:8765
```

### Compile a harness

```bash
python cli.py compile "Add a rate limiter to the payments API" --domain software_engineering -o harness.yaml
```

### Run evolution

```bash
python cli.py evolve harness.yaml --generations 5
```

---

## Web UI

| Tab | What it shows |
|---|---|
| **Configure** | Task input, domain, agent count, generations — submit a run |
| **Monitor** | Live agent cards, tool call stream, artifacts produced |
| **Evolution** | Topology graph, mutation proposals, gate decisions |
| **Metrics** | Per-generation score table, metric breakdown |
| **Leaderboard** | Top workflows by avg score from ClickHouse |

---

## Infrastructure

```
Your machine / App server (143.110.151.94)
├── python cli.py serve
├── Gemini 2.5 Flash  (Vertex AI)
├── Claude Sonnet 4.6 (Vertex AI)
└── connects to ──────────────────────────────────┐
                                                   │
MongoDB Atlas (cloud)                              │
└── cluster0.zsn3yev.mongodb.net                 │
    organizations, runs, evaluations,             │
    mutations, lessons, eval_cases                │
                                                   │
DigitalOcean Droplet 147.182.239.133 ◀────────────┘
├── Qdrant     :6333  (task embeddings)
└── ClickHouse :8123  (run history + decay scoring)

Kuzu (embedded, in-process)
└── /tmp/kuzu_harness  (topology gene pool graph)
```

### Droplet setup (Docker Compose)

```bash
# On 147.182.239.133
cd /opt/harness && docker-compose up -d
```

---

## Docs

| File | Description |
|---|---|
| [`docs/architecture_diagrams.md`](docs/architecture_diagrams.md) | Full ASCII architecture — 13 diagrams |
| [`docs/14_feedback_flywheel.md`](docs/14_feedback_flywheel.md) | Production feedback flywheel design |
| [`docs/07_evaluation.md`](docs/07_evaluation.md) | LLM judge + scoring details |
| [`docs/04_organization_ir.md`](docs/04_organization_ir.md) | Full harness IR schema reference |
| [`docs/06_evolution_engine.md`](docs/06_evolution_engine.md) | Mutation operators + standing rules |
| [`mod.md`](mod.md) | Changelog — what was built in this session |
