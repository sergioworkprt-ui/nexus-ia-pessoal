"""
NEXUS Command Layer — Natural-Language Command Parser
Converts free-form text into a structured ParsedIntent without requiring
exact keyword-command syntax.

Grammar (approximate):
    <verb> [<target>] [<name>] [<value>] [<modifiers>...]

Examples of accepted input:
    "run pipeline intelligence"
    "run intelligence"
    "show status"
    "generate report financial"
    "set max_drawdown to 0.15"
    "increase sentiment threshold by 10%"
    "disable evolution"
    "stop scheduler"
    "check audit chain"
    "show last 20 history entries"
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .command_registry import (
    CommandRegistry, CommandDef,
    VERBS, TARGETS, PIPELINE_NAMES, MODULE_NAMES,
)


# ---------------------------------------------------------------------------
# Output types
# ---------------------------------------------------------------------------

@dataclass
class ParsedIntent:
    """Structured result of parsing a natural-language command."""
    raw:     str
    verb:    str
    target:  str
    params:  Dict[str, Any]         = field(default_factory=dict)
    matched: Optional[CommandDef]   = None
    confidence: float               = 1.0   # 0–1; <0.6 means uncertain parse
    warnings: List[str]             = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.verb and self.target and self.matched)

    def __str__(self) -> str:
        return f"{self.verb} {self.target}  params={self.params}"


@dataclass
class ParseError:
    raw:     str
    reason:  str
    suggestions: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

# Verb synonyms → canonical verb
_VERB_SYNONYMS: Dict[str, str] = {
    # run
    "execute": "run", "trigger": "run", "launch": "run", "fire": "run",
    # show
    "display": "show", "print": "show", "get": "show", "view": "show",
    "fetch": "show", "what": "show", "whats": "show",
    # generate
    "create": "generate", "build": "generate", "export": "generate",
    "produce": "generate", "make": "generate",
    # start
    "activate": "start", "turn on": "start", "boot": "start",
    # stop
    "deactivate": "stop", "halt": "stop", "kill": "stop",
    "shutdown": "stop", "shut": "stop",
    # enable
    "switch on": "enable", "turn on": "enable", "activate": "enable",
    # disable
    "switch off": "disable", "turn off": "disable", "deactivate": "disable",
    # increase
    "raise": "increase", "up": "increase", "higher": "increase",
    "boost": "increase", "bump": "increase",
    # decrease
    "lower": "decrease", "reduce": "decrease", "drop": "decrease",
    "down": "decrease", "cut": "decrease",
    # set
    "change": "set", "update": "set", "assign": "set", "configure": "set",
    "adjust": "set", "modify": "set",
    # pause
    "freeze": "pause", "hold": "pause", "suspend": "pause",
    # resume
    "unpause": "resume", "continue": "resume", "restore": "resume",
    # reset
    "clear": "reset", "reinit": "reset", "restart": "reset",
    # list
    "ls": "list", "all": "list",
    # check
    "verify": "check", "validate": "check", "inspect": "check",
    "test": "check", "examine": "check",
}

# Target synonyms → canonical target
_TARGET_SYNONYMS: Dict[str, str] = {
    # pipeline
    "pipelines": "pipeline",
    "pipe": "pipeline",
    # report
    "reports": "report",
    # risk
    "risks": "risk",
    "drawdown": "limit",
    "exposure": "risk",
    # module
    "modules": "module",
    "component": "module",
    "subsystem": "module",
    # audit
    "audit chain": "audit",
    "chain": "audit",
    "log": "audit",
    "logs": "audit",
    # state
    "checkpoint": "state",
    "counters": "state",
    # evolution
    "auto evolution": "evolution",
    "auto-evolution": "evolution",
    "auto_evolution": "evolution",
    # intelligence
    "intel": "intelligence",
    "market intelligence": "intelligence",
    # consensus
    "vote": "consensus",
    "agreement": "consensus",
    # financial
    "finance": "financial",
    "portfolio": "financial",
    # limit
    "limits": "limit",
    "threshold": "limit",
    "thresholds": "limit",
    "parameter": "limit",
    "param": "limit",
    # status
    "health": "status",
    "overview": "status",
    "info": "status",
    # history
    "runs": "history",
    "executions": "history",
    "recent": "history",
    # scheduler
    "schedule": "scheduler",
    "scheduling": "scheduler",
    # reporting
    "reporting": "reporting",
}

# Known limit aliases → canonical config attribute names
_LIMIT_ALIASES: Dict[str, str] = {
    "max_drawdown":          "max_drawdown_alert",
    "drawdown":              "max_drawdown_alert",
    "drawdown_alert":        "max_drawdown_alert",
    "sharpe":                "sharpe_alert",
    "sharpe_ratio":          "sharpe_alert",
    "sentiment":             "limit",
    "sentiment_threshold":   "limit",
    "max_urls":              "max_urls",
    "urls":                  "max_urls",
    "patches":               "max_patches_per_cycle",
    "max_patches":           "max_patches_per_cycle",
    "n_agents":              "n_agents",
    "agents":                "n_agents",
    "agreement":             "agreement_alert",
    "agreement_alert":       "agreement_alert",
    "interval":              "interval_seconds",
    # canonical names as self-references (so the exact attr name also works)
    "max_drawdown_alert":    "max_drawdown_alert",
    "sharpe_alert":          "sharpe_alert",
    "max_patches_per_cycle": "max_patches_per_cycle",
}

# Words that are noise and carry no semantic value in command parsing
_NOISE: set = {
    "please", "now", "immediately", "quickly", "the", "a", "an",
    "for", "on", "to", "by", "with", "in", "of", "and", "or",
    "me", "us", "all", "every", "entire", "last", "latest",
    "current", "active", "running", "new", "my", "its", "this",
    "nexus", "system",
}


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class CommandParser:
    """
    Converts natural-language text into a ParsedIntent.

    Strategy:
    1. Tokenise and lowercase the input.
    2. Identify the first recognisable verb (with synonym expansion).
    3. Identify the first recognisable target after the verb.
    4. Extract numeric values, percentages, and named parameters.
    5. Look up the best-matching CommandDef in the registry.
    6. Return ParsedIntent with confidence score.
    """

    def __init__(self, registry: CommandRegistry) -> None:
        self._registry = registry

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def parse(self, text: str) -> Tuple[Optional[ParsedIntent], Optional[ParseError]]:
        """
        Parse a natural-language command string.

        Returns (ParsedIntent, None) on success or (None, ParseError) on failure.
        """
        if not text or not text.strip():
            return None, ParseError(text, "Empty input.")

        raw    = text.strip()
        tokens = self._tokenise(raw)
        if not tokens:
            return None, ParseError(raw, "No recognisable tokens.")

        verb    = self._extract_verb(tokens)
        if not verb:
            suggestions = self._suggest_verbs(raw)
            return None, ParseError(
                raw,
                f"Could not identify a command verb in: '{raw}'",
                suggestions,
            )

        target, target_idx = self._extract_target(tokens, verb)
        if not target:
            # Fall back: some targets are also pipeline/module names
            pipeline = self._find_pipeline_name(tokens)
            if pipeline and verb == "run":
                target = pipeline
                target_idx = tokens.index(pipeline) if pipeline in tokens else len(tokens)
            else:
                suggestions = [f"{verb} {t}" for t in sorted(TARGETS)[:6]]
                return None, ParseError(
                    raw,
                    f"Could not identify a target for verb '{verb}'.",
                    suggestions,
                )

        params = self._extract_params(tokens, verb, target, target_idx)
        matched = self._match_command(verb, target, params)
        confidence = self._score_confidence(verb, target, params, matched)

        intent = ParsedIntent(
            raw=raw,
            verb=verb,
            target=target,
            params=params,
            matched=matched,
            confidence=confidence,
        )

        if confidence < 0.6:
            intent.warnings.append(
                f"Low confidence parse ({confidence:.0%}). "
                "Verify the command before executing."
            )

        return intent, None

    # ------------------------------------------------------------------
    # Tokenisation
    # ------------------------------------------------------------------

    def _tokenise(self, text: str) -> List[str]:
        """Lowercase, strip punctuation (keep % and .), split on whitespace."""
        text = text.lower()
        text = re.sub(r"[^\w\s%.,-]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return [t for t in text.split() if t not in _NOISE]

    # ------------------------------------------------------------------
    # Verb extraction
    # ------------------------------------------------------------------

    def _extract_verb(self, tokens: List[str]) -> Optional[str]:
        for tok in tokens[:3]:            # verb is almost always in first 3 words
            if tok in VERBS:
                return tok
            canon = _VERB_SYNONYMS.get(tok)
            if canon:
                return canon
        # two-word verb check
        for i in range(min(len(tokens) - 1, 3)):
            two = f"{tokens[i]} {tokens[i+1]}"
            canon = _VERB_SYNONYMS.get(two)
            if canon:
                return canon
        return None

    # ------------------------------------------------------------------
    # Target extraction
    # ------------------------------------------------------------------

    def _extract_target(
        self, tokens: List[str], verb: str
    ) -> Tuple[Optional[str], int]:
        """
        Returns (canonical_target, index_in_tokens_after_target).
        Scans tokens after the verb token.
        """
        verb_idx = self._verb_index(tokens, verb)
        scan = tokens[verb_idx + 1:]

        for i, tok in enumerate(scan):
            # Direct match
            if tok in TARGETS:
                return tok, verb_idx + 1 + i + 1

            # Synonym match
            canon = _TARGET_SYNONYMS.get(tok)
            if canon:
                return canon, verb_idx + 1 + i + 1

            # Pipeline name used as target shorthand: "run intelligence"
            if tok in PIPELINE_NAMES and verb in ("run", "start", "stop", "enable", "disable", "pause", "resume"):
                return tok, verb_idx + 1 + i + 1

            # Module name used as target shorthand
            if tok in MODULE_NAMES and verb in ("enable", "disable", "show", "start", "stop"):
                return "module", verb_idx + 1 + i + 1

            # Limit alias used directly as target: "set max_drawdown 0.12"
            if verb in ("set", "increase", "decrease") and tok in _LIMIT_ALIASES:
                return "limit", verb_idx + 1 + i

            # Two-token target: "audit chain", "auto evolution"
            if i < len(scan) - 1:
                two = f"{tok} {scan[i+1]}"
                canon = _TARGET_SYNONYMS.get(two)
                if canon:
                    return canon, verb_idx + 1 + i + 2

        return None, len(tokens)

    def _verb_index(self, tokens: List[str], verb: str) -> int:
        for i, tok in enumerate(tokens[:4]):
            if tok == verb or _VERB_SYNONYMS.get(tok) == verb:
                return i
        return 0

    def _find_pipeline_name(self, tokens: List[str]) -> Optional[str]:
        for tok in tokens:
            if tok in PIPELINE_NAMES:
                return tok
        return None

    # ------------------------------------------------------------------
    # Parameter extraction
    # ------------------------------------------------------------------

    def _extract_params(
        self,
        tokens: List[str],
        verb: str,
        target: str,
        after_idx: int,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        remaining = tokens[after_idx:]

        # ── pipeline name ────────────────────────────────────────────────
        if target in ("pipeline", "report", *PIPELINE_NAMES):
            for tok in remaining:
                if tok in PIPELINE_NAMES:
                    params["pipeline"] = tok
                    params.setdefault("name", tok)
                    break
        # if target IS a pipeline name, record it directly
        if target in PIPELINE_NAMES:
            params["name"] = target

        # ── module name ──────────────────────────────────────────────────
        if target == "module":
            for tok in remaining:
                if tok in MODULE_NAMES:
                    params["name"] = tok
                    break

        # ── limit name ───────────────────────────────────────────────────
        if target in ("limit", "risk") or verb in ("increase", "decrease", "set"):
            for tok in remaining:
                canon = _LIMIT_ALIASES.get(tok)
                if canon:
                    params["name"] = canon
                    break
                # multi-word limit alias (e.g. "max drawdown")
            for i in range(len(remaining) - 1):
                two = f"{remaining[i]}_{remaining[i+1]}"
                canon = _LIMIT_ALIASES.get(two)
                if canon:
                    params["name"] = canon
                    break

        # ── numeric value / percentage ───────────────────────────────────
        percent_pattern = re.compile(r"(\d+(?:\.\d+)?)%")
        number_pattern  = re.compile(r"^-?\d+(?:\.\d+)?$")

        for tok in remaining:
            m = percent_pattern.fullmatch(tok)
            if m:
                raw_pct = float(m.group(1))
                # store as fraction for consistent usage (e.g. 10% → 0.10)
                params["percent"] = raw_pct / 100.0
                params["amount"]  = raw_pct / 100.0
                break
            if number_pattern.fullmatch(tok):
                val = float(tok) if "." in tok else int(tok)
                # Heuristic: if it looks like a ratio (0–1) and target is a limit,
                # treat as direct value; otherwise treat as integer count
                if target in ("limit", "risk") or verb in ("set", "increase", "decrease"):
                    params.setdefault("value", val)
                    params.setdefault("amount", val)
                else:
                    params.setdefault("limit", val)
                break

        # ── export path ──────────────────────────────────────────────────
        for tok in remaining:
            if "/" in tok or tok.endswith(".json"):
                params["export"] = tok
                break

        return params

    # ------------------------------------------------------------------
    # Command matching
    # ------------------------------------------------------------------

    def _match_command(
        self, verb: str, target: str, params: Dict[str, Any]
    ) -> Optional[CommandDef]:
        """Find the best-matching CommandDef from the registry."""
        defn = self._registry.get(verb, target)
        if defn:
            return defn

        # If target is a pipeline name, fall back to verb:pipeline
        if target in PIPELINE_NAMES:
            defn = self._registry.get(verb, "pipeline")
            if defn:
                return defn

        # If target is a module name, fall back to verb:module
        if target in MODULE_NAMES:
            defn = self._registry.get(verb, "module")
            if defn:
                return defn

        # risk used as target for mutating verbs → fall back to limit
        if target == "risk" and verb in ("set", "increase", "decrease"):
            defn = self._registry.get(verb, "limit")
            if defn:
                return defn

        return None

    # ------------------------------------------------------------------
    # Confidence scoring
    # ------------------------------------------------------------------

    def _score_confidence(
        self,
        verb: str,
        target: str,
        params: Dict[str, Any],
        matched: Optional[CommandDef],
    ) -> float:
        score = 1.0

        if not matched:
            score -= 0.4

        # Penalise if required params are missing
        if matched:
            for p in matched.params:
                if p.required and p.name not in params:
                    score -= 0.2

        # Penalise if verb was derived from a synonym (less certain)
        if verb not in VERBS:
            score -= 0.1

        return max(0.0, min(1.0, score))

    # ------------------------------------------------------------------
    # Suggestions
    # ------------------------------------------------------------------

    def _suggest_verbs(self, raw: str) -> List[str]:
        return [f"{v} <target>" for v in sorted(VERBS)[:6]]
