"""Verify a YouTube source and rip its transcript into a TutAIR capture.

This finishes the job TutAIR V1 intake left open. Intake records a YouTube URL and
marks the capture `needs_source_content`; this command fetches the real transcript and
hands back a capture that is `ready_for_processing`.

The rule that matters: nothing is ingested until it has been fetched and confirmed to
exist. Verification is a separate step from loading, it never raises for a missing
video, and it reads the title and author from YouTube rather than trusting whatever the
person or a model claimed the link was.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from tutair_intake import (
    default_inbox_root,
    load_env,
    TutairCapture,
    dated_inbox_dir,
    extract_youtube_video_id,
    is_youtube_url,
    save_capture,
    slugify,
)


OEMBED_ENDPOINT = "https://www.youtube.com/oembed"
USER_AGENT = "TutAIR/1.0 (GCSE revision helper)"
VERIFY_TIMEOUT_SECONDS = 15


@dataclass(frozen=True)
class VerifiedSource:
    """A YouTube video that has been confirmed to exist, described by YouTube."""

    video_id: str
    url: str
    title: str
    author: str


@dataclass(frozen=True)
class TranscriptSegment:
    start_seconds: float
    text: str


def verify_youtube(url: str, opener=None) -> VerifiedSource | None:
    """Confirm the video exists and read its real title and author.

    Returns None when the video cannot be verified. This never raises for a missing
    source: a link that does not resolve is an ordinary answer, not an error.
    """
    if not is_youtube_url(url):
        return None

    video_id = extract_youtube_video_id(url)
    if not video_id:
        return None

    canonical = f"https://www.youtube.com/watch?v={video_id}"
    query = urlencode({"url": canonical, "format": "json"})
    request = Request(f"{OEMBED_ENDPOINT}?{query}", headers={"User-Agent": USER_AGENT})

    try:
        fetch = opener or urlopen
        with fetch(request, timeout=VERIFY_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, ValueError, OSError):
        return None

    title = str(payload.get("title", "")).strip()
    author = str(payload.get("author_name", "")).strip()
    if not title:
        return None

    return VerifiedSource(video_id=video_id, url=canonical, title=title, author=author or "unknown")


def fetch_transcript(video_id: str, languages: list[str] | None = None) -> list[TranscriptSegment]:
    """Fetch the caption track for a video using youtube_transcript_api."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError as error:  # pragma: no cover - depends on the machine
        raise RuntimeError(
            "youtube_transcript_api is not installed. Run: pip install -r requirements.txt"
        ) from error

    wanted = languages or ["en", "en-GB", "en-US"]
    raw = _call_transcript_api(YouTubeTranscriptApi, video_id, wanted)
    return [segment for segment in (_to_segment(item) for item in raw) if segment is not None]


def _call_transcript_api(api, video_id: str, languages: list[str]):
    """Support both the 0.6-style classmethod and the 1.x instance API."""
    if hasattr(api, "get_transcript"):
        return api.get_transcript(video_id, languages=languages)
    return api().fetch(video_id, languages=languages)


def _to_segment(item) -> TranscriptSegment | None:
    if isinstance(item, dict):
        text = str(item.get("text", "")).strip()
        start = float(item.get("start", 0.0))
    else:
        text = str(getattr(item, "text", "")).strip()
        start = float(getattr(item, "start", 0.0))

    if not text or text.startswith("[") and text.endswith("]"):
        return None
    return TranscriptSegment(start_seconds=start, text=text)


def format_timestamp(seconds: float) -> str:
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def build_transcript_text(segments: list[TranscriptSegment]) -> str:
    """Plain prose, no timestamps. This is what the processor reads as source content."""
    return " ".join(segment.text for segment in segments).strip()


def build_timestamped_transcript(source: VerifiedSource, segments: list[TranscriptSegment]) -> str:
    lines = [
        f"# Transcript - {source.title}",
        "",
        f"- Source URL: {source.url}",
        f"- Channel: {source.author}",
        f"- Segments: {len(segments)}",
        "",
        "Each line is the minute of the video that said it. Question writers cite these.",
        "",
    ]
    for segment in segments:
        lines.append(f"[{format_timestamp(segment.start_seconds)}] {segment.text}")
    return "\n".join(lines) + "\n"


def save_transcript_files(
    source: VerifiedSource,
    segments: list[TranscriptSegment],
    subject: str,
    topic: str,
    captured_on: date,
    inbox_root: Path | None = None,
) -> tuple[Path, Path]:
    """Write the plain source content and the timestamped transcript. Returns both paths."""
    out_dir = dated_inbox_dir(inbox_root, captured_on) / "source-content"
    out_dir.mkdir(parents=True, exist_ok=True)

    stem = f"{captured_on.isoformat()}-{slugify(f'source-{subject}-{topic}')}"
    source_path = out_dir / f"{stem}.txt"
    source_path.write_text(build_transcript_text(segments) + "\n", encoding="utf-8")

    transcript_path = out_dir / f"{stem}-timestamped.md"
    transcript_path.write_text(build_timestamped_transcript(source, segments), encoding="utf-8")

    return source_path, transcript_path


def build_ready_capture(
    source: VerifiedSource,
    segments: list[TranscriptSegment],
    subject: str,
    topic: str,
    captured_on: date,
    source_content_path: Path,
    possible_exam_board: str = "unknown",
    confidence_level: str = "low",
) -> TutairCapture:
    return TutairCapture(
        source_type="youtube_transcript",
        subject=subject,
        topic=topic,
        source_url=source.url,
        learning_content=build_transcript_text(segments),
        captured_on=captured_on,
        source_content_status="ready",
        source_content_path=str(source_content_path),
        processing_readiness="ready_for_processing",
        confidence_level=confidence_level,
        possible_exam_board=possible_exam_board,
        exam_board_status="unconfirmed",
        exam_board_evidence="none",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify a YouTube video, rip its transcript, and save a ready TutAIR capture."
    )
    parser.add_argument("--url", required=True, help="Educational YouTube URL.")
    parser.add_argument("--subject", required=True, help="GCSE subject, for example Science.")
    parser.add_argument("--topic", required=True, help="Learning topic, for example Cell division.")
    parser.add_argument("--possible-exam-board", default="unknown")
    parser.add_argument("--confidence-level", default="low", choices=["low", "medium", "high"])
    x
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_env()
    args = parse_args(argv)
    inbox_root = args.inbox_root or default_inbox_root()

    source = verify_youtube(args.url)
    if source is None:
        print("Could not verify that YouTube URL. Nothing was ingested.")
        print("Check the link opens in a browser, then try again.")
        return 1

    print(f"Verified: {source.title}")
    print(f"Channel:  {source.author}")

    segments = fetch_transcript(source.video_id)
    if not segments:
        print("That video has no usable captions, so there is no transcript to rip.")
        print("Nothing was ingested.")
        return 1

    captured_on = datetime.now().date()
    source_path, transcript_path = save_transcript_files(
        source, segments, args.subject, args.topic, captured_on, inbox_root
    )
    capture = build_ready_capture(
        source,
        segments,
        args.subject,
        args.topic,
        captured_on,
        source_path,
        args.possible_exam_board,
        args.confidence_level,
    )
    capture_path = save_capture(capture, inbox_root)

    print(f"Saved source content:      {source_path}")
    print(f"Saved timestamped transcript: {transcript_path}")
    print(f"Saved TutAIR capture:      {capture_path}")
    print("Next: python .\\tutair_process.py \"" + str(capture_path) + "\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
