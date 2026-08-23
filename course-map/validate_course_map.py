"""Validate TutAIR GCSE course-map data."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


OBJECTIVE_ID_PATTERN = re.compile(
    r"^LO-[A-Z0-9]+-[A-Z0-9-]+-[A-Z0-9]+-[A-Z0-9]+-[A-Z0-9-]+-[A-Z0-9-]+-\d{3}$"
)
RESOURCE_KEYS = {"resources", "learning_resources", "flashcards", "questions", "notes"}


def load_course_map(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def iter_learning_objectives(course_map: dict[str, Any]) -> list[dict[str, Any]]:
    objectives: list[dict[str, Any]] = []
    for subject in course_map.get("subjects", []):
        for qualification in subject.get("qualifications", []):
            for board in qualification.get("exam_boards", []):
                for tier in board.get("tiers", []):
                    for paper in tier.get("papers", []):
                        for topic in paper.get("topics", []):
                            for subtopic in topic.get("subtopics", []):
                                objectives.extend(subtopic.get("learning_objectives", []))
    return objectives


def collect_nested_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, nested in value.items():
            keys.add(key)
            keys.update(collect_nested_keys(nested))
    elif isinstance(value, list):
        for item in value:
            keys.update(collect_nested_keys(item))
    return keys


def validate_course_map(course_map: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for required in ["schema_version", "map_id", "status", "subjects"]:
        if required not in course_map:
            errors.append(f"Missing required top-level field: {required}")

    objectives = iter_learning_objectives(course_map)
    if not objectives:
        errors.append("Course map must contain at least one learning objective.")

    objective_ids = [objective.get("objective_id", "") for objective in objectives]
    duplicate_ids = sorted({objective_id for objective_id in objective_ids if objective_ids.count(objective_id) > 1})
    for duplicate_id in duplicate_ids:
        errors.append(f"Duplicate learning objective ID: {duplicate_id}")

    for objective in objectives:
        objective_id = objective.get("objective_id", "")
        if not OBJECTIVE_ID_PATTERN.match(objective_id):
            errors.append(f"Invalid learning objective ID: {objective_id}")
        if not objective.get("statement"):
            errors.append(f"Missing statement for objective: {objective_id}")
        if not objective.get("source_ref"):
            errors.append(f"Missing source_ref for objective: {objective_id}")
        source_trace = objective.get("source_trace", {})
        for required_trace in ["source_id", "section", "page", "trace_status"]:
            if not source_trace.get(required_trace):
                errors.append(f"Missing source_trace.{required_trace} for objective: {objective_id}")

    all_keys = collect_nested_keys(course_map)
    forbidden_keys = sorted(RESOURCE_KEYS.intersection(all_keys))
    for key in forbidden_keys:
        errors.append(f"Course map must not embed learning resource key: {key}")

    known_objective_ids = set(objective_ids)
    for example in course_map.get("capture_link_examples", []):
        for linked_id in example.get("linked_learning_objectives", []):
            if linked_id not in known_objective_ids:
                errors.append(f"Capture example links to unknown objective ID: {linked_id}")

    return errors


def main() -> int:
    data_path = Path(__file__).parent / "data" / "course-map-mvp.json"
    errors = validate_course_map(load_course_map(data_path))
    if errors:
        for error in errors:
            print(error)
        return 1
    print(f"Course map valid: {data_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
