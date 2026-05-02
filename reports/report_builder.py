"""
NEXUS Reports — Report Builder
Base primitives for constructing structured, serializable reports.
Provides sections, tables, metric blocks, and a BaseReport skeleton
that all domain-specific report classes extend.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Union


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class ReportStatus(str, Enum):
    DRAFT     = "draft"
    FINAL     = "final"
    ARCHIVED  = "archived"


class ReportSeverity(str, Enum):
    INFO     = "info"
    WARNING  = "warning"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# Primitive building blocks
# ---------------------------------------------------------------------------

@dataclass
class Metric:
    """A single named metric with an optional unit and severity tag."""
    name:     str
    value:    Union[int, float, str, bool, None]
    unit:     str = ""
    severity: ReportSeverity = ReportSeverity.INFO
    note:     str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name":     self.name,
            "value":    self.value,
            "unit":     self.unit,
            "severity": self.severity.value,
            "note":     self.note,
        }


@dataclass
class MetricBlock:
    """A named group of related Metric objects."""
    title:   str
    metrics: List[Metric] = field(default_factory=list)

    def add(self, name: str, value: Any, unit: str = "",
            severity: ReportSeverity = ReportSeverity.INFO, note: str = "") -> None:
        self.metrics.append(Metric(name=name, value=value, unit=unit,
                                   severity=severity, note=note))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title":   self.title,
            "metrics": [m.to_dict() for m in self.metrics],
        }


@dataclass
class TableRow:
    cells: List[Any]

    def to_dict(self) -> List[Any]:
        return list(self.cells)


@dataclass
class ReportTable:
    """A labelled table with headers and typed rows."""
    title:   str
    headers: List[str]
    rows:    List[TableRow] = field(default_factory=list)

    def add_row(self, *cells: Any) -> None:
        self.rows.append(TableRow(list(cells)))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title":   self.title,
            "headers": self.headers,
            "rows":    [r.to_dict() for r in self.rows],
        }


@dataclass
class ReportSection:
    """
    A logical section of a report.
    Contains a title, optional free-text body, metric blocks, and tables.
    """
    title:         str
    body:          str = ""
    metric_blocks: List[MetricBlock] = field(default_factory=list)
    tables:        List[ReportTable] = field(default_factory=list)
    subsections:   List["ReportSection"] = field(default_factory=list)
    severity:      ReportSeverity = ReportSeverity.INFO

    def add_metric_block(self, block: MetricBlock) -> None:
        self.metric_blocks.append(block)

    def add_table(self, table: ReportTable) -> None:
        self.tables.append(table)

    def add_subsection(self, section: "ReportSection") -> None:
        self.subsections.append(section)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title":         self.title,
            "severity":      self.severity.value,
            "body":          self.body,
            "metric_blocks": [b.to_dict() for b in self.metric_blocks],
            "tables":        [t.to_dict() for t in self.tables],
            "subsections":   [s.to_dict() for s in self.subsections],
        }


# ---------------------------------------------------------------------------
# Base report
# ---------------------------------------------------------------------------

class BaseReport:
    """
    Abstract base for all NEXUS reports.

    Subclasses implement build() to populate self.sections and call
    self._add_section() / self._add_metric_block() helpers.

    Every report is serializable to dict and JSON.
    """

    report_type: str = "base"

    def __init__(
        self,
        title:       str,
        description: str = "",
        tags:        Optional[List[str]] = None,
    ) -> None:
        self.report_id:   str = str(uuid.uuid4())[:12]
        self.title:       str = title
        self.description: str = description
        self.tags:        List[str] = tags or []
        self.status:      ReportStatus = ReportStatus.DRAFT
        self.sections:    List[ReportSection] = []
        self.created_at:  str = datetime.now(timezone.utc).isoformat()
        self.finalised_at: Optional[str] = None
        self._meta:       Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Builder helpers
    # ------------------------------------------------------------------

    def _add_section(self, section: ReportSection) -> ReportSection:
        self.sections.append(section)
        return section

    def _new_section(
        self,
        title:    str,
        body:     str = "",
        severity: ReportSeverity = ReportSeverity.INFO,
    ) -> ReportSection:
        s = ReportSection(title=title, body=body, severity=severity)
        self.sections.append(s)
        return s

    def finalise(self) -> "BaseReport":
        self.status = ReportStatus.FINAL
        self.finalised_at = datetime.now(timezone.utc).isoformat()
        return self

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id":    self.report_id,
            "report_type":  self.report_type,
            "title":        self.title,
            "description":  self.description,
            "tags":         self.tags,
            "status":       self.status.value,
            "created_at":   self.created_at,
            "finalised_at": self.finalised_at,
            "meta":         self._meta,
            "sections":     [s.to_dict() for s in self.sections],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self) -> Dict[str, Any]:
        """Lightweight summary without full section detail."""
        severity_counts: Dict[str, int] = {}
        for s in self.sections:
            severity_counts[s.severity.value] = (
                severity_counts.get(s.severity.value, 0) + 1
            )
        return {
            "report_id":   self.report_id,
            "report_type": self.report_type,
            "title":       self.title,
            "status":      self.status.value,
            "sections":    len(self.sections),
            "severities":  severity_counts,
            "created_at":  self.created_at,
        }

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} id={self.report_id!r} "
            f"title={self.title!r} status={self.status.value}>"
        )
