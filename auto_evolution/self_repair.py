"""
NEXUS Auto-Evolution — Self Repair
Automatic error detection, file integrity checks, rollback, and recovery.
"""

from __future__ import annotations

import ast
import hashlib
import json
import shutil
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .evolution_rules import EvolutionPermission, EvolutionRules, RuleViolation


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class FileSnapshot:
    """Point-in-time snapshot of a file's content and checksum."""
    path: str
    checksum: str
    size_bytes: int
    captured_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    label: str = "auto"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "checksum": self.checksum,
            "size_bytes": self.size_bytes,
            "captured_at": self.captured_at,
            "label": self.label,
        }


@dataclass
class RepairResult:
    """Outcome of a single repair attempt."""
    action: str           # "syntax_fix" | "rollback" | "integrity_restored" | "no_action"
    file_path: str
    success: bool
    detail: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "file": self.file_path,
            "success": self.success,
            "detail": self.detail,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Self Repair
# ---------------------------------------------------------------------------

class SelfRepair:
    """
    Monitors Python source files for integrity issues and performs repairs.

    Capabilities:
    - Checksum-based integrity verification (detects unexpected external changes)
    - Python syntax validation
    - Automatic rollback to last good snapshot
    - Snapshot registry persisted to disk for cross-process durability
    - Integration hook for core.logger if available
    """

    def __init__(
        self,
        rules: Optional[EvolutionRules] = None,
        snapshot_dir: str = "data/snapshots",
        base_dir: str = ".",
    ) -> None:
        self._rules       = rules or EvolutionRules()
        self._base        = Path(base_dir)
        self._snap_dir    = Path(snapshot_dir)
        self._snap_dir.mkdir(parents=True, exist_ok=True)
        self._registry_path = self._snap_dir / "registry.json"
        self._registry: Dict[str, List[Dict[str, Any]]] = self._load_registry()
        self._repair_log: List[RepairResult] = []

    # ------------------------------------------------------------------
    # Snapshot management
    # ------------------------------------------------------------------

    def snapshot(self, file_path: str, label: str = "auto") -> FileSnapshot:
        """Capture and persist a snapshot of the given file."""
        path = self._base / file_path
        if not path.exists():
            raise FileNotFoundError(f"Cannot snapshot '{file_path}': file not found.")

        content  = path.read_bytes()
        checksum = hashlib.sha256(content).hexdigest()
        snap     = FileSnapshot(
            path=file_path,
            checksum=checksum,
            size_bytes=len(content),
            label=label,
        )

        # Persist content to snapshot dir
        snap_file = self._snap_dir / f"{self._safe_name(file_path)}_{checksum[:12]}.py"
        snap_file.write_bytes(content)

        # Register metadata
        self._registry.setdefault(file_path, []).append(snap.to_dict())
        self._save_registry()
        return snap

    def restore(self, file_path: str, checksum: Optional[str] = None) -> bool:
        """
        Restore a file to a previous snapshot.
        If checksum is None, restores to the most recent snapshot.
        Raises RuleViolation if repair permission is not granted.
        """
        self._rules.check_permission(EvolutionPermission.REPAIR)
        self._rules.check_path(file_path)

        snaps = self._registry.get(file_path, [])
        if not snaps:
            return False

        target = None
        if checksum:
            target = next((s for s in reversed(snaps) if s["checksum"].startswith(checksum)), None)
        else:
            target = snaps[-1] if snaps else None

        if target is None:
            return False

        snap_file = self._snap_dir / f"{self._safe_name(file_path)}_{target['checksum'][:12]}.py"
        if not snap_file.exists():
            return False

        dest = self._base / file_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(snap_file, dest)
        self._record(RepairResult(action="rollback", file_path=file_path, success=True,
                                   detail=f"Restored to snapshot {target['checksum'][:12]} ({target['captured_at']})."))
        return True

    def list_snapshots(self, file_path: str) -> List[Dict[str, Any]]:
        return list(self._registry.get(file_path, []))

    # ------------------------------------------------------------------
    # Integrity & syntax checks
    # ------------------------------------------------------------------

    def check_integrity(self, file_path: str) -> Tuple[bool, str]:
        """
        Compare the current file checksum against the last registered snapshot.
        Returns (ok, message).
        """
        path = self._base / file_path
        if not path.exists():
            return False, f"File '{file_path}' does not exist."

        current_checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        snaps = self._registry.get(file_path, [])
        if not snaps:
            return True, "No baseline snapshot — integrity assumed OK."

        last = snaps[-1]["checksum"]
        if current_checksum == last:
            return True, "Checksum matches last snapshot."
        return False, f"Checksum mismatch. Expected {last[:12]}, got {current_checksum[:12]}."

    def check_syntax(self, file_path: str) -> Tuple[bool, str]:
        """Return (ok, message) after parsing the file with ast.parse."""
        path = self._base / file_path
        if not path.exists():
            return False, f"File '{file_path}' does not exist."
        try:
            ast.parse(path.read_text(encoding="utf-8"))
            return True, "Syntax OK."
        except SyntaxError as exc:
            return False, f"SyntaxError at line {exc.lineno}: {exc.msg}"

    # ------------------------------------------------------------------
    # Automatic repair
    # ------------------------------------------------------------------

    def auto_repair(self, file_path: str) -> RepairResult:
        """
        Attempt to repair a file automatically:
        1. If syntax is broken → rollback to last good snapshot.
        2. If checksum mismatch (unexpected change) → log; rollback only if
           repair permission is granted and the caller requests it.
        Returns a RepairResult describing the outcome.
        """
        syn_ok, syn_msg = self.check_syntax(file_path)
        if not syn_ok:
            try:
                restored = self.restore(file_path)
                result = RepairResult(
                    action="rollback",
                    file_path=file_path,
                    success=restored,
                    detail=f"Syntax error detected ({syn_msg}). {'Rolled back to last snapshot.' if restored else 'No snapshot available.'}",
                )
            except RuleViolation as exc:
                result = RepairResult(action="rollback", file_path=file_path, success=False, detail=str(exc))
            self._record(result)
            return result

        int_ok, int_msg = self.check_integrity(file_path)
        if not int_ok:
            result = RepairResult(
                action="integrity_restored",
                file_path=file_path,
                success=False,
                detail=f"Integrity warning: {int_msg} — manual review recommended.",
            )
            self._record(result)
            return result

        result = RepairResult(action="no_action", file_path=file_path, success=True, detail="File is healthy.")
        self._record(result)
        return result

    def scan_and_repair(self, file_paths: List[str]) -> List[RepairResult]:
        """Run auto_repair on multiple files and return all results."""
        return [self.auto_repair(fp) for fp in file_paths]

    # ------------------------------------------------------------------
    # Audit log
    # ------------------------------------------------------------------

    def repair_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        return [r.to_dict() for r in self._repair_log[-limit:]]

    def stats(self) -> Dict[str, Any]:
        tracked = len(self._registry)
        total_snaps = sum(len(v) for v in self._registry.values())
        successes = sum(1 for r in self._repair_log if r.success)
        return {
            "tracked_files": tracked,
            "total_snapshots": total_snaps,
            "repairs_attempted": len(self._repair_log),
            "repairs_succeeded": successes,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _record(self, result: RepairResult) -> None:
        self._repair_log.append(result)

    def _load_registry(self) -> Dict[str, List[Dict[str, Any]]]:
        if self._registry_path.exists():
            try:
                return json.loads(self._registry_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError):
                pass
        return {}

    def _save_registry(self) -> None:
        self._registry_path.write_text(
            json.dumps(self._registry, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    @staticmethod
    def _safe_name(path: str) -> str:
        return Path(path).as_posix().replace("/", "_").replace(".", "_")
