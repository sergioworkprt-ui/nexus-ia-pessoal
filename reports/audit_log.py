"""
NEXUS Reports — Audit Log
Append-only, tamper-resistant audit log using a SHA-256 hash chain.
Each entry embeds the hash of the previous entry, making silent
modification detectable. Entries are serializable to JSON.

Thread-safe. Supports in-memory and file-backed modes.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Iterator, List, Optional


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------

class AuditEventType(str, Enum):
    # System lifecycle
    SYSTEM_START     = "system_start"
    SYSTEM_STOP      = "system_stop"
    MODULE_LOADED    = "module_loaded"
    # Security
    AUTH_SUCCESS     = "auth_success"
    AUTH_FAILURE     = "auth_failure"
    RATE_LIMIT_HIT   = "rate_limit_hit"
    VIOLATION        = "violation"
    ESCALATION       = "escalation"
    ACTOR_BLOCKED    = "actor_blocked"
    # Operations
    TASK_SUBMITTED   = "task_submitted"
    TASK_COMPLETED   = "task_completed"
    TASK_FAILED      = "task_failed"
    # Trading
    ORDER_PLACED     = "order_placed"
    ORDER_REJECTED   = "order_rejected"
    RISK_BREACH      = "risk_breach"
    KILL_SWITCH      = "kill_switch"
    # Evolution
    PATCH_APPLIED    = "patch_applied"
    ROLLBACK         = "rollback"
    MUTATION_STARTED = "mutation_started"
    # Multi-IA
    CONSENSUS_REACHED    = "consensus_reached"
    CONSENSUS_ESCALATED  = "consensus_escalated"
    CONTRADICTION_FOUND  = "contradiction_found"
    # Generic
    INFO             = "info"
    WARNING          = "warning"
    CRITICAL         = "critical"


class AuditSeverity(str, Enum):
    DEBUG    = "debug"
    INFO     = "info"
    WARNING  = "warning"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# Audit entry
# ---------------------------------------------------------------------------

@dataclass
class AuditEntry:
    """A single immutable audit record in the hash chain."""
    entry_id:   str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: AuditEventType = AuditEventType.INFO
    severity:   AuditSeverity  = AuditSeverity.INFO
    actor:      str = ""
    action:     str = ""
    target:     str = ""
    outcome:    str = ""
    detail:     Dict[str, Any] = field(default_factory=dict)
    timestamp:  str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    seq:        int = 0
    prev_hash:  str = "0" * 64   # genesis block starts with zeroes
    entry_hash: str = ""         # computed after creation

    # ------------------------------------------------------------------
    # Hash chain
    # ------------------------------------------------------------------

    def compute_hash(self) -> str:
        """
        Compute SHA-256 over the canonical fields.
        Excludes entry_hash itself to avoid circular dependency.
        """
        payload = json.dumps({
            "entry_id":   self.entry_id,
            "event_type": self.event_type,
            "severity":   self.severity,
            "actor":      self.actor,
            "action":     self.action,
            "target":     self.target,
            "outcome":    self.outcome,
            "detail":     self.detail,
            "timestamp":  self.timestamp,
            "seq":        self.seq,
            "prev_hash":  self.prev_hash,
        }, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()

    def seal(self) -> "AuditEntry":
        """Compute and store the entry's own hash. Call once after creation."""
        self.entry_hash = self.compute_hash()
        return self

    def verify(self) -> bool:
        """Return True if the stored hash matches the computed hash."""
        return self.entry_hash == self.compute_hash()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_id":   self.entry_id,
            "event_type": self.event_type.value,
            "severity":   self.severity.value,
            "actor":      self.actor,
            "action":     self.action,
            "target":     self.target,
            "outcome":    self.outcome,
            "detail":     self.detail,
            "timestamp":  self.timestamp,
            "seq":        self.seq,
            "prev_hash":  self.prev_hash,
            "entry_hash": self.entry_hash,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AuditEntry":
        return cls(
            entry_id=d.get("entry_id",   str(uuid.uuid4())),
            event_type=AuditEventType(d.get("event_type", AuditEventType.INFO)),
            severity=AuditSeverity(d.get("severity",   AuditSeverity.INFO)),
            actor=d.get("actor",    ""),
            action=d.get("action",   ""),
            target=d.get("target",   ""),
            outcome=d.get("outcome",  ""),
            detail=d.get("detail",   {}),
            timestamp=d.get("timestamp", datetime.now(timezone.utc).isoformat()),
            seq=d.get("seq",       0),
            prev_hash=d.get("prev_hash",  "0" * 64),
            entry_hash=d.get("entry_hash", ""),
        )


# ---------------------------------------------------------------------------
# AuditLog
# ---------------------------------------------------------------------------

class AuditLog:
    """
    Append-only tamper-resistant audit log.

    Hash chain: each entry's prev_hash = previous entry's entry_hash.
    Tampering with any entry breaks the chain from that point onwards,
    detectable via verify_chain().

    Thread-safe. Optionally persists to a JSONL file.

    Usage:
        log = AuditLog(file_path="logs/audit_chain.jsonl")
        log.append(AuditEventType.AUTH_FAILURE, actor="user_x",
                   action="login", outcome="bad credentials",
                   severity=AuditSeverity.WARNING)
        ok, errors = log.verify_chain()
    """

    def __init__(
        self,
        file_path:      Optional[str] = None,
        load_existing:  bool = True,
        max_memory:     int  = 10_000,
    ) -> None:
        self._lock:    threading.RLock = threading.RLock()
        self._entries: List[AuditEntry] = []
        self._seq:     int = 0
        self._file:    Optional[str] = file_path
        self._max_mem: int = max_memory

        if file_path and load_existing and os.path.isfile(file_path):
            self._load_from_file(file_path)

    # ------------------------------------------------------------------
    # Append
    # ------------------------------------------------------------------

    def append(
        self,
        event_type: AuditEventType = AuditEventType.INFO,
        actor:      str = "",
        action:     str = "",
        target:     str = "",
        outcome:    str = "",
        severity:   AuditSeverity  = AuditSeverity.INFO,
        detail:     Optional[Dict[str, Any]] = None,
    ) -> AuditEntry:
        """
        Create a new entry, seal it into the chain, and append it.
        Returns the sealed entry.
        """
        with self._lock:
            prev_hash = self._entries[-1].entry_hash if self._entries else "0" * 64
            entry = AuditEntry(
                event_type=event_type,
                severity=severity,
                actor=actor,
                action=action,
                target=target,
                outcome=outcome,
                detail=detail or {},
                seq=self._seq,
                prev_hash=prev_hash,
            ).seal()
            self._seq += 1

            # Keep memory bounded — drop oldest if over limit
            if len(self._entries) >= self._max_mem:
                self._entries.pop(0)
            self._entries.append(entry)

            if self._file:
                self._write_entry(entry)

        return entry

    # ------------------------------------------------------------------
    # Chain verification
    # ------------------------------------------------------------------

    def verify_chain(self) -> tuple[bool, List[str]]:
        """
        Verify the integrity of the entire in-memory chain.
        Returns (all_ok: bool, error_messages: List[str]).
        """
        errors: List[str] = []
        with self._lock:
            entries = list(self._entries)

        prev_hash = "0" * 64
        for i, entry in enumerate(entries):
            # 1. Hash integrity
            if not entry.verify():
                errors.append(
                    f"Entry {i} (seq={entry.seq}): hash mismatch — entry may have been tampered."
                )
            # 2. Chain linkage
            if entry.prev_hash != prev_hash:
                errors.append(
                    f"Entry {i} (seq={entry.seq}): broken chain — "
                    f"expected prev_hash={prev_hash[:16]}…, got {entry.prev_hash[:16]}…"
                )
            prev_hash = entry.entry_hash

        return len(errors) == 0, errors

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def query(
        self,
        event_type: Optional[AuditEventType] = None,
        actor:      Optional[str] = None,
        severity:   Optional[AuditSeverity] = None,
        limit:      int = 100,
    ) -> List[AuditEntry]:
        with self._lock:
            results = list(self._entries)

        if event_type is not None:
            results = [e for e in results if e.event_type == event_type]
        if actor is not None:
            results = [e for e in results if e.actor == actor]
        if severity is not None:
            results = [e for e in results if e.severity == severity]

        return results[-limit:]

    def recent(self, limit: int = 50) -> List[AuditEntry]:
        with self._lock:
            return list(self._entries[-limit:])

    def count(self) -> int:
        with self._lock:
            return len(self._entries)

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            entries = list(self._entries)

        by_type:     Dict[str, int] = {}
        by_severity: Dict[str, int] = {}
        for e in entries:
            by_type[e.event_type.value]   = by_type.get(e.event_type.value,   0) + 1
            by_severity[e.severity.value] = by_severity.get(e.severity.value, 0) + 1

        return {
            "total_entries":   len(entries),
            "by_event_type":   by_type,
            "by_severity":     by_severity,
            "chain_head_hash": entries[-1].entry_hash if entries else "—",
            "chain_seq":       entries[-1].seq         if entries else -1,
        }

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def to_list(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [e.to_dict() for e in self._entries]

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_list(), indent=indent, default=str)

    # ------------------------------------------------------------------
    # File persistence (JSONL — one JSON object per line)
    # ------------------------------------------------------------------

    def _write_entry(self, entry: AuditEntry) -> None:
        """Append a single entry to the JSONL file. Best-effort."""
        try:
            dir_path = os.path.dirname(self._file)  # type: ignore[arg-type]
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)
            with open(self._file, "a", encoding="utf-8") as fh:  # type: ignore[arg-type]
                fh.write(json.dumps(entry.to_dict(), default=str) + "\n")
        except OSError:
            pass

    def _load_from_file(self, path: str) -> None:
        """Load existing JSONL entries into memory (no re-verification)."""
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        entry = AuditEntry.from_dict(d)
                        self._entries.append(entry)
                        self._seq = max(self._seq, entry.seq + 1)
                    except (json.JSONDecodeError, ValueError):
                        pass
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Convenience wrapper: ViolationLog
# ---------------------------------------------------------------------------

class ViolationLog(AuditLog):
    """
    Specialised audit log for rule/security violations.
    Adds a record_violation() shortcut.
    """

    def record_violation(
        self,
        actor:   str,
        code:    str,
        detail:  str = "",
        target:  str = "",
    ) -> AuditEntry:
        return self.append(
            event_type=AuditEventType.VIOLATION,
            severity=AuditSeverity.WARNING,
            actor=actor,
            action="violation",
            target=target,
            outcome=code,
            detail={"code": code, "detail": detail},
        )

    def record_critical(
        self,
        actor:   str,
        action:  str,
        detail:  str = "",
    ) -> AuditEntry:
        return self.append(
            event_type=AuditEventType.CRITICAL,
            severity=AuditSeverity.CRITICAL,
            actor=actor,
            action=action,
            outcome="critical event",
            detail={"detail": detail},
        )
