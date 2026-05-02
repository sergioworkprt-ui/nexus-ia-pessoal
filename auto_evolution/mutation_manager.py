"""
NEXUS Auto-Evolution — Mutation Manager
Variant generation, A/B tracking, performance scoring and version selection.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .evolution_rules import EvolutionPermission, EvolutionRules, RiskLevel


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Variant:
    """A single named alternative version of a file or configuration."""
    variant_id: str
    name: str
    file_path: str
    content: str
    parent_id: Optional[str]       # ID of the variant this was derived from
    risk: RiskLevel
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metrics: Dict[str, float] = field(default_factory=dict)  # populated after evaluation
    status: str = "candidate"      # "candidate" | "active" | "rejected" | "archived"

    def checksum(self) -> str:
        return hashlib.sha256(self.content.encode()).hexdigest()[:12]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "name": self.name,
            "file": self.file_path,
            "parent_id": self.parent_id,
            "risk": self.risk.value,
            "checksum": self.checksum(),
            "created_at": self.created_at,
            "metrics": self.metrics,
            "status": self.status,
        }


@dataclass
class ABTest:
    """Tracks an active A/B experiment comparing two or more variants."""
    test_id: str
    name: str
    file_path: str
    control_id: str                  # variant_id of the baseline
    challenger_ids: List[str]        # variant_ids being tested
    metric: str                      # e.g. "latency_ms", "error_rate", "score"
    higher_is_better: bool = True
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    ended_at: Optional[str] = None
    winner_id: Optional[str] = None
    status: str = "running"          # "running" | "concluded" | "aborted"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "test_id": self.test_id,
            "name": self.name,
            "file": self.file_path,
            "control": self.control_id,
            "challengers": self.challenger_ids,
            "metric": self.metric,
            "higher_is_better": self.higher_is_better,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "winner_id": self.winner_id,
            "status": self.status,
        }


# ---------------------------------------------------------------------------
# Mutation strategies (pure functions — easily replaceable)
# ---------------------------------------------------------------------------

def _identity_mutation(content: str) -> str:
    """Return content unchanged (baseline / control variant)."""
    return content


def _strip_comments_mutation(content: str) -> str:
    """Remove inline # comments from non-string lines (cosmetic only)."""
    import re
    lines = []
    for line in content.splitlines():
        # Only strip comments outside string literals (simplified heuristic)
        if not line.strip().startswith("#"):
            line = re.sub(r'\s+#[^"\']*$', "", line)
        lines.append(line)
    return "\n".join(lines) + "\n"


def _add_module_docstring_mutation(content: str) -> str:
    """Prepend a TODO module docstring if none exists."""
    stripped = content.lstrip()
    if stripped.startswith('"""') or stripped.startswith("'''"):
        return content
    return '"""\nTODO: add module-level documentation.\n"""\n' + content


MutationFn = Callable[[str], str]

BUILTIN_MUTATIONS: Dict[str, MutationFn] = {
    "identity":              _identity_mutation,
    "strip_comments":        _strip_comments_mutation,
    "add_module_docstring":  _add_module_docstring_mutation,
}


# ---------------------------------------------------------------------------
# Mutation Manager
# ---------------------------------------------------------------------------

class MutationManager:
    """
    Generates and tracks code variants, runs A/B experiments, and selects
    winning versions based on recorded metrics.

    Variants are persisted to disk so experiments survive restarts.
    """

    def __init__(
        self,
        rules: Optional[EvolutionRules] = None,
        base_dir: str = ".",
        storage_dir: str = "data/mutations",
    ) -> None:
        self._rules     = rules or EvolutionRules()
        self._base      = Path(base_dir)
        self._store_dir = Path(storage_dir)
        self._store_dir.mkdir(parents=True, exist_ok=True)
        self._variants: Dict[str, Variant] = {}
        self._tests:    Dict[str, ABTest]  = {}
        self._mutations: Dict[str, MutationFn] = dict(BUILTIN_MUTATIONS)
        self._load_state()

    # ------------------------------------------------------------------
    # Variant management
    # ------------------------------------------------------------------

    def create_variant(
        self,
        file_path: str,
        mutation: str = "identity",
        name: Optional[str] = None,
        parent_id: Optional[str] = None,
        risk: RiskLevel = RiskLevel.LOW,
    ) -> Variant:
        """Generate a new variant of a file by applying a named mutation."""
        self._rules.check_permission(EvolutionPermission.MUTATE)
        self._rules.check_path(file_path)
        self._rules.check_risk(risk, file_path)

        path = self._base / file_path
        if not path.exists():
            raise FileNotFoundError(f"Source file '{file_path}' not found.")

        mutation_fn = self._mutations.get(mutation)
        if mutation_fn is None:
            raise ValueError(f"Unknown mutation '{mutation}'. Available: {list(self._mutations)}")

        original = path.read_text(encoding="utf-8")
        mutated  = mutation_fn(original)

        vid = hashlib.sha1(f"{file_path}{mutation}{time.time()}".encode()).hexdigest()[:12]
        variant = Variant(
            variant_id=vid,
            name=name or f"{Path(file_path).stem}_{mutation}_{vid}",
            file_path=file_path,
            content=mutated,
            parent_id=parent_id,
            risk=risk,
        )
        self._variants[vid] = variant
        self._save_state()
        return variant

    def apply_variant(self, variant_id: str) -> bool:
        """Write a variant's content to disk (replaces the current file)."""
        self._rules.check_permission(EvolutionPermission.PATCH)
        variant = self._variants.get(variant_id)
        if variant is None:
            return False
        if self._rules.is_dry_run():
            variant.status = "active"
            return True
        dest = self._base / variant.file_path
        dest.write_text(variant.content, encoding="utf-8")
        variant.status = "active"
        self._save_state()
        return True

    def reject_variant(self, variant_id: str) -> bool:
        variant = self._variants.get(variant_id)
        if not variant:
            return False
        variant.status = "rejected"
        self._save_state()
        return True

    def record_metric(self, variant_id: str, metric: str, value: float) -> None:
        """Attach an observed performance metric to a variant."""
        variant = self._variants.get(variant_id)
        if variant:
            variant.metrics[metric] = value
            self._save_state()

    def list_variants(self, file_path: Optional[str] = None) -> List[Dict[str, Any]]:
        variants = self._variants.values()
        if file_path:
            variants = (v for v in variants if v.file_path == file_path)  # type: ignore[assignment]
        return [v.to_dict() for v in variants]

    # ------------------------------------------------------------------
    # A/B testing
    # ------------------------------------------------------------------

    def start_ab_test(
        self,
        name: str,
        file_path: str,
        control_id: str,
        challenger_ids: List[str],
        metric: str,
        higher_is_better: bool = True,
    ) -> ABTest:
        """Create and register a new A/B experiment."""
        test_id = hashlib.sha1(f"{name}{time.time()}".encode()).hexdigest()[:10]
        test = ABTest(
            test_id=test_id,
            name=name,
            file_path=file_path,
            control_id=control_id,
            challenger_ids=challenger_ids,
            metric=metric,
            higher_is_better=higher_is_better,
        )
        self._tests[test_id] = test
        self._save_state()
        return test

    def conclude_test(self, test_id: str) -> Optional[str]:
        """
        Evaluate a running test and declare a winner based on recorded metrics.
        Returns the winning variant_id, or None if insufficient data.
        """
        test = self._tests.get(test_id)
        if test is None or test.status != "running":
            return None

        all_ids = [test.control_id] + test.challenger_ids
        scored: List[Tuple[float, str]] = []
        for vid in all_ids:
            variant = self._variants.get(vid)
            if variant and test.metric in variant.metrics:
                scored.append((variant.metrics[test.metric], vid))

        if not scored:
            return None

        scored.sort(key=lambda x: x[0], reverse=test.higher_is_better)
        winner_id = scored[0][1]
        test.winner_id = winner_id
        test.ended_at  = datetime.now(timezone.utc).isoformat()
        test.status    = "concluded"
        self._save_state()
        return winner_id

    def abort_test(self, test_id: str) -> bool:
        test = self._tests.get(test_id)
        if not test:
            return False
        test.status   = "aborted"
        test.ended_at = datetime.now(timezone.utc).isoformat()
        self._save_state()
        return True

    def list_tests(self) -> List[Dict[str, Any]]:
        return [t.to_dict() for t in self._tests.values()]

    # ------------------------------------------------------------------
    # Mutation registration
    # ------------------------------------------------------------------

    def register_mutation(self, name: str, fn: MutationFn) -> None:
        """Register a custom mutation strategy."""
        self._mutations[name] = fn

    def available_mutations(self) -> List[str]:
        return list(self._mutations.keys())

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_state(self) -> None:
        state = {
            "variants": {vid: v.to_dict() for vid, v in self._variants.items()},
            "tests":    {tid: t.to_dict() for tid, t in self._tests.items()},
        }
        (self._store_dir / "state.json").write_text(
            json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _load_state(self) -> None:
        state_file = self._store_dir / "state.json"
        if not state_file.exists():
            return
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            return

        for vid, data in state.get("variants", {}).items():
            try:
                self._variants[vid] = Variant(
                    variant_id=data["variant_id"],
                    name=data["name"],
                    file_path=data["file"],
                    content=data.get("content", ""),
                    parent_id=data.get("parent_id"),
                    risk=RiskLevel(data["risk"]),
                    created_at=data["created_at"],
                    metrics=data.get("metrics", {}),
                    status=data.get("status", "candidate"),
                )
            except (KeyError, ValueError):
                pass

        for tid, data in state.get("tests", {}).items():
            try:
                self._tests[tid] = ABTest(
                    test_id=data["test_id"],
                    name=data["name"],
                    file_path=data["file"],
                    control_id=data["control"],
                    challenger_ids=data["challengers"],
                    metric=data["metric"],
                    higher_is_better=data.get("higher_is_better", True),
                    started_at=data["started_at"],
                    ended_at=data.get("ended_at"),
                    winner_id=data.get("winner_id"),
                    status=data.get("status", "running"),
                )
            except (KeyError, ValueError):
                pass
