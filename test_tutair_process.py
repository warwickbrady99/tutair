import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

from tutair_intake import TutairCapture, save_capture, save_source_content, with_source_content_fields
from tutair_process import (
    build_processed_note,
    default_output_path,
    parse_capture,
    process_capture,
    read_source_content,
    safe_exam_board_status,
)


class TestTutairProcess(unittest.TestCase):
    def test_parse_capture_reads_metadata_and_raw_content(self):
        temp_dir = Path(tempfile.mkdtemp(prefix="tutair-process-"))
        try:
            capture_path = make_capture(temp_dir)
            parsed = parse_capture(capture_path)

            self.assertEqual(parsed.metadata["subject"], "Science")
            self.assertEqual(parsed.metadata["topic"], "Cell division")
            self.assertIn("Mitosis makes new body cells.", parsed.source_content)
        finally:
            shutil.rmtree(temp_dir)

    def test_processed_note_contains_required_sections(self):
        temp_dir = Path(tempfile.mkdtemp(prefix="tutair-process-"))
        try:
            parsed = parse_capture(make_capture(temp_dir))
            note = build_processed_note(parsed, date(2026, 7, 9))

            self.assertIn("## Tiny Summary", note)
            self.assertIn("## Key Facts", note)
            self.assertIn("## What This Means", note)
            self.assertIn("## Exam-Style Questions", note)
            self.assertIn("## Flashcards", note)
            self.assertIn("## Next Revision Task", note)
            self.assertIn("## Exam Board Mapping", note)
            self.assertIn("exam_board_status: unconfirmed", note)
        finally:
            shutil.rmtree(temp_dir)

    def test_exam_board_status_stays_unconfirmed_without_evidence(self):
        status = safe_exam_board_status("confirmed", "none")

        self.assertEqual(status, "unconfirmed")

    def test_exam_board_status_can_be_confirmed_with_evidence(self):
        status = safe_exam_board_status("confirmed", "teacher confirmation")

        self.assertEqual(status, "confirmed")

    def test_default_output_path_uses_processed_folder(self):
        capture_path = Path("Team Inbox") / "TutAIR" / "2026" / "07" / "capture.md"
        output_path = default_output_path(
            capture_path,
            {"subject": "Science", "topic": "Cell division", "captured_on": "2026-07-09"},
        )

        self.assertEqual(
            output_path,
            Path("Team Inbox")
            / "TutAIR"
            / "2026"
            / "07"
            / "processed"
            / "2026-07-09-processed-science-cell-division.md",
        )

    def test_process_capture_writes_processed_markdown(self):
        temp_dir = Path(tempfile.mkdtemp(prefix="tutair-process-"))
        try:
            capture_path = make_capture(temp_dir)
            output_path = process_capture(capture_path)
            text = output_path.read_text(encoding="utf-8")

            self.assertTrue(output_path.exists())
            self.assertEqual(output_path.parent.name, "processed")
            self.assertIn("# Science - Cell division", text)
            self.assertIn("- Status: unconfirmed", text)
            self.assertIn("source_content_status: ready", text)
        finally:
            shutil.rmtree(temp_dir)

    def test_process_capture_blocks_url_only_capture_without_source_content(self):
        temp_dir = Path(tempfile.mkdtemp(prefix="tutair-process-"))
        try:
            capture_path = save_capture(
                TutairCapture(
                    source_type="youtube_url",
                    subject="Science",
                    topic="Cell division",
                    source_url="https://www.youtube.com/watch?v=abcdefghijk",
                    learning_content="YouTube educational URL captured for TutAIR processing.",
                    captured_on=date(2026, 7, 9),
                ),
                temp_dir,
            )

            with self.assertRaisesRegex(ValueError, "blocked"):
                process_capture(capture_path)
        finally:
            shutil.rmtree(temp_dir)

    def test_read_source_content_uses_separate_file_when_present(self):
        temp_dir = Path(tempfile.mkdtemp(prefix="tutair-process-"))
        try:
            capture_path = make_capture(temp_dir)
            parsed = parse_capture(capture_path)

            source_text = read_source_content(
                capture_path,
                parsed.metadata,
                "Fallback text should not be used.",
            )

            self.assertIn("The parent cell divides", source_text)
            self.assertNotIn("Fallback text", source_text)
        finally:
            shutil.rmtree(temp_dir)


def make_capture(root: Path) -> Path:
    capture = TutairCapture(
        source_type="pasted_text",
        subject="Science",
        topic="Cell division",
        source_url="",
        learning_content=(
            "Mitosis makes new body cells. "
            "The parent cell divides to make two identical daughter cells. "
            "This helps organisms grow and repair tissue."
        ),
        captured_on=date(2026, 7, 9),
    )
    source_path = save_source_content(capture, root)
    return save_capture(with_source_content_fields(capture, source_path), root)


if __name__ == "__main__":
    unittest.main()
