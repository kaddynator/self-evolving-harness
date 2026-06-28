# What Was Built

## Removed
- `src/runtime/mock_agents.py` — all fake tool simulation deleted
- `mongomock` dependency — removed from CLI
- `--gemini` flag — redundant, Gemini is now always default
- All test files under `tests/` — deleted per request

## Real Execution (no mocking)
- `RuntimeExecutor` — `agent_runner` is now required, no mock default
- `EvolutionPipeline` — `agent_runner` required, Gemini runner wired as default
- `cli.py` — Gemini 2.5 Flash is default for all commands (compile, run, evolve, serve)
- Web server callback — was hardcoding `agent_runner = None` (mock), now uses real Gemini

## Storage Stack

### MongoDB Atlas
- URI: `cluster0.zsn3yev.mongodb.net`
- Stores: organizations, runs, evaluations, mutations, lessons
- Auto-loaded from `.env`

### Qdrant (147.182.239.133:6333)
- `src/memory/qdrant_store.py`
- Task embeddings via Gemini `text-embedding-004`
- Cosine similarity search for warm-start topology retrieval

### Kuzu (embedded, no server)
- `src/memory/kuzu_store.py`
- Graph DB for agent topology gene pool
- Nodes: Task, Workflow, AgentNode, Tool
- Edges: RAN, HAS_NODE, CONNECTS_TO, USES_TOOL, SIMILAR_TO

### ClickHouse (147.182.239.133:8123)
- `src/memory/clickhouse_store.py`
- Run history with 90-day TTL
- Score = quality / cost with time-decay (`exp(-days/30)`)
- Tables: tasks, runs, agent_nodes

## Evolution Loop (updated)
```
Task
  → Qdrant: find similar past tasks by embedding
  → ClickHouse: top scoring workflow_ids for those tasks (decay-weighted)
  → Kuzu: load full topology for those workflows
  → Main Agent (Gemini): generate mutations using prior topologies as context
  → Run all candidates
  → Score each: quality / cost
  → Store results → Qdrant + Kuzu + ClickHouse
  → Repeat
```

## Mutation Types
- `modify_prompt` — strengthen agent instructions
- `adjust_budget` — tighten max tool calls
- `add_agent` — insert verifier agent
- `remove_agent` — prune redundant agents
- `modify_tools` — fix tool permissions
- `modify_runtime_policy` — enforce artifact/retry rules
- `reorder_edges` — enforce execution order
- `change_model` — upgrade model tier

## Infrastructure

### DB Droplet (147.182.239.133)
- Qdrant :6333
- ClickHouse :8123 / :9000
- Running via Docker Compose at `/opt/harness/docker-compose.yml`

### App Droplet (143.110.151.94)
- Pending deploy
- Runs `python3 cli.py serve --port 8765`

## Config (.env)
```
MONGODB_URI=mongodb+srv://...
DROPLET_IP=147.182.239.133
CH_USER=harness
CH_PASSWORD=harness123
CH_DB=harness
KUZU_PATH=/tmp/kuzu_harness
```

## UI Changes
- New **Leaderboard** tab — fetches top workflows from ClickHouse via `/api/leaderboard`
- Scores ranked by avg quality/cost ratio across all runs
- Auto-loads when tab is clicked

## CLI
```bash
python cli.py serve              # start web UI (Gemini default)
python cli.py compile "task"    # synthesize harness YAML
python cli.py evolve harness.yaml --generations 5
python cli.py --do-ai serve     # use DigitalOcean AI instead of Gemini
python cli.py --droplet <IP>    # override droplet IP for vector stores
```
