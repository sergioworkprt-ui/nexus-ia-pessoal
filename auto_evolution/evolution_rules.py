"""
NEXUS Auto-Evolution — Evolution Rules
Safety policies, permission levels, file/module restrictions, and cycle limits.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class EvolutionPermission(str, Enum):
    """Granular permission flags for evolution operations."""
    ANALYSE   = "analyse"    # read and analyse code only
    SUGGEST   = "suggest"    # produce suggestions without applying
    PATCH     = "patch"      # apply non-destructive patches
    REFACTOR  = "refactor"   # structural refactoring
    DELETE    = "delete"     # allow deletion of code / files
    MUTATE    = "mutate"     # generate and test variants
    REPAIR    = "repair"     # self-repair and rollback


class RiskLevel(str, Enum):
    LOW      = "low"       # cosmetic / formatting
    MEDIUM   = "medium"    # logic changes, new helpers
    HIGH     = "high"      # architectural / cross-module
    CRITICAL = "critical"  # security or data-touching code


# ---------------------------------------------------------------------------
# Rule violations
# ---------------------------------------------------------------------------

class RuleViolation(Exception):
    """Raised when an evolution action breaches a policy."""

    def __init__(self, rule: str, detail: str) -> None:
        super().__init__(f"[{rule}] {detail}")
        self.rule   = rule
        self.detail = detail


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class FilePolicy:
    """Per-file or per-glob policy override."""
    pattern: str                               # glob or regex pattern
    allowed_permissions: Set[EvolutionPermission] = field(default_factory=set)
    max_risk: RiskLevel = RiskLevel.MEDIUM
    immutable: bool = False                    # if True, no changes ever


@dataclass
class EvolutionPolicy:
    """
    Top-level policy governing all auto-evolution behaviour.

    Safe defaults allow analysis and suggestions only; all mutations and
    deletions are off unless explicitly enabled.
    """
    # Permissions granted globally
    granted_permissions: Set[EvolutionPermission] = field(
        default_factory=lambda: {EvolutionPermission.ANALYSE, EvolutionPermission.SUGGEST}
    )

    # Files that can never be touched
    immutable_paths: Set[str] = field(default_factory=lambda: {
        "core/security_manager.py",
        "core/core_init.py",
        "core/__init__.py",
        ".env",
        "requirements.txt",
        "runtime.txt",
        "Procfile",
        "railway.toml",
        "render.yaml",
    })

    # Glob patterns of paths allowed for evolution
    allowed_path_patterns: List[str] = field(default_factory=lambda: [
        "auto_evolution/*.py",
        "web_intelligence/*.py",
        "profit_engine/*.py",
        "multi_ia/*.py",
        "modules/*.py",
    ])

    # Hard limit on how many files may be mutated per cycle
    max_files_per_cycle: int = 5

    # Hard limit on patch size (lines changed) per file
    max_patch_lines: int = 100

    # Maximum risk level permitted without human approval
    auto_approve_max_risk: RiskLevel = RiskLevel.LOW

    # How many evolution cycles may run per hour
    max_cycles_per_hour: int = 6

    # Per-file overrides
    file_policies: List[FilePolicy] = field(default_factory=list)

    # If True, always create a backup before patching
    require_backup: bool = True

    # If True, run a syntax check before accepting any patch
    require_syntax_check: bool = True

    # If True, dry-run mode — patches are computed but never written
    dry_run: bool = False


# ---------------------------------------------------------------------------
# Rules engine
# ---------------------------------------------------------------------------

class EvolutionRules:
    """
    Evaluates proposed evolution actions against the active EvolutionPolicy.

    All public check methods raise RuleViolation on failure and return None
    on success, so callers can call them as guards without inspecting returns.
    """

    def __init__(self, policy: Optional[EvolutionPolicy] = None) -> None:
        self._policy = policy or EvolutionPolicy()

    # ------------------------------------------------------------------
    # Public checks
    # ------------------------------------------------------------------

    def check_permission(self, permission: EvolutionPermission) -> None:
        """Raise RuleViolation if the permission is not granted."""
        if permission not in self._policy.granted_permissions:
            raise RuleViolation(
                "PERMISSION_DENIED",
                f"Permission '{permission.value}' is not granted by the active policy.",
            )

    def check_path(self, path: str) -> None:
        """Raise RuleViolation if the path is immutable or not allowed."""
        norm = Path(path).as_posix()

        # Immutable exact paths
        for immutable in self._policy.immutable_paths:
            if norm == Path(immutable).as_posix() or norm.endswith("/" + immutable):
                raise RuleViolation("IMMUTABLE_PATH", f"'{norm}' is marked immutable and cannot be modified.")

        # Per-file policy overrides
        for fp in self._policy.file_policies:
            if self._match_pattern(norm, fp.pattern) and fp.immutable:
                raise RuleViolation("FILE_POLICY_IMMUTABLE", f"'{norm}' is immutable by file policy.")

        # Must match at least one allowed pattern
        if self._policy.allowed_path_patterns:
            if not any(self._match_pattern(norm, p) for p in self._policy.allowed_path_patterns):
                raise RuleViolation(
                    "PATH_NOT_ALLOWED",
                    f"'{norm}' does not match any allowed path pattern.",
                )

    def check_risk(self, risk: RiskLevel, path: str = "") -> None:
        """Raise RuleViolation if the risk exceeds the auto-approve threshold."""
        order = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]

        # Check per-file override first
        for fp in self._policy.file_policies:
            if path and self._match_pattern(Path(path).as_posix(), fp.pattern):
                ceiling = fp.max_risk
                if order.index(risk) > order.index(ceiling):
                    raise RuleViolation(
                        "RISK_EXCEEDS_FILE_POLICY",
                        f"Risk '{risk.value}' exceeds per-file ceiling '{ceiling.value}' for '{path}'.",
                    )
                return

        ceiling = self._policy.auto_approve_max_risk
        if order.index(risk) > order.index(ceiling):
            raise RuleViolation(
                "RISK_TOO_HIGH",
                f"Risk '{risk.value}' exceeds auto-approve ceiling '{ceiling.value}'. Human approval required.",
            )

    def check_patch_size(self, lines_changed: int) -> None:
        if lines_changed > self._policy.max_patch_lines:
            raise RuleViolation(
                "PATCH_TOO_LARGE",
                f"Patch touches {lines_changed} lines; limit is {self._policy.max_patch_lines}.",
            )

    def check_cycle_quota(self, cycles_this_hour: int) -> None:
        if cycles_this_hour >= self._policy.max_cycles_per_hour:
            raise RuleViolation(
                "CYCLE_QUOTA_EXCEEDED",
                f"Already ran {cycles_this_hour} cycles this hour (limit: {self._policy.max_cycles_per_hour}).",
            )

    def check_files_per_cycle(self, file_count: int) -> None:
        if file_count > self._policy.max_files_per_cycle:
            raise RuleViolation(
                "TOO_MANY_FILES",
                f"Cycle targets {file_count} files; limit per cycle is {self._policy.max_files_per_cycle}.",
            )

    def is_dry_run(self) -> bool:
        return self._policy.dry_run

    def requires_backup(self) -> bool:
        return self._policy.require_backup

    def requires_syntax_check(self) -> bool:
        return self._policy.require_syntax_check

    # ------------------------------------------------------------------
    # Policy management
    # ------------------------------------------------------------------

    def update_policy(self, policy: EvolutionPolicy) -> None:
        self._policy = policy

    def grant(self, permission: EvolutionPermission) -> None:
        self._policy.granted_permissions.add(permission)

    def revoke(self, permission: EvolutionPermission) -> None:
        self._policy.granted_permissions.discard(permission)

    def add_immutable(self, path: str) -> None:
        self._policy.immutable_paths.add(path)

    def snapshot(self) -> Dict:
        p = self._policy
        return {
            "granted_permissions": [perm.value for perm in p.granted_permissions],
            "immutable_paths": sorted(p.immutable_paths),
            "max_files_per_cycle": p.max_files_per_cycle,
            "max_patch_lines": p.max_patch_lines,
            "auto_approve_max_risk": p.auto_approve_max_risk.value,
            "max_cycles_per_hour": p.max_cycles_per_hour,
            "dry_run": p.dry_run,
            "require_backup": p.require_backup,
            "require_syntax_check": p.require_syntax_check,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _match_pattern(path: str, pattern: str) -> bool:
        """Match a path against a glob-style or regex pattern."""
        # Convert glob wildcards to regex
        regex = re.escape(pattern).replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
        return bool(re.fullmatch(regex, path))
