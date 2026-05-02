"""
NEXUS Multi-IA — Agent
Base class and mock implementations for external AI agents.
All concrete agents are mock-only: no real API calls, no credentials.
Swap a mock for a real implementation by subclassing BaseAgent.
"""

from __future__ import annotations

import hashlib
import random
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Any, Dict, FrozenSet, List, Optional, Set


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class AgentCapability(str, Enum):
    TEXT_GENERATION  = "text_generation"
    CODE_GENERATION  = "code_generation"
    CODE_REVIEW      = "code_review"
    REASONING        = "reasoning"
    ANALYSIS         = "analysis"
    SUMMARISATION    = "summarisation"
    CLASSIFICATION   = "classification"
    STRUCTURED_OUTPUT = "structured_output"
    SEARCH           = "search"
    MATH             = "math"
    TRANSLATION      = "translation"


class AgentStatus(str, Enum):
    AVAILABLE = "available"
    BUSY      = "busy"
    OFFLINE   = "offline"
    ERROR     = "error"


class AgentProvider(str, Enum):
    ANTHROPIC = "anthropic"
    OPENAI    = "openai"
    MICROSOFT = "microsoft"
    GOOGLE    = "google"
    LOCAL     = "local"
    CUSTOM    = "custom"


# ---------------------------------------------------------------------------
# Request / Response
# ---------------------------------------------------------------------------

@dataclass
class AgentRequest:
    """A task submitted to an AI agent."""
    task:          str
    context:       Dict[str, Any]    = field(default_factory=dict)
    max_tokens:    int               = 1024
    temperature:   float             = 0.7
    timeout:       float             = 30.0
    request_id:    str               = field(default_factory=lambda: str(uuid.uuid4())[:12])
    required_caps: Set[AgentCapability] = field(default_factory=set)
    metadata:      Dict[str, Any]    = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.task.strip():
            raise ValueError("AgentRequest.task must not be empty.")
        if not 0.0 <= self.temperature <= 2.0:
            raise ValueError(f"temperature must be in [0, 2], got {self.temperature}.")


@dataclass
class AgentResponse:
    """The output produced by an AI agent for a given request."""
    request_id:  str
    agent_id:    str
    agent_name:  str
    provider:    AgentProvider
    model:       str
    content:     str
    confidence:  float              # 0.0 – 1.0 (self-reported or estimated)
    tokens_used: int
    latency_ms:  float
    timestamp:   str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    error:       Optional[str] = None
    metadata:    Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.content.strip())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "agent_id":   self.agent_id,
            "agent":      self.agent_name,
            "provider":   self.provider.value,
            "model":      self.model,
            "content":    self.content[:500],     # truncate for logging
            "confidence": round(self.confidence, 4),
            "tokens":     self.tokens_used,
            "latency_ms": round(self.latency_ms, 2),
            "ok":         self.ok,
            "error":      self.error,
        }


# ---------------------------------------------------------------------------
# Base agent
# ---------------------------------------------------------------------------

class BaseAgent(ABC):
    """
    Abstract base class for all NEXUS AI agent integrations.

    Subclass this to add real provider calls (Claude API, OpenAI, etc.).
    All subclasses must implement call() and health_check().
    """

    def __init__(
        self,
        name: str,
        provider: AgentProvider,
        model: str,
        capabilities: Set[AgentCapability],
        priority: int = 5,              # 1 (highest) – 10 (lowest)
    ) -> None:
        self.agent_id    = str(uuid.uuid4())[:12]
        self.name        = name
        self.provider    = provider
        self.model       = model
        self.capabilities: FrozenSet[AgentCapability] = frozenset(capabilities)
        self.priority    = priority
        self.status      = AgentStatus.AVAILABLE
        self._call_count = 0
        self._error_count = 0
        self._total_latency_ms = 0.0

    @abstractmethod
    def call(self, request: AgentRequest) -> AgentResponse:
        """Submit a request and return the agent's response."""
        ...

    @abstractmethod
    def health_check(self) -> bool:
        """Return True if the agent is reachable and functional."""
        ...

    def supports(self, capability: AgentCapability) -> bool:
        return capability in self.capabilities

    def supports_all(self, caps: Set[AgentCapability]) -> bool:
        return caps.issubset(self.capabilities)

    def stats(self) -> Dict[str, Any]:
        avg_lat = (self._total_latency_ms / self._call_count) if self._call_count else 0
        return {
            "agent_id":       self.agent_id,
            "name":           self.name,
            "provider":       self.provider.value,
            "model":          self.model,
            "status":         self.status.value,
            "priority":       self.priority,
            "capabilities":   [c.value for c in self.capabilities],
            "call_count":     self._call_count,
            "error_count":    self._error_count,
            "avg_latency_ms": round(avg_lat, 2),
        }

    def _record(self, latency_ms: float, error: bool = False) -> None:
        self._call_count += 1
        self._total_latency_ms += latency_ms
        if error:
            self._error_count += 1


# ---------------------------------------------------------------------------
# Mock agents (no real API calls)
# ---------------------------------------------------------------------------

class _MockAgentBase(BaseAgent):
    """
    Deterministic mock base that generates structured fake responses.
    Simulates realistic latency, occasional errors, and varying confidence.
    Intended for development, testing, and architecture validation only.
    """

    _LATENCY_MEAN_MS: float = 400.0
    _LATENCY_STD_MS:  float = 120.0
    _ERROR_RATE:      float = 0.03     # 3% simulated error rate
    _CONFIDENCE_RANGE: tuple = (0.70, 0.95)

    def __init__(self, *args: Any, seed: Optional[int] = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._rng = random.Random(seed)

    def call(self, request: AgentRequest) -> AgentResponse:
        t0 = time.perf_counter()
        latency = max(10.0, self._rng.gauss(self._LATENCY_MEAN_MS, self._LATENCY_STD_MS))

        # Simulated error
        if self._rng.random() < self._ERROR_RATE:
            self.status = AgentStatus.ERROR
            elapsed = (time.perf_counter() - t0) * 1000 + latency
            self._record(elapsed, error=True)
            return AgentResponse(
                request_id=request.request_id,
                agent_id=self.agent_id, agent_name=self.name,
                provider=self.provider, model=self.model,
                content="", confidence=0.0, tokens_used=0,
                latency_ms=round(elapsed, 2),
                error=f"[MOCK] Simulated transient error from {self.name}.",
            )

        self.status = AgentStatus.BUSY
        content    = self._generate_response(request)
        confidence = round(self._rng.uniform(*self._CONFIDENCE_RANGE), 4)
        tokens     = max(10, int(len(content.split()) * 1.3))
        elapsed    = (time.perf_counter() - t0) * 1000 + latency

        self.status = AgentStatus.AVAILABLE
        self._record(elapsed)
        return AgentResponse(
            request_id=request.request_id,
            agent_id=self.agent_id, agent_name=self.name,
            provider=self.provider, model=self.model,
            content=content, confidence=confidence,
            tokens_used=tokens, latency_ms=round(elapsed, 2),
            metadata={"mock": True},
        )

    def health_check(self) -> bool:
        return self.status != AgentStatus.OFFLINE

    def _generate_response(self, request: AgentRequest) -> str:
        """Override in subclasses to produce persona-specific mock content."""
        return f"[{self.name}] Processed: {request.task[:80]}"


class MockClaudeAgent(_MockAgentBase):
    """Mock of Anthropic Claude — analytical, structured, high reasoning."""

    _LATENCY_MEAN_MS = 350.0
    _CONFIDENCE_RANGE = (0.82, 0.97)

    def __init__(self, model: str = "claude-sonnet-4-6", seed: Optional[int] = None) -> None:
        super().__init__(
            name="claude", provider=AgentProvider.ANTHROPIC, model=model,
            capabilities={
                AgentCapability.TEXT_GENERATION, AgentCapability.REASONING,
                AgentCapability.ANALYSIS, AgentCapability.CODE_GENERATION,
                AgentCapability.CODE_REVIEW, AgentCapability.SUMMARISATION,
                AgentCapability.STRUCTURED_OUTPUT, AgentCapability.MATH,
            },
            priority=1, seed=seed,
        )

    def _generate_response(self, request: AgentRequest) -> str:
        task = request.task[:120]
        digest = hashlib.md5(task.encode()).hexdigest()[:6]
        return (
            f"Analysis [{digest}]: Based on a careful review of the task '{task}', "
            f"I identify the following key considerations. "
            f"First, the core objective requires structured decomposition. "
            f"Second, risk factors include uncertainty in input quality. "
            f"Recommendation: proceed with a stepwise approach, validating each stage. "
            f"Confidence in this analysis is high given the available context."
        )


class MockGPTAgent(_MockAgentBase):
    """Mock of OpenAI GPT — conversational, broad knowledge, fast."""

    _LATENCY_MEAN_MS = 280.0
    _CONFIDENCE_RANGE = (0.75, 0.92)

    def __init__(self, model: str = "gpt-4o", seed: Optional[int] = None) -> None:
        super().__init__(
            name="gpt", provider=AgentProvider.OPENAI, model=model,
            capabilities={
                AgentCapability.TEXT_GENERATION, AgentCapability.REASONING,
                AgentCapability.ANALYSIS, AgentCapability.CODE_GENERATION,
                AgentCapability.SUMMARISATION, AgentCapability.TRANSLATION,
                AgentCapability.CLASSIFICATION,
            },
            priority=2, seed=seed,
        )

    def _generate_response(self, request: AgentRequest) -> str:
        task = request.task[:120]
        digest = hashlib.md5(task.encode()).hexdigest()[:6]
        return (
            f"Response [{digest}]: Here's my take on '{task}'. "
            f"This is a multi-faceted problem. "
            f"The most straightforward approach would be to break it into smaller components. "
            f"I suggest starting with data validation, then applying the main logic iteratively. "
            f"Let me know if you need a more detailed breakdown."
        )


class MockCopilotAgent(_MockAgentBase):
    """Mock of Microsoft Copilot — code-focused, integration-aware."""

    _LATENCY_MEAN_MS = 320.0
    _CONFIDENCE_RANGE = (0.72, 0.90)

    def __init__(self, model: str = "copilot-enterprise", seed: Optional[int] = None) -> None:
        super().__init__(
            name="copilot", provider=AgentProvider.MICROSOFT, model=model,
            capabilities={
                AgentCapability.CODE_GENERATION, AgentCapability.CODE_REVIEW,
                AgentCapability.TEXT_GENERATION, AgentCapability.STRUCTURED_OUTPUT,
                AgentCapability.SUMMARISATION,
            },
            priority=3, seed=seed,
        )

    def _generate_response(self, request: AgentRequest) -> str:
        task = request.task[:120]
        digest = hashlib.md5(task.encode()).hexdigest()[:6]
        return (
            f"Copilot [{digest}]: Reviewing '{task}'. "
            f"From a code and systems perspective, the implementation should follow "
            f"standard modular patterns. Suggested structure: input validation, "
            f"core processing, output formatting. "
            f"Consider adding unit tests for edge cases. "
            f"Integration with existing systems appears feasible."
        )


class MockLocalAgent(_MockAgentBase):
    """Mock of a locally-hosted open-source model — fast, private, lower confidence."""

    _LATENCY_MEAN_MS  = 150.0
    _CONFIDENCE_RANGE = (0.55, 0.80)
    _ERROR_RATE       = 0.05

    def __init__(self, model: str = "llama3-8b-local", seed: Optional[int] = None) -> None:
        super().__init__(
            name="local_llm", provider=AgentProvider.LOCAL, model=model,
            capabilities={
                AgentCapability.TEXT_GENERATION, AgentCapability.SUMMARISATION,
                AgentCapability.CLASSIFICATION, AgentCapability.TRANSLATION,
            },
            priority=5, seed=seed,
        )

    def _generate_response(self, request: AgentRequest) -> str:
        task = request.task[:80]
        digest = hashlib.md5(task.encode()).hexdigest()[:6]
        return (
            f"[local/{digest}] Task: {task}. "
            f"Summary: the request involves processing and transformation. "
            f"Output depends on additional context. "
            f"Proceed with caution — local model confidence is limited."
        )
