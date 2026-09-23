"""One command: a YouTube URL in, reviewed multiple-choice questions out.

This runs the whole TutAIR chain in order, stopping at the first honest failure:

    verify the video  ->  rip the transcript  ->  process into a revision note
                      ->  mint questions against the specification and the transcript

Each step is the same code the individual commands use. Nothing here does work of its
own, so the pipeline cannot drift away from the pieces it calls.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from tutair_intake import DEFAULT_INBOX_ROOT, save_capture
from tutair_process import process_capture
from tutair_questions import (
    DEFAULT_QUESTION_COUNT,
    build_questions_markdown,
    load_env,
    mint_questions,
    read_note_metadata,
    read_transcript_for_note,
    resolve_provider,
    run_model,
    save_questions_json,
    upsert_questions_section,
)
from tutair_spec import build_spec_context
from tutair_transcript import build_ready_capture, fetch_transcript, save_transcript_files, verify_youtube


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Take a YouTube URL all the way to reviewed multiple-choice questions."
    )
    parser.add_argument("--url", required=True, help="Educational YouTube URL.")
    parser.add_argument("--subject", required=True, help="GCSE subject, for example Science.")
    parser.add_argument("--topic", required=True, help="Learning topic, for example Cell structure.")
    parser.add_argument("--count", type=int, default=DEFAULT_QUESTION_COUNT)
    parser.add_argument("--board", default="", help="Exam board id, for example AQA.")
    parser.add_argument("--provider", choices=["claude", "openai"], help="Overrides TUTAIR_AI_PROVIDER.")
    parser.add_argument("--course-map", type=Path, help="Course map JSON. Defaults to the bundled MVP map.")
    parser.add_argument("--spec-dir", type=Path, help="Folder of official specification PDFs.")
    parser.add_argument("--no-spec", action="store_true", help="Mint from the transcript alone.")
    parser.add_argument("--inbox-root", type=Path, default=DEFAULT_INBOX_ROOT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_env()

    print("1/4  Verifying the source ...")
    source = verify_youtube(args.url)
    if source is None:
        print("     Could not verify that YouTube URL. Nothing was ingested.")
        return 1
    print(f"     {source.title}")
    print(f"     {source.author}")

    print("2/4  Ripping the transcript ...")
    segments = fetch_transcript(source.video_id)
    if not segments:
        print("     That video has no usable captions. Nothing was ingested.")
        return 1
    print(f"     {len(segments)} caption segments")

    captured_on = datetime.now().date()
    source_path, transcript_path = save_transcript_files(
        source, segments, args.subject, args.topic, captured_on, args.inbox_root
    )
    capture_path = save_capture(
        build_ready_capture(
            source, segments, args.subject, args.topic, captured_on, source_path
        ),
        args.inbox_root,
    )

    print("3/4  Building the revision note ...")
    note_path = process_capture(capture_path)
    print(f"     {note_path}")

    print("4/4  Writing and reviewing questions ...")
    note_text = note_path.read_text(encoding="utf-8")
    metadata = read_note_metadata(note_text)
    transcript = read_transcript_for_note(note_text, note_path)

    spec = None
    if not args.no_spec:
        spec = build_spec_context(
            subject=args.subject,
            topic=args.topic,
            board_id=args.board,
            course_map_path=args.course_map,
            specification_dir=args.spec_dir,
        )
        print(f"     Specification grounding: {spec.provenance()}")

    provider = args.provider or resolve_provider()
    result = mint_questions(
        transcript=transcript,
        subject=args.subject,
        topic=args.topic,
        source_url=metadata.get("source_url", source.url),
        count=args.count,
        runner=lambda prompt: run_model(prompt, provider),
        spec=spec,
    )

    if not result.questions:
        print("     The writer returned no usable questions. The note was still saved.")
        return 1

    note_path.write_text(
        upsert_questions_section(note_text, build_questions_markdown(result)), encoding="utf-8"
    )
    json_path = save_questions_json(result, note_path)

    print(f"     Approved {len(result.approved)} of {len(result.questions)} written questions.")
    for question in result.drafts:
        print(f"       rejected {question.id}: {question.objection}")

    print()
    print(f"Transcript: {transcript_path}")
    print(f"Note:       {note_path}")
    print(f"Questions:  {json_path}")
    print()
    print("Open it with:")
    print(f"  python .\\tutair_viewer.py --root \"{args.inbox_root}\"")
    print("then press Quiz Me on the note.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
