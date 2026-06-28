from __future__ import annotations

from typing import Any, Dict, List, Optional

from pymongo import MongoClient, DESCENDING
from pymongo.database import Database

from src.ir.schema import OrganizationHarness
from src.runtime.executor import RunResult
from src.evaluation.scorer import EvaluationResult
from src.evaluation.gate import GateDecision
from src.memory.serializers import (
    harness_to_doc,
    run_to_doc,
    eval_to_doc,
    gate_decision_to_doc,
    lesson_doc,
)
from src.eval_dataset.models import EvalCase, NEEDS_LABEL, LABELED

_DEFAULT_URI = "mongodb://localhost:27017"
_DEFAULT_DB = "harness_memory"


class MongoMemoryStore:
    """Persistent store for all harness run artifacts.

    Pass an explicit ``db`` (e.g. from mongomock) to avoid a real connection
    in tests.
    """

    def __init__(
        self,
        uri: str = _DEFAULT_URI,
        db_name: str = _DEFAULT_DB,
        db: Optional[Database] = None,
    ) -> None:
        if db is not None:
            self._db = db
        else:
            self._client = MongoClient(uri)
            self._db = self._client[db_name]

        # Ensure useful indexes (idempotent)
        self._db["runs"].create_index([("harness_id", 1), ("harness_version", 1)])
        self._db["evaluations"].create_index([("harness_id", 1), ("total_score", DESCENDING)])
        self._db["mutations"].create_index([("harness_id", 1), ("accepted", 1)])
        self._db["lessons"].create_index([("harness_id", 1)])
        self._db["eval_cases"].create_index([("agent_id", 1), ("status", 1)])

    # ------------------------------------------------------------------
    # Organizations
    # ------------------------------------------------------------------

    def save_organization(self, harness: OrganizationHarness) -> str:
        doc = harness_to_doc(harness)
        self._db["organizations"].replace_one({"_id": doc["_id"]}, doc, upsert=True)
        return doc["_id"]

    def get_organization(self, org_id: str) -> Optional[Dict[str, Any]]:
        return self._db["organizations"].find_one({"_id": org_id}, {"_id": 0})

    def get_best_organization(self, harness_id_prefix: str) -> Optional[Dict[str, Any]]:
        """Return the organization with the highest total_score for a task prefix."""
        top_eval = self._db["evaluations"].find_one(
            {"harness_id": {"$regex": f"^{harness_id_prefix}"}},
            sort=[("total_score", DESCENDING)],
        )
        if not top_eval:
            return None
        return self.get_organization(top_eval["harness_id"])

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------

    def save_run(self, run: RunResult) -> str:
        doc = run_to_doc(run)
        self._db["runs"].replace_one({"_id": doc["_id"]}, doc, upsert=True)
        return doc["_id"]

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        return self._db["runs"].find_one({"_id": run_id}, {"_id": 0})

    def get_runs_for_harness(self, harness_id: str) -> List[Dict[str, Any]]:
        return list(self._db["runs"].find({"harness_id": harness_id}, {"_id": 0}))

    # ------------------------------------------------------------------
    # Evaluations
    # ------------------------------------------------------------------

    def save_evaluation(self, ev: EvaluationResult) -> str:
        doc = eval_to_doc(ev)
        self._db["evaluations"].replace_one({"_id": doc["_id"]}, doc, upsert=True)
        return doc["_id"]

    def get_evaluation(self, run_id: str) -> Optional[Dict[str, Any]]:
        return self._db["evaluations"].find_one({"_id": run_id}, {"_id": 0})

    def get_best_score(self, harness_id: str) -> Optional[float]:
        top = self._db["evaluations"].find_one(
            {"harness_id": harness_id},
            sort=[("total_score", DESCENDING)],
        )
        return top["total_score"] if top else None

    # ------------------------------------------------------------------
    # Mutations / validation decisions
    # ------------------------------------------------------------------

    def save_mutation(
        self,
        run_id: str,
        harness_id: str,
        harness_version: int,
        decision: GateDecision,
        parent_run_id: Optional[str] = None,
    ) -> str:
        doc = gate_decision_to_doc(run_id, harness_id, harness_version, decision, parent_run_id)
        self._db["mutations"].replace_one({"_id": doc["_id"]}, doc, upsert=True)
        return run_id

    def get_accepted_mutations(self, harness_id: str) -> List[Dict[str, Any]]:
        return list(
            self._db["mutations"].find({"harness_id": harness_id, "accepted": True}, {"_id": 0})
        )

    def get_rejected_mutations(self, harness_id: str) -> List[Dict[str, Any]]:
        return list(
            self._db["mutations"].find({"harness_id": harness_id, "accepted": False}, {"_id": 0})
        )

    # ------------------------------------------------------------------
    # Lessons
    # ------------------------------------------------------------------

    def save_lesson(
        self,
        harness_id: str,
        run_id: str,
        failure_signatures: List[Dict[str, Any]],
        accepted: bool,
    ) -> None:
        doc = lesson_doc(harness_id, run_id, failure_signatures, accepted)
        self._db["lessons"].insert_one(doc)

    def get_lessons(self, harness_id: str) -> List[Dict[str, Any]]:
        return list(self._db["lessons"].find({"harness_id": harness_id}, {"_id": 0}))

    # ------------------------------------------------------------------
    # Eval cases (dataset of labeled / unlabeled production cases)
    # ------------------------------------------------------------------

    @staticmethod
    def _eval_doc_to_api(doc: Dict[str, Any]) -> Dict[str, Any]:
        """Map a raw eval_cases doc to an API-friendly dict (``_id`` -> ``id``)."""
        out = dict(doc)
        if "_id" in out:
            out["id"] = out.pop("_id")
        return out

    def save_eval_case(self, case: EvalCase) -> str:
        """Upsert an :class:`EvalCase` into ``eval_cases``; return its id."""
        doc = case.to_doc()
        self._db["eval_cases"].replace_one({"_id": doc["_id"]}, doc, upsert=True)
        return doc["_id"]

    def get_eval_case(self, case_id: str) -> Optional[Dict[str, Any]]:
        doc = self._db["eval_cases"].find_one({"_id": case_id})
        return self._eval_doc_to_api(doc) if doc else None

    def list_eval_cases(
        self,
        status: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List eval cases, optionally filtered by status and/or agent_id."""
        query: Dict[str, Any] = {}
        if status is not None:
            query["status"] = status
        if agent_id is not None:
            query["agent_id"] = agent_id
        return [self._eval_doc_to_api(d) for d in self._db["eval_cases"].find(query)]

    def count_eval_cases(self, agent_id: Optional[str] = None) -> Dict[str, int]:
        """Return counts of needs_label / labeled / total cases."""
        base: Dict[str, Any] = {}
        if agent_id is not None:
            base["agent_id"] = agent_id
        needs = self._db["eval_cases"].count_documents({**base, "status": NEEDS_LABEL})
        labeled = self._db["eval_cases"].count_documents({**base, "status": LABELED})
        total = self._db["eval_cases"].count_documents(base)
        return {"needs_label": needs, "labeled": labeled, "total": total}

    def get_labeled_cases(self, agent_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return all labeled cases (usable as references), optionally per-agent."""
        return self.list_eval_cases(status=LABELED, agent_id=agent_id)

    def label_eval_case(
        self,
        case_id: str,
        expected_output: str,
        labeled_by: str = "admin",
    ) -> Optional[Dict[str, Any]]:
        """Label a case with its expected output; return the updated doc or None."""
        doc = self._db["eval_cases"].find_one({"_id": case_id})
        if not doc:
            return None
        case = EvalCase.from_doc(doc)
        case.label(expected_output, labeled_by=labeled_by)
        self.save_eval_case(case)
        return self._eval_doc_to_api(case.to_doc())

    # ------------------------------------------------------------------
    # Summary helpers (for demo / compiler context)
    # ------------------------------------------------------------------

    def run_summary(self, harness_id: str) -> Dict[str, Any]:
        """Return a compact summary useful for feeding back into the compiler."""
        runs = self.get_runs_for_harness(harness_id)
        best_score = self.get_best_score(harness_id)
        accepted = self.get_accepted_mutations(harness_id)
        lessons = self.get_lessons(harness_id)
        return {
            "harness_id": harness_id,
            "total_runs": len(runs),
            "best_score": best_score,
            "accepted_mutations": len(accepted),
            "lessons": lessons,
        }
