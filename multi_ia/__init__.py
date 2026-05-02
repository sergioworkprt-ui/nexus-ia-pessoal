"""
NEXUS Multi-IA package.

Orchestrates multiple AI agents (mock interfaces; swap for real API clients).
Provides routing, consensus, contradiction detection, and security escalation.

Quick start:
    from multi_ia import MultiIA

    ia = MultiIA()
    ia.start()

    # Single best agent
    response = ia.ask("Analyse the current market trend")

    # Parallel + consensus
    result = ia.ask_all("Should we invest in tech?", n_agents=3)
    print(result.consensus_result.agreement_score)

    # Voting
    vote = ia.vote("Is the current strategy profitable?")
    print(vote.final_content, vote.agreement_score)

    # Custom pipeline
    from multi_ia import PipelineStep
    steps = [
        PipelineStep("research",  lambda ctx: "Research the topic: AI in finance"),
        PipelineStep("summarise", lambda ctx: f"Summarise this: {ctx.get('research','')}",
                     store_as="summary"),
    ]
    result = ia.collaborate(steps)

    # With NexusCore
    from core import get_core
    ia = MultiIA.from_core(get_core())
    ia.start()
"""

# Agent primitives
from .agent import (
    AgentCapability,
    AgentProvider,
    AgentRequest,
    AgentResponse,
    AgentStatus,
    BaseAgent,
    MockClaudeAgent,
    MockCopilotAgent,
    MockGPTAgent,
    MockLocalAgent,
)

# Registry
from .registry import AgentRecord, AgentRegistry, agent_from_config

# Router
from .router import Router, RoutingDecision, RoutingRule, RoutingStrategy

# Consensus
from .consensus import (
    ConsensusEngine,
    ConsensusMethod,
    ConsensusResult,
    Contradiction,
    ContradictionSeverity,
    ContradictionType,
)

# Orchestrator
from .orchestrator import (
    Orchestrator,
    PipelineResult,
    PipelineStep,
    StepResult,
    StepStatus,
)

# Facade
from .multi_ia import MultiIA, MultiIAConfig

__all__ = [
    # Agent
    "AgentCapability", "AgentProvider", "AgentRequest", "AgentResponse",
    "AgentStatus", "BaseAgent",
    "MockClaudeAgent", "MockCopilotAgent", "MockGPTAgent", "MockLocalAgent",
    # Registry
    "AgentRecord", "AgentRegistry", "agent_from_config",
    # Router
    "Router", "RoutingDecision", "RoutingRule", "RoutingStrategy",
    # Consensus
    "ConsensusEngine", "ConsensusMethod", "ConsensusResult",
    "Contradiction", "ContradictionSeverity", "ContradictionType",
    # Orchestrator
    "Orchestrator", "PipelineResult", "PipelineStep", "StepResult", "StepStatus",
    # Facade
    "MultiIA", "MultiIAConfig",
]
