"""
NEXUS Multi-IA — Registry
Central store of available AI agents with dynamic registration,
capability indexing, health tracking, and config-driven loading.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Type

from .agent import (
    AgentCapability,
    AgentProvider,
    AgentStatus,
    BaseAgent,
    MockClaudeAgent,
    MockCopilotAgent,
    MockGPTAgent,
    MockLocalAgent,
)


# ---------------------------------------------------------------------------
# Agent metadata
# ---------------------------------------------------------------------------

@dataclass
class AgentRecord:
    """Registry entry combining a live agent instance with its configuration."""
    agent:          BaseAgent
    registered_at:  str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    enabled:        bool = True
    tags:           List[str] = field(default_factory=list)
    description:    str = ""

    @property
    def name(self) -> str:
        return self.agent.name

    @property
    def status(self) -> AgentStatus:
        return self.agent.status

    def to_dict(self) -> Dict[str, Any]:
        return {
            **self.agent.stats(),
            "registered_at": self.registered_at,
            "enabled":       self.enabled,
            "tags":          self.tags,
            "description":   self.description,
        }


# ---------------------------------------------------------------------------
# Config-driven loading
# ---------------------------------------------------------------------------

# Maps provider+model string pairs to mock agent classes for config loading
_MOCK_CATALOGUE: Dict[str, Type[BaseAgent]] = {
    "anthropic": MockClaudeAgent,
    "openai":    MockGPTAgent,
    "microsoft": MockCopilotAgent,
    "local":     MockLocalAgent,
}


def agent_from_config(config: Dict[str, Any]) -> BaseAgent:
    """
    Instantiate an agent from a configuration dict.

    Minimal config:
        {"provider": "anthropic", "model": "claude-sonnet-4-6"}

    Optional keys: name, priority, seed, capabilities (list of strings).
    """
    provider = config.get("provider", "local").lower()
    cls      = _MOCK_CATALOGUE.get(provider, MockLocalAgent)
    kwargs: Dict[str, Any] = {}

    model = config.get("model")
    if model:
        kwargs["model"] = model

    seed = config.get("seed")
    if seed is not None:
        kwargs["seed"] = seed

    agent = cls(**kwargs)

    # Allow config overrides
    if "name" in config:
        agent.name = config["name"]
    if "priority" in config:
        agent.priority = int(config["priority"])

    return agent


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class AgentRegistry:
    """
    Thread-safe registry for all active AI agents.

    Features:
    - Register / unregister agents at runtime
    - Query by name, capability, provider, or tag
    - Enable / disable individual agents
    - Config-driven bulk loading
    - Health polling (records last known status)
    """

    def __init__(self) -> None:
        self._records: Dict[str, AgentRecord] = {}
        self._lock    = threading.RLock()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        agent: BaseAgent,
        description: str = "",
        tags: Optional[List[str]] = None,
        enabled: bool = True,
    ) -> None:
        """Register an agent. Replaces any existing entry with the same name."""
        with self._lock:
            self._records[agent.name] = AgentRecord(
                agent=agent,
                description=description,
                tags=tags or [],
                enabled=enabled,
            )

    def unregister(self, name: str) -> bool:
        with self._lock:
            return self._records.pop(name, None) is not None

    def load_from_config(self, configs: List[Dict[str, Any]]) -> List[str]:
        """Bulk-load agents from a list of config dicts. Returns names loaded."""
        loaded: List[str] = []
        for cfg in configs:
            try:
                agent = agent_from_config(cfg)
                self.register(
                    agent,
                    description=cfg.get("description", ""),
                    tags=cfg.get("tags", []),
                    enabled=cfg.get("enabled", True),
                )
                loaded.append(agent.name)
            except Exception:
                pass
        return loaded

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get(self, name: str) -> Optional[BaseAgent]:
        with self._lock:
            rec = self._records.get(name)
            return rec.agent if rec and rec.enabled else None

    def get_record(self, name: str) -> Optional[AgentRecord]:
        with self._lock:
            return self._records.get(name)

    def get_by_capability(
        self,
        capability: AgentCapability,
        only_available: bool = True,
    ) -> List[BaseAgent]:
        with self._lock:
            agents = [
                rec.agent for rec in self._records.values()
                if rec.enabled
                and rec.agent.supports(capability)
                and (not only_available or rec.agent.status == AgentStatus.AVAILABLE)
            ]
        agents.sort(key=lambda a: a.priority)
        return agents

    def get_by_capabilities(
        self,
        capabilities: Set[AgentCapability],
        only_available: bool = True,
    ) -> List[BaseAgent]:
        with self._lock:
            agents = [
                rec.agent for rec in self._records.values()
                if rec.enabled
                and rec.agent.supports_all(capabilities)
                and (not only_available or rec.agent.status == AgentStatus.AVAILABLE)
            ]
        agents.sort(key=lambda a: a.priority)
        return agents

    def get_by_provider(self, provider: AgentProvider) -> List[BaseAgent]:
        with self._lock:
            return [
                rec.agent for rec in self._records.values()
                if rec.enabled and rec.agent.provider == provider
            ]

    def get_by_tag(self, tag: str) -> List[BaseAgent]:
        with self._lock:
            return [
                rec.agent for rec in self._records.values()
                if rec.enabled and tag in rec.tags
            ]

    def get_available(self) -> List[BaseAgent]:
        with self._lock:
            agents = [
                rec.agent for rec in self._records.values()
                if rec.enabled and rec.agent.status == AgentStatus.AVAILABLE
            ]
        agents.sort(key=lambda a: a.priority)
        return agents

    def all_agents(self) -> List[BaseAgent]:
        with self._lock:
            return [rec.agent for rec in self._records.values() if rec.enabled]

    # ------------------------------------------------------------------
    # Enable / Disable
    # ------------------------------------------------------------------

    def enable(self, name: str) -> None:
        with self._lock:
            if name in self._records:
                self._records[name].enabled = True

    def disable(self, name: str) -> None:
        with self._lock:
            if name in self._records:
                self._records[name].enabled = False

    # ------------------------------------------------------------------
    # Health polling
    # ------------------------------------------------------------------

    def refresh_health(self) -> Dict[str, bool]:
        """Run health_check() on every registered agent. Returns name → ok map."""
        results: Dict[str, bool] = {}
        with self._lock:
            records = list(self._records.values())
        for rec in records:
            try:
                ok = rec.agent.health_check()
                rec.agent.status = AgentStatus.AVAILABLE if ok else AgentStatus.ERROR
            except Exception:
                ok = False
                rec.agent.status = AgentStatus.ERROR
            results[rec.name] = ok
        return results

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def list(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [rec.to_dict() for rec in self._records.values()]

    def names(self) -> List[str]:
        with self._lock:
            return list(self._records.keys())

    def capability_map(self) -> Dict[str, List[str]]:
        """Return a map of capability → list of agent names that support it."""
        result: Dict[str, List[str]] = {}
        with self._lock:
            for rec in self._records.values():
                for cap in rec.agent.capabilities:
                    result.setdefault(cap.value, []).append(rec.name)
        return result

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            total    = len(self._records)
            enabled  = sum(1 for r in self._records.values() if r.enabled)
            available = sum(
                1 for r in self._records.values()
                if r.enabled and r.agent.status == AgentStatus.AVAILABLE
            )
        return {
            "total_agents":     total,
            "enabled_agents":   enabled,
            "available_agents": available,
        }
