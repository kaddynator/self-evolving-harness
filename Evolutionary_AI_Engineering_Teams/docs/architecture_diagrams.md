# Architecture Diagrams

---

## 1. System Overview

```
                    ┌─────────────────────────────────────────┐
                    │        SELF-EVOLVING HARNESS             │
                    │                                          │
                    │  "Agent teams that improve themselves    │
                    │   from production failures"              │
                    └─────────────────────────────────────────┘

  Plain English Task
         │
         ▼
  ┌─────────────┐     ┌──────────────┐     ┌──────────────┐
  │  COMPILER   │────▶│   RUNTIME    │────▶│  EVALUATOR   │
  │  (Gemini)   │     │  (Executor)  │     │  (LLM Judge) │
  └─────────────┘     └──────────────┘     └──────────────┘
         │                   │                    │
         │            Harness IR            EvaluationResult
         │                   │                    │
         ▼                   ▼                    ▼
  ┌─────────────┐     ┌──────────────┐     ┌──────────────┐
  │  EVOLUTION  │◀────│  WEAKNESS    │◀────│    GATE      │
  │  ENGINE     │     │   MINER      │     │  (accept?)   │
  └─────────────┘     └──────────────┘     └──────────────┘
         │
         ▼
  ┌─────────────┐     ┌──────────────┐
  │  MONGODB    │     │  FEEDBACK    │
  │  MEMORY     │◀────│  FLYWHEEL    │
  └─────────────┘     └──────────────┘
```

---

## 2. Organization Harness IR (the core data structure)

```
  OrganizationHarness
  ├── organization
  │     id: "wf-ratelimiter"          ← stable across generations
  │     version: 3                    ← increments per mutation
  │     parent_id: "wf-ratelimiter"
  │     objective: "Add rate limiter..."
  │     domain: "software_engineering"
  │
  ├── task
  │     id, title, description
  │     success_conditions: ["API returns 429...", "Tests pass"]
  │     artifacts_expected: ["code_patch", "test_results"]
  │
  ├── agents[]
  │     ┌──────────────────────────────────────┐
  │     │ requirements_agent                   │
  │     │   model: "gemini-2.5-flash"          │
  │     │   tools: [read_files, list_files]    │
  │     │   budget: {max_tool_calls: 5}        │
  │     │   prompt: "Analyze the codebase..."  │
  │     └──────────────────────────────────────┘
  │     ┌──────────────────────────────────────┐
  │     │ coder_agent                          │
  │     │   tools: [read_files, edit_files,    │
  │     │           run_tests, git_diff]       │
  │     │   budget: {max_tool_calls: 10}       │
  │     └──────────────────────────────────────┘
  │     ┌──────────────────────────────────────┐
  │     │ tester_agent / reviewer_agent        │
  │     └──────────────────────────────────────┘
  │
  ├── communication
  │     topology: "linear"
  │     edges:
  │       requirements_agent ──blocking──▶ coder_agent
  │       coder_agent        ──blocking──▶ tester_agent
  │       tester_agent       ──blocking──▶ reviewer_agent
  │     shared_memory: {enabled: true}
  │
  ├── execution
  │     mode: "phased"
  │     phases:
  │       understand:  [requirements_agent]
  │       implement:   [coder_agent]
  │       verify:      [tester_agent, reviewer_agent]
  │
  ├── evaluation
  │     metrics:
  │       tests_pass          weight: +50   (boolean)
  │       reviewer_acceptance weight: +30   (boolean)
  │       tool_calls          weight:  -1   (numeric, lower=better)
  │     binary_checks:
  │       output_produced     verifier: artifact_check
  │       success_criteria    verifier: llm_judge
  │     scoring: {success_threshold: 70.0}
  │     validation_gate:
  │       require_no_regression:   [tests_pass]
  │       require_improvement_any: [total_score, tool_calls]
  │
  └── mutation_policy
        allowed_mutations: [modify_prompt, add_agent, remove_agent,
                            adjust_budget, modify_tools, change_model,
                            reorder_edges, modify_runtime_policy]
        proposal_width: 3
```

---

## 3. Compiler

```
  Input: task_description (str), domain, constraints[], prior_lessons[]
         │
         ▼
  ┌──────────────────────────────────────────────────────┐
  │                  HarnessCompiler.compile()           │
  │                                                      │
  │  build_compilation_prompt()                          │
  │    ├── task + domain + constraints                   │
  │    ├── prior_lessons from MongoDB                    │
  │    └── prompt_detail: brief|detailed|exhaustive      │
  │                  │                                   │
  │                  ▼                                   │
  │         Gemini / Claude LLM                          │
  │                  │                                   │
  │                  ▼ raw YAML                          │
  │  _extract_yaml() ──▶ _parse_and_validate()           │
  │          │                   │                       │
  │          │ fail              │ ok                    │
  │          ▼                   ▼                       │
  │  build_retry_prompt()   _normalize_evaluation_       │
  │  (feed error back)      contract()                   │
  │  loop up to 3x          (canonical metrics)          │
  │                                │                     │
  │                                ▼                     │
  │                     _expand_agents()                 │
  │                     (pad/trim to num_agents)         │
  │                                │                     │
  └────────────────────────────────┼─────────────────────┘
                                   │
                                   ▼
                          OrganizationHarness IR

  Domain templates (mock mode):
  ┌─────────────────────┬──────────────────────────────┐
  │ software_engineering│ requirements→coder→tester    │
  │                     │ →reviewer (4 agents)          │
  ├─────────────────────┼──────────────────────────────┤
  │ research            │ researcher→analyst→writer     │
  ├─────────────────────┼──────────────────────────────┤
  │ data_pipeline       │ fetcher→processor→reporter   │
  ├─────────────────────┼──────────────────────────────┤
  │ bloated_engineering │ 30 agents, 5 phases           │
  │                     │ (stress-test evolution)       │
  └─────────────────────┴──────────────────────────────┘
```

---

## 4. Runtime Executor

```
  OrganizationHarness
         │
         ▼
  RuntimeExecutor.run(harness, generation)
         │
         ├─ emit: run_started
         │
         ▼
  ┌──────────────────────────────────────────────┐
  │  for phase in harness.execution.phases:      │
  │                                              │
  │   phase.parallel?                            │
  │     YES ──▶ ThreadPoolExecutor               │
  │     NO  ──▶ sequential                       │
  │                                              │
  │   for agent in phase.agents:                 │
  │   ┌──────────────────────────────────┐       │
  │   │  emit: agent_started             │       │
  │   │                                  │       │
  │   │  agent_runner(agent)             │       │
  │   │  ├── Gemini function-call loop   │       │
  │   │  │     contents → LLM            │       │
  │   │  │     LLM → function_call?      │       │
  │   │  │       YES → ToolSandbox       │       │
  │   │  │             dispatch(tool)    │       │
  │   │  │             append result     │       │
  │   │  │             loop (cap: budget)│       │
  │   │  │       NO  → final text        │       │
  │   │  │                               │       │
  │   │  ├── emit: agent_tool_call(×N)   │       │
  │   │  ├── merge artifacts             │       │
  │   │  ├── update shared_memory        │       │
  │   │  └── emit: agent_finished        │       │
  │   └──────────────────────────────────┘       │
  └──────────────────────────────────────────────┘
         │
         ▼
  ToolSandbox (per-agent temp dir):
  ┌────────────────────────────────────────┐
  │ read_files   list_files   write_file   │
  │ edit_files   delete_file  run_command  │
  │ run_tests    python_repl  git_diff     │
  │ git_log                                │
  │ [web_search / read_url / query_db]     │
  │  └── stubs (not_configured)           │
  └────────────────────────────────────────┘
         │
         ▼
  RunResult:
    run_id, harness_id, harness_version
    success, stop_reason
    events:        [TraceEvent{type, agent_id, phase, data}]
    artifacts:     {code_patch, test_results, review_notes,
                    acceptance_criteria, execution_trace}
    shared_memory: {<same keys, cross-agent>}
    total_tool_calls: int
    elapsed_seconds:  float
```

---

## 5. Evaluation & Scoring

```
  RunResult + Evaluation spec + optional LLM Judge
         │
         ▼
  score_run()
         │
         ├─ _extract_raw_metrics(run)
         │     tests_pass          ← test_results.failed == 0
         │     reviewer_acceptance ← "approved" in review_notes
         │     tool_calls          ← run.total_tool_calls
         │     diff_size           ← len(code_patch.splitlines())
         │     runtime_seconds     ← run.elapsed_seconds
         │
         ├─ GeminiJudge.grade(run, harness)   [if judge present]
         │     ├─ Build prompt: success_conditions + artifacts
         │     ├─ LLM call (Claude 4.6 or Gemini 3.5-flash)
         │     └─ Parse JSON verdicts → override boolean raw_metrics
         │
         ├─ _score_metric() per metric
         │     boolean: 1.0 if true, 0.0 if false  × weight
         │     numeric: raw_value                  × weight
         │     ─────────────────────────────────────────────
         │     tests_pass:          true  → +50
         │     reviewer_acceptance: true  → +30
         │     tool_calls:          12    → -12
         │     ─────────────────────────────────
         │     total_score = 50 + 30 - 12 = 68
         │
         ├─ _run_binary_check() per check
         │     "test_runner"  → tests_pass metric
         │     "llm_judge"    → diff_size <= 30
         │     "artifact_check" → artifact present?
         │
         └─▶ EvaluationResult:
               raw_metrics:          {tests_pass: true, ...}
               metric_scores:        {tests_pass: 50, tool_calls: -12}
               binary_check_results: [{id, passed, detail}]
               total_score:          68.0
               passed_threshold:     false  (< 70.0)

  ─────────────────────────────────────────────────────
  LLM Clients (src/llm/clients.py):

  build_judge_client(prefer="claude")
       │
       ├── AnthropicVertexClient      [preferred]
       │     Claude Sonnet 4.6 via Vertex AI
       │     Auth: Google ADC
       │     Env: CLAUDE_MODEL, VERTEX_PROJECT
       │
       └── GeminiAPIClient            [fallback]
             Gemini 3.5-flash via REST
             Auth: GEMINI_API_KEY
             Env: GEMINI_MODEL, GEMINI_API_KEY
```

---

## 6. Weakness Mining

```
  RunResult + EvaluationResult + OrganizationHarness
         │
         ▼
  mine_weaknesses()
         │
  ┌──────┴──────────────────────────────────────────────┐
  │  Rule                    Fires when                  │
  ├──────────────────────────────────────────────────────┤
  │  _check_tests_failed     ev.tests_pass == False      │
  │  → WEAK_REQUIREMENTS_GROUNDING                       │
  │                                                      │
  │  _check_missing_artifacts  artifact not in           │
  │  → MISSING_REQUIRED_ARTIFACT  run.artifacts          │
  │                                                      │
  │  _check_repeated_tool_errors  same (agent, tool)     │
  │  → REPEATED_FAILED_TOOL_CALL  errors > 1             │
  │                                                      │
  │  _check_excessive_exploration  tool_calls >          │
  │  → EXCESSIVE_EXPLORATION       threshold             │
  │                                                      │
  │  _check_wrong_tool_permission  error="not_permitted" │
  │  → WRONG_TOOL_PERMISSION                             │
  │                                                      │
  │  _check_oversized_patch   diff_size > 100 lines      │
  │  → OVERSIZED_PATCH                                   │
  │                                                      │
  │  _check_unverified_completion  verify_before=True    │
  │  → UNVERIFIED_COMPLETION       but no test artifact  │
  │                                                      │
  │  _check_late_testing     coder runs tests before     │
  │  → LATE_TESTING          tester phase                │
  │                                                      │
  │  _check_redundant_agents  agents > 5 and             │
  │  → REDUNDANT_AGENT        excess tool calls          │
  └──────────────────────────────────────────────────────┘
         │
         ▼  _deduplicate() by (mechanism, agent_behavior)
         │
  List[FailureSignature]:
    mechanism:       WEAK_REQUIREMENTS_GROUNDING
    verifier_cause:  "tests_failed"
    agent_behavior:  "implementation_produced_failing_tests"
    agent_id:        "coder_agent"
    detail:          "2 tests failed..."
```

---

## 7. Evolution Engine & Mutators

```
  FailureSignatures + OrganizationHarness + optional LLM client
         │
         ▼
  propose_mutations()
         │
         ├─ STANDING RULES (every generation)
         │    │
         │    ├─ _rule_evolve_a_prompt()
         │    │     pick most-implicated agent
         │    │     expand_agent_prompt(client, agent)
         │    │       └─ LLM: "Expand this prompt with guidance: {sigs}"
         │    │     modify_prompt(harness, agent_id, grown_prompt)
         │    │     → candidate_v(n+1)
         │    │
         │    └─ _rule_optimize_agent_model()
         │          pick underperforming agent
         │          next_tier(current_model)
         │            gemini-2.0-flash → gemini-2.5-flash → gemini-2.5-pro
         │          change_model(harness, agent_id, new_model)
         │          → candidate_v(n+1)
         │
         └─ SIGNATURE-DRIVEN RULES
              │
              ├─ WEAK_REQUIREMENTS_GROUNDING
              │    └─ modify_prompt(requirements_agent, "+Always ground in test assertions")
              │
              ├─ MISSING_REQUIRED_ARTIFACT
              │    └─ modify_runtime_policy(require_artifact_before_finish=True)
              │
              ├─ WRONG_TOOL_PERMISSION
              │    └─ modify_tools(agent_id, add_tools=[missing_tool])
              │
              ├─ EXCESSIVE_EXPLORATION
              │    └─ adjust_budget(coder_agent, max_tool_calls=current-1)
              │
              ├─ REPEATED_FAILED_TOOL_CALL
              │    └─ modify_runtime_policy(prevent_identical_retry=True)
              │
              ├─ OVERSIZED_PATCH
              │    └─ modify_prompt(coder, "+Keep patch under 30 lines")
              │
              ├─ UNVERIFIED_COMPLETION
              │    └─ add_agent(verifier_agent, last_phase)
              │          [reads artifacts, runs tests, blocks completion]
              │
              ├─ LATE_TESTING
              │    └─ reorder_edges(coder→tester, type="blocking")
              │
              └─ REDUNDANT_AGENT
                   └─ remove_agent(non_core_agent_id)

  ─────────────────────────────────────────────────────────────
  All mutators call _clone(harness) first:
    clone.organization.version += 1   (id stays constant)
    clone.organization.parent_id = original.id
  Then apply the specific structural change.

  Returns: List[(MutationProposal, CandidateHarness)]
           capped at mutation_policy.proposal_width (default 3)
```

---

## 8. Validation Gate

```
  For each (proposal, candidate_harness):

  candidate_harness
         │
         ├─ RuntimeExecutor.run(candidate)  → cand_run
         ├─ score_run(cand_run)             → cand_ev
         │
         ▼
  apply_validation_gate(cand_ev, parent_ev, gate)
         │
         ├─ Check 1: Runtime budget
         │     cand.runtime_seconds ≤ gate.max_runtime_seconds?
         │     NO  → REJECT "exceeded max runtime"
         │
         ├─ Check 2: First run (no parent)
         │     cand.passed_threshold?
         │     YES → ACCEPT
         │     NO  → REJECT
         │
         ├─ Check 3: Regressions
         │     for metric in gate.require_no_regression:
         │       if cand_val < parent_val:
         │         regressions.append(metric)
         │     regressions not empty → REJECT "regressed: [tests_pass]"
         │
         └─ Check 4: Improvement
               for metric in gate.require_improvement_any:
                 tool_calls / runtime: lower is better
                 others: higher is better
               improvements not empty → ACCEPT
               improvements empty    → REJECT "no improvement detected"
         │
         ▼
  GateDecision:
    accepted:     True / False
    reason:       "improved total_score (+12.0)" | "regressed tests_pass"
    regressions:  []
    improvements: ["total_score"]
         │
         ▼
  If accepted:
    store.save_organization(candidate)
    store.save_run(cand_run)
    store.save_evaluation(cand_ev)
    accepted_candidate = candidate  (advances next generation)
```

---

## 9. Full Evolution Loop

```
  ┌──────────────────────────────────────────────────────────────────┐
  │                    run_evolution(harness, max_gen=3)             │
  │                                                                  │
  │  gen=1                    gen=2                    gen=3         │
  │  ┌─────────┐              ┌─────────┐              ┌─────────┐   │
  │  │ harness │              │  v2     │              │  v3     │   │
  │  │   v1    │─ accepted ──▶│ cand    │─ accepted ──▶│ cand    │   │
  │  └─────────┘              └─────────┘              └─────────┘   │
  │       │                        │                        │        │
  │   run_cycle()              run_cycle()              run_cycle()  │
  │       │                        │                        │        │
  │  ┌────▼──────────────────────────────────────────────────────┐   │
  │  │  1. save_organization(harness)                            │   │
  │  │  2. executor.run()     → RunResult                        │   │
  │  │  3. save_run()                                            │   │
  │  │  4. score_run()        → EvaluationResult  (score=68)     │   │
  │  │  5. save_evaluation()                                     │   │
  │  │  6. mine_weaknesses()  → [WEAK_REQUIREMENTS_GROUNDING]    │   │
  │  │  7. save_lesson()                                         │   │
  │  │  8. propose_mutations() → 3 candidates                    │   │
  │  │      ├── cand_A: modify_prompt                            │   │
  │  │      ├── cand_B: evolve_prompt (LLM-grown)                │   │
  │  │      └── cand_C: change_model                             │   │
  │  │  9. for each candidate:                                   │   │
  │  │      executor.run(cand)    → cand_run                     │   │
  │  │      score_run(cand_run)   → cand_ev  (score=81)          │   │
  │  │      apply_gate(cand_ev)   → ACCEPTED (81 > 68, no regr.) │   │
  │  │      save_mutation(accepted=True)                         │   │
  │  │  10. return CycleResult(accepted_candidate=cand_A)        │   │
  │  └───────────────────────────────────────────────────────────┘   │
  │                                                                  │
  │  Events emitted throughout (SSE → browser UI):                  │
  │  evolution_start → generation_start → agent_start               │
  │  → agent_tool_call(×N) → agent_finish → run_complete            │
  │  → evaluation_complete → weakness_mined → mutation_proposed     │
  │  → gate_decision → harness_snapshot → generation_finish         │
  │  → evolution_complete                                            │
  └──────────────────────────────────────────────────────────────────┘
```

---

## 10. Feedback Flywheel

```
  PRODUCTION SERVING
         │
         ▼
  ┌─────────────────────────────────────┐
  │  Current harness serves requests   │
  │  (e.g., finops-gcp agent)          │
  └─────────────────────────────────────┘
         │
         │  user: "this is useless, rate limiter doesn't work"
         ▼
  ┌─────────────────────────────────────┐
  │  Sentiment Sentinel                 │
  │  (platform-level, NOT a harness    │
  │   node — cannot be evolved away)   │
  │                                    │
  │  negative? → capture EvalCase      │
  └─────────────────────────────────────┘
         │
         ▼
  EvalCase (status=needs_label):
    agent_id:         "finops-gcp"
    input:            "Implement rate limiter..."
    context_snapshot: {repo: "...", test_cmd: "npm test"}  ← frozen, replayable
    actual_output:    "Sorry, that is complex."
    feedback:         "useless, doesn't work"
    sentiment:        "negative"
         │
         │  admin: "Here is the correct answer"
         ▼
  EvalCase (status=labeled):
    expected_output: "Added rate limiter in routes.py line 42,
                      5 req/min per user, 3 tests pass"
         │
         │  batch threshold reached (N labeled cases)
         ▼
  ┌─────────────────────────────────────┐
  │  Trigger Evolution                  │
  │  run_cycle(harness) against         │
  │  FULL labeled dataset               │
  └─────────────────────────────────────┘
         │
         ▼
  Reference Grading (per candidate):
  GeminiJudge.grade_against_expected(
    input:           "Implement rate limiter..."
    actual_output:   candidate's output
    expected_output: admin's labeled answer
  ) → {match: bool, score: 0-1, missing: [], rationale}
         │
         ▼
  Validation Gate:
    new harness fixes complaint?  YES ┐
    no regression on old cases?   YES ┘ → ACCEPT → REDEPLOY
    otherwise                         → REJECT → keep current
         │
         ▼
  ┌─────────────────────────────────────┐
  │  Serve updated harness              │
  │  (loop continues)                  │
  └─────────────────────────────────────┘
```

---

## 11. MongoDB Memory

```
  ┌─────────────────────────────────────────────────────────────┐
  │                    MongoDB Atlas                             │
  │                                                             │
  │  organizations                                              │
  │    _id: "wf-ratelimiter"                                    │
  │    full harness IR (YAML-equivalent as doc)                 │
  │    indexed by: _id                                          │
  │                                                             │
  │  runs                                                       │
  │    _id: run_id (UUID)                                       │
  │    harness_id, harness_version                              │
  │    events[], artifacts{}, total_tool_calls, elapsed         │
  │    indexed by: (harness_id, harness_version)                │
  │                                                             │
  │  evaluations                                                │
  │    _id: run_id                                              │
  │    harness_id, total_score, metric_scores{}, passed         │
  │    indexed by: (harness_id, total_score DESC)               │
  │                                                             │
  │  mutations                                                  │
  │    _id: run_id                                              │
  │    harness_id, accepted, reason, parent_run_id              │
  │    indexed by: (harness_id, accepted)                       │
  │                                                             │
  │  lessons                                                    │
  │    harness_id, run_id                                       │
  │    failure_signatures[], accepted                           │
  │    indexed by: harness_id                                   │
  │                                                             │
  │  eval_cases                                                 │
  │    _id: "ec-<hex>"                                          │
  │    agent_id, input, context_snapshot{}                      │
  │    expected_output (null → labeled)                         │
  │    actual_output, status, source, feedback                  │
  │    indexed by: (agent_id, status)                           │
  └─────────────────────────────────────────────────────────────┘

  run_summary(harness_id) →
    {total_runs, best_score, accepted_mutations, lessons[]}
    (fed back into compiler as prior_lessons for next compile)
```

---

## 12. Observability & Web UI

```
  EvolutionPipeline
         │ emits PipelineEvent
         ▼
  ┌─────────────────┐
  │    EventBus     │──── publish() ────▶ subscribers
  └─────────────────┘
         │
         ├──▶ PipelineStateTracker (in-memory REST state)
         │      GET /api/state → full run state snapshot
         │
         ├──▶ RichTerminalObserver (terminal output)
         │
         └──▶ SSE stream (/api/events)
                    │
                    ▼ browser
  ┌────────────────────────────────────────────────┐
  │              Web UI (index.html)               │
  │                                                │
  │  ┌──────────┬──────────┬──────────┬──────────┐ │
  │  │Configure │ Monitor  │Evolution │ Metrics  │ │
  │  └──────────┴──────────┴──────────┴──────────┘ │
  │                                                │
  │  Configure tab:                                │
  │    task input, domain, num_agents, generations │
  │    POST /api/run → starts pipeline thread      │
  │                                                │
  │  Monitor tab:                                  │
  │    live agent cards (running/done/error)       │
  │    tool call stream, artifact list             │
  │    score gauge, generation progress            │
  │                                                │
  │  Evolution tab:                                │
  │    topology graph (agents + edges)             │
  │    mutation proposals + gate decisions         │
  │                                                │
  │  Metrics tab:                                  │
  │    per-generation score table                  │
  │    metric breakdown                            │
  └────────────────────────────────────────────────┘

  API endpoints:
    POST /api/run          start evolution
    POST /api/stop         stop between generations
    POST /api/feedback     continue with user feedback
    GET  /api/state        current pipeline state
    GET  /api/events       SSE stream
    GET  /api/leaderboard  top workflows from ClickHouse
```

---

## 13. Infrastructure

```
  Your Mac (dev / local serve)
  ├── python cli.py serve
  ├── Gemini / Claude API calls (LLM inference)
  └── connects to ──────────────────────────────┐
                                                 │
  MongoDB Atlas (cloud)                          │
  └── cluster0.zsn3yev.mongodb.net              │
      organizations, runs, evaluations,          │
      mutations, lessons, eval_cases             │
                                                 │
  Droplet 147.182.239.133 (DB server) ◀──────────┘
  ├── Qdrant  :6333  (task embeddings)
  └── ClickHouse :8123  (run history + decay scoring)

  Droplet 143.110.151.94 (app server — pending deploy)
  └── python cli.py serve --port 8765
      connects to both Atlas + 147.182.239.133

  Kuzu (embedded, in-process)
  └── /tmp/kuzu_harness  (topology gene pool graph)
```
