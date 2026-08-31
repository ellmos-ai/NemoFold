"""Edit a saved voyage from the chat - as a confirmable diff, never a rewrite.

The desk reads an edit request against one stored voyage and returns the step
list before and after, so a person sees the change and accepts it. Nothing is
written here. A chat that silently rewrote a saved plan would undo the reason
the library exists: that you can trust what you kept.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .wizard import (
    WORKFLOW_ORDER,
    WORKFLOW_TITLES,
    matched_roadmap,
    matched_workflows,
    mentions,
    normalize_request,
    parameters_for,
)

INSERT_KEYWORDS = (
    "füge", "fuege", "ergänze", "ergaenze", "einfügen", "einfuegen", "hinzufügen",
    "hinzufuegen", "add ", "insert", "append",
)
REMOVE_KEYWORDS = (
    "entferne", "lösche", "loesche", "streiche", "remove", "delete", "drop ",
)
REPLACE_KEYWORDS = ("ersetze", "tausche", "replace", "swap")
RENAME_KEYWORDS = ("nenne", "benenne", "umbenennen", "rename")

_BETWEEN = re.compile(
    r"zwischen\s+schritt\s+(\d+)\s+und\s+\d+|between\s+step\s+(\d+)\s+and\s+\d+"
)
_BEFORE = re.compile(r"vor\s+schritt\s+(\d+)|before\s+step\s+(\d+)")
_AFTER = re.compile(r"nach\s+schritt\s+(\d+)|after\s+step\s+(\d+)")
_STEP_REF = re.compile(r"schritt\s+(\d+)|step\s+(\d+)")
_QUOTED = re.compile("[\"'„»]([^\"'“«]{1,120})[\"'“«]")
_START_TERMS = ("am anfang", "at the start", "zuerst", "ganz vorne")


@dataclass(frozen=True, slots=True)
class VoyageEdit:
    request_text: str
    action: str
    applicable: bool
    summary: str
    before: tuple[str, ...]
    after: tuple[str, ...]
    steps_after: tuple[dict[str, Any], ...]
    new_name: str | None = None
    notes: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return self.applicable and (self.before != self.after or self.new_name is not None)


def _first_group(match: re.Match[str] | None) -> int | None:
    if match is None:
        return None
    for value in match.groups():
        if value is not None:
            return int(value)
    return None


def _insert_position(haystack: str, count: int) -> int:
    """Read where the new step goes. Without a position it lands at the end."""
    between = _first_group(_BETWEEN.search(haystack))
    if between is not None:
        return min(max(between, 0), count)
    before = _first_group(_BEFORE.search(haystack))
    if before is not None:
        return min(max(before - 1, 0), count)
    after = _first_group(_AFTER.search(haystack))
    if after is not None:
        return min(max(after, 0), count)
    if any(mentions(haystack, term) for term in _START_TERMS):
        return 0
    return count


def _referenced_step(haystack: str, steps: tuple[dict[str, Any], ...]) -> int | None:
    number = _first_group(_STEP_REF.search(haystack))
    if number is not None and 1 <= number <= len(steps):
        return number - 1
    for index, step in enumerate(steps):
        workflow = str(step.get("workflow", ""))
        if not workflow:
            continue
        if workflow in haystack or mentions(haystack, workflow.replace("_", " ")):
            return index
        title = WORKFLOW_TITLES.get(workflow, "")
        if title and mentions(haystack, title.casefold()):
            return index
    return None


def _proposed_step(workflow: str, request: str, template: dict[str, Any]) -> dict[str, Any]:
    job = dict(template.get("job", {}))
    return {
        "workflow": workflow,
        "job": {
            **job,
            "workflow": workflow,
            "questions": [],
            "privacy_mode": "local_only",
            "action_mode": "dry_run",
            "model_budget_usd": 0,
            "parameters": parameters_for(workflow, request),
        },
        "note": "Proposed by the captain's desk; review before running.",
        "reads_previous_output": False,
    }


def plan_voyage_edit(text: str, voyage: dict[str, Any]) -> VoyageEdit:
    """Propose one edit to a saved voyage. Returns a diff, writes nothing."""
    request = normalize_request(text)
    haystack = request.casefold()
    steps = tuple(voyage.get("steps") or ())
    before = tuple(str(step.get("workflow", "")) for step in steps)
    notes: list[str] = []

    def unchanged(action: str, summary: str) -> VoyageEdit:
        return VoyageEdit(
            request_text=request,
            action=action,
            applicable=False,
            summary=summary,
            before=before,
            after=before,
            steps_after=steps,
            notes=tuple(notes),
        )

    if any(mentions(haystack, keyword) for keyword in RENAME_KEYWORDS):
        quoted = _QUOTED.search(request)
        if quoted is None:
            notes.append(
                'Put the new name in quotes, for example: rename it to "Unfall 2026".'
            )
            return unchanged("rename", "No new name was given.")
        name = quoted.group(1).strip()
        return VoyageEdit(
            request_text=request,
            action="rename",
            applicable=True,
            summary=f'Rename the voyage to "{name}".',
            before=before,
            after=before,
            steps_after=steps,
            new_name=name,
            notes=tuple(notes),
        )

    if any(mentions(haystack, keyword) for keyword in REMOVE_KEYWORDS):
        index = _referenced_step(haystack, steps)
        if index is None:
            notes.append(
                'Name the step to remove, by position ("step 2") or by its workflow.'
            )
            return unchanged("remove", "No step in this voyage matched the request.")
        remaining = steps[:index] + steps[index + 1 :]
        if not remaining:
            notes.append("A voyage needs at least one step, so this one was kept.")
            return unchanged("remove", "Removing the only step would leave an empty voyage.")
        return VoyageEdit(
            request_text=request,
            action="remove",
            applicable=True,
            summary=f"Remove step {index + 1} ({before[index]}).",
            before=before,
            after=tuple(str(item.get("workflow", "")) for item in remaining),
            steps_after=remaining,
            notes=tuple(notes),
        )

    replacing = any(mentions(haystack, keyword) for keyword in REPLACE_KEYWORDS)
    inserting = any(mentions(haystack, keyword) for keyword in INSERT_KEYWORDS)
    if not (replacing or inserting):
        notes.append(
            "Editing understands inserting, removing, replacing and renaming, with a "
            'position such as "between step 2 and 3".'
        )
        return unchanged("none", "This request was not recognised as an edit.")

    matched = sorted(matched_workflows(haystack), key=lambda item: WORKFLOW_ORDER[item])
    # A workflow already in the plan is what the edit refers to, not what is
    # being added, so it must not be mistaken for the new step.
    candidates = [item for item in matched if item not in before] or matched
    if not candidates:
        roadmap = matched_roadmap(haystack)
        if roadmap:
            notes.extend(f"{item.label}: {item.reason}" for item in roadmap)
            return unchanged(
                "insert", "The requested step is a planned service, not an active workflow."
            )
        notes.append(
            "No active workflow matched. Anonymization, for example, is part of every "
            "step's privacy gate rather than a step of its own."
        )
        return unchanged("insert", "No active workflow matched the requested step.")

    workflow = candidates[0]
    addition = _proposed_step(workflow, request, steps[0] if steps else {})
    if replacing:
        index = _referenced_step(haystack, steps)
        if index is None:
            notes.append("Name the step to replace by position or by its workflow.")
            return unchanged("replace", "No step in this voyage matched the request.")
        updated = steps[:index] + (addition,) + steps[index + 1 :]
        summary = f"Replace step {index + 1} ({before[index]}) with {workflow}."
        action = "replace"
    else:
        position = _insert_position(haystack, len(steps))
        updated = steps[:position] + (addition,) + steps[position:]
        summary = f"Insert {workflow} as step {position + 1}."
        action = "insert"

    return VoyageEdit(
        request_text=request,
        action=action,
        applicable=True,
        summary=summary,
        before=before,
        after=tuple(str(item.get("workflow", "")) for item in updated),
        steps_after=updated,
        notes=tuple(notes),
    )


def edit_to_primitive(edit: VoyageEdit) -> dict[str, Any]:
    return {
        "schema": "nemofold.voyage-edit.v1",
        "request_text": edit.request_text,
        "action": edit.action,
        "applicable": edit.applicable,
        "changed": edit.changed,
        "summary": edit.summary,
        "before": list(edit.before),
        "after": list(edit.after),
        "steps_after": [dict(step) for step in edit.steps_after],
        "new_name": edit.new_name,
        "notes": list(edit.notes),
        "applied": False,
    }
