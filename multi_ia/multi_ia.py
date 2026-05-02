"""
NEXUS Multi-IA — Facade
Top-level entry point that wires agent registry, router, consensus engine,
and orchestrator. Integrates with NexusCore when available.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .agent import (
    AgentCapability, AgentRequest, AgentResponse,
    BaseAgent, MockClaudeAgent, MockCopilotAgent, MockGPTAgent, MockLocalAgent,
)
from .consensus import ConsensusEngine, ConsensusMethod, ConsensusResult
from .orchestrator import Orchestrator, PipelineResult, PipelineStep
from .registry import AgentRegistry
from .router import Router, RoutingRule, RoutingStrategy


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class MultiIAConfig:
    """Runtime configuration for the MultiIA facade."""
    default_consensus_method: ConsensusMethod  = ConsensusMethod.WEIGHTED_AVERAGE
    default_routing_strategy: RoutingStrategy  = RoutingStrategy.BEST_CAPABILITY
    load_default_mocks:       bool             = True   # auto-register all mock agents
    max_parallel_agents:      int              = 4
    escalation_to_security:   bool             = True   # hook contradictions → security


# ---------------------------------------------------------------------------
# MultiIA facade
# ---------------------------------------------------------------------------

class MultiIA:
    """
    Single entry-point for the NEXUS multi-agent subsystem.

    Integrates with NexusCore via from_core() — receives logger, memory,
    and security manager. All security escalations from consensus are forwarded
    to core.security as audit violations.

    Usage (standalone):
        ia = MultiIA()
        ia.start()
        response = ia.ask("Summarise the current market outlook")
        result   = ia.ask_all("Should we proceed?")
        print(result.consensus_result.agreement_score)

    Usage (with NexusCore):
        from core import get_core
        ia = MultiIA.from_core(get_core())
        ia.start()
    """

    def __init__(self, config: Optional[MultiIAConfig] = None) -> None:
        self._config   = config or MultiIAConfig()
        self._running  = False

        # Core integration handles
        self._logger   = None
        self._memory   = None
        self._security = None

        # Sub-systems
        self.registry  = AgentRegistry()
        self.router    = Router(self.registry, self._config.default_routing_strategy)
        self.consensus = ConsensusEngine(
            default_method=self._config.default_consensus_method,
            escalation_hook=self._on_escalation,
        )
        self.orchestrator = Orchestrator(self.registry, self.router, self.consensus)

        if self._config.load_default_mocks:
            self._register_default_agents()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @classmethod
    def from_core(cls, core: Any, config: Optional[MultiIAConfig] = None) -> "MultiIA":
        """Create a MultiIA instance wired to a running NexusCore."""
        instance = cls(config)
        instance._logger   = core.logger
        instance._memory   = core.memory
        instance._security = core.security
        return instance

    def start(self) -> None:
        self._running = True
        self.registry.refresh_health()
        self._log("multi_ia", "MultiIA subsystem started.",
                  agents=len(self.registry.all_agents()))

    def stop(self) -> None:
        self._running = False
        self._log("multi_ia", "MultiIA subsystem stopped.")

    # ------------------------------------------------------------------
    # Primary interfaces
    # ------------------------------------------------------------------

    def ask(
        self,
        task:     str,
        agent:    Optional[str] = None,
        strategy: RoutingStrategy = RoutingStrategy.BEST_CAPABILITY,
        context:  Optional[Dict[str, Any]] = None,
        max_tokens: int = 1024,
    ) -> Optional[AgentResponse]:
        """
        Send a task to a single agent and return its response.
        If agent name is given, routes directly; otherwise uses the router.
        """
        request = AgentRequest(task=task, context=context or {}, max_tokens=max_tokens)
        if agent:
            a = self.registry.get(agent)
        else:
            a = self.router.route(request, strategy)

        if a is None:
            self._log("multi_ia", f"No agent available for task: {task[:60]}", level="warning")
            return None

        response = a.call(request)
        self._log("multi_ia", f"ask → {a.name}: ok={response.ok}, conf={response.confidence:.2f}")
        if self._memory and response.ok:
            self._memory.remember(f"ia_response_{response.request_id}", response.to_dict())
        return response

    def ask_all(
        self,
        task:             str,
        n_agents:         int = 3,
        consensus_method: ConsensusMethod = ConsensusMethod.WEIGHTED_AVERAGE,
        context:          Optional[Dict[str, Any]] = None,
    ) -> PipelineResult:
        """
        Send the same task to multiple agents simultaneously and reach consensus.
        Returns a PipelineResult with consensus_result populated.
        """
        result = self.orchestrator.run_parallel(
            task=task,
            n_agents=n_agents,
            consensus_method=consensus_method,
            context=context,
            pipeline_name="ask_all",
        )
        self._log(
            "multi_ia",
            f"ask_all ({n_agents} agents): agreement={result.consensus_result.agreement_score:.2f}"
            if result.consensus_result else "ask_all: no consensus",
        )
        return result

    def collaborate(
        self,
        steps: List[PipelineStep],
        initial_context: Optional[Dict[str, Any]] = None,
        pipeline_name: str = "collaborate",
    ) -> PipelineResult:
        """Run a custom sequential multi-agent pipeline."""
        result = self.orchestrator.run_pipeline(steps, initial_context, pipeline_name)
        self._log("multi_ia", f"Pipeline '{pipeline_name}': ok={result.ok}, "
                  f"steps={len(result.step_results)}, ms={result.total_ms:.0f}")
        return result

    def with_fallback(
        self,
        task:    str,
        context: Optional[Dict[str, Any]] = None,
    ) -> PipelineResult:
        """Try agents in priority order until one succeeds."""
        return self.orchestrator.run_with_fallback(task, context=context)

    def broadcast(self, message: str) -> List[AgentResponse]:
        """Send a message to all available agents and return all responses."""
        agents  = self.registry.get_available()
        results: List[AgentResponse] = []
        for agent in agents:
            req  = AgentRequest(task=message)
            resp = agent.call(req)
            results.append(resp)
        self._log("multi_ia", f"Broadcast to {len(agents)} agents.")
        return results

    def vote(
        self,
        question: str,
        n_agents: int = 3,
    ) -> ConsensusResult:
        """Ask a yes/no or directional question and return a voting consensus."""
        pipeline = self.orchestrator.run_parallel(
            task=question, n_agents=n_agents,
            consensus_method=ConsensusMethod.MAJORITY_VOTE,
            pipeline_name="vote",
        )
        return pipeline.consensus_result or ConsensusResult()

    # ------------------------------------------------------------------
    # Agent management
    # ------------------------------------------------------------------

    def register_agent(
        self,
        agent:       BaseAgent,
        description: str = "",
        tags:        Optional[List[str]] = None,
    ) -> None:
        self.registry.register(agent, description=description, tags=tags or [])
        self._log("multi_ia", f"Agent '{agent.name}' registered.")

    def add_routing_rule(self, rule: RoutingRule) -> None:
        self.router.add_rule(rule)

    def refresh_health(self) -> Dict[str, bool]:
        return self.registry.refresh_health()

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        return {
            "running":      self._running,
            "registry":     self.registry.stats(),
            "agents":       self.registry.list(),
            "router":       self.router.stats(),
            "consensus":    self.consensus.stats(),
            "orchestrator": self.orchestrator.stats(),
        }

    def history(self, limit: int = 10) -> List[Dict[str, Any]]:
        return self.orchestrator.history(limit=limit)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _register_default_agents(self) -> None:
        defaults = [
            (MockClaudeAgent(),   "Anthropic Claude — analytical and reasoning",  ["primary", "reasoning"]),
            (MockGPTAgent(),      "OpenAI GPT — broad knowledge, conversational",  ["primary", "general"]),
            (MockCopilotAgent(),  "Microsoft Copilot — code and integration focus", ["code"]),
            (MockLocalAgent(),    "Local LLM — private, fast, lower confidence",   ["local", "fast"]),
        ]
        for agent, desc, tags in defaults:
            self.registry.register(agent, description=desc, tags=tags)

    def _on_escalation(self, consensus: ConsensusResult) -> None:
        """Called by ConsensusEngine when a high-severity contradiction is detected."""
        self._log(
            "multi_ia",
            f"Consensus escalation: {consensus.escalation_reason}",
            level="warning",
            consensus_id=consensus.consensus_id,
        )
        if self._security and self._config.escalation_to_security:
            try:
                self._security.audit(  # type: ignore[attr-defined]
                    actor="multi_ia.consensus",
                    action="escalate_contradiction",
                    target=consensus.consensus_id,
                    outcome=consensus.escalation_reason or "high-severity contradiction",
                )
            except AttributeError:
                # Fallback: record as a violation if audit isn't available
                try:
                    self._security._record_violation(  # type: ignore[attr-defined]
                        actor="multi_ia",
                        code="CONSENSUS_CONTRADICTION",
                        detail=consensus.escalation_reason or "",
                    )
                except Exception:
                    pass

    def _log(self, module: str, message: str, level: str = "info", **kwargs: Any) -> None:
        if self._logger:
            getattr(self._logger, level, self._logger.info)(module, message, **kwargs)
