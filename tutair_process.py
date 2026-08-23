"""Process TutAIR capture Markdown into ADHD-friendly learning notes."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from tutair_intake import slugify


@dataclass(frozen=True)
class ParsedCapture:
    path: Path
    metadata: dict[str, str]
    raw_learning_content: str
    source_content: str


def parse_capture(path: Path) -> ParsedCapture:
    text = path.read_text(encoding="utf-8")
    metadata = parse_frontmatter(text)
    raw_content = extract_section(text, "Raw Learning Content")
    source_content = read_source_content(path, metadata, raw_content)
    return ParsedCapture(
        path=path,
        metadata=metadata,
        raw_learning_content=raw_content,
        source_content=source_content,
    )


def read_source_content(capture_path: Path, metadata: dict[str, str], fallback: str) -> str:
    source_content_path = metadata.get("source_content_path", "").strip()
    if not source_content_path:
        return fallback

    path = Path(source_content_path)
    if not path.is_absolute():
        path = capture_path.parent / path
    if not path.exists():
        raise FileNotFoundError(f"Source content file does not exist: {path}")
    return path.read_text(encoding="utf-8")


def parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}

    try:
        frontmatter = text.split("---", 2)[1]
    except IndexError:
        return {}

    metadata: dict[str, str] = {}
    for line in frontmatter.splitlines():
        if ":" not in line or line.startswith(" ") or line.startswith("-"):
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip('"')
    return metadata


def extract_section(text: str, heading: str) -> str:
    pattern = re.compile(rf"^## {re.escape(heading)}\s*$", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return ""

    start = match.end()
    next_heading = re.search(r"^## .+$", text[start:], re.MULTILINE)
    end = start + next_heading.start() if next_heading else len(text)
    return text[start:end].strip()


def build_processed_note(capture: ParsedCapture, created_on: date | None = None) -> str:
    validate_processing_readiness(capture)
    created = created_on or date.today()
    metadata = capture.metadata
    subject = metadata.get("subject", "needs adding")
    topic = metadata.get("topic", "needs adding")
    possible_exam_board = metadata.get("possible_exam_board", "unknown")
    exam_board_status = safe_exam_board_status(
        metadata.get("exam_board_status", "unconfirmed"),
        metadata.get("exam_board_evidence", "none"),
    )
    exam_board_evidence = metadata.get("exam_board_evidence", "none") or "none"
    confidence_level = metadata.get("confidence_level", "low")
    source_url = metadata.get("source_url", "")
    raw_capture = str(capture.path)
    source_content_path = metadata.get("source_content_path", "")
    source_content_status = metadata.get("source_content_status", "legacy_inline")
    content = capture.source_content.strip()
    facts = choose_key_facts(content)
    tiny_summary = build_tiny_summary(content, subject, topic)
    what_this_means = build_plain_explanation(content, topic)

    return f"""---
type: tutair_learning_resource
source_capture: {raw_capture}
source_content: {source_content_path}
source_content_status: {source_content_status}
subject: {subject}
topic: {topic}
possible_exam_board: {possible_exam_board}
exam_board_status: {exam_board_status}
exam_board_evidence: {exam_board_evidence}
created_on: {created.isoformat()}
confidence_level: {confidence_level}
tags:
  - tutair
  - gcse
---

# {subject} - {topic}

## Tiny Summary

{tiny_summary}

## Key Facts

{format_bullets(facts)}

## What This Means

{what_this_means}

## Exam-Style Questions

1. What is the main idea in this source?
2. Explain one key fact about {topic}.
3. Apply this idea to a GCSE-style example or question.

## Flashcards

Q: What topic is this note about?
A: {topic}

Q: What is one key fact from the source?
A: {facts[0]}

Q: What should be checked before using exam-board-specific revision?
A: The exam board mapping and specification evidence.

## Next Revision Task

Spend 5 to 15 minutes turning the key facts into your own words, then answer the three exam-style questions.

## Exam Board Mapping

- Status: {exam_board_status}
- Possible exam board: {possible_exam_board}
- Evidence: {exam_board_evidence}
- What needs checking: official specification, teacher confirmation, school document, exam timetable, or confirmed course source

Do not turn possible mapping into fact without evidence from an official specification, teacher, school document, exam timetable, or confirmed course source.

## Source Link

- Raw capture: {raw_capture}
- Raw source content: {source_content_path}
- Source URL: {source_url}
"""


def validate_processing_readiness(capture: ParsedCapture) -> None:
    status = capture.metadata.get("source_content_status", "legacy_inline").strip().lower()
    readiness = capture.metadata.get("processing_readiness", "ready_for_processing").strip().lower()
    content = capture.source_content.strip()

    if status == "needs_source_content" or readiness == "blocked_needs_source_content":
        raise ValueError(
            "TutAIR capture is blocked: add transcript, lesson text, or another raw source content file before processing."
        )
    if not content:
        raise ValueError("TutAIR capture has no source content to process.")


def safe_exam_board_status(status: str, evidence: str) -> str:
    normalized_status = (status or "unconfirmed").strip().lower()
    normalized_evidence = (evidence or "none").strip().lower()
    if normalized_status == "confirmed" and normalized_evidence not in {"", "none", "unverified"}:
        return "confirmed"
    return "unconfirmed"


def build_tiny_summary(content: str, subject: str, topic: str) -> str:
    sentences = split_sentences(content)
    if sentences:
        return " ".join(sentences[:2])
    return f"This capture is about {topic} in {subject}. Review the source and fill in the main idea."


def choose_key_facts(content: str) -> list[str]:
    sentences = split_sentences(content)
    facts = [sentence for sentence in sentences if len(sentence.split()) >= 4][:3]
    while len(facts) < 3:
        facts.append("Add one clear fact from the source.")
    return facts


def build_plain_explanation(content: str, topic: str) -> str:
    sentences = split_sentences(content)
    if sentences:
        return f"In plain English, {topic} matters because: {sentences[0]}"
    return f"In plain English, this note should explain why {topic} matters for GCSE revision."


def split_sentences(content: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", content).strip()
    if not cleaned:
        return []
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    return [part.strip("- ").strip() for part in parts if part.strip("- ").strip()]


def format_bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def default_output_path(capture_path: Path, metadata: dict[str, str]) -> Path:
    subject = metadata.get("subject", "gcse")
    topic = metadata.get("topic", capture_path.stem)
    captured_on = metadata.get("captured_on", datetime.now().date().isoformat())
    slug = slugify(f"processed-{subject}-{topic}")
    return capture_path.parent / "processed" / f"{captured_on}-{slug}.md"


def process_capture(capture_path: Path, output_path: Path | None = None) -> Path:
    capture = parse_capture(capture_path)
    destination = output_path or default_output_path(capture_path, capture.metadata)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(build_processed_note(capture), encoding="utf-8")
    return destination


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create an ADHD-friendly TutAIR learning note.")
    parser.add_argument("capture", type=Path, help="Path to a TutAIR capture Markdown file.")
    parser.add_argument("--output", type=Path, help="Optional output Markdown path.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_path = process_capture(args.capture, args.output)
    print(f"Saved processed TutAIR note: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
