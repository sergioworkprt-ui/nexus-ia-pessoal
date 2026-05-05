"""
NEXUS Runtime package.

Unified operational layer that integrates all NEXUS modules into a
scheduled, event-driven, stateful runtime system.

Modes:
    - SIMULATION: dry-run, no live IO, safe for testing
    - LIVE: full operation with real module instances

Quick start (simulation):
    from nexus_runtime import NexusRuntime

    runtime = NexusRuntime.simulation()
    runtime.start()

    # Run a pipeline manually
    result = runtime.run_pipeline("consensus")
    print(result.status, result.duration_ms)

    # Check status
    print(runtime.status())

    runtime.stop()

Quick start (live, with NexusCore):
    from core import get_core
    from nexus_runtime import NexusRuntime, RuntimeConfig

    config = RuntimeConfig.live()
    runtime = NexusRuntime.from_core(get_core(), config=config)
    runtime.start()

Event bus:
    from nexus_runtime import EventType

    def on_pattern(event):
        print("Pattern:", event.data)

    runtime.bus.subscribe(on_pattern, event_type=EventType.PATTERN_DETECTED)

Scheduler:
    runtime.scheduler.schedule("my_task", my_fn, interval_seconds=60)
    runtime.scheduler.schedule_once("boot_check", check_fn, delay_seconds=0)
"""

# Config
from .runtime_config import (
    RuntimeConfig,
    RuntimeMode,
    PipelineMode,
    IntelligenceConfig,
    FinancialConfig,
    EvolutionConfig,
    ConsensusConfig,
    ReportingConfig,
    SchedulerConfig,
    StateConfig,
    IBKRConfig,
)

# Events
from .events import Event, EventBus, EventType

# Scheduler
from .scheduler import Scheduler, ScheduledTask, TaskResult, TaskStatus

# State
from .state_manager import RuntimeState, StateManager, Checkpoint

# Integration
from .integration import NexusIntegration, ModuleHandles

# Pipelines
from .pipelines import (
    BasePipeline,
    IntelligencePipeline,
    FinancialPipeline,
    EvolutionPipeline,
    ConsensusPipeline,
    ReportingPipeline,
    PipelineRunResult,
    PipelineStatus,
)

# Signal Engine
from .signal_engine import SignalEngine, SignalResult, EntryEvaluation, ExitEvaluation, RiskMetrics

# Evolution Engine
from .evolution_engine import (
    EvolutionEngine,
    PerformanceReport,
    SignalLearning,
    Proposal,
    ApplyResult,
    RollbackResult,
)

# IBKR Integration
from .ibkr_integration import IBKRIntegration, OrderResult, Position
from .capital_manager import CapitalManager, CapitalState
from .risk_manager import RiskManager, RiskState
from .ibkr_client_portal import IBKRClientPortal, CPGAuthError, CPGRequestError

# Runtime
from .runtime import NexusRuntime

__all__ = [
    # Config
    "RuntimeConfig", "RuntimeMode", "PipelineMode",
    "IntelligenceConfig", "FinancialConfig", "EvolutionConfig",
    "ConsensusConfig", "ReportingConfig", "SchedulerConfig", "StateConfig",
    "IBKRConfig",
    # Events
    "Event", "EventBus", "EventType",
    # Scheduler
    "Scheduler", "ScheduledTask", "TaskResult", "TaskStatus",
    # State
    "RuntimeState", "StateManager", "Checkpoint",
    # Integration
    "NexusIntegration", "ModuleHandles",
    # Pipelines
    "BasePipeline",
    "IntelligencePipeline", "FinancialPipeline", "EvolutionPipeline",
    "ConsensusPipeline", "ReportingPipeline",
    "PipelineRunResult", "PipelineStatus",
    # Signal Engine
    "SignalEngine", "SignalResult", "EntryEvaluation", "ExitEvaluation", "RiskMetrics",
    # Evolution Engine
    "EvolutionEngine", "PerformanceReport", "SignalLearning",
    "Proposal", "ApplyResult", "RollbackResult",
    # IBKR Integration
    "IBKRIntegration", "OrderResult", "Position",
    "CapitalManager", "CapitalState",
    "RiskManager", "RiskState",
    "IBKRClientPortal", "CPGAuthError", "CPGRequestError",
    # Runtime
    "NexusRuntime",
]
