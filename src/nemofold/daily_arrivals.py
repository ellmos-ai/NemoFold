"""Report what newly arrived in a folder since the last snapshot.

Name, size, modification time and a short readable content for every new file,
plus the account that owns it where the platform can answer that question. On
Windows the standard library cannot, and this module says so per file instead
of leaving the column suspiciously blank - a report that looks complete while
one column silently means nothing is worse than one that admits the gap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

MAX_SUMMARY_SENTENCES = 3
MAX_SUMMARY_CHARS = 320
MAX_ARRIVALS = 500
SENTENCE_SPLIT = re.compile(r"(?<![0-9])(?<=[.!?])\s+")

OWNER_RESOLVED = "resolved"
OWNER_UNSUPPORTED = "unavailable_on_platform"
OWNER_DENIED = "permission_denied"
OWNER_UNKNOWN = "unknown"

OWNER_NOTES = {
    OWNER_RESOLVED: "Owner read from the file system.",
    OWNER_UNSUPPORTED: (
        "This platform's standard library cannot name a file owner. NemoFold does not "
        "shell out to another program to find one, so the field stays empty."
    ),
    OWNER_DENIED: "The file system refused to name the owner of this file.",
    OWNER_UNKNOWN: "The owner could not be read for this file.",
}


@dataclass(frozen=True, slots=True)
class Arrival:
    source_id: str
    display_name: str
    size_bytes: int
    modified: str
    summary: str
    owner: str | None
    owner_status: str


@dataclass(frozen=True, slots=True)
class ArrivalsReport:
    arrivals: tuple[Arrival, ...]
    owner_status: str
    total_sources: int

    @property
    def count(self) -> int:
        return len(self.arrivals)


def resolve_owner(path: Path) -> tuple[str | None, str]:
    """Name the owning account, or say precisely why it cannot be named."""
    try:
        # typeshed marks Path.owner as unavailable on Windows, which is exactly
        # the case this function exists to report at runtime rather than avoid.
        return path.owner(), OWNER_RESOLVED  # type: ignore[misc]
    except NotImplementedError:
        # Windows: pathlib needs the pwd module, which does not exist there.
        return None, OWNER_UNSUPPORTED
    except PermissionError:
        return None, OWNER_DENIED
    except (OSError, KeyError, ValueError):
        return None, OWNER_UNKNOWN


def _summary(text: str, max_sentences: int) -> str:
    collapsed = " ".join(text.split())
    if not collapsed:
        return ""
    sentences = [item.strip() for item in SENTENCE_SPLIT.split(collapsed) if item.strip()]
    return " ".join(sentences[:max_sentences])[:MAX_SUMMARY_CHARS]


def build_arrivals(
    records: tuple[tuple[str, str, str], ...],
    texts: dict[str, str],
    new_source_ids: tuple[str, ...],
    *,
    max_sentences: int = MAX_SUMMARY_SENTENCES,
) -> ArrivalsReport:
    """Describe each newly seen source; records are (source_id, display_name, path)."""
    wanted = set(new_source_ids)
    arrivals: list[Arrival] = []
    statuses: set[str] = set()
    for source_id, display_name, path_value in records:
        if source_id not in wanted:
            continue
        path = Path(path_value)
        try:
            stat = path.stat()
            size = stat.st_size
            modified = datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(
                timespec="seconds"
            )
        except OSError:
            size = 0
            modified = ""
        owner, status = resolve_owner(path)
        statuses.add(status)
        arrivals.append(
            Arrival(
                source_id=source_id,
                display_name=display_name,
                size_bytes=size,
                modified=modified,
                summary=_summary(texts.get(source_id, ""), max_sentences),
                owner=owner,
                owner_status=status,
            )
        )
        if len(arrivals) >= MAX_ARRIVALS:
            break
    overall = (
        OWNER_RESOLVED
        if statuses == {OWNER_RESOLVED}
        else (statuses - {OWNER_RESOLVED}).pop()
        if statuses - {OWNER_RESOLVED}
        else OWNER_UNKNOWN
    )
    return ArrivalsReport(
        arrivals=tuple(arrivals),
        owner_status=overall if arrivals else OWNER_UNKNOWN,
        total_sources=len(records),
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
