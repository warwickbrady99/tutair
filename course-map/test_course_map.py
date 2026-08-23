"""Focused tests for the TutAIR course-map MVP."""

from __future__ import annotations

import unittest
from pathlib import Path

from validate_course_map import (
    OBJECTIVE_ID_PATTERN,
    iter_learning_objectives,
    load_course_map,
    validate_course_map,
)


DATA_PATH = Path(__file__).parent / "data" / "course-map-mvp.json"


class CourseMapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.course_map = load_course_map(DATA_PATH)

    def test_course_map_validates(self) -> None:
        self.assertEqual([], validate_course_map(self.course_map))

    def test_learning_objective_ids_are_unique(self) -> None:
        objective_ids = [objective["objective_id"] for objective in iter_learning_objectives(self.course_map)]
        self.assertEqual(len(objective_ids), len(set(objective_ids)))

    def test_learning_objective_ids_match_stable_pattern(self) -> None:
        for objective in iter_learning_objectives(self.course_map):
            self.assertRegex(objective["objective_id"], OBJECTIVE_ID_PATTERN)

    def test_learning_objectives_have_traceable_spec_references(self) -> None:
        for objective in iter_learning_objectives(self.course_map):
            self.assertIn("AQA 8464 section", objective["source_ref"])
            self.assertEqual("AQA-8464-SPEC", objective["source_trace"]["source_id"])
            self.assertRegex(objective["source_trace"]["section"], r"^4\.1\.")
            self.assertIsInstance(objective["source_trace"]["page"], int)
            self.assertEqual("verified_against_official_specification", objective["source_trace"]["trace_status"])

    def test_capture_examples_link_to_existing_objectives(self) -> None:
        known_ids = {objective["objective_id"] for objective in iter_learning_objectives(self.course_map)}
        for example in self.course_map["capture_link_examples"]:
            for objective_id in example["linked_learning_objectives"]:
                self.assertIn(objective_id, known_ids)

    def test_topic_declares_partial_mvp_coverage_and_gaps(self) -> None:
        topic = self.course_map["subjects"][0]["qualifications"][0]["exam_boards"][0]["tiers"][0]["papers"][0]["topics"][0]

        self.assertEqual("partial_mvp", topic["coverage_status"])
        self.assertIn("known_gaps", topic)
        self.assertIn("4.1.3 Transport in cells", topic["known_gaps"])

    def test_mvp_contains_aqa_combined_science_biology_slice(self) -> None:
        subject = self.course_map["subjects"][0]
        qualification = subject["qualifications"][0]
        board = qualification["exam_boards"][0]
        paper = board["tiers"][0]["papers"][0]
        topic = paper["topics"][0]

        self.assertEqual("Science", subject["name"])
        self.assertEqual("GCSE Combined Science: Trilogy", qualification["name"])
        self.assertEqual("AQA", board["board_id"])
        self.assertEqual("8464", board["specification_code"])
        self.assertEqual("Biology Paper 1", paper["name"])
        self.assertEqual("Cell biology", topic["name"])


if __name__ == "__main__":
    unittest.main()
