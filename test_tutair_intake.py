import os
import shutil
import tempfile
import unittest
from unittest import mock
from datetime import date
from pathlib import Path

from tutair_intake import (
    TutairCapture,
    default_inbox_root,
    build_capture_markdown,
    dated_inbox_dir,
    detect_source_type,
    extract_youtube_video_id,
    save_capture,
    save_source_content,
    slugify,
    with_source_content_fields,
)


class TestTutairIntake(unittest.TestCase):
    def test_dated_inbox_dir_uses_year_month(self):
        path = dated_inbox_dir(Path("Team Inbox") / "TutAIR", date(2026, 7, 9))

        self.assertEqual(path, Path("Team Inbox") / "TutAIR" / "2026" / "07")

    def test_slugify_uses_kebab_case(self):
        self.assertEqual(slugify("GCSE Biology: Cell Division!"), "gcse-biology-cell-division")

    def test_youtube_url_detects_source_type(self):
        source_type = detect_source_type("https://www.youtube.com/watch?v=abcdefghijk", None)

        self.assertEqual(source_type, "youtube_url")

    def test_extract_youtube_video_id(self):
        video_id = extract_youtube_video_id("https://youtu.be/abcdefghijk")

        self.assertEqual(video_id, "abcdefghijk")

    def test_markdown_defaults_exam_board_to_unconfirmed(self):
        markdown = build_capture_markdown(
            TutairCapture(
                source_type="pasted_text",
                subject="Science",
                topic="Cell division",
                source_url="",
                learning_content="Cells divide by mitosis.",
                captured_on=date(2026, 7, 9),
            )
        )

        self.assertIn("type: tutair_learning_capture", markdown)
        self.assertIn("exam_board_status: unconfirmed", markdown)
        self.assertIn("exam_board_evidence: none", markdown)
        self.assertIn("source_content_status: needs_source_content", markdown)
        self.assertIn("processing_readiness: blocked_needs_source_content", markdown)
        self.assertIn("## Raw Learning Content", markdown)
        self.assertIn("Cells divide by mitosis.", markdown)

    def test_save_capture_writes_to_dated_tutair_inbox(self):
        temp_dir = Path(tempfile.mkdtemp(prefix="tutair-test-"))
        try:
            output_path = save_capture(
                TutairCapture(
                    source_type="pasted_text",
                    subject="Science",
                    topic="Cell division",
                    source_url="",
                    learning_content="Cells divide by mitosis.",
                    captured_on=date(2026, 7, 9),
                ),
                temp_dir,
            )

            self.assertEqual(
                output_path,
                temp_dir / "2026" / "07" / "2026-07-09-gcse-science-cell-division.md",
            )
            self.assertTrue(output_path.exists())
            self.assertIn("handoff_status: blocked_needs_source_content", output_path.read_text())
        finally:
            shutil.rmtree(temp_dir)

    def test_save_source_content_writes_separate_raw_text_file(self):
        temp_dir = Path(tempfile.mkdtemp(prefix="tutair-source-"))
        try:
            capture = TutairCapture(
                source_type="pasted_text",
                subject="Science",
                topic="Cell division",
                source_url="",
                learning_content="Cells divide by mitosis.",
                captured_on=date(2026, 7, 9),
            )
            source_path = save_source_content(capture, temp_dir)
            ready_capture = with_source_content_fields(capture, source_path)
            markdown = build_capture_markdown(ready_capture)

            self.assertEqual(source_path.parent.name, "source-content")
            self.assertEqual(source_path.read_text(encoding="utf-8").strip(), "Cells divide by mitosis.")
            self.assertIn("source_content_status: ready", markdown)
            self.assertIn("processing_readiness: ready_for_processing", markdown)
            self.assertIn(str(source_path), markdown)
        finally:
            shutil.rmtree(temp_dir)


class TestDefaultInboxRoot(unittest.TestCase):
    """The notes folder must follow the machine, not one developer's Windows login."""

    def test_the_environment_variable_wins(self):
        with mock.patch.dict(os.environ, {"TUTAIR_INBOX_ROOT": "D:/notes/TutAIR"}):
            self.assertEqual(default_inbox_root(), Path("D:/notes/TutAIR"))

    def test_without_it_the_path_sits_under_the_current_user_home(self):
        # Remove only our variable: clearing the whole environment takes USERPROFILE
        # with it, and Path.home() needs that on Windows.
        with mock.patch.dict(os.environ):
            os.environ.pop("TUTAIR_INBOX_ROOT", None)
            root = default_inbox_root()

        self.assertTrue(str(root).startswith(str(Path.home())))
        self.assertEqual(root.name, "TutAIR")

    def test_a_blank_setting_is_ignored_rather_than_used(self):
        with mock.patch.dict(os.environ, {"TUTAIR_INBOX_ROOT": "   "}):
            self.assertEqual(default_inbox_root().name, "TutAIR")


if __name__ == "__main__":
    unittest.main()
