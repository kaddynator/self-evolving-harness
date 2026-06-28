from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TopologyType(str, Enum):
    linear = "linear"
    custom_graph = "custom_graph"
    broadcast = "broadcast"
    pipeline = "pipeline"

class EdgeType(str, Enum):
    blocking = "blocking"
    feedback = "feedback"
    broadcast = "broadcast"

class ExecutionMode(str, Enum):
    phased = "phased"
    sequential = "sequential"
    parallel = "parallel"

class MetricType(str, Enum):
    boolean = "boolean"
    numeric = "numeric"

class TraceLevel(str, Enum):
    minimal = "minimal"
    standard = "standard"
    detailed = "detailed"

class MutationType(str, Enum):
    add_agent = "add_agent"
    remove_agent = "remove_agent"
    modify_prompt = "modify_prompt"
    modify_tools = "modify_tools"
    reorder_edges = "reorder_edges"
    change_topology = "change_topology"
    adjust_budget = "adjust_budget"
    modify_runtime_policy = "modify_runtime_policy"
    modify_failure_recovery = "modify_failure_recovery"
    change_model = "change_model"


# ---------------------------------------------------------------------------
# Organization
# ---------------------------------------------------------------------------

class Organization(BaseModel):
    id: str
    name: str
    version: int = 1
    parent_id: Optional[str] = None
    objective: str
    domain: str
    constraints: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------

class Task(BaseModel):
    id: str
    title: str
    description: str
    inputs: Dict[str, Any] = Field(default_factory=dict)
    success_conditions: List[str]
    artifacts_expected: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

class AgentBudget(BaseModel):
    max_tool_calls: int = 20
    max_runtime_seconds: int = 300

class AgentMemoryPolicy(BaseModel):
    read_shared: bool = True
    write_shared: bool = True

class AgentOutputContract(BaseModel):
    type: str
    required_sections: List[str] = Field(default_factory=list)

class Agent(BaseModel):
    id: str
    name: str
    role: str
    responsibilities: List[str] = Field(default_factory=list)
    prompt: str
    model: Optional[str] = None
    tools: List[str] = Field(default_factory=list)
    budget: AgentBudget = Field(default_factory=AgentBudget)
    memory_policy: AgentMemoryPolicy = Field(default_factory=AgentMemoryPolicy)
    output_contract: Optional[AgentOutputContract] = None


# ---------------------------------------------------------------------------
# Communication
# ---------------------------------------------------------------------------

class Edge(BaseModel):
    from_agent: str = Field(alias="from")
    to: str
    type: EdgeType
    artifact: Optional[str] = None
    max_rounds: Optional[int] = None

    model_config = {"populate_by_name": True}

class SharedMemory(BaseModel):
    enabled: bool = True
    store: List[str] = Field(default_factory=list)

class Communication(BaseModel):
    topology: TopologyType
    edges: List[Edge] = Field(default_factory=list)
    shared_memory: SharedMemory = Field(default_factory=SharedMemory)


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

class Phase(BaseModel):
    name: str
    agents: List[str]
    parallel: bool = False

class RetryPolicy(BaseModel):
    max_retries: int = 1
    retry_on: List[str] = Field(default_factory=list)

class Execution(BaseModel):
    mode: ExecutionMode
    phases: List[Phase]
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    stopping_conditions: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def phases_not_empty(self) -> "Execution":
        if not self.phases:
            raise ValueError("execution.phases must not be empty")
        return self


# ---------------------------------------------------------------------------
# Runtime policies & failure recovery
# ---------------------------------------------------------------------------

class RuntimePolicies(BaseModel):
    max_repeated_tool_errors: int = 2
    max_tool_calls_before_reflection: int = 20
    require_artifact_before_finish: bool = True
    verify_before_conclude: bool = True
    prevent_identical_retry: bool = True
    exploration_to_implementation_threshold: int = 12

class FailureRecovery(BaseModel):
    on_tool_error: str = "Inspect the error, change strategy, do not repeat."
    on_missing_artifact: str = "Create the required artifact immediately."
    on_test_failure: str = "Read the failing assertion and make the smallest fix."
    on_timeout_risk: str = "Stop exploration and produce the best verified artifact."


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

class Metric(BaseModel):
    name: str
    type: MetricType
    source: str
    weight: float

class BinaryCheck(BaseModel):
    id: str
    question: str
    verifier: str

class Scoring(BaseModel):
    formula: str = "weighted_sum"
    success_threshold: float = 70.0

class ValidationGate(BaseModel):
    require_no_regression: List[str] = Field(default_factory=list)
    require_improvement_any: List[str] = Field(default_factory=list)
    max_runtime_seconds: int = 600

class Evaluation(BaseModel):
    metrics: List[Metric]
    binary_checks: List[BinaryCheck] = Field(default_factory=list)
    scoring: Scoring = Field(default_factory=Scoring)
    validation_gate: ValidationGate = Field(default_factory=ValidationGate)

    @model_validator(mode="after")
    def metrics_not_empty(self) -> "Evaluation":
        if not self.metrics:
            raise ValueError("evaluation.metrics must not be empty")
        return self


# ---------------------------------------------------------------------------
# Weakness mining
# ---------------------------------------------------------------------------

class ClusteringConfig(BaseModel):
    method: str = "exact_signature"
    min_cluster_size: int = 1

class WeaknessMining(BaseModel):
    enabled: bool = True
    failure_signature_fields: List[str] = Field(
        default_factory=lambda: ["verifier_cause", "agent_behavior", "mechanism"]
    )
    clustering: ClusteringConfig = Field(default_factory=ClusteringConfig)


# ---------------------------------------------------------------------------
# Mutation policy
# ---------------------------------------------------------------------------

class MutationPolicy(BaseModel):
    allowed_mutations: List[MutationType] = Field(default_factory=list)
    protected_components: List[str] = Field(
        default_factory=lambda: ["task.success_conditions", "evaluation.validation_gate"]
    )
    proposal_width: int = 3
    exploration_strategy: str = "validation_gated_mutate_winner"


# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------

class Observability(BaseModel):
    trace_level: TraceLevel = TraceLevel.standard
    log_events: List[str] = Field(default_factory=list)
    collect_artifacts: bool = True


# ---------------------------------------------------------------------------
# Root: Organization Harness IR
# ---------------------------------------------------------------------------

class OrganizationHarness(BaseModel):
    organization: Organization
    task: Task
    agents: List[Agent]
    communication: Communication
    execution: Execution
    runtime_policies: RuntimePolicies = Field(default_factory=RuntimePolicies)
    failure_recovery: FailureRecovery = Field(default_factory=FailureRecovery)
    evaluation: Evaluation
    weakness_mining: WeaknessMining = Field(default_factory=WeaknessMining)
    mutation_policy: MutationPolicy = Field(default_factory=MutationPolicy)
    observability: Observability = Field(default_factory=Observability)

    @model_validator(mode="after")
    def agents_not_empty(self) -> "OrganizationHarness":
        if not self.agents:
            raise ValueError("agents list must not be empty")
        return self

    @model_validator(mode="after")
    def execution_agents_exist(self) -> "OrganizationHarness":
        agent_ids = {a.id for a in self.agents}
        for phase in self.execution.phases:
            for agent_id in phase.agents:
                if agent_id not in agent_ids:
                    raise ValueError(
                        f"execution phase '{phase.name}' references unknown agent '{agent_id}'"
                    )
        return self

    @model_validator(mode="after")
    def edge_agents_exist(self) -> "OrganizationHarness":
        agent_ids = {a.id for a in self.agents}
        for edge in self.communication.edges:
            for ref in (edge.from_agent, edge.to):
                if ref not in agent_ids:
                    raise ValueError(
                        f"communication edge references unknown agent '{ref}'"
                    )
        return self

    def agent_by_id(self, agent_id: str) -> Agent:
        for agent in self.agents:
            if agent.id == agent_id:
                return agent
        raise KeyError(f"agent '{agent_id}' not found")
