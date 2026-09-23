import shutil
import tempfile
import unittest
from pathlib import Path

from tutair_spec import (
    SpecContext,
    SpecObjective,
    find_objectives,
    find_spec_pdf,
    format_objectives,
    keywords,
    topic_excerpt,
)


COURSE_MAP = {
    "subjects": [
        {
            "subject_id": "SCI",
            "name": "Science",
            "qualifications": [
                {
                    "name": "GCSE Combined Science: Trilogy",
                    "exam_boards": [
                        {
                            "board_id": "AQA",
                            "specification_code": "8464",
                            "tiers": [
                                {
                                    "papers": [
                                        {
                                            "topics": [
                                                {
                                                    "name": "Cell biology",
                                                    "spec_reference": "AQA 8464 section 4.1",
                                                    "subtopics": [
                                                        {
                                                            "name": "Cell structure",
                                                            "spec_reference": "AQA 8464 section 4.1.1.1",
                                                            "learning_objectives": [
                                                                {
                                                                    "objective_id": "LO-CELL-001",
                                                                    "statement": "Explain how sub-cellular structures relate to their functions.",
                                                                }
                                                            ],
                                                        },
                                                        {
                                                            "name": "Microscopy",
                                                            "spec_reference": "AQA 8464 section 4.1.1.5",
                                                            "learning_objectives": [
                                                                {
                                                                    "objective_id": "LO-MICRO-001",
                                                                    "statement": "Use magnification, image size and real size in calculations.",
                                                                }
                                                            ],
                                                        },
                                                    ],
                                                }
                                            ]
                                        }
                                    ]
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    ]
}


class TestObjectiveLookup(unittest.TestCase):
    def test_a_topic_selects_only_its_own_objectives(self):
        found = find_objectives(COURSE_MAP, subject="Science", topic="Microscopy")

        self.assertEqual([objective.objective_id for objective in found], ["LO-MICRO-001"])
        self.assertEqual(found[0].specification_code, "8464")
        self.assertEqual(found[0].spec_reference, "AQA 8464 section 4.1.1.5")

    def test_an_unmapped_topic_returns_nothing_rather_than_guessing(self):
        self.assertEqual(find_objectives(COURSE_MAP, subject="Science", topic="Ecology"), [])

    def test_a_wrong_board_filters_everything_out(self):
        self.assertEqual(find_objectives(COURSE_MAP, subject="Science", board_id="OCR"), [])

    def test_no_topic_filter_returns_the_whole_subject(self):
        self.assertEqual(len(find_objectives(COURSE_MAP, subject="Science")), 2)

    def test_common_words_do_not_match_everything(self):
        self.assertNotIn("the", keywords("The GCSE revision topic"))
        self.assertIn("photosynthesis", keywords("Photosynthesis"))


class TestSpecExcerpt(unittest.TestCase):
    def test_only_paragraphs_mentioning_the_topic_are_kept(self):
        text = (
            "Students should describe photosynthesis as an endothermic reaction.\n\n"
            "Students should recall the structure of the atom.\n\n"
            "The rate of photosynthesis is affected by light intensity."
        )

        excerpt = topic_excerpt(text, "Photosynthesis")

        self.assertIn("endothermic", excerpt)
        self.assertIn("light intensity", excerpt)
        self.assertNotIn("structure of the atom", excerpt)

    def test_an_excerpt_respects_its_character_budget(self):
        text = "\n\n".join(["Photosynthesis paragraph number %d." % n for n in range(200)])

        excerpt = topic_excerpt(text, "Photosynthesis", max_chars=120)

        self.assertLessEqual(len(excerpt), 160)

    def test_no_topic_gives_no_excerpt(self):
        self.assertEqual(topic_excerpt("Some specification text.", ""), "")


class TestSpecPdfLookup(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="tutair-spec-"))
        for name in [
            "AQA-GCSE-CombinedScience-Trilogy-8464.pdf",
            "OCR-GCSE-ComputerScience-J277.pdf",
        ]:
            (self.dir / name).write_bytes(b"%PDF-1.4\n")

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_the_specification_code_wins(self):
        found = find_spec_pdf("J277", "Science", self.dir)
        self.assertEqual(found.name, "OCR-GCSE-ComputerScience-J277.pdf")

    def test_the_subject_is_used_when_there_is_no_code(self):
        found = find_spec_pdf("", "Computer Science", self.dir)
        self.assertEqual(found.name, "OCR-GCSE-ComputerScience-J277.pdf")

    def test_an_unknown_subject_finds_nothing(self):
        self.assertIsNone(find_spec_pdf("", "Latin", self.dir))

    def test_a_missing_folder_finds_nothing(self):
        self.assertIsNone(find_spec_pdf("8464", "Science", self.dir / "nope"))


class TestSpecContext(unittest.TestCase):
    def test_a_context_with_nothing_in_it_is_not_grounded(self):
        context = SpecContext(subject="Science", topic="Ecology")

        self.assertFalse(context.grounded)
        self.assertEqual(context.provenance(), "none")

    def test_provenance_names_both_sources(self):
        context = SpecContext(
            subject="Science",
            topic="Cell structure",
            objectives=[SpecObjective("LO-1", "statement", "Cell biology", "Cell structure", "4.1", "AQA", "8464")],
            excerpt="spec wording",
            excerpt_source="AQA-8464.pdf",
        )

        self.assertTrue(context.grounded)
        self.assertIn("course map (1 objectives)", context.provenance())
        self.assertIn("AQA-8464.pdf", context.provenance())

    def test_objectives_format_with_their_spec_reference(self):
        formatted = format_objectives(
            [SpecObjective("LO-1", "Explain cells.", "Cell biology", "Cell structure", "AQA 8464 4.1.1.1", "AQA", "8464")]
        )

        self.assertIn("LO-1", formatted)
        self.assertIn("[AQA 8464 4.1.1.1]", formatted)
        self.assertIn("Explain cells.", formatted)


if __name__ == "__main__":
    unittest.main()
