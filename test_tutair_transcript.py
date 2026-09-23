import io
import json
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

from tutair_transcript import (
    TranscriptSegment,
    VerifiedSource,
    build_ready_capture,
    build_timestamped_transcript,
    build_transcript_text,
    format_timestamp,
    save_transcript_files,
    verify_youtube,
    _to_segment,
)


def fake_opener(payload: dict | None, error: Exception | None = None):
    """Stand in for urlopen without touching the network."""

    def opener(request, timeout=None):
        if error is not None:
            raise error
        return io.BytesIO(json.dumps(payload).encode("utf-8"))

    return opener


class TestVerification(unittest.TestCase):
    def test_verify_reads_title_and_author_from_youtube(self):
        source = verify_youtube(
            "https://www.youtube.com/watch?v=abcdefghijk",
            opener=fake_opener({"title": "Mitosis explained", "author_name": "Cognito"}),
        )

        self.assertIsNotNone(source)
        self.assertEqual(source.video_id, "abcdefghijk")
        self.assertEqual(source.title, "Mitosis explained")
        self.assertEqual(source.author, "Cognito")

    def test_verify_returns_none_for_a_video_that_does_not_resolve(self):
        source = verify_youtube(
            "https://www.youtube.com/watch?v=abcdefghijk",
            opener=fake_opener(None, error=OSError("404")),
        )

        self.assertIsNone(source)

    def test_verify_never_raises_for_a_missing_source(self):
        try:
            result = verify_youtube(
                "https://youtu.be/missing1234",
                opener=fake_opener(None, error=TimeoutError("slow")),
            )
        except Exception as error:  # pragma: no cover - the point of the test
            self.fail(f"verify_youtube raised {error!r} instead of returning None")
        self.assertIsNone(result)

    def test_verify_rejects_a_non_youtube_url(self):
        self.assertIsNone(verify_youtube("https://example.com/lesson"))

    def test_verify_rejects_a_reply_with_no_title(self):
        source = verify_youtube(
            "https://www.youtube.com/watch?v=abcdefghijk",
            opener=fake_opener({"author_name": "Cognito"}),
        )
        self.assertIsNone(source)


class TestSegments(unittest.TestCase):
    def test_timestamps_format_as_minutes_and_hours(self):
        self.assertEqual(format_timestamp(0), "00:00")
        self.assertEqual(format_timestamp(75), "01:15")
        self.assertEqual(format_timestamp(3725), "1:02:05")

    def test_sound_effect_captions_are_dropped(self):
        self.assertIsNone(_to_segment({"text": "[Music]", "start": 1.0}))
        self.assertIsNone(_to_segment({"text": "   ", "start": 1.0}))
        self.assertIsNotNone(_to_segment({"text": "Mitosis makes new body cells.", "start": 1.0}))

    def test_transcript_text_is_plain_prose(self):
        segments = [
            TranscriptSegment(0.0, "Mitosis makes new body cells."),
            TranscriptSegment(4.5, "Meiosis makes gametes."),
        ]
        self.assertEqual(
            build_transcript_text(segments),
            "Mitosis makes new body cells. Meiosis makes gametes.",
        )

    def test_timestamped_transcript_marks_every_line(self):
        source = VerifiedSource("abcdefghijk", "https://youtu.be/abcdefghijk", "Mitosis", "Cognito")
        segments = [TranscriptSegment(0.0, "First line."), TranscriptSegment(62.0, "Second line.")]

        markdown = build_timestamped_transcript(source, segments)

        self.assertIn("[00:00] First line.", markdown)
        self.assertIn("[01:02] Second line.", markdown)
        self.assertIn("Cognito", markdown)


class TestCaptureHandoff(unittest.TestCase):
    def test_a_ripped_transcript_produces_a_ready_capture(self):
        temp_dir = Path(tempfile.mkdtemp(prefix="tutair-transcript-"))
        try:
            source = VerifiedSource("abcdefghijk", "https://youtu.be/abcdefghijk", "Mitosis", "Cognito")
            segments = [TranscriptSegment(0.0, "Mitosis makes new body cells.")]
            captured_on = date(2026, 9, 21)

            source_path, transcript_path = save_transcript_files(
                source, segments, "Science", "Cell division", captured_on, temp_dir
            )
            capture = build_ready_capture(
                source, segments, "Science", "Cell division", captured_on, source_path
            )

            self.assertTrue(source_path.exists())
            self.assertTrue(transcript_path.exists())
            self.assertEqual(capture.source_content_status, "ready")
            self.assertEqual(capture.processing_readiness, "ready_for_processing")
            self.assertEqual(capture.source_type, "youtube_transcript")
        finally:
            shutil.rmtree(temp_dir)

    def test_a_ripped_transcript_does_not_confirm_an_exam_board(self):
        source = VerifiedSource("abcdefghijk", "https://youtu.be/abcdefghijk", "Mitosis", "Cognito")
        capture = build_ready_capture(
            source,
            [TranscriptSegment(0.0, "Mitosis makes new body cells.")],
            "Science",
            "Cell division",
            date(2026, 9, 21),
            Path("source.txt"),
        )

        self.assertEqual(capture.exam_board_status, "unconfirmed")
        self.assertEqual(capture.exam_board_evidence, "none")


if __name__ == "__main__":
    unittest.main()
