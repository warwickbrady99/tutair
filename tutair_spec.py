"""Specification grounding for TutAIR question minting.

Questions written from a video alone test what the video happened to say. Questions
written against the specification test what the exam board will actually ask about.
This module supplies the second half: the learning objectives a question should target,
and the official specification wording that decides whether it is in scope.

Two sources, in order of authority:

1. The **course map** (`course-map/data/*.json`) - TutAIR's curriculum spine, where every
   learning objective already has a stable ID and a spec reference.
2. The **official specification PDF**, searched for the topic, used as supporting wording.

Neither source is allowed to confirm which course a student is actually entered for.
That rule belongs to the course map and it is kept here: mapping a specification is not
the same as confirming a student's route.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path


TUTAIR_ROOT = Path(__file__).resolve().parent
DEFAULT_COURSE_MAP = TUTAIR_ROOT / "course-map" / "data" / "course-map-mvp.json"
DEFAULT_SPEC_DIR = TUTAIR_ROOT / "specifications"
SPEC_CACHE_DIR = TUTAIR_ROOT / ".spec-cache"
MAX_EXCERPT_CHARS = 6000
STOP_WORDS = {
    "the", "and", "for", "with", "how", "why", "what", "into", "from", "that", "this",
    "gcse", "revision", "topic", "paper", "unit", "part", "level",
}


class SpecUnavailable(RuntimeError):
    """The specification could not be read. Mint without it rather than failing."""


@dataclass(frozen=True)
class SpecObjective:
    objective_id: str
    statement: str
    topic: str
    subtopic: str
    spec_reference: str
    board_id: str
    specification_code: str


@dataclass(frozen=True)
class SpecContext:
    """Everything the writer and reviewer are allowed to treat as specification authority."""

    subject: str
    topic: str
    board_id: str = ""
    specification_code: str = ""
    objectives: list[SpecObjective] = field(default_factory=list)
    excerpt: str = ""
    excerpt_source: str = ""

    @property
    def grounded(self) -> bool:
        return bool(self.objectives or self.excerpt)

    def provenance(self) -> str:
        if not self.grounded:
            return "none"
        parts = []
        if self.objectives:
            parts.append(f"course map ({len(self.objectives)} objectives)")
        if self.excerpt_source:
            parts.append(f"specification PDF ({self.excerpt_source})")
        return "; ".join(parts)


# --------------------------------------------------------------------------------------
# Course map
# --------------------------------------------------------------------------------------

def load_course_map(path: Path | None = None) -> dict:
    source = path or DEFAULT_COURSE_MAP
    if not source.exists():
        return {}
    try:
        return json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def iter_objectives(course_map: dict):
    """Walk Subject > Qualification > Exam Board > Tier > Paper > Topic > Sub-topic > Objective."""
    for subject in course_map.get("subjects", []):
        for qualification in subject.get("qualifications", []):
            for board in qualification.get("exam_boards", []):
                for tier in board.get("tiers", []):
                    for paper in tier.get("papers", []):
                        for topic in paper.get("topics", []):
                            for subtopic in topic.get("subtopics", []):
                                for objective in subtopic.get("learning_objectives", []):
                                    yield subject, board, topic, subtopic, objective


def find_objectives(
    course_map: dict,
    subject: str = "",
    topic: str = "",
    board_id: str = "",
) -> list[SpecObjective]:
    """Objectives matching the subject and topic. An empty filter matches everything."""
    wanted_subject = subject.strip().lower()
    wanted_board = board_id.strip().lower()
    terms = keywords(topic)

    matches: list[SpecObjective] = []
    for subject_node, board, topic_node, subtopic, objective in iter_objectives(course_map):
        if wanted_subject and wanted_subject not in subject_node.get("name", "").lower():
            continue
        if wanted_board and wanted_board != board.get("board_id", "").lower():
            continue
        if terms and not objective_matches(terms, topic_node, subtopic, objective):
            continue
        matches.append(
            SpecObjective(
                objective_id=objective.get("objective_id", ""),
                statement=objective.get("statement", ""),
                topic=topic_node.get("name", ""),
                subtopic=subtopic.get("name", ""),
                spec_reference=subtopic.get("spec_reference", "") or topic_node.get("spec_reference", ""),
                board_id=board.get("board_id", ""),
                specification_code=board.get("specification_code", ""),
            )
        )
    return matches


def objective_matches(terms: set[str], topic_node: dict, subtopic: dict, objective: dict) -> bool:
    haystack = " ".join(
        [
            topic_node.get("name", ""),
            subtopic.get("name", ""),
            objective.get("statement", ""),
        ]
    ).lower()
    return any(term in haystack for term in terms)


def keywords(text: str) -> set[str]:
    words = re.findall(r"[a-z]{3,}", (text or "").lower())
    return {word for word in words if word not in STOP_WORDS}


# --------------------------------------------------------------------------------------
# Specification PDFs
# --------------------------------------------------------------------------------------

def spec_dir() -> Path:
    configured = os.getenv("TUTAIR_SPEC_DIR", "").strip()
    return Path(configured) if configured else DEFAULT_SPEC_DIR


def find_spec_pdf(
    specification_code: str = "",
    subject: str = "",
    directory: Path | None = None,
) -> Path | None:
    """Find the specification PDF, preferring an exact specification-code match."""
    folder = directory or spec_dir()
    if not folder.exists():
        return None

    pdfs = sorted(folder.glob("*.pdf"))
    code = specification_code.strip().lower()
    if code:
        for pdf in pdfs:
            if code in pdf.stem.lower():
                return pdf

    # Rank by how many subject words the filename matches. "Computer Science" must not
    # settle for "Combined Science" just because it also contains the word "science".
    terms = keywords(subject)
    if not terms:
        return None

    best: tuple[int, Path] | None = None
    for pdf in pdfs:
        stem = pdf.stem.lower()
        score = sum(1 for term in terms if term in stem)
        if score and (best is None or score > best[0]):
            best = (score, pdf)
    return best[1] if best else None


def spec_text(pdf_path: Path, cache_dir: Path | None = None) -> str:
    """Extract the whole specification once, then reuse the cached text."""
    cache_root = cache_dir or SPEC_CACHE_DIR
    cache_root.mkdir(parents=True, exist_ok=True)
    cached = cache_root / f"{pdf_path.stem}.txt"
    if cached.exists():
        return cached.read_text(encoding="utf-8")

    try:
        from pypdf import PdfReader
    except ImportError as error:  # pragma: no cover - depends on the machine
        raise SpecUnavailable("pypdf is not installed. Run: pip install -r requirements.txt") from error

    # Exam board PDFs are often encrypted, and some need `cryptography` to open at all.
    # A specification we cannot read is a reason to mint without one, never a reason to
    # lose the transcript and the questions.
    try:
        reader = PdfReader(str(pdf_path))
        pages = []
        for page in reader.pages:
            try:
                pages.append(page.extract_text() or "")
            except Exception:  # pragma: no cover - a single bad page must not stop the run
                pages.append("")
    except Exception as error:
        raise SpecUnavailable(f"Could not read {pdf_path.name}: {error}") from error

    text = "\n".join(pages)
    cached.write_text(text, encoding="utf-8")
    return text


def clean_pdf_text(text: str) -> str:
    """PDF bullet glyphs extract as replacement characters. Turn them into plain dashes."""
    replaced = re.sub(r"[�•●]", "-", text)
    return re.sub(r"(?m)^\s*-\s*-\s*", "- ", replaced)


def topic_excerpt(text: str, topic: str, max_chars: int = MAX_EXCERPT_CHARS) -> str:
    """Pull the parts of the specification that mention the topic."""
    terms = keywords(topic)
    if not terms or not text:
        return ""

    paragraphs = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    if len(paragraphs) < 5:
        paragraphs = [line.strip() for line in text.splitlines() if line.strip()]

    scored = []
    for index, paragraph in enumerate(paragraphs):
        lowered = paragraph.lower()
        score = sum(lowered.count(term) for term in terms)
        if score:
            scored.append((score, index, paragraph))

    scored.sort(key=lambda row: (-row[0], row[1]))

    chosen: list[str] = []
    budget = max_chars
    for _, _, paragraph in scored:
        snippet = re.sub(r"[ \t]+", " ", clean_pdf_text(paragraph))
        if len(snippet) > budget:
            snippet = snippet[:budget]
        chosen.append(snippet)
        budget -= len(snippet)
        if budget <= 0:
            break
    return "\n\n".join(chosen).strip()


# --------------------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------------------

def build_spec_context(
    subject: str,
    topic: str,
    board_id: str = "",
    course_map_path: Path | None = None,
    specification_dir: Path | None = None,
) -> SpecContext:
    course_map = load_course_map(course_map_path)
    objectives = find_objectives(course_map, subject=subject, topic=topic, board_id=board_id)

    code = objectives[0].specification_code if objectives else ""
    board = objectives[0].board_id if objectives else board_id

    excerpt = ""
    excerpt_source = ""
    pdf = find_spec_pdf(code, subject, specification_dir)
    if pdf is not None:
        try:
            excerpt = topic_excerpt(spec_text(pdf), topic)
        except SpecUnavailable as error:
            print(f"Specification PDF skipped. {error}")
            excerpt = ""
        if excerpt:
            excerpt_source = pdf.name

    return SpecContext(
        subject=subject,
        topic=topic,
        board_id=board,
        specification_code=code,
        objectives=objectives,
        excerpt=excerpt,
        excerpt_source=excerpt_source,
    )


def format_objectives(objectives: list[SpecObjective]) -> str:
    if not objectives:
        return ""
    lines = []
    for objective in objectives:
        reference = f" [{objective.spec_reference}]" if objective.spec_reference else ""
        lines.append(f"- {objective.objective_id}{reference}: {objective.statement}")
    return "\n".join(lines)
