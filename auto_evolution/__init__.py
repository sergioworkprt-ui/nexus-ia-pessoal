"""
NEXUS Auto-Evolution package.

Provides autonomous code analysis, improvement, self-repair, and A/B variant
testing for the NEXUS system.

Quick start:
    from auto_evolution import AutoEvolution

    ae = AutoEvolution()
    ae.start()
    report = ae.run_cycle(["modules/reporter.py"])
    suggestions = ae.suggest("modules/reporter.py")
"""

from .evolution_rules import (
    EvolutionPolicy,
    EvolutionPermission,
    EvolutionRules,
    FilePolicy,
    RiskLevel,
    RuleViolation,
)
from .evolution_engine import (
    CodeIssue,
    EvolutionCycleReport,
    EvolutionEngine,
    Patch,
)
from .self_repair import (
    FileSnapshot,
    RepairResult,
    SelfRepair,
)
from .optimizer import (
    OptimisationReport,
    Optimizer,
    Suggestion,
)
from .mutation_manager import (
    ABTest,
    MutationManager,
    Variant,
)
from .auto_evolution import AutoEvolution, AutoEvolutionConfig

__all__ = [
    # Rules
    "EvolutionPolicy",
    "EvolutionPermission",
    "EvolutionRules",
    "FilePolicy",
    "RiskLevel",
    "RuleViolation",
    # Engine
    "CodeIssue",
    "EvolutionCycleReport",
    "EvolutionEngine",
    "Patch",
    # Repair
    "FileSnapshot",
    "RepairResult",
    "SelfRepair",
    # Optimizer
    "OptimisationReport",
    "Optimizer",
    "Suggestion",
    # Mutation
    "ABTest",
    "MutationManager",
    "Variant",
    # Facade
    "AutoEvolution",
    "AutoEvolutionConfig",
]
