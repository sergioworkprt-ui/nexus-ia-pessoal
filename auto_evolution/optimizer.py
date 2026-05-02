"""
NEXUS Auto-Evolution — Optimizer
Code refactoring suggestions, simplification heuristics, and performance hints.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .evolution_rules import EvolutionPermission, EvolutionRules, RiskLevel


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Suggestion:
    """A single optimisation suggestion for a specific location in a file."""
    suggestion_id: str
    file_path: str
    line: int
    category: str
    description: str
    risk: RiskLevel
    effort: str           # "trivial" | "low" | "medium" | "high"
    example: Optional[str] = None
    auto_applicable: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.suggestion_id,
            "file": self.file_path,
            "line": self.line,
            "category": self.category,
            "description": self.description,
            "risk": self.risk.value,
            "effort": self.effort,
            "example": self.example,
            "auto_applicable": self.auto_applicable,
        }


@dataclass
class OptimisationReport:
    """Aggregated optimisation report for one or more files."""
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    suggestions: List[Suggestion] = field(default_factory=list)
    files_scanned: int = 0

    def by_category(self) -> Dict[str, List[Suggestion]]:
        result: Dict[str, List[Suggestion]] = {}
        for s in self.suggestions:
            result.setdefault(s.category, []).append(s)
        return result

    def by_risk(self) -> Dict[str, List[Suggestion]]:
        result: Dict[str, List[Suggestion]] = {}
        for s in self.suggestions:
            result.setdefault(s.risk.value, []).append(s)
        return result

    def summary(self) -> Dict[str, Any]:
        cats = {}
        for s in self.suggestions:
            cats[s.category] = cats.get(s.category, 0) + 1
        return {
            "generated_at": self.generated_at,
            "files_scanned": self.files_scanned,
            "total_suggestions": len(self.suggestions),
            "by_category": cats,
            "auto_applicable": sum(1 for s in self.suggestions if s.auto_applicable),
        }


# ---------------------------------------------------------------------------
# AST-based optimisation visitors
# ---------------------------------------------------------------------------

class _OptimisationVisitor(ast.NodeVisitor):
    """
    Walks the AST of a single file and collects Suggestion objects.
    Each visit_* method targets a specific anti-pattern.
    """

    def __init__(self, file_path: str) -> None:
        self._file    = file_path
        self._counter = 0
        self.suggestions: List[Suggestion] = []

    # -- helpers -----------------------------------------------------------

    def _add(self, line: int, category: str, description: str, risk: RiskLevel,
             effort: str, example: Optional[str] = None, auto: bool = False) -> None:
        self._counter += 1
        self.suggestions.append(Suggestion(
            suggestion_id=f"opt-{self._counter:04d}",
            file_path=self._file,
            line=line,
            category=category,
            description=description,
            risk=risk,
            effort=effort,
            example=example,
            auto_applicable=auto,
        ))

    # -- visitors ----------------------------------------------------------

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._check_function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._check_function(node)
        self.generic_visit(node)

    def _check_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        # Detect mutable default arguments: def f(x=[]) / def f(x={})
        for default in node.args.defaults + node.args.kw_defaults:
            if default is None:
                continue
            if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                self._add(
                    line=node.lineno,
                    category="mutable_default_arg",
                    description=f"Function '{node.name}' uses a mutable default argument.",
                    risk=RiskLevel.MEDIUM,
                    effort="trivial",
                    example="Use `None` as default and initialise inside the function body.",
                    auto=False,
                )

        # Detect bare `except:` (catches everything including KeyboardInterrupt)
        for n in ast.walk(node):
            if isinstance(n, ast.ExceptHandler) and n.type is None:
                self._add(
                    line=n.lineno,
                    category="bare_except",
                    description=f"Bare `except:` clause in or near '{node.name}'. Catches all exceptions including system exits.",
                    risk=RiskLevel.MEDIUM,
                    effort="trivial",
                    example="Use `except Exception:` or a specific exception type.",
                    auto=False,
                )

        # Detect `== None` / `!= None` instead of `is None` / `is not None`
        for n in ast.walk(node):
            if isinstance(n, ast.Compare):
                for op, comparator in zip(n.ops, n.comparators):
                    if isinstance(op, (ast.Eq, ast.NotEq)) and isinstance(comparator, ast.Constant) and comparator.value is None:
                        verb = "==" if isinstance(op, ast.Eq) else "!="
                        self._add(
                            line=n.lineno,
                            category="identity_check",
                            description=f"Use `is None` / `is not None` instead of `{verb} None`.",
                            risk=RiskLevel.LOW,
                            effort="trivial",
                            auto=False,
                        )

    def visit_For(self, node: ast.For) -> None:  # noqa: N802
        # Detect `for i in range(len(x)):` → suggest enumerate
        if (isinstance(node.iter, ast.Call) and
                isinstance(node.iter.func, ast.Name) and node.iter.func.id == "range" and
                node.iter.args and isinstance(node.iter.args[0], ast.Call) and
                isinstance(node.iter.args[0].func, ast.Name) and node.iter.args[0].func.id == "len"):
            self._add(
                line=node.lineno,
                category="use_enumerate",
                description="`for i in range(len(x)):` can be simplified with `enumerate(x)`.",
                risk=RiskLevel.LOW,
                effort="trivial",
                example="for i, item in enumerate(x):",
                auto=False,
            )
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        # Detect wildcard imports: from x import *
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        for alias in node.names:
            if alias.name == "*":
                self._add(
                    line=node.lineno,
                    category="wildcard_import",
                    description=f"`from {node.module} import *` pollutes the namespace.",
                    risk=RiskLevel.LOW,
                    effort="low",
                    example="Import only the names you need.",
                    auto=False,
                )
        self.generic_visit(node)

    def visit_Global(self, node: ast.Global) -> None:  # noqa: N802
        self._add(
            line=node.lineno,
            category="global_variable",
            description=f"Use of `global {', '.join(node.names)}` detected. Prefer passing state explicitly.",
            risk=RiskLevel.MEDIUM,
            effort="medium",
        )
        self.generic_visit(node)


# ---------------------------------------------------------------------------
# String-level optimisation (regex, no AST needed)
# ---------------------------------------------------------------------------

def _string_level_suggestions(source: str, file_path: str) -> List[Suggestion]:
    suggestions: List[Suggestion] = []
    counter = 1000

    lines = source.splitlines()
    for i, line in enumerate(lines, start=1):
        # Detect print() calls in non-test files (should use logger)
        if re.search(r'\bprint\s*\(', line) and "test" not in file_path.lower():
            suggestions.append(Suggestion(
                suggestion_id=f"opt-str-{counter:04d}",
                file_path=file_path,
                line=i,
                category="print_statement",
                description=f"Line {i}: `print()` found — use the NEXUS logger instead.",
                risk=RiskLevel.LOW,
                effort="trivial",
                example="from core.logger import get_logger; get_logger().info(__name__, 'message')",
                auto_applicable=False,
            ))
            counter += 1

        # Detect hardcoded credentials patterns
        if re.search(r'(?i)(password|secret|api_key)\s*=\s*["\'][^"\']{4,}["\']', line):
            suggestions.append(Suggestion(
                suggestion_id=f"opt-str-{counter:04d}",
                file_path=file_path,
                line=i,
                category="hardcoded_secret",
                description=f"Line {i}: Possible hardcoded secret detected. Move to environment variables.",
                risk=RiskLevel.CRITICAL,
                effort="low",
                auto_applicable=False,
            ))
            counter += 1

    return suggestions


# ---------------------------------------------------------------------------
# Optimizer
# ---------------------------------------------------------------------------

class Optimizer:
    """
    Produces human-readable (and machine-actionable) optimisation suggestions
    for Python source files without modifying them.

    Separation of concerns: this module only *suggests*; the EvolutionEngine
    is responsible for actually applying changes.
    """

    def __init__(self, rules: Optional[EvolutionRules] = None, base_dir: str = ".") -> None:
        self._rules = rules or EvolutionRules()
        self._base  = Path(base_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyse_file(self, file_path: str) -> List[Suggestion]:
        """Return all optimisation suggestions for a single file."""
        self._rules.check_permission(EvolutionPermission.ANALYSE)
        path = self._base / file_path
        if not path.exists():
            return []

        source = path.read_text(encoding="utf-8")
        suggestions: List[Suggestion] = []

        try:
            tree = ast.parse(source)
            visitor = _OptimisationVisitor(file_path)
            visitor.visit(tree)
            suggestions.extend(visitor.suggestions)
        except SyntaxError:
            pass  # syntax errors are handled by SelfRepair, not Optimizer

        suggestions.extend(_string_level_suggestions(source, file_path))
        return suggestions

    def analyse_files(self, file_paths: List[str]) -> OptimisationReport:
        """Analyse multiple files and return an aggregated report."""
        report = OptimisationReport()
        for fp in file_paths:
            try:
                self._rules.check_path(fp)
            except Exception:
                continue
            suggestions = self.analyse_file(fp)
            report.suggestions.extend(suggestions)
            report.files_scanned += 1
        return report

    def top_suggestions(
        self, file_paths: List[str], limit: int = 10, max_risk: RiskLevel = RiskLevel.MEDIUM
    ) -> List[Suggestion]:
        """
        Return the most impactful suggestions across files,
        filtered by maximum acceptable risk.
        """
        risk_order = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]
        max_idx = risk_order.index(max_risk)
        report = self.analyse_files(file_paths)
        filtered = [s for s in report.suggestions if risk_order.index(s.risk) <= max_idx]
        # Sort: critical first, then by line number for determinism
        filtered.sort(key=lambda s: (risk_order.index(s.risk), s.file_path, s.line), reverse=True)
        return filtered[:limit]
