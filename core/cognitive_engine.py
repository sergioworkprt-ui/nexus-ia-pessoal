"""
NEXUS Core — Cognitive Engine
Main reasoning engine: processes inputs, selects strategies, produces outputs.
"""

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


# ---------------------------------------------------------------------------
# Strategy framework
# ---------------------------------------------------------------------------

class ReasoningStrategy(str, Enum):
    DIRECT = "direct"           # Single-step answer
    CHAIN_OF_THOUGHT = "chain"  # Step-by-step reasoning
    DECOMPOSE = "decompose"     # Break into sub-problems
    REFLECT = "reflect"         # Evaluate and revise initial answer
    SEARCH = "search"           # Retrieve before reasoning


@dataclass
class CognitiveInput:
    content: str
    context: Dict[str, Any] = field(default_factory=dict)
    strategy: ReasoningStrategy = ReasoningStrategy.DIRECT
    max_steps: int = 10
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReasoningStep:
    step_number: int
    thought: str
    conclusion: Optional[str] = None
    confidence: float = 1.0     # 0.0 – 1.0


@dataclass
class CognitiveOutput:
    input_content: str
    strategy_used: ReasoningStrategy
    steps: List[ReasoningStep]
    final_answer: str
    confidence: float
    elapsed_ms: float
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "input": self.input_content,
            "strategy": self.strategy_used.value,
            "steps": [
                {
                    "step": s.step_number,
                    "thought": s.thought,
                    "conclusion": s.conclusion,
                    "confidence": s.confidence,
                }
                for s in self.steps
            ],
            "final_answer": self.final_answer,
            "confidence": self.confidence,
            "elapsed_ms": self.elapsed_ms,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Strategy handlers (injectable, default to rule-based stubs)
# ---------------------------------------------------------------------------

StrategyFn = Callable[[CognitiveInput], CognitiveOutput]


def _direct_strategy(inp: CognitiveInput) -> CognitiveOutput:
    t0 = time.perf_counter()
    step = ReasoningStep(
        step_number=1,
        thought=f"Processing: {inp.content}",
        conclusion=inp.content,
        confidence=0.9,
    )
    return CognitiveOutput(
        input_content=inp.content,
        strategy_used=ReasoningStrategy.DIRECT,
        steps=[step],
        final_answer=step.conclusion or inp.content,
        confidence=step.confidence,
        elapsed_ms=(time.perf_counter() - t0) * 1000,
    )


def _chain_strategy(inp: CognitiveInput) -> CognitiveOutput:
    t0 = time.perf_counter()
    steps: List[ReasoningStep] = []
    parts = inp.content.split(".")[:inp.max_steps]
    for i, part in enumerate(parts, start=1):
        part = part.strip()
        if not part:
            continue
        steps.append(ReasoningStep(step_number=i, thought=part, conclusion=part, confidence=0.85))
    if not steps:
        steps = [ReasoningStep(step_number=1, thought=inp.content, conclusion=inp.content, confidence=0.8)]
    final = " → ".join(s.conclusion for s in steps if s.conclusion)
    avg_conf = sum(s.confidence for s in steps) / len(steps)
    return CognitiveOutput(
        input_content=inp.content,
        strategy_used=ReasoningStrategy.CHAIN_OF_THOUGHT,
        steps=steps,
        final_answer=final,
        confidence=avg_conf,
        elapsed_ms=(time.perf_counter() - t0) * 1000,
    )


# ---------------------------------------------------------------------------
# Cognitive Engine
# ---------------------------------------------------------------------------

class CognitiveEngine:
    """
    Central reasoning engine for NEXUS.

    Selects and executes the appropriate reasoning strategy for each input.
    Strategy handlers are injectable, allowing integration with external AI
    models (e.g., Claude API) without changing this class.
    """

    _DEFAULT_STRATEGIES: Dict[ReasoningStrategy, StrategyFn] = {
        ReasoningStrategy.DIRECT: _direct_strategy,
        ReasoningStrategy.CHAIN_OF_THOUGHT: _chain_strategy,
        ReasoningStrategy.DECOMPOSE: _chain_strategy,    # override to customise
        ReasoningStrategy.REFLECT: _direct_strategy,     # override to customise
        ReasoningStrategy.SEARCH: _direct_strategy,      # override to customise
    }

    def __init__(self) -> None:
        self._strategies: Dict[ReasoningStrategy, StrategyFn] = dict(self._DEFAULT_STRATEGIES)
        self._history: List[CognitiveOutput] = []
        self._pre_hooks: List[Callable[[CognitiveInput], CognitiveInput]] = []
        self._post_hooks: List[Callable[[CognitiveOutput], CognitiveOutput]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def think(self, inp: CognitiveInput) -> CognitiveOutput:
        """Run the reasoning pipeline and return a CognitiveOutput."""
        for hook in self._pre_hooks:
            inp = hook(inp)

        strategy_fn = self._strategies.get(inp.strategy, _direct_strategy)
        output = strategy_fn(inp)

        for hook in self._post_hooks:
            output = hook(output)

        self._history.append(output)
        return output

    def think_raw(
        self,
        content: str,
        strategy: ReasoningStrategy = ReasoningStrategy.DIRECT,
        context: Optional[Dict[str, Any]] = None,
    ) -> CognitiveOutput:
        """Convenience wrapper: create a CognitiveInput and call think()."""
        return self.think(CognitiveInput(content=content, strategy=strategy, context=context or {}))

    # ------------------------------------------------------------------
    # Strategy management
    # ------------------------------------------------------------------

    def register_strategy(self, strategy: ReasoningStrategy, fn: StrategyFn) -> None:
        """Replace the built-in handler for a strategy with a custom one."""
        self._strategies[strategy] = fn

    def add_pre_hook(self, fn: Callable[[CognitiveInput], CognitiveInput]) -> None:
        """Add a pre-processing hook (runs before strategy execution)."""
        self._pre_hooks.append(fn)

    def add_post_hook(self, fn: Callable[[CognitiveOutput], CognitiveOutput]) -> None:
        """Add a post-processing hook (runs after strategy execution)."""
        self._post_hooks.append(fn)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def history(self, limit: int = 20) -> List[Dict[str, Any]]:
        return [o.to_dict() for o in self._history[-limit:]]

    def clear_history(self) -> None:
        self._history.clear()

    def available_strategies(self) -> List[str]:
        return [s.value for s in self._strategies]

    def stats(self) -> Dict[str, Any]:
        if not self._history:
            return {"total_thoughts": 0}
        confidences = [o.confidence for o in self._history]
        elapsed = [o.elapsed_ms for o in self._history]
        return {
            "total_thoughts": len(self._history),
            "avg_confidence": sum(confidences) / len(confidences),
            "avg_elapsed_ms": sum(elapsed) / len(elapsed),
            "strategies_used": list({o.strategy_used.value for o in self._history}),
        }
