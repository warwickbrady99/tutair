"""Mint multiple-choice questions from a TutAIR transcript, with an independent review.

One model call that writes questions and checks its own work agrees with itself. So this
uses two calls with different instructions:

  writer   - produces candidate questions grounded in the transcript, each citing the
             timestamp of the moment that taught it
  reviewer - a separate call that tries to prove each question unfair: more than one
             defensible answer, a key you can spot from the wording alone, a claim the
             transcript does not support, or a clue that teaches nothing

Anything the reviewer objects to is written out with status `draft` and the objection
attached. Only `approved` questions are ever shown for revision.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


TUTAIR_ROOT = Path(__file__).resolve().parent
TUTAIR_ENV_PATH = TUTAIR_ROOT / ".env"
QUESTIONS_HEADING = "Multiple Choice Questions"
DEFAULT_QUESTION_COUNT = 8
MODEL_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class QuestionOption:
    id: str
    text: str


@dataclass(frozen=True)
class MintedQuestion:
    id: str
    stem: str
    options: list[QuestionOption]
    answer_id: str
    explanation: str
    source_timestamp: str
    objective_id: str = ""
    status: str = "draft"
    objection: str = ""

    def option_text(self, option_id: str) -> str:
        for option in self.options:
            if option.id == option_id:
                return option.text
        return ""


@dataclass(frozen=True)
class MintingResult:
    subject: str
    topic: str
    source_url: str
    questions: list[MintedQuestion] = field(default_factory=list)
    spec_provenance: str = "none"

    @property
    def approved(self) -> list[MintedQuestion]:
        return [question for question in self.questions if question.status == "approved"]

    @property
    def drafts(self) -> list[MintedQuestion]:
        return [question for question in self.questions if question.status != "approved"]


# --------------------------------------------------------------------------------------
# Prompts
# --------------------------------------------------------------------------------------

WRITER_INSTRUCTIONS = """You write GCSE multiple-choice questions for a Year 11 student.

You will be given a timestamped transcript of a lesson video, and where available the exam
board specification the student is assessed against. Write {count} questions that test
understanding of what the transcript teaches AND that fall inside the specification.

The transcript decides what is answerable. The specification decides what is worth asking.
Where the transcript goes beyond the specification, leave that material alone.

Rules:
- Every question must be answerable from the transcript alone. Do not use outside knowledge.
- Where specification objectives are listed, each question must target one of them, and you
  must return its id in `objective_id`. Use "" only if no listed objective fits.
- Exactly one option is defensible. The others must be wrong, not merely worse.
- Four options per question, labelled A, B, C, D.
- Do not make the correct option the longest, the most detailed, or the most hedged.
- Do not reuse wording from the stem in the correct option.
- Distractors should be mistakes a student might really make, not nonsense.
- Cite `source_timestamp` as the [MM:SS] marker of the line that taught the answer.
- Plain English. Short stems. No trick questions.

Return JSON only, no prose and no code fence:

{{"questions": [
  {{"id": "q1",
    "stem": "...",
    "options": [{{"id": "A", "text": "..."}}, {{"id": "B", "text": "..."}},
                {{"id": "C", "text": "..."}}, {{"id": "D", "text": "..."}}],
    "answer_id": "B",
    "explanation": "One sentence on why B is right.",
    "source_timestamp": "04:12",
    "objective_id": ""}}
]}}"""

REVIEWER_INSTRUCTIONS = """You are reviewing GCSE multiple-choice questions written by someone else.
Your job is to try to prove each question unfair. Be hard to please.

Reject a question if any of these hold:
- More than one option is defensible, or the keyed answer is arguable.
- The answer can be inferred from wording, grammar, length or hedging alone.
- It asserts something the transcript does not support.
- The stem gives the answer away, or the distractors are obviously silly.
- Answering it correctly teaches nothing transferable.
- The cited timestamp does not match the content of the question.
- It goes beyond what the specification covers, where a specification is supplied.
- It claims a specification objective it does not actually test.

Approve only questions you would be content to put in front of a student sitting a real exam.

You will be given the transcript and the questions. Return JSON only, no prose and no code fence:

{"verdicts": [
  {"id": "q1", "verdict": "approve", "objection": ""},
  {"id": "q2", "verdict": "reject", "objection": "Both B and C are defensible because ..."}
]}"""


def format_spec_block(spec=None) -> str:
    """The specification half of the prompt. Absent specification, say so plainly."""
    if spec is None or not getattr(spec, "grounded", False):
        return (
            "\nSpecification: none available for this topic. Write from the transcript only, "
            "and do not claim exam board coverage.\n"
        )

    from tutair_spec import format_objectives

    block = [""]
    if spec.board_id or spec.specification_code:
        block.append(f"Exam board: {spec.board_id} {spec.specification_code}".strip())
    if spec.objectives:
        block.append("Specification objectives to target:")
        block.append(format_objectives(spec.objectives))
    if spec.excerpt:
        block.append("Specification wording (authoritative on scope):")
        block.append(spec.excerpt)
    block.append("")
    return "\n".join(block)


def build_writer_prompt(transcript: str, subject: str, topic: str, count: int, spec=None) -> str:
    return (
        WRITER_INSTRUCTIONS.format(count=count)
        + f"\n\nSubject: {subject}\nTopic: {topic}\n"
        + format_spec_block(spec)
        + f"\nTranscript:\n{transcript}\n"
    )


def build_reviewer_prompt(transcript: str, questions: list[MintedQuestion], spec=None) -> str:
    payload = {"questions": [_question_for_review(question) for question in questions]}
    return (
        REVIEWER_INSTRUCTIONS
        + format_spec_block(spec)
        + f"\nTranscript:\n{transcript}\n\nQuestions:\n{json.dumps(payload, indent=2)}\n"
    )


def _question_for_review(question: MintedQuestion) -> dict:
    return {
        "id": question.id,
        "stem": question.stem,
        "options": [asdict(option) for option in question.options],
        "answer_id": question.answer_id,
        "explanation": question.explanation,
        "source_timestamp": question.source_timestamp,
        "objective_id": question.objective_id,
    }


# --------------------------------------------------------------------------------------
# Model calls
# --------------------------------------------------------------------------------------

def load_env() -> None:
    if load_dotenv and TUTAIR_ENV_PATH.exists():
        load_dotenv(TUTAIR_ENV_PATH)


def resolve_provider() -> str:
    return (os.getenv("TUTAIR_AI_PROVIDER") or "claude").strip().lower()


def run_model(prompt: str, provider: str | None = None) -> str:
    chosen = (provider or resolve_provider()).strip().lower()
    if chosen == "claude":
        return run_claude(prompt)
    if chosen == "openai":
        return run_openai(prompt)
    raise ValueError(f"Unknown TUTAIR_AI_PROVIDER: {chosen}. Use 'claude' or 'openai'.")


def run_claude(prompt: str) -> str:
    """Use the Claude Code CLI, so minting runs on a subscription rather than per-token."""
    executable = shutil.which("claude")
    if not executable:
        raise RuntimeError(
            "The 'claude' command was not found. Install Claude Code, or set "
            "TUTAIR_AI_PROVIDER=openai in .env."
        )
    completed = subprocess.run(
        [executable, "-p", prompt],
        capture_output=True,
        text=True,
        timeout=MODEL_TIMEOUT_SECONDS,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"claude -p failed: {completed.stderr.strip()[:400]}")
    return completed.stdout


def run_openai(prompt: str) -> str:
    from urllib.request import Request, urlopen

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key or api_key == "your-api-key-here":
        raise RuntimeError("OPENAI_API_KEY is not set in .env.")

    model = (os.getenv("TUTAIR_AI_MODEL") or "gpt-4o-mini").strip()
    body = json.dumps(
        {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.2}
    ).encode("utf-8")
    request = Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    with urlopen(request, timeout=MODEL_TIMEOUT_SECONDS) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload["choices"][0]["message"]["content"]


def extract_json(text: str) -> dict:
    """Models like to wrap JSON in prose or a code fence. Take the outermost object."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else None

    if candidate is None:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("No JSON object found in the model reply.")
        candidate = text[start : end + 1]

    return json.loads(candidate)


# --------------------------------------------------------------------------------------
# Minting
# --------------------------------------------------------------------------------------

def normalise_timestamp(value) -> str:
    """Keep the cited marker plain ASCII.

    Writers sometimes return a range rather than a single moment, and they punctuate it
    with an en or em dash. That is fine as content, but it is the one field printed to a
    console during a run, and a Windows console on a legacy code page renders it as
    mojibake. Fold the dashes to a hyphen and strip any brackets.
    """
    text = str(value or "").strip().strip("[]").strip()
    text = re.sub(r"[‐-―−]", "-", text)
    return re.sub(r"\s+", " ", text)


def parse_writer_reply(text: str) -> list[MintedQuestion]:
    payload = extract_json(text)
    questions: list[MintedQuestion] = []
    for index, item in enumerate(payload.get("questions", []), start=1):
        options = [
            QuestionOption(id=str(option.get("id", "")).strip(), text=str(option.get("text", "")).strip())
            for option in item.get("options", [])
        ]
        question = MintedQuestion(
            id=str(item.get("id") or f"q{index}").strip(),
            stem=str(item.get("stem", "")).strip(),
            options=options,
            answer_id=str(item.get("answer_id", "")).strip(),
            explanation=str(item.get("explanation", "")).strip(),
            source_timestamp=normalise_timestamp(item.get("source_timestamp", "")),
            objective_id=str(item.get("objective_id", "")).strip(),
        )
        if is_structurally_valid(question):
            questions.append(question)
    return questions


def is_structurally_valid(question: MintedQuestion) -> bool:
    """Cheap checks the reviewer should not have to spend a call on."""
    if not question.stem or len(question.options) != 4:
        return False
    option_ids = [option.id for option in question.options]
    if len(set(option_ids)) != 4:
        return False
    if question.answer_id not in option_ids:
        return False
    return all(option.text for option in question.options)


def parse_reviewer_reply(text: str) -> dict[str, tuple[str, str]]:
    payload = extract_json(text)
    verdicts: dict[str, tuple[str, str]] = {}
    for item in payload.get("verdicts", []):
        question_id = str(item.get("id", "")).strip()
        verdict = str(item.get("verdict", "reject")).strip().lower()
        objection = str(item.get("objection", "")).strip()
        if question_id:
            verdicts[question_id] = (verdict, objection)
    return verdicts


def apply_verdicts(
    questions: list[MintedQuestion], verdicts: dict[str, tuple[str, str]]
) -> list[MintedQuestion]:
    """No verdict means no approval. Silence is not consent."""
    reviewed: list[MintedQuestion] = []
    for question in questions:
        verdict, objection = verdicts.get(question.id, ("reject", "The reviewer did not return a verdict."))
        approved = verdict == "approve"
        reviewed.append(
            MintedQuestion(
                id=question.id,
                stem=question.stem,
                options=question.options,
                answer_id=question.answer_id,
                explanation=question.explanation,
                source_timestamp=question.source_timestamp,
                objective_id=question.objective_id,
                status="approved" if approved else "draft",
                objection="" if approved else (objection or "Rejected without a stated reason."),
            )
        )
    return reviewed


def mint_questions(
    transcript: str,
    subject: str,
    topic: str,
    source_url: str = "",
    count: int = DEFAULT_QUESTION_COUNT,
    runner=None,
    spec=None,
) -> MintingResult:
    call = runner or run_model
    provenance = spec.provenance() if spec is not None else "none"

    written = parse_writer_reply(call(build_writer_prompt(transcript, subject, topic, count, spec)))
    if not written:
        return MintingResult(
            subject=subject, topic=topic, source_url=source_url, questions=[], spec_provenance=provenance
        )

    verdicts = parse_reviewer_reply(call(build_reviewer_prompt(transcript, written, spec)))
    return MintingResult(
        subject=subject,
        topic=topic,
        source_url=source_url,
        questions=apply_verdicts(written, verdicts),
        spec_provenance=provenance,
    )


# --------------------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------------------

def build_questions_markdown(result: MintingResult) -> str:
    approved = result.approved
    if not approved:
        return (
            f"## {QUESTIONS_HEADING}\n\n"
            "No questions passed review for this source yet. "
            "The rejected drafts and the reviewer's objections are in `questions.json`.\n"
        )

    # Plain Markdown only. The TutAIR viewer renders headings, paragraphs and bullets;
    # bold markers and raw HTML leak through as literal text. Answers are hidden
    # properly in Quiz Me, which reads the JSON sidecar rather than this section.
    lines = [f"## {QUESTIONS_HEADING}", ""]
    for number, question in enumerate(approved, start=1):
        lines.append(f"{number}. {question.stem}")
        lines.append("")
        for option in question.options:
            lines.append(f"- {option.id}. {option.text}")
        lines.append("")
        marker = f" (taught at {question.source_timestamp})" if question.source_timestamp else ""
        answer = f"Answer: {question.answer_id}. {question.option_text(question.answer_id)}{marker}"
        if question.explanation:
            answer = f"{answer}. {question.explanation}"
        lines.append(answer)
        lines.append("")

    lines.append(
        f"{len(approved)} of {len(result.questions)} written questions passed independent review."
    )
    lines.append("")
    lines.append(f"Specification grounding: {result.spec_provenance}.")
    return "\n".join(lines) + "\n"


def questions_payload(result: MintingResult) -> dict:
    return {
        "subject": result.subject,
        "topic": result.topic,
        "source_url": result.source_url,
        "spec_provenance": result.spec_provenance,
        "written": len(result.questions),
        "approved": len(result.approved),
        "questions": [
            {
                "id": question.id,
                "stem": question.stem,
                "options": [asdict(option) for option in question.options],
                "answer_id": question.answer_id,
                "explanation": question.explanation,
                "source_timestamp": question.source_timestamp,
                "objective_id": question.objective_id,
                "status": question.status,
                "objection": question.objection,
            }
            for question in result.questions
        ],
    }


def save_questions_json(result: MintingResult, note_path: Path) -> Path:
    destination = note_path.with_name(f"{note_path.stem}-questions.json")
    destination.write_text(
        json.dumps(questions_payload(result), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return destination


def upsert_questions_section(note_text: str, section: str) -> str:
    """Add the questions section, replacing an existing one so reruns stay clean."""
    pattern = re.compile(rf"^## {re.escape(QUESTIONS_HEADING)}\s*$", re.MULTILINE)
    match = pattern.search(note_text)
    if not match:
        return note_text.rstrip() + "\n\n" + section

    start = match.start()
    following = re.search(r"^## .+$", note_text[match.end() :], re.MULTILINE)
    end = match.end() + following.start() if following else len(note_text)
    return note_text[:start] + section + "\n" + note_text[end:].lstrip("\n")


def read_note_metadata(note_text: str) -> dict[str, str]:
    if not note_text.startswith("---\n"):
        return {}
    parts = note_text.split("---", 2)
    if len(parts) < 3:
        return {}

    metadata: dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" not in line or line.startswith(" ") or line.startswith("-"):
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip('"')
    return metadata


def read_transcript_for_note(note_text: str, note_path: Path) -> str:
    source_content = read_note_metadata(note_text).get("source_content", "").strip()
    if not source_content:
        raise ValueError(
            "This note has no `source_content` in its frontmatter, so there is no transcript "
            "to write questions from. Re-run tutair_transcript.py for this source."
        )

    path = Path(source_content)
    if not path.is_absolute():
        path = note_path.parent / path
    if not path.exists():
        raise FileNotFoundError(f"Source content file does not exist: {path}")

    timestamped = path.with_name(f"{path.stem}-timestamped.md")
    return (timestamped if timestamped.exists() else path).read_text(encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write and independently review multiple-choice questions for a TutAIR note."
    )
    parser.add_argument("note", type=Path, help="Path to a processed TutAIR note.")
    parser.add_argument("--count", type=int, default=DEFAULT_QUESTION_COUNT)
    parser.add_argument("--provider", choices=["claude", "openai"], help="Overrides TUTAIR_AI_PROVIDER.")
    parser.add_argument("--board", default="", help="Exam board id, for example AQA, to narrow the course map.")
    parser.add_argument("--course-map", type=Path, help="Course map JSON. Defaults to the bundled MVP map.")
    parser.add_argument("--spec-dir", type=Path, help="Folder of official specification PDFs.")
    parser.add_argument("--no-spec", action="store_true", help="Mint from the transcript alone.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_env()

    note_text = args.note.read_text(encoding="utf-8")
    metadata = read_note_metadata(note_text)
    transcript = read_transcript_for_note(note_text, args.note)

    subject = metadata.get("subject", "GCSE")
    topic = metadata.get("topic", args.note.stem)

    spec = None
    if not args.no_spec:
        from tutair_spec import build_spec_context

        spec = build_spec_context(
            subject=subject,
            topic=topic,
            board_id=args.board or metadata.get("possible_exam_board", ""),
            course_map_path=args.course_map,
            specification_dir=args.spec_dir,
        )
        print(f"Specification grounding: {spec.provenance()}")

    provider = args.provider or resolve_provider()
    print(f"Writing {args.count} questions with {provider} ...")
    result = mint_questions(
        transcript=transcript,
        subject=subject,
        topic=topic,
        source_url=metadata.get("source_url", ""),
        count=args.count,
        runner=lambda prompt: run_model(prompt, provider),
        spec=spec,
    )

    if not result.questions:
        print("The writer returned no usable questions. Nothing was written to the note.")
        return 1

    args.note.write_text(
        upsert_questions_section(note_text, build_questions_markdown(result)), encoding="utf-8"
    )
    json_path = save_questions_json(result, args.note)

    print(f"Approved {len(result.approved)} of {len(result.questions)} written questions.")
    for question in result.drafts:
        print(f"  rejected {question.id}: {question.objection}")
    print(f"Updated note:     {args.note}")
    print(f"Saved questions:  {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
