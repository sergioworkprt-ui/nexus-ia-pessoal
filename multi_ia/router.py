"""
NEXUS Multi-IA — Router
Routing logic that selects the best agent(s) for a given task based on
capabilities, priority, latency history, confidence, and configurable rules.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from .agent import AgentCapability, AgentRequest, BaseAgent
from .registry import AgentRegistry


# ---------------------------------------------------------------------------
# Routing strategies & rules
# ---------------------------------------------------------------------------

class RoutingStrategy(str, Enum):
    BEST_CAPABILITY    = "best_capability"    # highest priority agent with required caps
    ROUND_ROBIN        = "round_robin"        # rotate evenly across eligible agents
    LOWEST_LATENCY     = "lowest_latency"     # agent with best avg latency so far
    HIGHEST_CONFIDENCE = "highest_confidence" # agent with best historical confidence
    RANDOM             = "random"             # random eligible agent (for load spread)
    ALL                = "all"                # return every eligible agent (for consensus)


@dataclass
class RoutingRule:
    """
    A declarative rule that maps task patterns to routing preferences.
    Rules are evaluated in order; the first match wins.
    """
    name:                  str
    task_pattern:          Optional[str]                = None   # regex on task text
    required_capabilities: Set[AgentCapability]         = field(default_factory=set)
    preferred_agents:      List[str]                    = field(default_factory=list)
    excluded_agents:       List[str]                    = field(default_factory=list)
    strategy:              RoutingStrategy              = RoutingStrategy.BEST_CAPABILITY
    min_agents:            int                          = 1      # for ALL strategy
    description:           str                          = ""


# ---------------------------------------------------------------------------
# Routing decision
# ---------------------------------------------------------------------------

@dataclass
class RoutingDecision:
    """Result of a routing evaluation."""
    agents:    List[BaseAgent]
    rule_name: str
    strategy:  RoutingStrategy
    reason:    str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agents":    [a.name for a in self.agents],
            "rule":      self.rule_name,
            "strategy":  self.strategy.value,
            "reason":    self.reason,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

class Router:
    """
    Selects AI agents for incoming tasks using a rule-based decision engine.

    Evaluation order:
    1. Match the task against registered RoutingRules (first match wins).
    2. Apply the matched strategy over eligible agents.
    3. Fall back to the default strategy if no rule matches.

    Thread-safe. Routing decisions are logged for auditability.
    """

    def __init__(
        self,
        registry: AgentRegistry,
        default_strategy: RoutingStrategy = RoutingStrategy.BEST_CAPABILITY,
    ) -> None:
        self._registry  = registry
        self._default   = default_strategy
        self._rules:    List[RoutingRule] = []
        self._lock      = threading.RLock()
        self._rr_index: Dict[str, int] = {}     # round-robin cursor per rule
        self._history:  List[RoutingDecision] = []

    # ------------------------------------------------------------------
    # Rule management
    # ------------------------------------------------------------------

    def add_rule(self, rule: RoutingRule) -> None:
        with self._lock:
            self._rules.append(rule)

    def remove_rule(self, name: str) -> bool:
        with self._lock:
            before = len(self._rules)
            self._rules = [r for r in self._rules if r.name != name]
            return len(self._rules) < before

    def list_rules(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                {
                    "name":     r.name,
                    "pattern":  r.task_pattern,
                    "strategy": r.strategy.value,
                    "required_caps": [c.value for c in r.required_capabilities],
                    "preferred": r.preferred_agents,
                }
                for r in self._rules
            ]

    # ------------------------------------------------------------------
    # Primary routing methods
    # ------------------------------------------------------------------

    def route(
        self,
        request: AgentRequest,
        strategy: Optional[RoutingStrategy] = None,
    ) -> Optional[BaseAgent]:
        """Return the single best agent for this request, or None if none qualify."""
        decision = self._decide(request, strategy, n=1)
        return decision.agents[0] if decision.agents else None

    def route_many(
        self,
        request: AgentRequest,
        n: int = 3,
        strategy: Optional[RoutingStrategy] = None,
    ) -> List[BaseAgent]:
        """Return up to n agents for this request (e.g. for consensus runs)."""
        decision = self._decide(request, strategy or RoutingStrategy.ALL, n=n)
        return decision.agents

    def route_with_fallbacks(
        self,
        request: AgentRequest,
    ) -> List[BaseAgent]:
        """
        Return agents sorted by priority, so callers can try each in turn
        if the first fails. Falls back from preferred to any available.
        """
        decision = self._decide(request, RoutingStrategy.BEST_CAPABILITY, n=99)
        return decision.agents

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def history(self, limit: int = 20) -> List[Dict[str, Any]]:
        return [d.to_dict() for d in self._history[-limit:]]

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            rule_hits: Dict[str, int] = {}
            for d in self._history:
                rule_hits[d.rule_name] = rule_hits.get(d.rule_name, 0) + 1
        return {
            "total_routes": len(self._history),
            "rules_defined": len(self._rules),
            "rule_hit_counts": rule_hits,
        }

    # ------------------------------------------------------------------
    # Internal decision logic
    # ------------------------------------------------------------------

    def _decide(
        self,
        request: AgentRequest,
        strategy: Optional[RoutingStrategy],
        n: int,
    ) -> RoutingDecision:
        with self._lock:
            rule = self._match_rule(request)

        effective_strategy = strategy or (rule.strategy if rule else self._default)
        required_caps = (rule.required_capabilities if rule else set()) | request.required_caps
        preferred     = rule.preferred_agents if rule else []
        excluded      = rule.excluded_agents  if rule else []
        rule_name     = rule.name if rule else "__default__"

        # Gather eligible agents
        if required_caps:
            candidates = self._registry.get_by_capabilities(required_caps, only_available=True)
        else:
            candidates = self._registry.get_available()

        # Apply exclusions
        candidates = [a for a in candidates if a.name not in excluded]
        if not candidates:
            decision = RoutingDecision(
                agents=[], rule_name=rule_name,
                strategy=effective_strategy,
                reason="No eligible agents found.",
            )
            self._history.append(decision)
            return decision

        agents = self._apply_strategy(
            candidates, effective_strategy, preferred, n, rule_name
        )
        reason = (
            f"Strategy '{effective_strategy.value}' selected {len(agents)} agent(s) "
            f"from {len(candidates)} candidates."
            + (f" Rule '{rule_name}' matched." if rule else "")
        )
        decision = RoutingDecision(
            agents=agents, rule_name=rule_name,
            strategy=effective_strategy, reason=reason,
        )
        self._history.append(decision)
        return decision

    def _match_rule(self, request: AgentRequest) -> Optional[RoutingRule]:
        for rule in self._rules:
            if rule.task_pattern:
                if not re.search(rule.task_pattern, request.task, re.IGNORECASE):
                    continue
            if rule.required_capabilities:
                available = self._registry.get_by_capabilities(
                    rule.required_capabilities, only_available=False
                )
                if not available:
                    continue
            return rule
        return None

    def _apply_strategy(
        self,
        candidates: List[BaseAgent],
        strategy:   RoutingStrategy,
        preferred:  List[str],
        n:          int,
        rule_name:  str,
    ) -> List[BaseAgent]:
        import random as _random

        # Preferred agents first (preserve order)
        ordered = sorted(
            candidates,
            key=lambda a: (
                preferred.index(a.name) if a.name in preferred else len(preferred),
                a.priority,
            ),
        )

        if strategy == RoutingStrategy.BEST_CAPABILITY:
            return ordered[:n]

        if strategy == RoutingStrategy.ALL:
            return ordered[:n]

        if strategy == RoutingStrategy.ROUND_ROBIN:
            idx   = self._rr_index.get(rule_name, 0) % len(ordered)
            self._rr_index[rule_name] = idx + 1
            rotated = ordered[idx:] + ordered[:idx]
            return rotated[:n]

        if strategy == RoutingStrategy.LOWEST_LATENCY:
            by_lat = sorted(
                ordered,
                key=lambda a: (
                    a._total_latency_ms / a._call_count if a._call_count else 9999
                ),
            )
            return by_lat[:n]

        if strategy == RoutingStrategy.HIGHEST_CONFIDENCE:
            # Proxy: sort by error_count ascending (fewer errors = better confidence)
            by_conf = sorted(ordered, key=lambda a: a._error_count)
            return by_conf[:n]

        if strategy == RoutingStrategy.RANDOM:
            sample = list(ordered)
            _random.shuffle(sample)
            return sample[:n]

        return ordered[:n]
