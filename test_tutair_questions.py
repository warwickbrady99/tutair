import json
import unittest

from tutair_questions import (
    MintingResult,
    MintedQuestion,
    QuestionOption,
    apply_verdicts,
    build_questions_markdown,
    extract_json,
    is_structurally_valid,
    mint_questions,
    normalise_timestamp,
    parse_reviewer_reply,
    parse_writer_reply,
    upsert_questions_section,
)


def make_question(question_id="q1", answer_id="B", options=None, **overrides):
    defaults = dict(
        id=question_id,
        stem="What does mitosis produce?",
        options=options
        or [
            QuestionOption("A", "Gametes"),
            QuestionOption("B", "Body cells"),
            QuestionOption("C", "Enzymes"),
            QuestionOption("D", "Hormones"),
        ],
        answer_id=answer_id,
        explanation="Mitosis makes new body cells.",
        source_timestamp="04:12",
    )
    defaults.update(overrides)
    return MintedQuestion(**defaults)


WRITER_REPLY = json.dumps(
    {
        "questions": [
            {
                "id": "q1",
                "stem": "What does mitosis produce?",
                "options": [
                    {"id": "A", "text": "Gametes"},
                    {"id": "B", "text": "Body cells"},
                    {"id": "C", "text": "Enzymes"},
                    {"id": "D", "text": "Hormones"},
                ],
                "answer_id": "B",
                "explanation": "Mitosis makes new body cells.",
                "source_timestamp": "04:12",
            },
            {
                "id": "q2",
                "stem": "What does meiosis produce?",
                "options": [
                    {"id": "A", "text": "Gametes"},
                    {"id": "B", "text": "Body cells"},
                    {"id": "C", "text": "Enzymes"},
                    {"id": "D", "text": "Hormones"},
                ],
                "answer_id": "A",
                "explanation": "Meiosis makes gametes.",
                "source_timestamp": "06:30",
            },
        ]
    }
)

REVIEWER_REPLY = json.dumps(
    {
        "verdicts": [
            {"id": "q1", "verdict": "approve", "objection": ""},
            {"id": "q2", "verdict": "reject", "objection": "Both A and B are defensible here."},
        ]
    }
)


class TestParsing(unittest.TestCase):
    def test_json_is_extracted_from_a_code_fence(self):
        payload = extract_json('Here you go:\n```json\n{"questions": []}\n```\nHope that helps.')
        self.assertEqual(payload, {"questions": []})

    def test_json_is_extracted_from_surrounding_prose(self):
        payload = extract_json('Sure. {"verdicts": [{"id": "q1"}]} Let me know.')
        self.assertEqual(payload["verdicts"][0]["id"], "q1")

    def test_a_reply_with_no_json_is_rejected(self):
        with self.assertRaises(ValueError):
            extract_json("I could not do that.")

    def test_writer_reply_becomes_questions(self):
        questions = parse_writer_reply(WRITER_REPLY)
        self.assertEqual(len(questions), 2)
        self.assertEqual(questions[0].answer_id, "B")
        self.assertEqual(questions[0].source_timestamp, "04:12")


class TestStructuralChecks(unittest.TestCase):
    def test_a_well_formed_question_passes(self):
        self.assertTrue(is_structurally_valid(make_question()))

    def test_a_question_whose_key_is_not_an_option_fails(self):
        self.assertFalse(is_structurally_valid(make_question(answer_id="E")))

    def test_a_question_without_four_options_fails(self):
        options = [QuestionOption("A", "Gametes"), QuestionOption("B", "Body cells")]
        self.assertFalse(is_structurally_valid(make_question(options=options)))

    def test_questions_that_fail_structure_never_reach_the_reviewer(self):
        reply = json.dumps(
            {"questions": [{"id": "q1", "stem": "Broken", "options": [], "answer_id": "A"}]}
        )
        self.assertEqual(parse_writer_reply(reply), [])


class TestReview(unittest.TestCase):
    def test_only_approved_questions_are_marked_approved(self):
        questions = parse_writer_reply(WRITER_REPLY)
        verdicts = parse_reviewer_reply(REVIEWER_REPLY)

        reviewed = apply_verdicts(questions, verdicts)

        self.assertEqual(reviewed[0].status, "approved")
        self.assertEqual(reviewed[1].status, "draft")
        self.assertIn("defensible", reviewed[1].objection)

    def test_a_question_the_reviewer_ignored_is_not_approved(self):
        reviewed = apply_verdicts([make_question()], {})

        self.assertEqual(reviewed[0].status, "draft")
        self.assertIn("did not return a verdict", reviewed[0].objection)

    def test_minting_uses_two_separate_calls(self):
        prompts = []

        def runner(prompt):
            prompts.append(prompt)
            return WRITER_REPLY if len(prompts) == 1 else REVIEWER_REPLY

        result = mint_questions("[04:12] Mitosis makes body cells.", "Science", "Cell division", runner=runner)

        self.assertEqual(len(prompts), 2)
        self.assertIn("You write GCSE multiple-choice questions", prompts[0])
        self.assertIn("try to prove each question unfair", prompts[1])
        self.assertEqual(len(result.approved), 1)
        self.assertEqual(len(result.drafts), 1)

    def test_no_reviewer_call_when_the_writer_returns_nothing(self):
        calls = []

        def runner(prompt):
            calls.append(prompt)
            return json.dumps({"questions": []})

        result = mint_questions("transcript", "Science", "Cell division", runner=runner)

        self.assertEqual(len(calls), 1)
        self.assertEqual(result.questions, [])


class TestOutput(unittest.TestCase):
    def test_only_approved_questions_are_shown_for_revision(self):
        reviewed = apply_verdicts(parse_writer_reply(WRITER_REPLY), parse_reviewer_reply(REVIEWER_REPLY))
        result = MintingResult(subject="Science", topic="Cell division", source_url="", questions=reviewed)

        markdown = build_questions_markdown(result)

        self.assertIn("What does mitosis produce?", markdown)
        self.assertNotIn("What does meiosis produce?", markdown)
        self.assertIn("1 of 2", markdown)

    def test_rerunning_replaces_the_section_rather_than_stacking_it(self):
        note = "# Note\n\n## Multiple Choice Questions\n\nold\n\n## Flashcards\n\nkeep me\n"

        updated = upsert_questions_section(note, "## Multiple Choice Questions\n\nnew\n")

        self.assertEqual(updated.count("## Multiple Choice Questions"), 1)
        self.assertIn("new", updated)
        self.assertNotIn("old", updated)
        self.assertIn("keep me", updated)

    def test_the_section_is_appended_when_the_note_has_none(self):
        updated = upsert_questions_section("# Note\n\n## Flashcards\n\nkeep me\n", "## Multiple Choice Questions\n\nnew\n")

        self.assertIn("## Flashcards", updated)
        self.assertIn("## Multiple Choice Questions", updated)


class TestTimestampNormalising(unittest.TestCase):
    """The cited marker is printed to a console during a run, so keep it plain ASCII."""

    def test_an_en_dash_range_becomes_a_hyphen(self):
        self.assertEqual(normalise_timestamp("00:46–00:52"), "00:46-00:52")

    def test_an_em_dash_and_a_minus_sign_are_folded_too(self):
        self.assertEqual(normalise_timestamp("01:00—01:10"), "01:00-01:10")
        self.assertEqual(normalise_timestamp("01:00−01:10"), "01:00-01:10")

    def test_brackets_and_padding_are_stripped(self):
        self.assertEqual(normalise_timestamp("  [04:12] "), "04:12")

    def test_a_plain_timestamp_is_left_alone(self):
        self.assertEqual(normalise_timestamp("04:12"), "04:12")

    def test_a_missing_timestamp_is_empty_rather_than_none(self):
        self.assertEqual(normalise_timestamp(None), "")

    def test_a_normalised_timestamp_survives_into_the_question(self):
        reply = json.dumps({"questions": [{
            "id": "q1", "stem": "What does mitosis produce?",
            "options": [{"id": "A", "text": "Gametes"}, {"id": "B", "text": "Body cells"},
                        {"id": "C", "text": "Enzymes"}, {"id": "D", "text": "Hormones"}],
            "answer_id": "B", "explanation": "Mitosis makes body cells.",
            "source_timestamp": "00:46–00:52"}]})

        question = parse_writer_reply(reply)[0]

        self.assertEqual(question.source_timestamp, "00:46-00:52")
        self.assertTrue(question.source_timestamp.isascii())


if __name__ == "__main__":
    unittest.main()
