import os
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import tutair_pipeline
from tutair_questions import MintingResult
from tutair_transcript import TranscriptSegment, VerifiedSource


SOURCE = VerifiedSource(
    video_id="abcdefghijk",
    url="https://www.youtube.com/watch?v=abcdefghijk",
    title="Cell structure explained",
    author="A Revision Channel",
)
SEGMENTS = [
    TranscriptSegment(0.0, "Plant cells have a cell wall made of cellulose."),
    TranscriptSegment(12.0, "Bacterial cells have a single loop of DNA."),
]


def run_pipeline(inbox_root: Path, extra_args=None, minted=None):
    """Drive main() with the network and the model replaced."""
    argv = [
        "--url", SOURCE.url,
        "--subject", "Science",
        "--topic", "Cell structure",
        "--inbox-root", str(inbox_root),
        "--no-spec",
    ] + (extra_args or [])

    result = minted if minted is not None else MintingResult(
        subject="Science", topic="Cell structure", source_url=SOURCE.url, questions=[]
    )

    with mock.patch.object(tutair_pipeline, "verify_youtube", return_value=SOURCE), \
         mock.patch.object(tutair_pipeline, "fetch_transcript", return_value=SEGMENTS), \
         mock.patch.object(tutair_pipeline, "mint_questions", return_value=result), \
         mock.patch.object(tutair_pipeline, "load_env"):
        code = tutair_pipeline.main(argv)

    return code


def read_capture(inbox_root: Path) -> str:
    captures = [p for p in inbox_root.glob("**/*.md") if "processed" not in p.parts and "source-content" not in p.parts]
    return captures[0].read_text(encoding="utf-8")


class TestPipelineCarriesTheExamBoard(unittest.TestCase):
    """--board must reach the capture, or the note claims it knows nothing about the course."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="tutair-pipeline-"))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_the_board_reaches_the_capture(self):
        run_pipeline(self.root, ["--board", "AQA"])

        self.assertIn("possible_exam_board: AQA", read_capture(self.root))

    def test_naming_a_board_does_not_confirm_it(self):
        run_pipeline(self.root, ["--board", "AQA"])
        capture = read_capture(self.root)

        self.assertIn("exam_board_status: unconfirmed", capture)
        self.assertIn("exam_board_evidence: none", capture)

    def test_without_a_board_it_stays_unknown(self):
        run_pipeline(self.root)

        self.assertIn("possible_exam_board: unknown", read_capture(self.root))


class TestPipelineStopsHonestly(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="tutair-pipeline-"))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_an_unverifiable_url_writes_nothing(self):
        with mock.patch.object(tutair_pipeline, "verify_youtube", return_value=None), \
             mock.patch.object(tutair_pipeline, "load_env"):
            code = tutair_pipeline.main(
                ["--url", "https://www.youtube.com/watch?v=nope", "--subject", "Science",
                 "--topic", "Cell structure", "--inbox-root", str(self.root), "--no-spec"]
            )

        self.assertEqual(code, 1)
        self.assertEqual(list(self.root.glob("**/*.md")), [])

    def test_a_video_without_captions_writes_nothing(self):
        with mock.patch.object(tutair_pipeline, "verify_youtube", return_value=SOURCE), \
             mock.patch.object(tutair_pipeline, "fetch_transcript", return_value=[]), \
             mock.patch.object(tutair_pipeline, "load_env"):
            code = tutair_pipeline.main(
                ["--url", SOURCE.url, "--subject", "Science", "--topic", "Cell structure",
                 "--inbox-root", str(self.root), "--no-spec"]
            )

        self.assertEqual(code, 1)
        self.assertEqual(list(self.root.glob("**/*.md")), [])

    def test_the_transcript_and_note_survive_a_barren_minting_run(self):
        code = run_pipeline(self.root)

        self.assertEqual(code, 1)
        self.assertTrue(any("processed" in p.parts for p in self.root.glob("**/*.md")))


class TestPipelineHonoursTheInboxEnvironment(unittest.TestCase):
    """TUTAIR_INBOX_ROOT must reach the pipeline even with no --inbox-root flag.

    It did not before: the default was bound when tutair_intake was imported, so a value
    set afterwards by .env arrived too late and notes were written to the wrong folder.
    """

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="tutair-env-root-"))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_the_environment_variable_places_the_notes(self):
        argv = ["--url", SOURCE.url, "--subject", "Science", "--topic", "Cell structure", "--no-spec"]
        result = MintingResult(subject="Science", topic="Cell structure", source_url=SOURCE.url, questions=[])

        with (
            mock.patch.dict(os.environ, {"TUTAIR_INBOX_ROOT": str(self.root)}),
            mock.patch.object(tutair_pipeline, "verify_youtube", return_value=SOURCE),
            mock.patch.object(tutair_pipeline, "fetch_transcript", return_value=SEGMENTS),
            mock.patch.object(tutair_pipeline, "mint_questions", return_value=result),
            mock.patch.object(tutair_pipeline, "load_env"),
        ):
            tutair_pipeline.main(argv)

        written = list(self.root.glob("**/*.md"))
        self.assertTrue(written, "nothing was written to TUTAIR_INBOX_ROOT")

    def test_an_explicit_flag_still_beats_the_environment(self):
        flagged = Path(tempfile.mkdtemp(prefix="tutair-flag-"))
        self.addCleanup(shutil.rmtree, flagged, True)
        argv = ["--url", SOURCE.url, "--subject", "Science", "--topic", "Cell structure",
                "--inbox-root", str(flagged), "--no-spec"]
        result = MintingResult(subject="Science", topic="Cell structure", source_url=SOURCE.url, questions=[])

        with (
            mock.patch.dict(os.environ, {"TUTAIR_INBOX_ROOT": str(self.root)}),
            mock.patch.object(tutair_pipeline, "verify_youtube", return_value=SOURCE),
            mock.patch.object(tutair_pipeline, "fetch_transcript", return_value=SEGMENTS),
            mock.patch.object(tutair_pipeline, "mint_questions", return_value=result),
            mock.patch.object(tutair_pipeline, "load_env"),
        ):
            tutair_pipeline.main(argv)

        self.assertTrue(list(flagged.glob("**/*.md")), "the flag was ignored")
        self.assertEqual(list(self.root.glob("**/*.md")), [], "the env var overrode the flag")


if __name__ == "__main__":
    unittest.main()
