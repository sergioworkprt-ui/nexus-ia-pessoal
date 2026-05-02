"""
NEXUS Multi-IA — Orchestrator
Multi-agent pipeline execution: sequential, parallel, fallback, and custom DAG.
Each pipeline step can target a specific agent, use routing, or broadcast.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from .agent import AgentRequest, AgentResponse, BaseAgent
from .consensus import ConsensusEngine, ConsensusMethod, ConsensusResult
from .registry import AgentRegistry
from .router import Router, RoutingStrategy


# ---------------------------------------------------------------------------
# Pipeline primitives
# ---------------------------------------------------------------------------

class StepStatus(str, Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    DONE      = "done"
    FAILED    = "failed"
    SKIPPED   = "skipped"


@dataclass
class PipelineStep:
    """A single step in a multi-agent pipeline."""
    name:          str
    task_fn:       Callable[[Dict[str, Any]], str]   # receives context, returns task string
    agent_name:    Optional[str] = None              # target a specific agent
    strategy:      RoutingStrategy = RoutingStrategy.BEST_CAPABILITY
    timeout:       float = 30.0
    required:      bool  = True       # if False, failure is non-blocking
    store_as:      Optional[str] = None   # key to store result in shared context
    max_tokens:    int   = 1024

    def build_request(self, context: Dict[str, Any]) -> AgentRequest:
        task = self.task_fn(context)
        return AgentRequest(task=task, context=context,
                            max_tokens=self.max_tokens, timeout=self.timeout)


@dataclass
class StepResult:
    step_name:  str
    status:     StepStatus
    response:   Optional[AgentResponse] = None
    error:      Optional[str]           = None
    latency_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step":       self.step_name,
            "status":     self.status.value,
            "agent":      self.response.agent_name if self.response else None,
            "ok":         self.response.ok if self.response else False,
            "latency_ms": round(self.latency_ms, 2),
            "error":      self.error,
        }


@dataclass
class PipelineResult:
    """Aggregated outcome of a full pipeline run."""
    pipeline_id:      str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    pipeline_name:    str = ""
    strategy:         str = ""
    step_results:     List[StepResult] = field(default_factory=list)
    final_response:   Optional[AgentResponse] = None
    consensus_result: Optional[ConsensusResult] = None
    context:          Dict[str, Any] = field(default_factory=dict)
    started_at:       str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at:      Optional[str] = None
    total_ms:         float = 0.0
    errors:           List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        required_failed = [
            s for s in self.step_results
            if s.status == StepStatus.FAILED
        ]
        return len(required_failed) == 0

    def summary(self) -> Dict[str, Any]:
        return {
            "pipeline_id":   self.pipeline_id,
            "name":          self.pipeline_name,
            "strategy":      self.strategy,
            "steps":         len(self.step_results),
            "ok":            self.ok,
            "total_ms":      round(self.total_ms, 2),
            "step_details":  [s.to_dict() for s in self.step_results],
            "errors":        self.errors,
            "finished_at":   self.finished_at,
        }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class Orchestrator:
    """
    Executes multi-agent pipelines with four built-in execution models:

    - **sequential**: steps run one by one; output of each step is added to context
    - **parallel**: all agents called concurrently; consensus applied to outputs
    - **fallback**: try agents in priority order until one succeeds
    - **pipeline**: custom list of PipelineStep objects, supports mixed strategies

    All methods are thread-safe and non-blocking (agents are called in daemon threads
    for parallel/pipeline modes).
    """

    def __init__(
        self,
        registry:  AgentRegistry,
        router:    Router,
        consensus: ConsensusEngine,
    ) -> None:
        self._registry  = registry
        self._router    = router
        self._consensus = consensus
        self._history:  List[PipelineResult] = []

    # ------------------------------------------------------------------
    # Sequential execution
    # ------------------------------------------------------------------

    def run_sequential(
        self,
        steps: List[PipelineStep],
        initial_context: Optional[Dict[str, Any]] = None,
        pipeline_name: str = "sequential",
    ) -> PipelineResult:
        """
        Run steps one after another. Each step's output is stored in the shared
        context under step.store_as (or step.name if store_as is not set).
        """
        t0      = time.perf_counter()
        context = dict(initial_context or {})
        result  = PipelineResult(pipeline_name=pipeline_name, strategy="sequential",
                                  context=context)

        for step in steps:
            sr = self._run_step(step, context)
            result.step_results.append(sr)

            if sr.status == StepStatus.DONE and sr.response:
                key = step.store_as or step.name
                context[key] = sr.response.content
                result.final_response = sr.response
            elif sr.status == StepStatus.FAILED and step.required:
                result.errors.append(f"Required step '{step.name}' failed: {sr.error}")
                break

        result.total_ms   = (time.perf_counter() - t0) * 1000
        result.finished_at = datetime.now(timezone.utc).isoformat()
        self._history.append(result)
        return result

    # ------------------------------------------------------------------
    # Parallel execution + consensus
    # ------------------------------------------------------------------

    def run_parallel(
        self,
        task: str,
        agents: Optional[List[BaseAgent]] = None,
        n_agents: int = 3,
        consensus_method: ConsensusMethod = ConsensusMethod.WEIGHTED_AVERAGE,
        context: Optional[Dict[str, Any]] = None,
        pipeline_name: str = "parallel",
    ) -> PipelineResult:
        """
        Call multiple agents simultaneously with the same task, then
        apply consensus to produce a unified answer.
        """
        t0 = time.perf_counter()
        ctx = dict(context or {})

        if agents is None:
            req_tmp = AgentRequest(task=task)
            agents  = self._router.route_many(req_tmp, n=n_agents)

        if not agents:
            result = PipelineResult(pipeline_name=pipeline_name, strategy="parallel")
            result.errors.append("No agents available for parallel execution.")
            result.finished_at = datetime.now(timezone.utc).isoformat()
            result.total_ms    = (time.perf_counter() - t0) * 1000
            self._history.append(result)
            return result

        step_results_lock = threading.Lock()
        step_results: List[StepResult] = []
        responses:    List[AgentResponse] = []

        def _call(agent: BaseAgent) -> None:
            req = AgentRequest(task=task, context=ctx)
            ts = time.perf_counter()
            try:
                resp = agent.call(req)
                sr   = StepResult(
                    step_name=agent.name,
                    status=StepStatus.DONE if resp.ok else StepStatus.FAILED,
                    response=resp,
                    latency_ms=(time.perf_counter() - ts) * 1000,
                )
            except Exception as exc:
                sr = StepResult(
                    step_name=agent.name, status=StepStatus.FAILED,
                    error=str(exc), latency_ms=(time.perf_counter() - ts) * 1000,
                )
            with step_results_lock:
                step_results.append(sr)
                if sr.response and sr.response.ok:
                    responses.append(sr.response)

        threads = [threading.Thread(target=_call, args=(a,), daemon=True) for a in agents]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=max(a.priority * 5 + 30 for a in agents))

        consensus_result = self._consensus.reach_consensus(responses, consensus_method, task)

        result = PipelineResult(
            pipeline_name=pipeline_name, strategy="parallel",
            step_results=step_results,
            context=ctx,
            consensus_result=consensus_result,
        )
        if consensus_result.final_content:
            from .agent import AgentResponse as AR
            result.final_response = AR(
                request_id="consensus",
                agent_id="consensus",
                agent_name=consensus_result.selected_agent or "consensus",
                provider=agents[0].provider if agents else __import__("multi_ia.agent", fromlist=["AgentProvider"]).AgentProvider.CUSTOM,
                model="consensus",
                content=consensus_result.final_content,
                confidence=consensus_result.confidence,
                tokens_used=0,
                latency_ms=0.0,
            )
        if consensus_result.escalated:
            result.errors.append(
                f"Consensus escalated: {consensus_result.escalation_reason}"
            )

        result.total_ms    = (time.perf_counter() - t0) * 1000
        result.finished_at = datetime.now(timezone.utc).isoformat()
        self._history.append(result)
        return result

    # ------------------------------------------------------------------
    # Fallback execution
    # ------------------------------------------------------------------

    def run_with_fallback(
        self,
        task: str,
        agents: Optional[List[BaseAgent]] = None,
        context: Optional[Dict[str, Any]] = None,
        pipeline_name: str = "fallback",
    ) -> PipelineResult:
        """
        Try agents in order until one succeeds. Returns on first success.
        """
        t0  = time.perf_counter()
        ctx = dict(context or {})
        req = AgentRequest(task=task, context=ctx)

        if agents is None:
            agents = self._router.route_with_fallbacks(req)

        result = PipelineResult(pipeline_name=pipeline_name, strategy="fallback", context=ctx)

        for agent in agents:
            ts = time.perf_counter()
            try:
                resp = agent.call(req)
                sr   = StepResult(
                    step_name=agent.name,
                    status=StepStatus.DONE if resp.ok else StepStatus.FAILED,
                    response=resp,
                    latency_ms=(time.perf_counter() - ts) * 1000,
                )
                result.step_results.append(sr)
                if resp.ok:
                    result.final_response = resp
                    break
            except Exception as exc:
                result.step_results.append(StepResult(
                    step_name=agent.name, status=StepStatus.FAILED,
                    error=str(exc), latency_ms=(time.perf_counter() - ts) * 1000,
                ))

        if result.final_response is None:
            result.errors.append("All agents failed in fallback chain.")

        result.total_ms    = (time.perf_counter() - t0) * 1000
        result.finished_at = datetime.now(timezone.utc).isoformat()
        self._history.append(result)
        return result

    # ------------------------------------------------------------------
    # Custom pipeline
    # ------------------------------------------------------------------

    def run_pipeline(
        self,
        steps: List[PipelineStep],
        initial_context: Optional[Dict[str, Any]] = None,
        pipeline_name: str = "custom",
    ) -> PipelineResult:
        """
        Run an arbitrary list of PipelineSteps sequentially, supporting per-step
        agent targeting, routing strategy, and context propagation.
        """
        return self.run_sequential(steps, initial_context, pipeline_name=pipeline_name)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def history(self, limit: int = 20) -> List[Dict[str, Any]]:
        return [r.summary() for r in self._history[-limit:]]

    def stats(self) -> Dict[str, Any]:
        total   = len(self._history)
        ok      = sum(1 for r in self._history if r.ok)
        avg_ms  = (sum(r.total_ms for r in self._history) / total) if total else 0
        return {
            "total_pipelines": total,
            "successful":      ok,
            "failed":          total - ok,
            "avg_total_ms":    round(avg_ms, 2),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_step(self, step: PipelineStep, context: Dict[str, Any]) -> StepResult:
        ts = time.perf_counter()
        try:
            request = step.build_request(context)
            if step.agent_name:
                agent = self._registry.get(step.agent_name)
                if agent is None:
                    raise ValueError(f"Agent '{step.agent_name}' not found or disabled.")
            else:
                agent = self._router.route(request, step.strategy)
                if agent is None:
                    raise ValueError("No eligible agent found by router.")

            response = agent.call(request)
            status   = StepStatus.DONE if response.ok else StepStatus.FAILED
            return StepResult(
                step_name=step.name, status=status,
                response=response,
                error=response.error,
                latency_ms=(time.perf_counter() - ts) * 1000,
            )
        except Exception as exc:
            return StepResult(
                step_name=step.name, status=StepStatus.FAILED,
                error=str(exc),
                latency_ms=(time.perf_counter() - ts) * 1000,
            )
