"""Create Markdown-first TutAIR captures for GCSE learning sources."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse


DEFAULT_INBOX_ROOT = Path(r"C:\Users\Buggly\OneDrive\Desktop\MyPKA\Team Inbox\TutAIR")


@dataclass(frozen=True)
class TutairCapture:
    source_type: str
    subject: str
    topic: str
    source_url: str
    learning_content: str
    captured_on: date
    source_content_status: str = "needs_source_content"
    source_content_path: str = ""
    processing_readiness: str = "blocked_needs_source_content"
    confidence_level: str = "low"
    possible_exam_board: str = "unknown"
    exam_board_status: str = "unconfirmed"
    exam_board_evidence: str = "none"


def dated_inbox_dir(root: Path | None = None, captured_at: date | None = None) -> Path:
    capture_date = captured_at or date.today()
    base = root or DEFAULT_INBOX_ROOT
    return base / f"{capture_date:%Y}" / f"{capture_date:%m}"


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "learning-capture"


def build_capture_markdown(capture: TutairCapture) -> str:
    source_url = capture.source_url or ""
    source_content_path = capture.source_content_path or ""
    return f"""---
type: tutair_learning_capture
handoff_status: {capture.processing_readiness}
source_type: {capture.source_type}
source_content_status: {capture.source_content_status}
source_content_path: {source_content_path}
processing_readiness: {capture.processing_readiness}
subject: {capture.subject}
topic: {capture.topic}
possible_exam_board: {capture.possible_exam_board}
exam_board_status: {capture.exam_board_status}
exam_board_evidence: {capture.exam_board_evidence}
source_url: {source_url}
captured_on: {capture.captured_on.isoformat()}
confidence_level: {capture.confidence_level}
tags:
  - tutair
  - gcse
---

# TutAIR Capture - {capture.subject} - {capture.topic}

## Source

- Source type: {capture.source_type}
- Source URL: {source_url}
- Source content status: {capture.source_content_status}
- Source content path: {source_content_path}
- Processing readiness: {capture.processing_readiness}
- Source title:
- Captured on: {capture.captured_on.isoformat()}

## Learning Metadata

- Subject: {capture.subject}
- Topic: {capture.topic}
- Possible exam board: {capture.possible_exam_board}
- Exam-board status: {capture.exam_board_status}
- Confidence level: {capture.confidence_level}

## Exam Board Evidence

{capture.exam_board_evidence}

Do not mark an exam board as confirmed unless the evidence is known.

## Raw Learning Content

{capture.learning_content.strip()}

## Source Content Link

- Raw source content file: {source_content_path}
- Rule: process this capture only when `source_content_status` is `ready`.

## Processing Notes

- What looks useful?
- What is unclear?
- What should TutAIR turn into a revision resource?
"""


def save_capture(capture: TutairCapture, inbox_root: Path | None = None) -> Path:
    out_dir = dated_inbox_dir(inbox_root, capture.captured_on)
    out_dir.mkdir(parents=True, exist_ok=True)

    topic_slug = slugify(f"gcse-{capture.subject}-{capture.topic}")
    output_path = out_dir / f"{capture.captured_on.isoformat()}-{topic_slug}.md"
    output_path.write_text(build_capture_markdown(capture), encoding="utf-8")
    return output_path


def save_source_content(capture: TutairCapture, inbox_root: Path | None = None) -> Path:
    out_dir = dated_inbox_dir(inbox_root, capture.captured_on) / "source-content"
    out_dir.mkdir(parents=True, exist_ok=True)

    topic_slug = slugify(f"source-{capture.subject}-{capture.topic}")
    output_path = out_dir / f"{capture.captured_on.isoformat()}-{topic_slug}.txt"
    output_path.write_text(capture.learning_content.strip() + "\n", encoding="utf-8")
    return output_path


def with_source_content_fields(capture: TutairCapture, source_content_path: Path | None) -> TutairCapture:
    if source_content_path:
        return TutairCapture(
            source_type=capture.source_type,
            subject=capture.subject,
            topic=capture.topic,
            source_url=capture.source_url,
            learning_content=capture.learning_content,
            captured_on=capture.captured_on,
            source_content_status="ready",
            source_content_path=str(source_content_path),
            processing_readiness="ready_for_processing",
            confidence_level=capture.confidence_level,
            possible_exam_board=capture.possible_exam_board,
            exam_board_status=capture.exam_board_status,
            exam_board_evidence=capture.exam_board_evidence,
        )

    return capture


def detect_source_type(url: str | None, text_file: Path | None) -> str:
    if url and is_youtube_url(url):
        return "youtube_url"
    if url:
        return "url"
    if text_file:
        return "pasted_text"
    raise ValueError("Provide either --url or --text-file.")


def is_youtube_url(url: str) -> bool:
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host in {"youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}


def extract_youtube_video_id(url: str) -> str | None:
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower()
    path = parsed.path.strip("/")
    if host.startswith("www."):
        host = host[4:]

    if host in {"youtube.com", "m.youtube.com", "music.youtube.com"} and path == "watch":
        video_ids = parse_qs(parsed.query).get("v", [])
        return video_ids[0] if video_ids else None

    if host == "youtu.be":
        return path.split("/", 1)[0] if path else None

    if host in {"youtube.com", "m.youtube.com", "music.youtube.com"} and (
        path.startswith("shorts/") or path.startswith("embed/")
    ):
        return path.split("/", 1)[1].split("/", 1)[0]

    return None


def build_learning_content(url: str | None, text_file: Path | None) -> str:
    if text_file:
        return text_file.read_text(encoding="utf-8")

    if url and is_youtube_url(url):
        video_id = extract_youtube_video_id(url)
        extra = f"\n\nYouTube video ID: {video_id}" if video_id else ""
        return (
            "YouTube educational URL captured for TutAIR processing.\n"
            "Transcript extraction is not part of TutAIR V1 intake yet."
            f"{extra}"
        )

    if url:
        return "Learning URL captured for TutAIR processing."

    raise ValueError("Provide either --url or --text-file.")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a TutAIR GCSE learning capture.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--url", help="Educational YouTube URL or learning URL to capture.")
    source.add_argument("--text-file", type=Path, help="UTF-8 text file containing pasted learning text.")
    parser.add_argument("--subject", required=True, help="GCSE subject, for example Science or Maths.")
    parser.add_argument("--topic", required=True, help="Learning topic, for example Cell division.")
    parser.add_argument("--possible-exam-board", default="unknown")
    parser.add_argument("--confidence-level", default="low", choices=["low", "medium", "high"])
    parser.add_argument("--inbox-root", type=Path, default=DEFAULT_INBOX_ROOT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    captured_on = datetime.now().date()
    source_type = detect_source_type(args.url, args.text_file)
    learning_content = build_learning_content(args.url, args.text_file)

    capture = TutairCapture(
        source_type=source_type,
        subject=args.subject,
        topic=args.topic,
        source_url=args.url or "",
        learning_content=learning_content,
        captured_on=captured_on,
        confidence_level=args.confidence_level,
        possible_exam_board=args.possible_exam_board,
    )
    source_content_path = None
    if args.text_file:
        source_content_path = save_source_content(capture, args.inbox_root)
    capture = with_source_content_fields(capture, source_content_path)
    output_path = save_capture(capture, args.inbox_root)
    print(f"Saved TutAIR capture: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
