"""
NEXUS Command Layer
Natural-language command interface for the NexusRuntime.

    from nexus_commands import CommandEngine
    engine = CommandEngine(runtime)
    resp = engine.execute("run pipeline intelligence")
    print(resp)
"""

from .command_engine import CommandEngine, CommandResponse
from .command_parser import CommandParser, ParsedIntent, ParseError
from .command_registry import (
    CommandRegistry, CommandDef, ParamSchema,
    VERBS, TARGETS, PIPELINE_NAMES, MODULE_NAMES,
)

__all__ = [
    "CommandEngine",
    "CommandResponse",
    "CommandParser",
    "ParsedIntent",
    "ParseError",
    "CommandRegistry",
    "CommandDef",
    "ParamSchema",
    "VERBS",
    "TARGETS",
    "PIPELINE_NAMES",
    "MODULE_NAMES",
]
