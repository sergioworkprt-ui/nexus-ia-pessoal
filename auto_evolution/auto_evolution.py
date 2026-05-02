"""
NEXUS Auto-Evolution — Facade
Top-level orchestrator that wires all sub-modules and integrates with NexusCore.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .evolution_rules import EvolutionPermission, EvolutionPolicy, EvolutionRules, RiskLevel
from .evolution_engine import EvolutionCycleReport, EvolutionEngine
from .self_repair import RepairResult, SelfRepair
from .optimizer import OptimisationReport, Optimizer, Suggestion
from .mutation_manager import ABTest, MutationManager, Variant


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class AutoEvolutionConfig:
    base_dir: str       = "."
    data_dir: str       = "data"
    dry_run: bool       = True    # safe default: never write without explicit opt-in
    auto_approve_risk: RiskLevel = RiskLevel.LOW
    max_files_per_cycle: int = 5
    max_cycles_per_hour: int = 6
    require_backup: bool = True
    require_syntax_check: bool = True
    # Paths that are always allowed for evolution (overrides global defaults)
    allowed_paths: List[str] = field(default_factory=lambda: [
        "auto_evolution/*.py",
        "web_intelligence/*.py",
        "profit_engine/*.py",
        "multi_ia/*.py",
        "modules/*.py",
    ])


# ---------------------------------------------------------------------------
# AutoEvolution facade
# ---------------------------------------------------------------------------

class AutoEvolution:
    """
    Single entry-point for the NEXUS auto-evolution subsystem.

    Integrates with NexusCore when available (passes logger, memory, task queue)
    but also works fully standalone.

    Example (standalone):
        ae = AutoEvolution(AutoEvolutionConfig(dry_run=False))
        ae.start()
        report = ae.run_cycle(["modules/reporter.py"])
        print(report.summary())

    Example (with core):
        from core import get_core
        core = get_core()
        core.start()
        ae = AutoEvolution.from_core(core)
        ae.start()
    """

    def __init__(self, config: Optional[AutoEvolutionConfig] = None) -> None:
        self._config = config or AutoEvolutionConfig()
        self._running = False

        policy = EvolutionPolicy(
            granted_permissions={EvolutionPermission.ANALYSE, EvolutionPermission.SUGGEST},
            auto_approve_max_risk=self._config.auto_approve_risk,
            max_files_per_cycle=self._config.max_files_per_cycle,
            max_cycles_per_hour=self._config.max_cycles_per_hour,
            require_backup=self._config.require_backup,
            require_syntax_check=self._config.require_syntax_check,
            dry_run=self._config.dry_run,
            allowed_path_patterns=self._config.allowed_paths,
        )

        # Enable patch/repair/mutate only if not dry_run
        if not self._config.dry_run:
            policy.granted_permissions.update({
                EvolutionPermission.PATCH,
                EvolutionPermission.REPAIR,
                EvolutionPermission.MUTATE,
            })

        self._rules   = EvolutionRules(policy)
        self._engine  = EvolutionEngine(rules=self._rules, base_dir=self._config.base_dir)
        self._repair  = SelfRepair(
            rules=self._rules,
            snapshot_dir=f"{self._config.data_dir}/snapshots",
            base_dir=self._config.base_dir,
        )
        self._optimizer = Optimizer(rules=self._rules, base_dir=self._config.base_dir)
        self._mutations = MutationManager(
            rules=self._rules,
            base_dir=self._config.base_dir,
            storage_dir=f"{self._config.data_dir}/mutations",
        )

        # Optional core integration hooks
        self._log_fn = None   # set by from_core()
        self._mem    = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @classmethod
    def from_core(cls, core: Any, config: Optional[AutoEvolutionConfig] = None) -> "AutoEvolution":
        """
        Create an AutoEvolution instance wired to a running NexusCore.
        Injects the core logger and memory manager.
        """
        instance = cls(config)
        instance._log_fn = core.logger
        instance._mem    = core.memory
        return instance

    def start(self) -> None:
        self._running = True
        self._info("auto_evolution", "AutoEvolution subsystem started.",
                   dry_run=self._config.dry_run)

    def stop(self) -> None:
        self._running = False
        self._info("auto_evolution", "AutoEvolution subsystem stopped.")

    # ------------------------------------------------------------------
    # Primary operations
    # ------------------------------------------------------------------

    def run_cycle(self, target_files: List[str]) -> EvolutionCycleReport:
        """Run a full evolution cycle: analyse → patch → (optionally apply)."""
        report = self._engine.run_cycle(target_files)
        self._info("auto_evolution", f"Cycle {report.cycle_id} complete.",
                   files=report.files_analysed,
                   issues=len(report.issues_found),
                   patches=len(report.patches_generated),
                   applied=report.patches_applied)
        if self._mem:
            self._mem.remember(f"evolution_cycle_{report.cycle_id}", report.summary(), permanent=True)
        return report

    def suggest(self, file_path: str) -> List[Suggestion]:
        """Return optimisation suggestions for a single file."""
        return self._optimizer.analyse_file(file_path)

    def suggest_many(self, file_paths: List[str]) -> OptimisationReport:
        """Return a full optimisation report across multiple files."""
        return self._optimizer.analyse_files(file_paths)

    def repair(self, file_path: str) -> RepairResult:
        """Attempt to auto-repair a single file (syntax check + rollback)."""
        self._repair.snapshot(file_path, label="pre-repair")
        result = self._repair.auto_repair(file_path)
        self._info("auto_evolution", f"Repair '{file_path}': {result.action}.",
                   success=result.success, detail=result.detail)
        return result

    def snapshot(self, file_path: str, label: str = "manual") -> Dict[str, Any]:
        """Manually capture a snapshot of a file for future rollback."""
        snap = self._repair.snapshot(file_path, label=label)
        return snap.to_dict()

    def create_variant(
        self,
        file_path: str,
        mutation: str = "identity",
        name: Optional[str] = None,
    ) -> Variant:
        return self._mutations.create_variant(file_path, mutation=mutation, name=name)

    def start_ab_test(
        self,
        name: str,
        file_path: str,
        control_id: str,
        challenger_ids: List[str],
        metric: str,
        higher_is_better: bool = True,
    ) -> ABTest:
        return self._mutations.start_ab_test(
            name=name, file_path=file_path, control_id=control_id,
            challenger_ids=challenger_ids, metric=metric,
            higher_is_better=higher_is_better,
        )

    def conclude_ab_test(self, test_id: str) -> Optional[str]:
        return self._mutations.conclude_test(test_id)

    # ------------------------------------------------------------------
    # Status and introspection
    # ------------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "dry_run": self._config.dry_run,
            "engine": self._engine.stats(),
            "repair": self._repair.stats(),
            "rules": self._rules.snapshot(),
        }

    def history(self, limit: int = 10) -> List[Dict[str, Any]]:
        return self._engine.history(limit=limit)

    def policy(self) -> Dict[str, Any]:
        return self._rules.snapshot()

    def enable_writes(self) -> None:
        """Switch from dry-run to live mode (grants patch/repair/mutate)."""
        self._config.dry_run = False
        self._rules.grant(EvolutionPermission.PATCH)
        self._rules.grant(EvolutionPermission.REPAIR)
        self._rules.grant(EvolutionPermission.MUTATE)

    def disable_writes(self) -> None:
        """Revert to safe dry-run mode."""
        self._config.dry_run = True
        self._rules.revoke(EvolutionPermission.PATCH)
        self._rules.revoke(EvolutionPermission.REPAIR)
        self._rules.revoke(EvolutionPermission.MUTATE)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _info(self, module: str, message: str, **kwargs: Any) -> None:
        if self._log_fn:
            self._log_fn.info(module, message, **kwargs)
