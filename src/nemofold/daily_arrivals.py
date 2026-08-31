"""Report what newly arrived in a folder; the delta is a shared primitive.

snapshot_delta in primitives compares against the named baseline, reads size,
time and a short content, and resolves the owning account where the platform
can. This module keeps the report and the task template the user installs.

Removing the local copy also removed a real divergence: this module carried an
earlier sentence splitter that suppressed a split after any digit, so a year
ending a sentence ("2026.") was treated as an ordinal. Both callers now use the
one splitter that separates the two by digit count.
"""

from __future__ import annotations

from dataclasses import dataclass

from .primitives import (
    OWNER_DENIED,
    OWNER_RESOLVED,
    OWNER_UNKNOWN,
    OWNER_UNSUPPORTED,
    DeltaEntry,
    resolve_owner,
    snapshot_delta,
)

MAX_SUMMARY_SENTENCES = 3

OWNER_NOTES = {
    OWNER_RESOLVED: "Owner read from the file system.",
    OWNER_UNSUPPORTED: (
        "This platform's standard library cannot name a file owner. NemoFold does not "
        "shell out to another program to find one, so the field stays empty."
    ),
    OWNER_DENIED: "The file system refused to name the owner of this file.",
    OWNER_UNKNOWN: "The owner could not be read for this file.",
}

# The workflow keeps its own word for a delta entry.
Arrival = DeltaEntry

__all__ = [
    "OWNER_DENIED",
    "OWNER_NOTES",
    "OWNER_RESOLVED",
    "OWNER_UNKNOWN",
    "OWNER_UNSUPPORTED",
    "Arrival",
    "ArrivalsReport",
    "arrivals_markdown",
    "build_arrivals",
    "resolve_owner",
    "windows_task_xml",
]


@dataclass(frozen=True, slots=True)
class ArrivalsReport:
    arrivals: tuple[DeltaEntry, ...]
    owner_status: str
    total_sources: int

    @property
    def count(self) -> int:
        return len(self.arrivals)


def build_arrivals(
    records: tuple[tuple[str, str, str], ...],
    texts: dict[str, str],
    new_source_ids: tuple[str, ...],
    *,
    max_sentences: int = MAX_SUMMARY_SENTENCES,
) -> ArrivalsReport:
    """Adapt the shared snapshot delta to the workflow's report contract."""
    entries, owner_status = snapshot_delta(
        records, texts, new_source_ids, max_sentences=max_sentences
    )
    return ArrivalsReport(
        arrivals=entries, owner_status=owner_status, total_sources=len(records)
    )


def arrivals_markdown(report: ArrivalsReport, *, title: str, output_dir: str) -> str:
    lines = [f"# {title}", ""]
    if not report.arrivals:
        lines.extend(
            [
                "No new file arrived since the last snapshot of this folder.",
                "",
                f"{report.total_sources} sources were compared.",
            ]
        )
    else:
        lines.append(
            f"{report.count} new file(s) since the last snapshot, "
            f"out of {report.total_sources} sources."
        )
        lines.append("")
        for arrival in report.arrivals:
            lines.append(f"## {arrival.display_name}")
            lines.append("")
            lines.append(f"- source: {arrival.source_id}")
            lines.append(f"- size: {arrival.size_bytes} bytes")
            lines.append(f"- modified: {arrival.modified or 'unreadable'}")
            owner = arrival.owner if arrival.owner else f"— ({arrival.owner_status})"
            lines.append(f"- owner: {owner}")
            lines.append(f"- content: {arrival.summary or '— (no readable text)'}")
            lines.append("")
    lines.extend(
        [
            "## Owner field",
            "",
            OWNER_NOTES.get(report.owner_status, OWNER_NOTES[OWNER_UNKNOWN]),
            "",
            "## Standing routine",
            "",
            "NemoFold has no scheduler and does not start itself. To receive this report "
            "regularly, either run this job again whenever you want a fresh comparison, or "
            "install the exported task in your own operating system. NemoFold writes the "
            "task file; installing, inspecting and removing it stays with you.",
            "",
            f"The snapshot this comparison used lives in {output_dir}.",
        ]
    )
    return "\n".join(lines) + "\n"


def windows_task_xml(*, job_path: str, run_at: str = "07:00:00") -> str:
    """A Task Scheduler definition the user installs; NemoFold registers nothing."""
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<!-- NemoFold writes this file. It is NOT installed: register it yourself with
     schtasks /Create /TN NemoFoldDailyArrivals /XML <this file>
     and remove it with schtasks /Delete /TN NemoFoldDailyArrivals. -->
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>NemoFold daily arrivals report (installed by the user)</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2026-01-01T{run_at}</StartBoundary>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <StartWhenAvailable>true</StartWhenAvailable>
  </Settings>
  <Actions>
    <Exec>
      <Command>python</Command>
      <Arguments>-m nemofold run --job "{job_path}"</Arguments>
    </Exec>
  </Actions>
</Task>
"""
