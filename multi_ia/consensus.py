"""
NEXUS Multi-IA — Consensus Engine
Cross-agent validation, voting, agreement scoring, contradiction detection,
and security escalation when agent outputs are irreconcilably conflicted.
"""

from __future__ import annotations

import re
import statistics
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from .agent import AgentResponse


# ---------------------------------------------------------------------------
# Contradiction types & severity
# ---------------------------------------------------------------------------

class ContradictionType(str, Enum):
    FACTUAL       = "factual"        # agents assert opposing facts
    DIRECTIONAL   = "directional"    # opposite recommendation (do/don't)
    CONFIDENCE_GAP = "confidence_gap" # one agent very confident, another very uncertain
    STRUCTURAL    = "structural"     # fundamentally different response format/scope


class ContradictionSeverity(str, Enum):
    LOW      = "low"       # minor wording difference
    MEDIUM   = "medium"    # notable disagreement, human review suggested
    HIGH     = "high"      # direct contradiction — escalate to security
    CRITICAL = "critical"  # irreconcilable conflict — hard stop recommended


@dataclass
class Contradiction:
    """A detected conflict between two agent responses."""
    contradiction_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    agent_a:     str = ""
    agent_b:     str = ""
    type:        ContradictionType = ContradictionType.FACTUAL
    severity:    ContradictionSeverity = ContradictionSeverity.MEDIUM
    description: str = ""
    score_a:     float = 0.0
    score_b:     float = 0.0
    detected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contradiction_id": self.contradiction_id,
            "agent_a":  self.agent_a,
            "agent_b":  self.agent_b,
            "type":     self.type.value,
            "severity": self.severity.value,
            "description": self.description,
            "detected_at": self.detected_at,
        }


# ---------------------------------------------------------------------------
# Consensus methods & result
# ---------------------------------------------------------------------------

class ConsensusMethod(str, Enum):
    MAJORITY_VOTE      = "majority_vote"      # most common sentiment/direction wins
    WEIGHTED_AVERAGE   = "weighted_average"   # weighted by confidence
    BEST_CONFIDENCE    = "best_confidence"    # select response with highest confidence
    UNANIMOUS          = "unanimous"          # only resolve if all agents agree
    PRIORITY_FIRST     = "priority_first"     # use highest-priority (lowest priority int) agent


@dataclass
class ConsensusResult:
    """The outcome of reaching consensus across multiple agent responses."""
    consensus_id:    str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    method:          ConsensusMethod = ConsensusMethod.WEIGHTED_AVERAGE
    final_content:   str = ""
    selected_agent:  str = ""        # which agent's content was chosen (or "merged")
    agreement_score: float = 0.0     # 0.0 (total disagreement) – 1.0 (perfect agreement)
    confidence:      float = 0.0     # aggregated confidence of the consensus
    responses_used:  int   = 0
    contradictions:  List[Contradiction] = field(default_factory=list)
    escalated:       bool  = False   # True if security was notified
    escalation_reason: Optional[str] = None
    reached_at:      str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def has_contradictions(self) -> bool:
        return len(self.contradictions) > 0

    @property
    def is_reliable(self) -> bool:
        return self.agreement_score >= 0.5 and not self.escalated

    def to_dict(self) -> Dict[str, Any]:
        return {
            "consensus_id":    self.consensus_id,
            "method":          self.method.value,
            "final_content":   self.final_content[:300],
            "selected_agent":  self.selected_agent,
            "agreement_score": round(self.agreement_score, 4),
            "confidence":      round(self.confidence, 4),
            "responses_used":  self.responses_used,
            "contradictions":  len(self.contradictions),
            "escalated":       self.escalated,
            "escalation_reason": self.escalation_reason,
            "reached_at":      self.reached_at,
        }


# ---------------------------------------------------------------------------
# Similarity helpers (pure stdlib)
# ---------------------------------------------------------------------------

_OPPOSITE_PAIRS: List[Tuple[str, str]] = [
    ("yes", "no"), ("true", "false"), ("correct", "incorrect"),
    ("positive", "negative"), ("increase", "decrease"), ("buy", "sell"),
    ("safe", "unsafe"), ("valid", "invalid"), ("approved", "rejected"),
    ("bullish", "bearish"), ("succeed", "fail"), ("allow", "deny"),
    ("recommend", "discourage"), ("proceed", "abort"), ("start", "stop"),
]

_NEGATION_RE = re.compile(
    r"\b(not|never|no|cannot|can't|don't|doesn't|isn't|aren't|won't|shouldn't)\b",
    re.IGNORECASE,
)


def _word_overlap(a: str, b: str) -> float:
    """Jaccard similarity of word sets (lower-cased)."""
    wa = set(re.findall(r"\w+", a.lower()))
    wb = set(re.findall(r"\w+", b.lower()))
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def _directional_score(text: str) -> float:
    """
    Heuristic: count positive-leaning vs negative-leaning keywords.
    Returns a value in [-1, 1]: positive = optimistic, negative = pessimistic.
    """
    pos_words = {"yes", "proceed", "recommended", "valid", "positive", "safe",
                 "increase", "buy", "approve", "allow", "start", "bullish"}
    neg_words = {"no", "stop", "discourage", "invalid", "negative", "unsafe",
                 "decrease", "sell", "reject", "deny", "abort", "bearish"}
    tokens    = set(re.findall(r"\w+", text.lower()))
    pos = len(tokens & pos_words)
    neg = len(tokens & neg_words)
    total = pos + neg
    if total == 0:
        return 0.0
    return (pos - neg) / total


def _has_opposite_pair(a: str, b: str) -> Optional[Tuple[str, str]]:
    """Return the first opposite pair found between the two texts, or None."""
    ta = set(re.findall(r"\w+", a.lower()))
    tb = set(re.findall(r"\w+", b.lower()))
    for w1, w2 in _OPPOSITE_PAIRS:
        if (w1 in ta and w2 in tb) or (w2 in ta and w1 in tb):
            return (w1, w2)
    return None


# ---------------------------------------------------------------------------
# Consensus Engine
# ---------------------------------------------------------------------------

class ConsensusEngine:
    """
    Reaches consensus across a list of AgentResponses.

    Contradiction detection:
    - Word-overlap divergence below threshold → FACTUAL
    - Opposite-direction keywords → DIRECTIONAL
    - Large confidence gap → CONFIDENCE_GAP
    - Very short vs very long response → STRUCTURAL

    Escalation:
    - HIGH or CRITICAL contradictions trigger the escalation_hook (if set)
    - The hook should call core.security.record_violation or equivalent
    """

    # Thresholds
    LOW_OVERLAP_THRESHOLD   = 0.10   # Jaccard < this → potential factual contradiction
    DIRECTION_FLIP_THRESHOLD = 0.4   # directional score difference > this → directional conflict
    CONFIDENCE_GAP_THRESHOLD = 0.25  # confidence gap > this → confidence conflict
    ESCALATION_SEVERITY      = ContradictionSeverity.HIGH   # escalate at this level and above

    def __init__(
        self,
        default_method: ConsensusMethod = ConsensusMethod.WEIGHTED_AVERAGE,
        escalation_hook: Optional[Callable[[ConsensusResult], None]] = None,
    ) -> None:
        self._method          = default_method
        self._escalation_hook = escalation_hook
        self._history:        List[ConsensusResult] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reach_consensus(
        self,
        responses:  List[AgentResponse],
        method:     Optional[ConsensusMethod] = None,
        task:       str = "",
    ) -> ConsensusResult:
        """
        Aggregate multiple agent responses into a single ConsensusResult.
        Automatically detects contradictions and escalates if necessary.
        """
        valid = [r for r in responses if r.ok]
        if not valid:
            result = ConsensusResult(
                method=method or self._method,
                final_content="[No valid agent responses available.]",
                agreement_score=0.0,
                responses_used=0,
            )
            self._history.append(result)
            return result

        contradictions = self.detect_contradictions(valid)
        agreement      = self.score_agreement(valid)
        effective_method = method or self._method

        final_content, selected = self._resolve(valid, effective_method)
        avg_confidence = statistics.mean(r.confidence for r in valid)

        # Escalation decision
        escalated = False
        escalation_reason: Optional[str] = None
        severity_order = [
            ContradictionSeverity.LOW,
            ContradictionSeverity.MEDIUM,
            ContradictionSeverity.HIGH,
            ContradictionSeverity.CRITICAL,
        ]
        threshold_idx = severity_order.index(self.ESCALATION_SEVERITY)
        severe = [
            c for c in contradictions
            if severity_order.index(c.severity) >= threshold_idx
        ]
        if severe:
            escalated = True
            escalation_reason = (
                f"{len(severe)} high-severity contradiction(s) detected: "
                + "; ".join(c.description for c in severe[:3])
            )

        result = ConsensusResult(
            method=effective_method,
            final_content=final_content,
            selected_agent=selected,
            agreement_score=round(agreement, 4),
            confidence=round(avg_confidence, 4),
            responses_used=len(valid),
            contradictions=contradictions,
            escalated=escalated,
            escalation_reason=escalation_reason,
        )

        if escalated and self._escalation_hook:
            try:
                self._escalation_hook(result)
            except Exception:
                pass

        self._history.append(result)
        return result

    def detect_contradictions(self, responses: List[AgentResponse]) -> List[Contradiction]:
        """Compare every pair of responses and return detected contradictions."""
        contradictions: List[Contradiction] = []
        for i in range(len(responses)):
            for j in range(i + 1, len(responses)):
                a, b = responses[i], responses[j]
                found = self._compare_pair(a, b)
                contradictions.extend(found)
        return contradictions

    def score_agreement(self, responses: List[AgentResponse]) -> float:
        """
        Compute pairwise Jaccard similarity across all response pairs.
        Returns a value in [0, 1]: 1.0 = identical content across all agents.
        """
        if len(responses) < 2:
            return 1.0
        scores: List[float] = []
        for i in range(len(responses)):
            for j in range(i + 1, len(responses)):
                scores.append(_word_overlap(responses[i].content, responses[j].content))
        return round(statistics.mean(scores), 4) if scores else 1.0

    def history(self, limit: int = 20) -> List[Dict[str, Any]]:
        return [r.to_dict() for r in self._history[-limit:]]

    def stats(self) -> Dict[str, Any]:
        total      = len(self._history)
        escalated  = sum(1 for r in self._history if r.escalated)
        avg_agree  = statistics.mean(r.agreement_score for r in self._history) if self._history else 0.0
        return {
            "total_consensus_runs": total,
            "escalations":          escalated,
            "avg_agreement_score":  round(avg_agree, 4),
        }

    # ------------------------------------------------------------------
    # Resolution strategies
    # ------------------------------------------------------------------

    def _resolve(
        self,
        responses: List[AgentResponse],
        method:    ConsensusMethod,
    ) -> Tuple[str, str]:
        """Return (final_content, selected_agent_name)."""

        if method == ConsensusMethod.BEST_CONFIDENCE:
            best = max(responses, key=lambda r: r.confidence)
            return best.content, best.agent_name

        if method == ConsensusMethod.PRIORITY_FIRST:
            # Lower agent_id lexicographically → higher priority in mock context
            # In real use, registry priority would be passed in
            return responses[0].content, responses[0].agent_name

        if method == ConsensusMethod.UNANIMOUS:
            scores = [_word_overlap(responses[0].content, r.content) for r in responses[1:]]
            if scores and min(scores) > 0.5:
                return responses[0].content, responses[0].agent_name
            return "[UNANIMOUS consensus not reached — manual review required.]", "none"

        if method == ConsensusMethod.MAJORITY_VOTE:
            # Group by directional sign and pick the majority direction
            pos = [r for r in responses if _directional_score(r.content) >= 0]
            neg = [r for r in responses if _directional_score(r.content) < 0]
            pool = pos if len(pos) >= len(neg) else neg
            if not pool:
                pool = responses
            best = max(pool, key=lambda r: r.confidence)
            return best.content, best.agent_name

        # Default: WEIGHTED_AVERAGE → select content from highest-weight response
        # Weight = confidence × (1 / (1 + error_proxy)) where error_proxy = 1 if not ok
        weights = [r.confidence for r in responses]
        total_w = sum(weights) or 1.0
        best_idx = weights.index(max(weights))
        best     = responses[best_idx]
        return best.content, best.agent_name

    # ------------------------------------------------------------------
    # Contradiction detection helpers
    # ------------------------------------------------------------------

    def _compare_pair(
        self, a: AgentResponse, b: AgentResponse
    ) -> List[Contradiction]:
        found: List[Contradiction] = []

        # 1. Factual divergence — low word overlap
        overlap = _word_overlap(a.content, b.content)
        if overlap < self.LOW_OVERLAP_THRESHOLD:
            found.append(Contradiction(
                agent_a=a.agent_name, agent_b=b.agent_name,
                type=ContradictionType.FACTUAL,
                severity=ContradictionSeverity.MEDIUM,
                description=(
                    f"Low content overlap ({overlap:.2f}) between "
                    f"'{a.agent_name}' and '{b.agent_name}'."
                ),
                score_a=overlap, score_b=1.0 - overlap,
            ))

        # 2. Directional conflict — opposing sentiment / recommendation
        dir_a = _directional_score(a.content)
        dir_b = _directional_score(b.content)
        if abs(dir_a - dir_b) >= self.DIRECTION_FLIP_THRESHOLD:
            pair = _has_opposite_pair(a.content, b.content)
            severity = (ContradictionSeverity.HIGH
                        if abs(dir_a - dir_b) > 0.6
                        else ContradictionSeverity.MEDIUM)
            desc = (
                f"Directional conflict between '{a.agent_name}' "
                f"({dir_a:+.2f}) and '{b.agent_name}' ({dir_b:+.2f})."
                + (f" Opposing terms: {pair[0]!r} vs {pair[1]!r}." if pair else "")
            )
            found.append(Contradiction(
                agent_a=a.agent_name, agent_b=b.agent_name,
                type=ContradictionType.DIRECTIONAL,
                severity=severity,
                description=desc,
                score_a=dir_a, score_b=dir_b,
            ))

        # 3. Confidence gap
        conf_gap = abs(a.confidence - b.confidence)
        if conf_gap >= self.CONFIDENCE_GAP_THRESHOLD:
            found.append(Contradiction(
                agent_a=a.agent_name, agent_b=b.agent_name,
                type=ContradictionType.CONFIDENCE_GAP,
                severity=ContradictionSeverity.LOW,
                description=(
                    f"Confidence gap of {conf_gap:.2f} between "
                    f"'{a.agent_name}' ({a.confidence:.2f}) "
                    f"and '{b.agent_name}' ({b.confidence:.2f})."
                ),
                score_a=a.confidence, score_b=b.confidence,
            ))

        # 4. Structural mismatch — very different response lengths
        len_ratio = min(len(a.content), len(b.content)) / max(len(a.content), len(b.content), 1)
        if len_ratio < 0.15:
            found.append(Contradiction(
                agent_a=a.agent_name, agent_b=b.agent_name,
                type=ContradictionType.STRUCTURAL,
                severity=ContradictionSeverity.LOW,
                description=(
                    f"Structural mismatch: '{a.agent_name}' ({len(a.content)} chars) "
                    f"vs '{b.agent_name}' ({len(b.content)} chars)."
                ),
            ))

        return found
