import os
import shutil
import tempfile
import unittest
from unittest import mock
from datetime import date
from pathlib import Path

import tutair_intake
from tutair_intake import (
    LOCAL_INBOX,
    ONEDRIVE_INBOX,
    TutairCapture,
    default_inbox_root,
    load_env_fallback,
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
    """The notes folder must follow the machine, and must never be bound at import."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="tutair-home-"))

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def _clean_env(self):
        env = mock.patch.dict(os.environ)
        env.start()
        os.environ.pop("TUTAIR_INBOX_ROOT", None)
        self.addCleanup(env.stop)

    def test_1_the_environment_variable_wins(self):
        with mock.patch.dict(os.environ, {"TUTAIR_INBOX_ROOT": "D:/notes/TutAIR"}):
            self.assertEqual(default_inbox_root(), Path("D:/notes/TutAIR"))

    def test_2_onedrive_is_used_when_that_folder_already_exists(self):
        self._clean_env()
        existing = self.home.joinpath(*ONEDRIVE_INBOX)
        existing.mkdir(parents=True)

        with mock.patch.object(tutair_intake.Path, "home", return_value=self.home):
            self.assertEqual(default_inbox_root(), existing)

    def test_3_a_fresh_machine_is_never_sent_into_onedrive(self):
        self._clean_env()
        with mock.patch.object(tutair_intake.Path, "home", return_value=self.home):
            root = default_inbox_root()

        self.assertEqual(root, self.home.joinpath(*LOCAL_INBOX))
        self.assertNotIn("OneDrive", str(root))

    def test_an_empty_onedrive_folder_without_the_tutair_path_is_not_used(self):
        """The HP had a leftover empty OneDrive folder and notes were written into it."""
        self._clean_env()
        (self.home / "OneDrive").mkdir(parents=True)

        with mock.patch.object(tutair_intake.Path, "home", return_value=self.home):
            self.assertNotIn("OneDrive", str(default_inbox_root()))

    def test_a_blank_setting_is_ignored_rather_than_used(self):
        with mock.patch.dict(os.environ, {"TUTAIR_INBOX_ROOT": "   "}):
            with mock.patch.object(tutair_intake.Path, "home", return_value=self.home):
                self.assertEqual(default_inbox_root().name, "TutAIR")

    def test_it_is_not_frozen_at_import(self):
        """Changing the variable must change the answer, or .env arrives too late."""
        with mock.patch.dict(os.environ, {"TUTAIR_INBOX_ROOT": "D:/first"}):
            first = default_inbox_root()
        with mock.patch.dict(os.environ, {"TUTAIR_INBOX_ROOT": "D:/second"}):
            second = default_inbox_root()

        self.assertNotEqual(first, second)


class TestEnvFallbackParser(unittest.TestCase):
    """python-dotenv is not always installed, and a silently ignored .env is a trap."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="tutair-env-"))
        self.env = self.dir / ".env"

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_it_reads_key_value_pairs(self):
        self.env.write_text(
            "TUTAIR_AI_PROVIDER=claude\nTUTAIR_INBOX_ROOT=\"D:/notes\"\n",
            encoding="utf-8",
        )

        with mock.patch.dict(os.environ):
            os.environ.pop("TUTAIR_AI_PROVIDER", None)
            os.environ.pop("TUTAIR_INBOX_ROOT", None)
            load_env_fallback(self.env)

            self.assertEqual(os.environ["TUTAIR_AI_PROVIDER"], "claude")
            self.assertEqual(os.environ["TUTAIR_INBOX_ROOT"], "D:/notes")

    def test_comments_and_blank_lines_are_skipped(self):
        self.env.write_text("# a comment\n\nTUTAIR_AI_PROVIDER=claude\n", encoding="utf-8")

        with mock.patch.dict(os.environ):
            os.environ.pop("TUTAIR_AI_PROVIDER", None)
            load_env_fallback(self.env)

            self.assertEqual(os.environ["TUTAIR_AI_PROVIDER"], "claude")

    def test_a_real_environment_variable_beats_the_file(self):
        self.env.write_text("TUTAIR_AI_PROVIDER=openai\n", encoding="utf-8")

        with mock.patch.dict(os.environ, {"TUTAIR_AI_PROVIDER": "claude"}):
            load_env_fallback(self.env)

            self.assertEqual(os.environ["TUTAIR_AI_PROVIDER"], "claude")

    def test_a_missing_file_is_not_an_error(self):
        load_env_fallback(self.dir / "nope.env")


if __name__ == "__main__":
    unittest.main()
