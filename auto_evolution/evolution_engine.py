"""
NEXUS Auto-Evolution — Evolution Engine
Code analysis, improvement heuristics, patch generation and scoring.
"""

from __future__ import annotations

import ast
import difflib
import hashlib
import textwrap
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .evolution_rules import EvolutionPermission, EvolutionRules, RiskLevel


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CodeIssue:
    """A single detected problem or improvement opportunity in a source file."""
    file_path: str
    line: int
    category: str        # e.g. "complexity", "duplication", "missing_type_hint"
    description: str
    risk: RiskLevel = RiskLevel.LOW
    suggestion: Optional[str] = None


@dataclass
class Patch:
    """A proposed code change, ready to be applied or rejected."""
    patch_id: str
    file_path: str
    original: str
    proposed: str
    issues_addressed: List[str]
    risk: RiskLevel
    score: float         # 0.0 (useless) – 1.0 (perfect)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    applied: bool = False
    dry_run: bool = False

    def unified_diff(self) -> str:
        orig_lines = self.original.splitlines(keepends=True)
        prop_lines = self.proposed.splitlines(keepends=True)
        return "".join(
            difflib.unified_diff(orig_lines, prop_lines, fromfile=f"a/{self.file_path}", tofile=f"b/{self.file_path}")
        )

    def lines_changed(self) -> int:
        diff = self.unified_diff()
        return sum(1 for line in diff.splitlines() if line.startswith(("+", "-")) and not line.startswith(("+++", "---")))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "patch_id": self.patch_id,
            "file": self.file_path,
            "risk": self.risk.value,
            "score": round(self.score, 3),
            "lines_changed": self.lines_changed(),
            "issues_addressed": self.issues_addressed,
            "applied": self.applied,
            "dry_run": self.dry_run,
            "created_at": self.created_at,
        }


@dataclass
class EvolutionCycleReport:
    cycle_id: str
    started_at: str
    finished_at: Optional[str] = None
    files_analysed: int = 0
    issues_found: List[CodeIssue] = field(default_factory=list)
    patches_generated: List[Patch] = field(default_factory=list)
    patches_applied: int = 0
    errors: List[str] = field(default_factory=list)

    def summary(self) -> Dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "files_analysed": self.files_analysed,
            "issues_found": len(self.issues_found),
            "patches_generated": len(self.patches_generated),
            "patches_applied": self.patches_applied,
            "errors": self.errors,
        }


# ---------------------------------------------------------------------------
# Heuristic analyser (pure AST, no external tools)
# ---------------------------------------------------------------------------

class _ASTAnalyser:
    """
    Walks a Python AST and emits CodeIssues for common anti-patterns.
    Designed to be extended — add visit_* methods for more heuristics.
    """

    MAX_FUNCTION_LINES = 50
    MAX_ARGS           = 7
    COMPLEXITY_THRESHOLD = 10   # branches per function

    def analyse(self, source: str, file_path: str) -> List[CodeIssue]:
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            return [CodeIssue(file_path=file_path, line=exc.lineno or 0,
                              category="syntax_error", description=str(exc), risk=RiskLevel.CRITICAL)]
        issues: List[CodeIssue] = []
        self._walk(tree, source, file_path, issues)
        return issues

    def _walk(self, tree: ast.AST, source: str, file_path: str, issues: List[CodeIssue]) -> None:
        lines = source.splitlines()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._check_function(node, lines, file_path, issues)
            elif isinstance(node, ast.ClassDef):
                self._check_class(node, file_path, issues)

    def _check_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        lines: List[str],
        file_path: str,
        issues: List[CodeIssue],
    ) -> None:
        start = node.lineno
        end   = getattr(node, "end_lineno", start)
        length = end - start + 1

        if length > self.MAX_FUNCTION_LINES:
            issues.append(CodeIssue(
                file_path=file_path, line=start, category="long_function",
                description=f"Function '{node.name}' is {length} lines (limit {self.MAX_FUNCTION_LINES}).",
                risk=RiskLevel.MEDIUM,
                suggestion=f"Split '{node.name}' into smaller, single-responsibility functions.",
            ))

        num_args = len(node.args.args) + len(node.args.posonlyargs) + len(node.args.kwonlyargs)
        if num_args > self.MAX_ARGS:
            issues.append(CodeIssue(
                file_path=file_path, line=start, category="too_many_args",
                description=f"Function '{node.name}' has {num_args} parameters (limit {self.MAX_ARGS}).",
                risk=RiskLevel.LOW,
                suggestion=f"Group related params into a dataclass or config object.",
            ))

        # Missing return type annotation
        if node.returns is None and node.name != "__init__":
            issues.append(CodeIssue(
                file_path=file_path, line=start, category="missing_return_type",
                description=f"Function '{node.name}' is missing a return type annotation.",
                risk=RiskLevel.LOW,
                suggestion=f"Add a return type annotation to '{node.name}'.",
            ))

        # Cyclomatic complexity (count branches)
        complexity = sum(
            1 for n in ast.walk(node)
            if isinstance(n, (ast.If, ast.For, ast.While, ast.ExceptHandler,
                               ast.With, ast.Assert, ast.comprehension))
        )
        if complexity > self.COMPLEXITY_THRESHOLD:
            issues.append(CodeIssue(
                file_path=file_path, line=start, category="high_complexity",
                description=f"Function '{node.name}' has cyclomatic complexity ~{complexity} (threshold {self.COMPLEXITY_THRESHOLD}).",
                risk=RiskLevel.MEDIUM,
                suggestion=f"Reduce branching in '{node.name}' by extracting helpers or using early returns.",
            ))

    def _check_class(self, node: ast.ClassDef, file_path: str, issues: List[CodeIssue]) -> None:
        if not (ast.get_docstring(node)):
            issues.append(CodeIssue(
                file_path=file_path, line=node.lineno, category="missing_docstring",
                description=f"Class '{node.name}' has no docstring.",
                risk=RiskLevel.LOW,
                suggestion=f"Add a one-line docstring to class '{node.name}'.",
            ))


# ---------------------------------------------------------------------------
# Patch scorer
# ---------------------------------------------------------------------------

def _score_patch(patch: Patch) -> float:
    """
    Heuristic score for a patch: reward small, low-risk, targeted changes.
    Returns a value in [0.0, 1.0].
    """
    risk_penalty = {RiskLevel.LOW: 0.0, RiskLevel.MEDIUM: 0.15, RiskLevel.HIGH: 0.35, RiskLevel.CRITICAL: 0.8}
    size_penalty = min(patch.lines_changed() / 200, 0.4)
    coverage_bonus = min(len(patch.issues_addressed) * 0.1, 0.3)
    base = 0.7
    score = base + coverage_bonus - risk_penalty.get(patch.risk, 0.5) - size_penalty
    return max(0.0, min(1.0, score))


# ---------------------------------------------------------------------------
# Evolution Engine
# ---------------------------------------------------------------------------

class EvolutionEngine:
    """
    Orchestrates analysis → patch generation → optional application cycles.

    Each cycle:
      1. Scans target files with _ASTAnalyser
      2. Generates Patch objects for addressable issues
      3. Scores and filters patches by rules
      4. Optionally applies patches (unless dry_run or rules block)
    """

    def __init__(self, rules: Optional[EvolutionRules] = None, base_dir: str = ".") -> None:
        self._rules   = rules or EvolutionRules()
        self._base    = Path(base_dir)
        self._analyser = _ASTAnalyser()
        self._history: List[EvolutionCycleReport] = []
        self._cycle_timestamps: List[float] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyse_file(self, file_path: str) -> List[CodeIssue]:
        """Return all detected issues for a single file without modifying anything."""
        self._rules.check_permission(EvolutionPermission.ANALYSE)
        path = self._base / file_path
        if not path.exists():
            return []
        source = path.read_text(encoding="utf-8")
        return self._analyser.analyse(source, file_path)

    def generate_patch(self, file_path: str, issues: Optional[List[CodeIssue]] = None) -> Optional[Patch]:
        """
        Generate a Patch for a file.
        Currently produces documentation-stub patches for missing docstrings
        and annotations; extend this method for richer transformations.
        """
        self._rules.check_permission(EvolutionPermission.SUGGEST)
        path = self._base / file_path
        if not path.exists():
            return None

        source = path.read_text(encoding="utf-8")
        detected = issues or self._analyser.analyse(source, file_path)

        if not detected:
            return None

        proposed, addressed, max_risk = self._apply_heuristics(source, detected)
        if proposed == source:
            return None

        patch = Patch(
            patch_id=hashlib.sha1(f"{file_path}{time.time()}".encode()).hexdigest()[:12],
            file_path=file_path,
            original=source,
            proposed=proposed,
            issues_addressed=addressed,
            risk=max_risk,
            score=0.0,
            dry_run=self._rules.is_dry_run(),
        )
        patch.score = _score_patch(patch)
        return patch

    def run_cycle(self, target_files: List[str]) -> EvolutionCycleReport:
        """
        Run a full evolution cycle over the listed files.
        Applies patches if permitted by the active policy.
        """
        # Cycle quota check
        now = time.monotonic()
        self._cycle_timestamps = [t for t in self._cycle_timestamps if now - t < 3600]
        self._rules.check_cycle_quota(len(self._cycle_timestamps))
        self._rules.check_files_per_cycle(len(target_files))

        report = EvolutionCycleReport(
            cycle_id=hashlib.sha1(str(now).encode()).hexdigest()[:10],
            started_at=datetime.now(timezone.utc).isoformat(),
        )

        for fp in target_files:
            try:
                self._rules.check_path(fp)
            except Exception as exc:
                report.errors.append(str(exc))
                continue

            issues = self.analyse_file(fp)
            report.issues_found.extend(issues)
            report.files_analysed += 1

            patch = self.generate_patch(fp, issues)
            if patch is None:
                continue

            try:
                self._rules.check_risk(patch.risk, fp)
                self._rules.check_patch_size(patch.lines_changed())
            except Exception as exc:
                report.errors.append(str(exc))
                continue

            report.patches_generated.append(patch)

            if not self._rules.is_dry_run():
                self._apply_patch(patch, report)

        report.finished_at = datetime.now(timezone.utc).isoformat()
        self._history.append(report)
        self._cycle_timestamps.append(now)
        return report

    def history(self, limit: int = 20) -> List[Dict[str, Any]]:
        return [r.summary() for r in self._history[-limit:]]

    def stats(self) -> Dict[str, Any]:
        total_patches = sum(len(r.patches_generated) for r in self._history)
        total_applied = sum(r.patches_applied for r in self._history)
        return {
            "cycles_run": len(self._history),
            "total_patches_generated": total_patches,
            "total_patches_applied": total_applied,
            "cycles_this_hour": len(self._cycle_timestamps),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _apply_heuristics(
        self, source: str, issues: List[CodeIssue]
    ) -> Tuple[str, List[str], RiskLevel]:
        """
        Apply lightweight text-level fixes for low-risk issues.
        Returns (modified_source, addressed_categories, max_risk).
        """
        lines     = source.splitlines()
        addressed: List[str] = []
        max_risk  = RiskLevel.LOW

        try:
            tree = ast.parse(source)
        except SyntaxError:
            return source, [], RiskLevel.CRITICAL

        # Fix: add missing class docstrings
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and not ast.get_docstring(node):
                insert_at = node.body[0].lineno - 1   # line index of first statement
                indent    = " " * (node.col_offset + 4)
                stub      = f'{indent}"""TODO: document {node.name}."""'
                lines.insert(insert_at, stub)
                addressed.append("missing_docstring")
                # Re-parse with inserted line to keep offsets valid — skip for now
                break  # one insertion per cycle to avoid offset drift

        risk_order = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]
        for issue in issues:
            if issue.category in addressed:
                idx = risk_order.index(issue.risk)
                if idx > risk_order.index(max_risk):
                    max_risk = issue.risk

        return "\n".join(lines) + "\n", addressed, max_risk

    def _apply_patch(self, patch: Patch, report: EvolutionCycleReport) -> None:
        path = self._base / patch.file_path
        try:
            self._rules.check_permission(EvolutionPermission.PATCH)
            if self._rules.requires_backup():
                backup = path.with_suffix(path.suffix + ".bak")
                backup.write_text(patch.original, encoding="utf-8")
            path.write_text(patch.proposed, encoding="utf-8")
            patch.applied = True
            report.patches_applied += 1
        except Exception as exc:
            report.errors.append(f"Failed to apply patch {patch.patch_id}: {exc}")
