"""Local read-only web viewer for processed TutAIR Markdown notes."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import unquote, urlparse

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


from tutair_intake import default_inbox_root

# The viewer must look where intake writes, so both resolve the same way:
# TUTAIR_INBOX_ROOT if set, otherwise the MyPKA folder under the current user's home.
DEFAULT_TUTAIR_ROOT = default_inbox_root()
TUTAIR_MVP_ROOT = Path(__file__).resolve().parent
TUTAIR_ENV_PATH = TUTAIR_MVP_ROOT / ".env"
VIEWER_UI_VERSION = "approved-dashboard-2026-07-09"
TUTOR_UI_VERSION = "ai-tutor-v1-2026-07-10"
SECTIONS = [
    "Tiny Summary",
    "Key Facts",
    "What This Means",
    "Exam-Style Questions",
    "Multiple Choice Questions",
    "Flashcards",
    "Next Revision Task",
    "Exam Board Mapping",
]


@dataclass(frozen=True)
class LearningNote:
    id: str
    path: Path
    title: str
    subject: str
    topic: str
    exam_board_status: str
    possible_exam_board: str
    sections: dict[str, str]


def find_processed_notes(root: Path = DEFAULT_TUTAIR_ROOT) -> list[LearningNote]:
    notes: list[LearningNote] = []
    if not root.exists():
        return notes

    for path in sorted(root.glob("**/processed/*.md")):
        notes.append(parse_processed_note(path, root))
    return sorted(notes, key=lambda note: (note.subject.lower(), note.topic.lower(), note.title.lower()))


def parse_processed_note(path: Path, root: Path = DEFAULT_TUTAIR_ROOT) -> LearningNote:
    text = path.read_text(encoding="utf-8")
    metadata = parse_frontmatter(text)
    title = extract_title(text) or f"{metadata.get('subject', 'GCSE')} - {metadata.get('topic', path.stem)}"
    subject = metadata.get("subject", "Unknown")
    topic = metadata.get("topic", path.stem)
    sections = {section: extract_section(text, section) for section in SECTIONS}
    return LearningNote(
        id=note_id(path, root),
        path=path,
        title=title,
        subject=subject,
        topic=topic,
        exam_board_status=metadata.get("exam_board_status", "unconfirmed"),
        possible_exam_board=metadata.get("possible_exam_board", "unknown"),
        sections=sections,
    )


def parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}

    metadata: dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" not in line or line.startswith(" ") or line.startswith("-"):
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip('"')
    return metadata


def extract_title(text: str) -> str:
    match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def extract_section(text: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\s*$", text, re.MULTILINE)
    if not match:
        return ""
    start = match.end()
    next_heading = re.search(r"^## .+$", text[start:], re.MULTILINE)
    end = start + next_heading.start() if next_heading else len(text)
    return text[start:end].strip()


def note_id(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def group_notes(notes: list[LearningNote]) -> dict[str, list[LearningNote]]:
    grouped: dict[str, list[LearningNote]] = {}
    for note in notes:
        grouped.setdefault(note.subject, []).append(note)
    return grouped


def render_home(notes: list[LearningNote]) -> str:
    active_note = notes[0] if notes else None
    return render_page(notes, active_note)


def render_note(notes: list[LearningNote], requested_id: str) -> str:
    active_note = next((note for note in notes if note.id == requested_id), None)
    return render_page(notes, active_note)


def render_tutor(notes: list[LearningNote], requested_id: str = "", requested_subject: str = "") -> str:
    active_note = next((note for note in notes if note.id == requested_id), None) if requested_id else None
    note_options = render_tutor_note_options(notes, active_note)
    subject_label = subject_label_from_id(requested_subject)
    note_payload = render_note_payload(active_note, subject_label)
    context = tutor_context(active_note, {"subject": subject_label} if subject_label else {})
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TutAIR AI Tutor</title>
  <meta name="tutair-ui-version" content="{TUTOR_UI_VERSION}">
  <style>{CSS}</style>
</head>
<body>
  <main class="tutor-shell" aria-labelledby="tutor-title">
    <aside class="tutor-rail" aria-label="Tutor context">
      <a class="brand" href="/" aria-label="Back to TutAIR home">
        <span class="brand-mark">TA</span>
        <span>
          <strong>Tut<span>AIR</span></strong>
          <small>AI Tutor</small>
        </span>
      </a>
      <section class="tutor-context-card">
        <p class="eyebrow">Current Context</p>
        <dl>
          <div><dt>Student</dt><dd data-context-field="student_name">{html.escape(context["student_name"])}</dd></div>
          <div><dt>Year Group</dt><dd data-context-field="year_group">{html.escape(context["year_group"])}</dd></div>
          <div><dt>Selected Subjects</dt><dd data-context-field="selected_subjects">{html.escape(context["selected_subjects"])}</dd></div>
          <div><dt>Subject</dt><dd>{html.escape(context["subject"])}</dd></div>
          <div><dt>Exam Board</dt><dd>{html.escape(context["exam_board"])}</dd></div>
          <div><dt>Topic</dt><dd>{html.escape(context["topic"])}</dd></div>
        </dl>
      </section>
      <section class="tutor-topic-picker">
        <h2>Topics</h2>
        {note_options}
      </section>
      <a class="quiet-link" href="/">Back to revision viewer</a>
    </aside>
    <section class="tutor-main" aria-label="AI Tutor chat">
      <header class="tutor-header">
        <div>
          <p class="eyebrow">Learning Mission</p>
          <h1 id="tutor-title">TutAIR Coach</h1>
          <p data-tutor-subtitle>One tiny step at a time. No walls of text.</p>
        </div>
        <div class="tutor-header-actions">
          <button class="secondary-action" type="button" data-tutor-action="new-chat">New Chat</button>
          <button class="secondary-action" type="button" data-tutor-action="clear">Clear Chat</button>
        </div>
      </header>
      <section class="lesson-status" aria-label="Learning progress">
        <div class="xp-orb" data-xp-ring><strong data-lesson-xp>0</strong><span>XP</span></div>
        <div class="lesson-progress-copy">
          <strong data-lesson-title>{html.escape(active_note.topic if active_note else subject_label or "Choose a topic")}</strong>
          <span data-lesson-step>Ready to start</span>
          <div class="lesson-progress-bar"><span data-lesson-progress style="width: 0%"></span></div>
        </div>
        <div class="streak-chip" data-lesson-streak>1 day streak</div>
      </section>
      <section class="suggested-prompts" aria-label="One-click study actions">
        <button type="button" data-tutor-mode="lesson" data-prompt="Start an interactive tiny-step lesson for this topic.">Start Lesson</button>
        <button type="button" data-tutor-mode="explain" data-prompt="Explain this topic as one tiny lesson step.">Explain Simpler</button>
        <button type="button" data-tutor-mode="example" data-prompt="Give another example as a tiny lesson step.">Give Another Example</button>
        <button type="button" data-tutor-mode="youtube-summary" data-prompt="Explain my YouTube summary as a tiny lesson step.">Show Video</button>
        <button type="button" data-tutor-mode="flashcards" data-prompt="Create flashcards as an interactive lesson reward.">Create Flashcards</button>
        <button type="button" data-tutor-mode="exam-question" data-prompt="Give me one GCSE question as the next lesson step.">GCSE Question</button>
        <button type="button" data-tutor-mode="quiz" data-prompt="Test me with one mini question as the next lesson step.">Test Me</button>
        <button type="button" data-tutor-mode="continue" data-prompt="Continue the lesson with the next tiny step.">Continue</button>
      </section>
      <section class="learning-stage" aria-label="Interactive lesson" aria-live="polite" data-learning-stage></section>
      <section class="chat-window compact" aria-label="Conversation history" aria-live="polite" data-chat-history></section>
      <section class="tutor-save-panel" data-tutor-save-panel hidden>
        <span>Flashcards ready to save for later revision.</span>
        <button class="secondary-action" type="button" data-tutor-action="save-flashcards">Save Flashcards</button>
      </section>
      <form class="chat-composer" data-tutor-form>
        <label for="tutor-message">Message</label>
        <textarea id="tutor-message" name="message" rows="3" placeholder="Ask TutAIR for help with this topic..."></textarea>
        <button class="primary-action" type="submit" data-tutor-send>Send</button>
      </form>
      <p class="tutor-error" role="alert" data-tutor-error hidden></p>
    </section>
  </main>
  <script id="note-data" type="application/json">{note_payload}</script>
  <script>{JS}</script>
</body>
</html>"""


def render_tutor_note_options(notes: list[LearningNote], active_note: LearningNote | None) -> str:
    if not notes:
        return '<p class="muted">No processed topics yet.</p>'
    return "\n".join(
        f'<a class="topic-link{" active" if active_note and note.id == active_note.id else ""}" href="/tutor?note={html.escape(note.id)}">'
        f'<span class="topic-icon">{subject_icon(note.subject)}</span><span>{html.escape(note.topic)}</span></a>'
        for note in notes
    )


def render_page(notes: list[LearningNote], active_note: LearningNote | None) -> str:
    subject_nav = render_subject_nav(notes, active_note)
    topic_nav = render_topic_nav(notes, active_note)
    content = render_note_content(active_note) if active_note else render_empty_state()
    topic_label = html.escape(active_note.topic if active_note else "Choose a topic")
    subject_label = html.escape(active_note.subject if active_note else "TutAIR")
    note_payload = render_note_payload(active_note)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TutAIR Revision Viewer</title>
  <meta name="tutair-ui-version" content="{VIEWER_UI_VERSION}">
  <style>{CSS}</style>
</head>
<body>
  <div id="profile-app" class="profile-app" hidden></div>
  <div class="app-shell">
    <aside class="side-rail" aria-label="TutAIR navigation">
      <a class="brand" href="/" aria-label="TutAIR home">
        <span class="brand-mark">TA</span>
        <span>
          <strong>Tut<span>AIR</span></strong>
          <small>Focus. Understand. Remember.</small>
        </span>
      </a>
      <section class="rail-section">
        <h2>Subjects</h2>
        {subject_nav}
        <button class="rail-button placeholder" type="button" disabled>+ Add Subject</button>
      </section>
      <section class="rail-section plan">
        <h2>Today's Plan</h2>
        <label><input type="checkbox" checked disabled> 1 topic review</label>
        <label><input type="checkbox" checked disabled> 5 flashcards</label>
        <label><input type="checkbox" disabled> 1 quiz</label>
      </section>
      <section class="tip-card">
        <h2>Tip of the day</h2>
        <p>Try explaining this topic out loud like you're teaching a friend.</p>
      </section>
      <button class="break-button" type="button" disabled>Take a Break</button>
    </aside>
    <main class="workspace">
      <header class="hero">
        <div>
          <h1>GCSE Revision Viewer</h1>
          <p>You've got this! Small steps, big progress.</p>
        </div>
        <div class="hero-actions" aria-label="Display controls">
          <button type="button" data-action="focus">Focus Mode</button>
          <button type="button" data-action="coming-soon" data-feature="Colour Theme">Colour Theme</button>
          <button class="sun" type="button" disabled aria-label="Brightness"></button>
          <div class="streak" aria-label="Study streak">
            <strong>Keep Going!</strong>
            <span>3-day streak</span>
          </div>
        </div>
      </header>
      <nav class="crumb-bar" aria-label="Current topic">
        <div class="crumbs">
          <span>{subject_label}</span>
          <span aria-hidden="true">/</span>
          <span>Cell biology</span>
          <span aria-hidden="true">/</span>
          <strong>{topic_label}</strong>
        </div>
        <div class="toolbar">
          <button class="save" type="button" data-action="save-topic">Save Topic</button>
          <button class="export" type="button" data-action="coming-soon" data-feature="Export">Export</button>
          <button class="review" type="button" data-action="mark-reviewed">Mark as Reviewed</button>
        </div>
      </nav>
      <div class="study-grid">
        <aside class="topic-panel" aria-label="Topics">
          <h2>Topics</h2>
          {topic_nav}
          <div class="help-card">
            <strong>Need Help?</strong>
            <p>Stuck on a topic? Ask your study buddy for help.</p>
            <button type="button" disabled>Ask TutAIR</button>
          </div>
        </aside>
        <section class="content" aria-label="Revision note">
          {content}
        </section>
        <aside class="action-panel" aria-label="Study tools">
          {render_action_panel(active_note)}
        </aside>
      </div>
      <footer class="encouragement" aria-label="Encouragement">
        <span>You're learning!</span>
        <span>One step at a time</span>
        <span>Progress over perfection</span>
        <span>Celebrate tiny wins</span>
        <button type="button" disabled>I'm proud of you!</button>
      </footer>
    </main>
  </div>
  <div class="toast" role="status" aria-live="polite" hidden></div>
  <script id="note-data" type="application/json">{note_payload}</script>
  <script>{JS}</script>
</body>
</html>"""


def subject_label_from_id(subject_id: str) -> str:
    labels = {
        "maths": "Maths",
        "biology": "Biology",
        "chemistry": "Chemistry",
        "physics": "Physics",
        "english-language": "English Language",
        "english-literature": "English Literature",
        "geography": "Geography",
        "history": "History",
        "business": "Business",
        "computer-science": "Computer Science",
        "engineering": "Engineering",
        "construction": "Construction",
        "food-nutrition": "Food & Nutrition",
        "pe": "PE",
        "re": "RE",
        "art-design": "Art & Design",
        "music": "Music",
        "economics": "Economics",
        "environmental-science": "Environmental Science",
        "other": "Other",
    }
    clean = subject_id.strip().lower()
    return labels.get(clean, subject_id.replace("-", " ").title() if subject_id else "")


def subject_id_from_label(subject: str) -> str:
    return subject.strip().lower().replace("&", "").replace("/", " ").replace("  ", " ").replace(" ", "-")


def render_note_payload(note: LearningNote | None, subject: str = "") -> str:
    if not note:
        payload = {
            "id": "",
            "title": subject or "TutAIR",
            "subject": subject,
            "topic": "Topic not selected yet" if subject else "",
            "exam_board_status": "unknown",
            "possible_exam_board": "unknown",
            "sections": {},
            "flashcards": [],
            "questions": [],
        }
        return json.dumps(payload).replace("</", "<\\/")
    payload = {
        "id": note.id,
        "title": note.title,
        "subject": note.subject,
        "topic": note.topic,
        "exam_board_status": note.exam_board_status,
        "possible_exam_board": note.possible_exam_board,
        "sections": note.sections,
        "flashcards": parse_flashcards(note.sections.get("Flashcards", "")),
        "questions": load_quiz_questions(note),
    }
    return json.dumps(payload).replace("</", "<\\/")


def load_quiz_questions(note: LearningNote) -> list[dict[str, object]]:
    """Prefer real minted multiple-choice questions; fall back to the written prompts.

    Minted questions live in a sidecar `<note>-questions.json` written by
    tutair_questions.py. Only questions the independent reviewer approved are served.
    """
    minted = read_minted_questions(note.path)
    if minted:
        return minted
    return parse_questions(note.sections.get("Exam-Style Questions", ""))


def read_minted_questions(note_path: Path) -> list[dict[str, object]]:
    sidecar = note_path.with_name(f"{note_path.stem}-questions.json")
    if not sidecar.exists():
        return []

    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []

    questions: list[dict[str, object]] = []
    for item in payload.get("questions", []):
        if item.get("status") != "approved":
            continue
        options = [
            {"id": str(option.get("id", "")), "text": str(option.get("text", ""))}
            for option in item.get("options", [])
        ]
        answer_id = str(item.get("answer_id", ""))
        answer_text = next((option["text"] for option in options if option["id"] == answer_id), "")
        timestamp = str(item.get("source_timestamp", "")).strip()
        questions.append(
            {
                "question": str(item.get("stem", "")),
                "options": options,
                "answer_id": answer_id,
                "answer": f"{answer_id}. {answer_text}".strip(". "),
                "explanation": str(item.get("explanation", "")),
                "timestamp": timestamp,
                "objective_id": str(item.get("objective_id", "")).strip(),
            }
        )
    return questions


def parse_flashcards(markdown: str) -> list[dict[str, str]]:
    cards: list[dict[str, str]] = []
    current_question = ""
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("Q:"):
            current_question = stripped.removeprefix("Q:").strip()
        elif stripped.startswith("A:") and current_question:
            cards.append({"question": current_question, "answer": stripped.removeprefix("A:").strip()})
            current_question = ""
    return cards


def parse_questions(markdown: str) -> list[dict[str, str]]:
    questions: list[dict[str, str]] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        match = re.match(r"^\d+\.\s+(.+)$", stripped)
        if match:
            question = match.group(1).strip()
            questions.append({"question": question, "answer": "Use the note above to answer in your own words."})
    return questions


def render_subject_nav(notes: list[LearningNote], active_note: LearningNote | None) -> str:
    if not notes:
        return '<p class="rail-empty">No subjects yet</p>'

    parts: list[str] = []
    for subject in group_notes(notes):
        first_note = group_notes(notes)[subject][0]
        active = " active" if active_note and subject == active_note.subject else ""
        icon = subject_icon(subject)
        parts.append(
            f'<a class="subject-link{active}" href="/note/{html.escape(first_note.id)}">'
            f'<span class="subject-icon">{icon}</span>'
            f'<span>{html.escape(subject)}</span>'
            "</a>"
        )
    for subject in ["Maths", "English", "History", "Geography"]:
        if subject not in group_notes(notes):
            parts.append(
                f'<button class="subject-link ghost" type="button" disabled>'
                f'<span class="subject-icon">{subject_icon(subject)}</span>'
                f'<span>{html.escape(subject)}</span>'
                "</button>"
            )
    return "\n".join(parts)


def render_topic_nav(notes: list[LearningNote], active_note: LearningNote | None) -> str:
    if not notes:
        return '<p class="muted">No processed TutAIR notes found yet.</p>'

    active_subject = active_note.subject if active_note else notes[0].subject
    visible_notes = group_notes(notes).get(active_subject, notes)
    parts: list[str] = ['<div class="topic-list">']
    for index, note in enumerate(visible_notes):
        active = " active" if active_note and note.id == active_note.id else ""
        icon = ["◎", "◉", "✣", "◆", "⌕"][index % 5]
        parts.append(
            f'<a class="topic-link{active}" data-note-id="{html.escape(note.id)}" href="/note/{html.escape(note.id)}">'
            f'<span class="topic-icon">{icon}</span>'
            f'<span><strong>{html.escape(note.topic)}</strong>'
            f'<small>{html.escape(note.exam_board_status)}</small></span>'
            f'<b aria-hidden="true">›</b>'
            "</a>"
        )
    placeholders = ["Cell structure", "Specialised cells", "Plant cells", "Microscopy"]
    for index, topic in enumerate(placeholders):
        if topic.lower() not in {note.topic.lower() for note in visible_notes}:
            icon = ["◉", "✣", "◆", "⌕"][index % 4]
            parts.append(
                f'<button class="topic-link ghost" type="button" disabled>'
                f'<span class="topic-icon">{icon}</span>'
                f'<span><strong>{html.escape(topic)}</strong><small>unconfirmed</small></span>'
                "</button>"
            )
    parts.append("</div>")
    return "\n".join(parts)


def subject_icon(subject: str) -> str:
    icons = {
        "science": "S",
        "maths": "M",
        "english": "E",
        "history": "H",
        "geography": "G",
        "computer science": "CS",
        "business enterprise": "B",
        "construction": "C",
    }
    return icons.get(subject.lower(), subject[:1].upper())


def render_note_content(note: LearningNote) -> str:
    sections = "\n".join(render_section(name, note.sections.get(name, "")) for name in SECTIONS)
    return f"""
<article class="note">
  <div class="note-heading">
    <div>
      <p class="eyebrow">{html.escape(note.subject)}</p>
      <h2>{html.escape(note.topic)}</h2>
    </div>
    <div class="status">
      <span>Status: {html.escape(note.exam_board_status)}</span>
      <small>{html.escape(note.possible_exam_board)}</small>
    </div>
  </div>
  {sections}
  <details class="source">
    <summary>Source file</summary>
    <code>{html.escape(str(note.path))}</code>
  </details>
</article>
"""


def render_section(title: str, body: str) -> str:
    rendered = render_markdown_block(body) if body else '<p class="muted">Not filled yet.</p>'
    section_class = slugify_section(title)
    return f"""
<section class="revision-section {section_class}">
  <button class="collapse-dot" type="button" disabled aria-label="{html.escape(title)} is expanded"></button>
  <h3>{section_icon(title)} {html.escape(title)}</h3>
  {rendered}
</section>
"""


def slugify_section(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def section_icon(title: str) -> str:
    icons = {
        "Tiny Summary": "TS",
        "Key Facts": "KF",
        "What This Means": "WM",
        "Exam-Style Questions": "Q",
        "Flashcards": "FC",
        "Next Revision Task": "NR",
        "Exam Board Mapping": "EB",
    }
    return f'<span class="section-icon">{icons.get(title, "N")}</span>'


def render_action_panel(note: LearningNote | None) -> str:
    status = html.escape(note.exam_board_status if note else "none")
    return f"""
<section class="side-card quick-actions">
  <h2>Quick Actions</h2>
  <button class="flashcards" type="button" data-action="flashcards">Flashcards</button>
  <button class="quiz" type="button" data-action="quiz">Quiz Me</button>
  <button class="mindmap" type="button" data-action="coming-soon" data-feature="Mind Map">Mind Map</button>
  <button class="notes" type="button" data-action="notes">Notes</button>
  <button class="read" type="button" data-action="read-aloud">Read Aloud</button>
</section>
<section class="side-card timer">
  <h2>Focus Timer</h2>
  <div><strong>25:00</strong><button type="button" disabled aria-label="Start focus timer">▶</button></div>
  <p>Focus time <a href="#" aria-disabled="true">Skip Break</a></p>
</section>
<section class="side-card progress">
  <h2>Progress</h2>
  <div class="progress-row">
    <span>This Topic</span>
    <strong>0%</strong>
  </div>
  <label>Overall Progress <span>12%</span></label>
  <div class="bar"><span></span></div>
  <p class="muted">Mapping status: {status}</p>
</section>
"""


def render_markdown_block(markdown: str) -> str:
    lines = markdown.splitlines()
    output: list[str] = []
    list_items: list[str] = []

    def flush_list() -> None:
        if list_items:
            output.append("<ul>" + "".join(list_items) + "</ul>")
            list_items.clear()

    for line in lines:
        stripped = line.strip()
        if not stripped:
            flush_list()
            continue
        if stripped.startswith("- "):
            list_items.append(f"<li>{html.escape(stripped[2:])}</li>")
            continue
        if re.match(r"^\d+\.\s+", stripped):
            list_items.append(f"<li>{html.escape(re.sub(r'^\\d+\\.\\s+', '', stripped))}</li>")
            continue
        flush_list()
        if stripped.startswith("Q:") or stripped.startswith("A:"):
            output.append(f"<p class=\"flashline\">{html.escape(stripped)}</p>")
        else:
            output.append(f"<p>{html.escape(stripped)}</p>")

    flush_list()
    return "\n".join(output)


def render_empty_state() -> str:
    return """
<article class="empty">
  <h2>No processed notes yet</h2>
  <p>Create a TutAIR capture, then run the V2 processor. Processed notes appear here automatically.</p>
  <code>Team Inbox/TutAIR/YYYY/MM/processed/</code>
</article>
"""


class TutorProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class TutorEnvStatus:
    checked_path: Path
    dotenv_installed: bool
    dotenv_loaded: bool
    api_key_found: bool
    message: str


_TUTOR_ENV_STATUS: TutorEnvStatus | None = None


def load_tutair_env(env_path: Path = TUTAIR_ENV_PATH) -> TutorEnvStatus:
    dotenv_installed = load_dotenv is not None
    dotenv_loaded = False
    message = ""
    if env_path.is_file():
        if dotenv_installed:
            dotenv_loaded = bool(load_dotenv(env_path))
            message = "Loaded .env file with python-dotenv."
        else:
            dotenv_loaded = load_env_file_without_dependency(env_path)
            message = "python-dotenv is not installed; loaded .env with the built-in fallback parser."
    elif env_path.is_dir():
        dotenv_loaded = load_env_directory_without_dependency(env_path)
        message = ".env path is a directory, not a file; loaded supported entries from inside it as a compatibility fallback."
    else:
        message = ".env file was not found."
    status = TutorEnvStatus(
        checked_path=env_path,
        dotenv_installed=dotenv_installed,
        dotenv_loaded=dotenv_loaded,
        api_key_found=bool(os.getenv("OPENAI_API_KEY", "").strip()),
        message=message,
    )
    log_tutor_env_status(status)
    global _TUTOR_ENV_STATUS
    _TUTOR_ENV_STATUS = status
    return status


def load_env_file_without_dependency(env_path: Path) -> bool:
    loaded = False
    for line in env_path.read_text(encoding="utf-8").splitlines():
        loaded = set_env_from_dotenv_line(line) or loaded
    return loaded


def load_env_directory_without_dependency(env_dir: Path) -> bool:
    loaded = False
    for child in env_dir.iterdir():
        if not child.is_file():
            continue
        child_loaded = False
        try:
            for line in child.read_text(encoding="utf-8").splitlines():
                child_loaded = set_env_from_dotenv_line(line, override=True) or child_loaded
        except UnicodeDecodeError:
            continue
        if not child_loaded:
            child_loaded = set_env_from_dotenv_line(child.name) or child_loaded
        loaded = child_loaded or loaded
    return loaded


def set_env_from_dotenv_line(line: str, override: bool = False) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return False
    key, value = stripped.split("=", 1)
    key = key.strip()
    value = value.strip().strip('"').strip("'")
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
        return False
    if override:
        os.environ[key] = value
    else:
        os.environ.setdefault(key, value)
    return True


def log_tutor_env_status(status: TutorEnvStatus) -> None:
    print(
        "TutAIR env check: "
        f"python-dotenv installed={status.dotenv_installed}; "
        f"checked_path={status.checked_path}; "
        f"dotenv_loaded={status.dotenv_loaded}; "
        f"OPENAI_API_KEY found={status.api_key_found}; "
        f"{status.message}"
    )


def tutor_env_status() -> TutorEnvStatus:
    global _TUTOR_ENV_STATUS
    if _TUTOR_ENV_STATUS is None:
        _TUTOR_ENV_STATUS = load_tutair_env()
    return _TUTOR_ENV_STATUS


def tutor_context(note: LearningNote | None, profile: dict[str, object]) -> dict[str, str]:
    student_name = str(profile.get("name") or profile.get("display_name") or "Not set")
    year_group = str(profile.get("yearGroup") or profile.get("year_group") or "Not set")
    selected_subjects = profile_selected_subjects(profile)
    subject = note.subject if note else str(profile.get("currentSubject") or profile.get("subject") or "Not set")
    topic = note.topic if note else str(profile.get("currentTopic") or "Topic not selected yet")
    exam_board = "Unknown"
    if note and note.exam_board_status == "confirmed":
        exam_board = note.possible_exam_board or "Confirmed"
    elif note and note.possible_exam_board not in ("", "unknown"):
        exam_board = f"{note.possible_exam_board} (unconfirmed)"
    profile_boards = profile.get("examBoards")
    if isinstance(profile_boards, dict) and subject:
        subject_key = subject_id_from_label(subject)
        exam_board = str(profile_boards.get(subject_key) or profile_boards.get(subject.lower()) or exam_board)
    return {
        "student_name": student_name,
        "year_group": year_group,
        "selected_subjects": selected_subjects,
        "subject": subject,
        "exam_board": exam_board,
        "topic": topic,
    }


def profile_selected_subjects(profile: dict[str, object]) -> str:
    subjects = profile.get("subjects")
    if not isinstance(subjects, list) or not subjects:
        return "Not set"
    return ", ".join(str(subject).replace("-", " ").title() for subject in subjects)


def note_grounding_context(note: LearningNote | None) -> str:
    if not note:
        return ""
    useful_sections = [
        "Tiny Summary",
        "Key Facts",
        "What This Means",
        "Exam-Style Questions",
        "Flashcards",
        "Exam Board Mapping",
    ]
    blocks = []
    for section in useful_sections:
        value = note.sections.get(section, "").strip()
        if value:
            blocks.append(f"{section}: {value[:900]}")
    return "\n".join(blocks)


def build_tutor_messages(
    message: str,
    history: list[dict[str, str]],
    context: dict[str, str],
    note: LearningNote | None,
    mode: str = "general",
) -> list[dict[str, str]]:
    note_context = note_grounding_context(note)
    system = (
        "You are TutAIR, a warm private GCSE tutor for one student. Turn every response into a tiny interactive lesson step. "
        "Return strict JSON only. Do not return markdown, HTML, or prose outside JSON. "
        "Keep every text field short: no field should be more than 2 short sentences. "
        "Never assume an exam board is confirmed when the context says unknown or unconfirmed. "
        f"Student context: Name: {context['student_name']}; Year Group: {context['year_group']}; "
        f"Selected Subjects: {context['selected_subjects']}; Current Subject: {context['subject']}; "
        f"Exam Board: {context['exam_board']}; Current Topic: {context['topic']}."
    )
    system += (
        " JSON schema: {"
        "\"title\": string, "
        "\"step_label\": string, "
        "\"difficulty\": \"easy\"|\"medium\"|\"hard\", "
        "\"estimated_time\": string, "
        "\"robot_reaction\": string, "
        "\"explanation\": string, "
        "\"analogy\": string, "
        "\"important_fact\": string, "
        "\"example\": string, "
        "\"picture_placeholder\": string, "
        "\"quiz\": {\"question\": string, \"choices\": [string], \"correct_index\": number, \"explanation_if_wrong\": string}, "
        "\"gcse_question\": {\"question\": string, \"marks\": number, \"mark_scheme\": string, \"model_answer\": string}, "
        "\"flashcards\": [{\"front\": string, \"back\": string, \"difficulty\": string}], "
        "\"xp\": number, "
        "\"progress_delta\": number, "
        "\"badge\": string, "
        "\"next_step\": string, "
        "\"mission_complete\": boolean, "
        "\"suggested_next_topic\": string"
        "}. "
        "For normal explanation steps include a quiz with 3 choices. For GCSE question mode include gcse_question. "
        "For flashcard mode include flashcards. For mission completion set mission_complete true."
    )
    mode_instruction = tutor_mode_instruction(mode)
    if mode_instruction:
        system += f" Tutor mode: {mode_instruction}"
    if note_context:
        system += f"\nGrounding from the current learning note:\n{note_context}"
    messages = [{"role": "system", "content": system}]
    for item in history[-10:]:
        role = item.get("role", "")
        content = item.get("content", "")
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content[:2000]})
    messages.append({"role": "user", "content": message})
    return messages


def tutor_mode_instruction(mode: str) -> str:
    instructions = {
        "lesson": (
            "Start at step 1. Ask what we are learning today, name the topic, give easy difficulty, estimated time, and a Start-style next step."
        ),
        "continue": (
            "Continue the mission with the next tiny lesson step. Increase challenge slightly only if the previous step was easy."
        ),
        "exam-question": (
            "Generate one realistic GCSE question with marks, mark scheme, and model answer in the gcse_question object."
        ),
        "exam-answer": (
            "Mark the student's answer. Give a score, explain what was good, explain what could improve, and show a model answer."
        ),
        "flashcards": (
            "Generate 4 to 6 flashcards. Each flashcard must include front, back, and difficulty."
        ),
        "revision-notes": (
            "Create concise GCSE revision notes with headings, bullet points, examples, and memory tips."
        ),
        "quiz": (
            "Generate one mini multiple-choice question for the next lesson step."
        ),
        "youtube-summary": (
            "Use the current learning note as the YouTube summary context. Explain it simply and extract GCSE revision points."
        ),
        "test": "Ask one short check question, wait for the answer, then mark it kindly.",
        "explain": "Explain the topic like a patient private tutor using simple language and one example.",
        "example": "Give one clear example and explain how it connects to GCSE exam success.",
    }
    return instructions.get(mode, "")


def call_configured_ai_provider(messages: list[dict[str, str]]) -> str:
    status = tutor_env_status()
    provider = os.getenv("TUTAIR_AI_PROVIDER", "openai").strip().lower()
    if provider != "openai":
        raise TutorProviderError(f"TutAIR AI provider '{provider}' is not supported yet.")
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise TutorProviderError(
            "OPENAI_API_KEY is not set, so the AI Tutor cannot contact the configured provider yet. "
            f"Checked .env path: {status.checked_path}"
        )
    model = os.getenv("TUTAIR_AI_MODEL", "gpt-4o-mini").strip()
    log_openai_request_config(model, api_key)
    body = json.dumps({"model": model, "messages": messages, "temperature": 0.45}).encode("utf-8")
    request = Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        response_body = read_openai_error_body(exc)
        log_openai_http_error(exc.code, response_body)
        if exc.code == 401:
            raise TutorProviderError(
                "OpenAI authentication failed. TutAIR found an OPENAI_API_KEY, but OpenAI rejected it. "
                f"Checked .env path: {status.checked_path}. "
                "Make sure the .env file contains the full key value on a line like OPENAI_API_KEY=sk-..."
            ) from exc
        raise TutorProviderError(f"AI provider returned HTTP {exc.code}. See server log for the OpenAI response body.") from exc
    except URLError as exc:
        raise TutorProviderError("TutAIR could not reach the configured AI provider.") from exc
    try:
        return payload["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise TutorProviderError("AI provider returned an unexpected response.") from exc


def log_openai_request_config(model: str, api_key: str) -> None:
    print(
        "TutAIR OpenAI request: "
        "endpoint=https://api.openai.com/v1/chat/completions; "
        "authorization_header=Bearer <redacted>; "
        f"api_key_present={bool(api_key)}; "
        f"api_key_prefix={api_key[:7] if api_key else 'missing'}...; "
        f"api_key_length={len(api_key)}; "
        f"model={model}"
    )


def read_openai_error_body(exc: HTTPError) -> str:
    try:
        raw = exc.read()
    except Exception:
        return ""
    return raw.decode("utf-8", errors="replace")[:4000]


def log_openai_http_error(status_code: int, response_body: str) -> None:
    safe_body = sanitize_openai_log_text(response_body)
    print(f"TutAIR OpenAI error: http_status={status_code}; response_body={safe_body}")


def sanitize_openai_log_text(text: str) -> str:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    sanitized = text
    if api_key:
        sanitized = sanitized.replace(api_key, "<redacted-openai-key>")
    sanitized = re.sub(r"sk-[A-Za-z0-9_-]+", "sk-<redacted>", sanitized)
    return sanitized


class TutairRequestHandler(BaseHTTPRequestHandler):
    tutair_root = DEFAULT_TUTAIR_ROOT

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        notes = find_processed_notes(self.tutair_root)
        if parsed.path == "/":
            self.respond_html(render_home(notes))
            return
        if parsed.path.startswith("/note/"):
            requested_id = unquote(parsed.path.removeprefix("/note/"))
            self.respond_html(render_note(notes, requested_id))
            return
        if parsed.path == "/tutor":
            query = dict(item.split("=", 1) for item in parsed.query.split("&") if "=" in item)
            self.respond_html(render_tutor(notes, unquote(query.get("note", "")), unquote(query.get("subject", ""))))
            return
        if parsed.path == "/api/notes":
            payload = [
                {
                    "id": note.id,
                    "title": note.title,
                    "subject": note.subject,
                    "topic": note.topic,
                    "exam_board_status": note.exam_board_status,
                    "possible_exam_board": note.possible_exam_board,
                }
                for note in notes
            ]
            self.respond_json(payload)
            return
        self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/tutor/chat":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            message = str(payload.get("message", "")).strip()
            if not message:
                raise ValueError("Message is required.")
            notes = find_processed_notes(self.tutair_root)
            note_id_value = str(payload.get("note_id", ""))
            note = next((item for item in notes if item.id == note_id_value), None)
            profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
            context = tutor_context(note, profile)
            history = payload.get("history") if isinstance(payload.get("history"), list) else []
            mode = str(payload.get("mode", "general"))
            messages = build_tutor_messages(message, history, context, note, mode)
            reply = call_configured_ai_provider(messages)
            self.respond_json({"reply": reply, "context": context, "mode": mode})
        except (ValueError, json.JSONDecodeError) as exc:
            self.respond_json({"error": str(exc)}, status=400)
        except TutorProviderError as exc:
            self.respond_json({"error": str(exc)}, status=502)

    def respond_html(self, body: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def respond_json(self, payload: object, status: int = 200) -> None:
        encoded = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:
        return


def run_server(host: str, port: int, root: Path) -> None:
    load_tutair_env()
    handler = type("ConfiguredTutairRequestHandler", (TutairRequestHandler,), {"tutair_root": root})
    server = ThreadingHTTPServer((host, port), handler)
    print(f"TutAIR viewer running at http://{host}:{port}")
    print(f"UI version: {VIEWER_UI_VERSION}")
    print(f"Reading processed notes from: {root}")
    server.serve_forever()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local TutAIR revision viewer.")
    parser.add_argument("--root", type=Path, default=DEFAULT_TUTAIR_ROOT)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run_server(args.host, args.port, args.root)
    return 0


JS = r"""
(function () {
  const dataEl = document.getElementById("note-data");
  const note = dataEl ? JSON.parse(dataEl.textContent || "{}") : {};
  const app = document.querySelector(".app-shell");
  const profileApp = document.getElementById("profile-app");
  const content = document.querySelector(".content");
  const toast = document.querySelector(".toast");
  const storagePrefix = "tutair.viewer.";
  const tutorHistoryPrefix = "tutair.viewer.tutor.history.";
  const tutorSavedFlashcardsPrefix = "tutair.viewer.tutor.savedFlashcards.";
  const tutorSessionPrefix = "tutair.viewer.tutor.session.";
  const lessonStatePrefix = "tutair.viewer.lesson.state.";
  const profileKey = "tutair.viewer.profile";
  const sessionKey = "tutair.viewer.session";
  let flashIndex = 0;
  let flashShowingAnswer = false;
  let activeUtterance = null;
  let activeTutorMode = "general";
  let lastTutorReply = "";
  let currentLesson = null;

  const subjects = [
    { id: "maths", name: "Maths", icon: "+−×", tint: "green" },
    { id: "biology", name: "Biology", icon: "Leaf", tint: "green" },
    { id: "chemistry", name: "Chemistry", icon: "Flask", tint: "purple" },
    { id: "physics", name: "Physics", icon: "Atom", tint: "blue" },
    { id: "english-language", name: "English Language", icon: "Text", tint: "red" },
    { id: "english-literature", name: "English Literature", icon: "Book", tint: "orange" },
    { id: "geography", name: "Geography", icon: "Globe", tint: "aqua" },
    { id: "history", name: "History", icon: "Castle", tint: "yellow" },
    { id: "business", name: "Business", icon: "Case", tint: "pink" },
    { id: "computer-science", name: "Computer Science", icon: "Code", tint: "blue" },
    { id: "engineering", name: "Engineering", icon: "Gear", tint: "aqua" },
    { id: "construction", name: "Construction", icon: "Build", tint: "orange" },
    { id: "food-nutrition", name: "Food & Nutrition", icon: "Chef", tint: "red" },
    { id: "pe", name: "PE", icon: "Run", tint: "purple" },
    { id: "re", name: "RE", icon: "Pray", tint: "aqua" },
    { id: "art-design", name: "Art & Design", icon: "Paint", tint: "slate" },
    { id: "music", name: "Music", icon: "Note", tint: "purple" },
    { id: "economics", name: "Economics", icon: "Chart", tint: "pink" },
    { id: "environmental-science", name: "Environmental Science", icon: "Plant", tint: "green" },
    { id: "other", name: "Other", icon: "...", tint: "slate" }
  ];

  const examBoards = {
    default: ["AQA", "Edexcel", "OCR", "WJEC / Eduqas", "Unknown"],
    "english-language": ["AQA", "Edexcel", "OCR", "WJEC", "Eduqas", "Unknown"],
    "english-literature": ["AQA", "Edexcel", "OCR", "WJEC", "Eduqas", "Unknown"],
    maths: ["AQA", "Edexcel", "OCR", "Unknown"],
    science: ["AQA", "Edexcel", "OCR Gateway", "OCR Twenty First Century", "Unknown"],
    biology: ["AQA", "Edexcel", "OCR Gateway", "OCR Twenty First Century", "Unknown"],
    chemistry: ["AQA", "Edexcel", "OCR Gateway", "OCR Twenty First Century", "Unknown"],
    physics: ["AQA", "Edexcel", "OCR Gateway", "OCR Twenty First Century", "Unknown"],
    "computer-science": ["OCR", "AQA", "Edexcel", "Unknown"]
  };

  function loadProfile() {
    try {
      return JSON.parse(localStorage.getItem(profileKey) || "{}");
    } catch {
      return {};
    }
  }

  function saveProfile(profile) {
    localStorage.setItem(profileKey, JSON.stringify(profile));
  }

  function selectedSubjects(profile) {
    return subjects.filter((subject) => (profile.subjects || []).includes(subject.id));
  }

  function profileName(profile) {
    return (profile.name || "Warwick").trim();
  }

  function mascotMarkup(size = "large") {
    return `<div class="mascot ${size}" aria-hidden="true"><span class="mascot-cap"></span><span class="mascot-face"></span><span class="mascot-body"></span></div>`;
  }

  function progressStep(current) {
    const steps = [
      { id: 1, label: "Year Group" },
      { id: 2, label: "Subjects" },
      { id: 3, label: "Exam Boards (Optional)" }
    ];
    return `
      <div class="setup-progress" aria-label="Setup progress">
        <div class="setup-progress-bar"><span style="width:${Math.min(100, current * 33.333)}%"></span></div>
        ${steps.map((step) => `
          <div class="setup-step ${step.id < current ? "done" : ""} ${step.id === current ? "active" : ""}">
            <span>${step.id < current ? "✓" : step.id}</span>
            <strong>${step.label}</strong>
          </div>
        `).join("")}
      </div>`;
  }

  function subjectProgress(subject, index = 0) {
    const reviewed = getSet("reviewed").size;
    const base = ((subject.id.length * 13) + (index * 17) + reviewed * 7) % 64;
    return Math.max(0, Math.min(96, base));
  }

  function topicCount(subject) {
    return Math.max(4, (subject.name.length % 7) + 5);
  }

  function dashboardStats(profile, chosen) {
    const reviewed = getSet("reviewed").size;
    const favourites = getSet("favourites").size;
    const topicTotal = chosen.reduce((sum, subject) => sum + topicCount(subject), 0);
    const average = chosen.length
      ? Math.round(chosen.reduce((sum, subject, index) => sum + subjectProgress(subject, index), 0) / chosen.length)
      : 0;
    return {
      reviewed,
      favourites,
      topicTotal,
      average,
      xp: Math.max(120, chosen.length * 85 + reviewed * 25 + favourites * 15),
      level: Math.max(1, Math.floor((chosen.length * 85 + reviewed * 25 + favourites * 15) / 200) + 1),
      streak: Math.max(1, reviewed + (profile.completed ? 3 : 1))
    };
  }

  function showProfile(html, view = "onboarding") {
    if (!profileApp) return;
    stopSpeech();
    document.body.classList.remove("focus-mode");
    profileApp.innerHTML = html;
    profileApp.hidden = false;
    profileApp.style.display = "";
    if (app) {
      app.hidden = true;
      app.style.display = "none";
    }
    document.body.dataset.screen = "profile";
    document.body.dataset.profileView = view;
    window.scrollTo(0, 0);
    const first = profileApp.querySelector("button, input, a, select, textarea");
    if (first) window.setTimeout(() => first.focus(), 0);
  }

  function showViewer() {
    if (profileApp) {
      profileApp.hidden = true;
      profileApp.style.display = "none";
    }
    if (app) {
      app.hidden = false;
      app.style.display = "";
    }
    document.body.dataset.screen = "viewer";
    document.body.dataset.profileView = "";
    window.scrollTo(0, 0);
  }

  function renderLogin(mode = "login") {
    const profile = loadProfile();
    const isRegister = mode === "register";
    showProfile(`
      <main class="auth-screen" aria-labelledby="auth-title">
        <form class="auth-card" data-form="${isRegister ? "register" : "login"}">
          <div class="auth-logo-word">Tut<span>AIR</span></div>
          <p class="auth-subtitle">Your AI Study Companion</p>
          <h1 id="auth-title">${isRegister ? "Create your account" : "Welcome back!"}</h1>
          <p>${isRegister ? "Set up your personal GCSE revision space." : "Log in to continue your learning journey."}</p>
          <label class="${isRegister ? "" : "optional-field"}">Name
            <input name="name" type="text" autocomplete="name" value="${escapeText(profile.name || "")}" ${isRegister ? "required" : ""}>
          </label>
          <label>Email
            <input name="email" type="email" autocomplete="email" value="${escapeText(profile.email || "")}" required>
          </label>
          <label>Password
            <input name="password" type="password" autocomplete="${isRegister ? "new-password" : "current-password"}" required>
          </label>
          <label class="inline-choice">
            <input name="remember" type="checkbox" ${profile.rememberMe ? "checked" : ""}>
            Remember me on this device
          </label>
          <button class="primary-action" type="submit">${isRegister ? "Create Account" : "Login"}</button>
          <div class="auth-divider"><span>OR</span></div>
          <div class="auth-links">
            <button type="button" data-profile-action="${isRegister ? "login" : "register"}">${isRegister ? "Back to Login" : "Create New Account"}</button>
            <button type="button" data-profile-action="forgot">Forgot Password?</button>
          </div>
          <small>By logging in, you agree to our <a href="#" data-profile-action="terms">Terms of Service</a> and <a href="#" data-profile-action="privacy">Privacy Policy</a>.</small>
        </form>
        <section class="auth-hero">
          <span class="float-token token-a">A+</span>
          <span class="float-token token-b">f(x)</span>
          <span class="float-token token-c">☆</span>
          <h2>Smarter Revision.<br>Better Results.</h2>
          <p>Personalised learning, powered by AI.<br>Built for GCSE success.</p>
          ${mascotMarkup("large")}
          <div class="auth-benefits">
            <span><strong>Smart Tools</strong><small>Flashcards, quizzes, summaries and more</small></span>
            <span><strong>Personalised</strong><small>Made for you and your goals</small></span>
            <span><strong>Track Progress</strong><small>See your growth and stay motivated</small></span>
          </div>
        </section>
      </main>`);
  }

  function renderForgotPassword() {
    showProfile(`
      <main class="auth-screen" aria-labelledby="forgot-title">
        <section class="auth-brand">
          <span class="auth-logo">TA</span>
          <h1>Tut<span>AIR</span></h1>
          <p>Small steps, big progress.</p>
        </section>
        <form class="auth-card" data-form="forgot">
          <p class="eyebrow">Password Help</p>
          <h2 id="forgot-title">Reset link placeholder</h2>
          <p>This local prototype does not send email yet. Enter an address and TutAIR will remember where to return.</p>
          <label>Email
            <input name="email" type="email" autocomplete="email" required>
          </label>
          <button class="primary-action" type="submit">Continue</button>
          <button class="quiet-action" type="button" data-profile-action="login">Back to Login</button>
        </form>
      </main>`);
  }

  function renderYearGroup() {
    const profile = loadProfile();
    const years = [
      { label: "Year 9", icon: "Bag", text: "Building strong foundations", tint: "green" },
      { label: "Year 10", icon: "Rocket", text: "Learning the GCSE course", tint: "purple" },
      { label: "Year 11", icon: "Target", text: "Preparing for your exams", tint: "red" }
    ];
    showProfile(`
      <main class="onboarding-screen" aria-labelledby="year-title">
        ${stepHeader(1, "What year are you in?", "This helps us personalise your learning experience and show you the right content.")}
        ${progressStep(1)}
        <section class="choice-grid year-grid">
          ${years.map((year) => `
            <button class="choice-card year-choice ${year.tint} ${profile.yearGroup === year.label ? "selected" : ""}" type="button" data-year="${year.label}">
              <span class="choice-orb ${year.tint}">${year.icon}</span>
              <strong>${year.label}</strong>
              <small>${year.text}</small>
              <em aria-hidden="true"></em>
            </button>
          `).join("")}
        </section>
        <aside class="helper-strip">
          <span class="helper-star">★</span>
          <div><strong>Not sure?</strong><p>You can change this later in your settings whenever you need to.</p></div>
          ${mascotMarkup("small")}
        </aside>
        ${stepNav("dashboard", "subjects", Boolean(profile.yearGroup), "Continue")}
      </main>`);
  }

  function renderSubjectSelection() {
    const profile = loadProfile();
    const selected = new Set(profile.subjects || []);
    showProfile(`
      <main class="onboarding-screen" aria-labelledby="subject-title">
        ${stepHeader(2, "Which GCSE subjects do you study?", "Pick all the subjects you take. We'll only show you content that matters to you.")}
        ${progressStep(2)}
        <p class="select-note">Select all that apply</p>
        <section class="choice-grid subject-grid">
          ${subjects.map((subject) => `
            <button class="choice-card subject-choice ${selected.has(subject.id) ? "selected" : ""}" type="button" data-subject="${subject.id}">
              <span class="subject-dot ${subject.tint}">${subject.icon}</span>
              <strong>${subject.name}</strong>
              <small>${selected.has(subject.id) ? "Selected" : "Tap to add"}</small>
            </button>
          `).join("")}
        </section>
        <aside class="helper-strip">
          ${mascotMarkup("small")}
          <div><strong>You can change this anytime!</strong><p>Go to Settings anytime to add or remove subjects as your courses change.</p></div>
          <span class="helper-star">⚙</span>
        </aside>
        ${stepNav("year", "boards", selected.size > 0, "Continue")}
      </main>`);
  }

  function renderExamBoards() {
    const profile = loadProfile();
    const chosen = selectedSubjects(profile);
    showProfile(`
      <main class="onboarding-screen" aria-labelledby="boards-title">
        ${stepHeader(3, "Do you know your exam boards?", "This helps us personalise content to match your course. You can skip this for now and we'll ask later.")}
        ${progressStep(3)}
        <div class="board-mode">
          <button class="selected" type="button" data-profile-action="boards">Yes, I know my exam boards</button>
          <button type="button" data-profile-action="skip-boards">No, skip for now</button>
        </div>
        <div class="section-intro"><strong>Select your exam boards</strong><span>Choose the boards for your selected subjects.</span></div>
        <section class="board-list">
          ${chosen.length ? chosen.map((subject) => {
            const current = (profile.examBoards || {})[subject.id] || "";
            const boards = examBoards[subject.id] || examBoards.default;
            return `
              <article class="board-row">
                <div>
                  <span class="subject-dot ${subject.tint}">${subject.icon}</span>
                  <span><strong>${subject.name}</strong><small>Select your board</small></span>
                </div>
                <div class="board-options">
                  ${boards.map((board) => `<button type="button" class="${current === board ? "selected" : ""}" data-board-button="${subject.id}" data-board-value="${escapeText(board)}">${escapeText(board)}</button>`).join("")}
                </div>
              </article>`;
          }).join("") : `<p class="empty-panel">Choose subjects first so TutAIR knows which boards to ask about.</p>`}
        </section>
        <aside class="helper-strip board-help">
          ${mascotMarkup("small")}
          <div><strong>Not sure which board you're on?</strong><p>Check with your teacher or school. You can always update this in settings later.</p></div>
        </aside>
        <div class="step-actions">
          <button class="quiet-action" type="button" data-profile-action="subjects">Back</button>
          <button class="quiet-action" type="button" data-profile-action="skip-boards">Skip For Now</button>
          <button class="primary-action" type="button" data-profile-action="complete" ${chosen.length ? "" : "disabled"}>Continue</button>
        </div>
      </main>`);
  }

  function renderSetupComplete() {
    const profile = loadProfile();
    const chosen = selectedSubjects(profile);
    const boardCount = Object.values(profile.examBoards || {}).filter(Boolean).length;
    showProfile(`
      <main class="setup-complete" aria-labelledby="complete-title">
        <div class="complete-hero">
          <div>
            <div class="auth-logo-word">Tut<span>AIR</span></div>
            <h1 id="complete-title">You're all set,<br><span>${escapeText(profileName(profile))}!</span></h1>
            <p>Your TutAIR is ready. Let's start your learning journey.</p>
          </div>
          ${mascotMarkup("giant")}
        </div>
        <section class="complete-card">
          <h2>Here's your learning profile</h2>
          <div class="profile-summary">
            <span><strong>Year Group</strong><em>${escapeText(profile.yearGroup || "Unknown")}</em></span>
            <span><strong>Subjects</strong><em>${chosen.length} subject${chosen.length === 1 ? "" : "s"}</em></span>
            <span><strong>Exam Boards</strong><em>${boardCount ? "Set" : "Unknown"}</em></span>
          </div>
        </section>
        <section class="mission-panel">
          <h2>Ready to start your first mission?</h2>
          <p>TutAIR will guide you step by step, helping you learn smarter and achieve more.</p>
          <button class="primary-action" type="button" data-profile-action="dashboard">Start Today's Mission</button>
        </section>
        <section class="capability-row">
          ${["Learn", "Practice", "Track", "Achieve", "Get Help"].map((label) => `<span><strong>${label}</strong><small>${label === "Learn" ? "Clear notes and explanations" : label === "Practice" ? "Flashcards, quizzes and questions" : label === "Track" ? "See your progress" : label === "Achieve" ? "Earn XP and unlock wins" : "Ask for help anytime"}</small></span>`).join("")}
        </section>
      </main>`, "onboarding");
  }

  function renderPersonalDashboard() {
    const profile = loadProfile();
    const chosen = selectedSubjects(profile);
    const stats = dashboardStats(profile, chosen);
    const firstSubject = chosen[0];
    const firstProgress = firstSubject ? subjectProgress(firstSubject, 0) : 0;
    showProfile(`
      <div class="personal-shell">
        <aside class="personal-rail" aria-label="TutAIR dashboard navigation">
          <a class="brand" href="#" data-profile-action="dashboard" aria-label="TutAIR dashboard">
            <span class="brand-mark">TA</span>
            <span><strong>Tut<span>AIR</span></strong><small>Focus. Understand. Remember.</small></span>
          </a>
          ${mascotMarkup("avatar")}
          <section class="level-card">
            <strong>Level ${stats.level}</strong>
            <span>${stats.xp} XP</span>
            <div class="progress-track"><span style="width:${Math.min(100, stats.xp % 200 / 2)}%"></span></div>
            <small>${200 - (stats.xp % 200)} XP to next level</small>
          </section>
          <nav class="personal-nav">
            ${navButton("dashboard", "My Subjects", true)}
            ${navButton("subjects", "Subjects")}
            ${navButton("progress", "Progress")}
            ${navButton("ai-tutor", "AI Tutor")}
            ${navButton("flashcards-home", "Flashcards")}
            ${navButton("quiz-home", "Quiz Me")}
            ${navButton("youtube-summary", "YouTube Summary")}
            ${navButton("achievements", "Achievements")}
            ${navButton("settings", "Settings")}
          </nav>
          <section class="streak-card"><strong>${stats.streak} Day Streak</strong><small>Keep it going</small></section>
          <button class="break-button" type="button" data-profile-action="revision-notes">Revision Notes</button>
          <button class="break-button" type="button" data-profile-action="edit-subjects">Edit Subjects</button>
        </aside>
        <main class="personal-main" aria-labelledby="dashboard-title">
          <header class="personal-header">
            <div>
              <h1 id="dashboard-title">Welcome back, ${escapeText(profileName(profile))}!</h1>
              <p>Choose a subject to start your mission.</p>
            </div>
            <div class="dashboard-actions">
              <button type="button" data-profile-action="notifications">Notifications</button>
              <button type="button" data-profile-action="profile">Profile</button>
            </div>
          </header>
          <section class="continue-panel">
            <div>
              <strong>Continue where you left off</strong>
              <h2>${firstSubject ? escapeText(firstSubject.name) : "Choose your first subject"}</h2>
              <p>${firstSubject ? `${firstProgress}% complete` : "Your mission starts with one tap."}</p>
              <div class="progress-track"><span style="width:${firstProgress}%"></span></div>
            </div>
            ${mascotMarkup("medium")}
              <button type="button" data-profile-action="${firstSubject ? "open-subject" : "edit-subjects"}" ${firstSubject ? `data-subject-open="${firstSubject.id}"` : ""}>Continue</button>
          </section>
          <section class="subject-section-header">
            <div><h2>My Subjects</h2><p>Select a subject to explore topics and start learning.</p></div>
            <button type="button" data-profile-action="edit-subjects">Edit Subjects</button>
          </section>
          <section class="subject-dashboard-grid" data-subject-count="${chosen.length}">
            ${chosen.length ? chosen.map((subject) => subjectDashboardCard(subject, profile)).join("") : `
              <article class="empty-panel">
                <h2>No subjects selected yet</h2>
                <p>Add your GCSE subjects to build a personal dashboard.</p>
                <button class="primary-action" type="button" data-profile-action="edit-subjects">Edit Subjects</button>
              </article>`}
          </section>
          <p class="dynamic-note">Cards above are generated dynamically from your selected subjects.</p>
          <section class="dashboard-strip" aria-label="Quick dashboard actions">
            ${quickAction("ai-tutor", "AI Tutor", "Ask anything, get instant help")}
            ${quickAction("flashcards-home", "Flashcards", "Revise key facts")}
            ${quickAction("quiz-home", "Quiz Me", "Test your knowledge")}
            ${quickAction("youtube-summary", "YouTube Summary", "Summarise a video")}
          </section>
          <section class="dashboard-stats">
            <button type="button" data-profile-action="progress"><strong>${chosen.length}</strong><span>Subjects</span></button>
            <button type="button" data-profile-action="progress"><strong>${stats.topicTotal}</strong><span>Topics</span></button>
            <button type="button" data-profile-action="achievements"><strong>${stats.xp}</strong><span>Total XP</span></button>
            <button type="button" data-profile-action="progress"><strong>${stats.average}%</strong><span>Average progress</span></button>
          </section>
          <nav class="bottom-nav" aria-label="Bottom navigation">
            ${navButton("dashboard", "Home", true)}
            ${navButton("progress", "Progress")}
            ${navButton("ai-tutor", "Tutor")}
            ${navButton("settings", "Settings")}
          </nav>
        </main>
      </div>`, "dashboard");
  }

  function subjectDashboardCard(subject, profile) {
    const board = (profile.examBoards || {})[subject.id] || "Unknown";
    const index = selectedSubjects(profile).findIndex((item) => item.id === subject.id);
    const progress = subjectProgress(subject, index);
    return `
      <article class="dashboard-card ${subject.tint}">
        <div class="dashboard-card-top">
          <span class="subject-dot ${subject.tint}">${subject.icon}</span>
          <button type="button" data-profile-action="subject-menu" aria-label="${escapeText(subject.name)} options">...</button>
        </div>
        <h2>${escapeText(subject.name)}</h2>
        <p>${topicCount(subject)} Topics</p>
        <div class="progress-track" aria-label="${subject.name} progress"><span style="width: ${progress}%"></span></div>
        <small>${progress}%</small>
        <span class="board-pill">${escapeText(board)}</span>
        <div class="card-actions">
          <button type="button" data-profile-action="open-subject" data-subject-open="${subject.id}">Start Learning</button>
          <button type="button" data-profile-action="subject-progress" data-subject-open="${subject.id}">Progress</button>
        </div>
      </article>`;
  }

  function subjectAreas(subject) {
    if (subject.id === "maths") {
      return ["Number", "Algebra", "Geometry & Measures", "Statistics", "Probability", "Ratio & Proportion"];
    }
    if (subject.id === "biology") {
      return ["Cell Biology", "Organisation", "Infection & Response", "Bioenergetics", "Homeostasis", "Ecology"];
    }
    if (subject.id === "chemistry") {
      return ["Atomic Structure", "Bonding", "Quantitative Chemistry", "Chemical Changes", "Energy Changes", "Organic Chemistry"];
    }
    return ["Key Ideas", "Core Skills", "Practice Questions", "Exam Technique", "Revision Notes", "Flashcards"];
  }

  function popularSearches(subject) {
    if (subject.id === "maths") {
      return ["Pythagoras", "Circle Theorems", "Simultaneous Equations", "Trigonometry"];
    }
    if (subject.id === "biology") {
      return ["Cell Division", "Diffusion", "Photosynthesis", "Enzymes"];
    }
    if (subject.id === "chemistry") {
      return ["Periodic Table", "Ionic Bonding", "Electrolysis", "Rates of Reaction"];
    }
    return ["Exam Question", "Key Definitions", "Common Mistakes", "Revision Notes"];
  }

  function setCurrentSubject(subjectId) {
    const subject = subjects.find((item) => item.id === subjectId);
    if (!subject) return null;
    const profile = loadProfile();
    profile.currentSubject = subject.name;
    profile.currentSubjectId = subject.id;
    profile.currentTopic = "";
    saveProfile(profile);
    return subject;
  }

  function renderSubjectPage(subjectId) {
    const subject = setCurrentSubject(subjectId);
    if (!subject) {
      renderPersonalDashboard();
      return;
    }
    const profile = loadProfile();
    const board = (profile.examBoards || {})[subject.id] || "Unknown";
    const areas = subjectAreas(subject);
    const searches = popularSearches(subject);
    const recent = JSON.parse(localStorage.getItem(`${storagePrefix}recent.${subject.id}`) || "[]");
    showProfile(`
      <div class="personal-shell subject-page-shell">
        <aside class="personal-rail" aria-label="TutAIR subject navigation">
          <a class="brand" href="#" data-profile-action="dashboard" aria-label="TutAIR dashboard">
            <span class="brand-mark">TA</span>
            <span><strong>Tut<span>AIR</span></strong><small>${escapeText(subject.name)}</small></span>
          </a>
          ${mascotMarkup("avatar")}
          <nav class="personal-nav">
            ${navButton("dashboard", "My Subjects")}
            ${navButton("ai-tutor", "AI Tutor")}
            ${navButton("progress", "Progress")}
            ${navButton("settings", "Settings")}
          </nav>
        </aside>
        <main class="personal-main subject-page" aria-labelledby="subject-page-title">
          <header class="personal-header subject-page-header">
            <div>
              <p class="eyebrow">Current subject</p>
              <h1 id="subject-page-title">${escapeText(subject.name)}</h1>
              <p>Pick a topic when you're ready. TutAIR will not guess one for you.</p>
            </div>
            <span class="board-pill">${escapeText(board)}</span>
          </header>
          <section class="subject-search-panel" aria-label="${escapeText(subject.name)} topic search">
            <label for="subject-search">Search ${escapeText(subject.name)}</label>
            <input id="subject-search" type="search" placeholder="Search a topic, skill, or question">
            <button class="primary-action" type="button" data-profile-action="ai-tutor">Ask TutAIR</button>
          </section>
          <section class="continue-panel">
            <div>
              <strong>Continue where you left off</strong>
              <h2>${recent[0] ? escapeText(recent[0]) : "No topic selected yet"}</h2>
              <p>${recent[0] ? "Ready to continue." : "Choose an area below to start."}</p>
            </div>
            ${mascotMarkup("medium")}
            <button type="button" data-profile-action="ai-tutor">Open Tutor</button>
          </section>
          <section class="subject-topic-section">
            <div class="subject-section-header">
              <div><h2>Main areas</h2><p>One area at a time.</p></div>
            </div>
            <div class="subject-area-grid">
              ${areas.map((area) => `<button type="button" data-profile-action="topic-placeholder" data-topic-name="${escapeText(area)}"><strong>${escapeText(area)}</strong><span>Explore topics</span></button>`).join("")}
            </div>
          </section>
          <section class="subject-topic-section">
            <div class="subject-section-header">
              <div><h2>Popular searches</h2><p>Fast starts for common GCSE topics.</p></div>
            </div>
            <div class="popular-searches">
              ${searches.map((item) => `<button type="button" data-profile-action="topic-placeholder" data-topic-name="${escapeText(item)}">${escapeText(item)}</button>`).join("")}
            </div>
          </section>
          <section class="subject-topic-section">
            <div class="subject-section-header">
              <div><h2>Recently studied</h2><p>${recent.length ? "Your recent topics for this subject." : "Nothing here yet."}</p></div>
            </div>
            ${recent.length ? `<div class="popular-searches">${recent.slice(0, 4).map((item) => `<button type="button" data-profile-action="topic-placeholder" data-topic-name="${escapeText(item)}">${escapeText(item)}</button>`).join("")}</div>` : `<p class="empty-panel">Start a topic and it will appear here next time.</p>`}
          </section>
        </main>
      </div>`, "dashboard");
  }

  function renderPlaceholder(title) {
    showProfile(`
      <main class="placeholder-screen" aria-labelledby="placeholder-title">
        <section class="complete-card">
          <p class="eyebrow">Coming Soon</p>
          <h1 id="placeholder-title">${escapeText(title)}</h1>
          <p>This control is wired in the local prototype. The full feature will be added in a later TutAIR milestone.</p>
          <button class="primary-action" type="button" data-profile-action="dashboard">Back to My Subjects</button>
        </section>
      </main>`, "dashboard");
  }

  function renderSettings() {
    showProfile(`
      <main class="settings-screen" aria-labelledby="settings-title">
        <section class="settings-card">
          <p class="eyebrow">Settings</p>
          <h1 id="settings-title">Account settings</h1>
          <p>Manage this local TutAIR prototype profile on this device.</p>
          <div class="settings-list">
            <button type="button" data-profile-action="profile">Profile</button>
            <button type="button" data-profile-action="edit-subjects">Edit Subjects</button>
            <button type="button" data-profile-action="logout-confirm" class="danger-action">Log Out</button>
          </div>
          <button class="quiet-action" type="button" data-profile-action="dashboard">Back to My Subjects</button>
        </section>
      </main>`, "dashboard");
  }

  function renderLogoutConfirm() {
    showProfile(`
      <main class="settings-screen" aria-labelledby="logout-title">
        <section class="settings-card logout-card" role="dialog" aria-modal="true" aria-labelledby="logout-title">
          <p class="eyebrow">Log Out</p>
          <h1 id="logout-title">Are you sure you want to log out?</h1>
          <p>This will clear the local prototype profile, Remember Me, and setup choices on this browser.</p>
          <div class="settings-actions">
            <button class="quiet-action" type="button" data-profile-action="settings">Cancel</button>
            <button class="danger-action" type="button" data-profile-action="logout">Log Out</button>
          </div>
        </section>
      </main>`, "dashboard");
  }

  function logoutPrototypeUser() {
    localStorage.removeItem(profileKey);
    sessionStorage.removeItem(sessionKey);
    renderLogin("login");
  }

  function quickAction(action, title, text) {
    return `<button type="button" data-profile-action="${action}"><strong>${escapeText(title)}</strong><span>${escapeText(text)}</span></button>`;
  }

  function stepHeader(step, title, subtitle) {
    return `
      <header class="step-header">
        <button class="back-orb" type="button" data-profile-action="${step === 1 ? "login" : step === 2 ? "year" : "subjects"}" aria-label="Back">‹</button>
        <div class="auth-logo-word">Tut<span>AIR</span></div>
        <span class="step-pill">Step ${step} of 3</span>
        <div>
          <h1 id="${title.toLowerCase().replace(/\s+/g, "-")}-title">${escapeText(title)}</h1>
          <p>${escapeText(subtitle)}</p>
        </div>
      </header>`;
  }

  function stepNav(back, next, enabled, label) {
    return `
      <div class="step-actions">
        <button class="quiet-action" type="button" data-profile-action="${back}">Back</button>
        <button class="primary-action" type="button" data-profile-action="${next}" ${enabled ? "" : "disabled"}>${label}</button>
      </div>`;
  }

  function navButton(action, label, active = false) {
    return `<button class="${active ? "active" : ""}" type="button" data-profile-action="${action}"><span aria-hidden="true"></span>${escapeText(label)}</button>`;
  }

  function completeBoards(useUnknown = false) {
    const profile = loadProfile();
    const boards = { ...(profile.examBoards || {}) };
    selectedSubjects(profile).forEach((subject) => {
      if (useUnknown || !boards[subject.id]) boards[subject.id] = "Unknown";
    });
    profile.examBoards = boards;
    profile.completed = true;
    saveProfile(profile);
    renderSetupComplete();
  }

  function routeProfileAction(action, target) {
    const profile = loadProfile();
    if (action === "login") return renderLogin("login");
    if (action === "register") return renderLogin("register");
    if (action === "forgot") return renderForgotPassword();
    if (action === "year") return renderYearGroup();
    if (action === "subjects" || action === "edit-subjects") return renderSubjectSelection();
    if (action === "boards") return renderExamBoards();
    if (action === "skip-boards") return completeBoards(true);
    if (action === "complete") return completeBoards(false);
    if (action === "dashboard") return renderPersonalDashboard();
    if (action === "settings") return renderSettings();
    if (action === "logout-confirm") return renderLogoutConfirm();
    if (action === "logout") return logoutPrototypeUser();
    if (action === "open-subject") {
      return renderSubjectPage(target?.dataset.subjectOpen || profile.currentSubjectId || "");
    }
    if (action === "revision-notes") {
      if (window.location.pathname === "/" || isNoteRoute()) return showViewer();
      window.location.href = "/?view=notes";
      return;
    }
    if (action === "ai-tutor") {
      const subjectId = target?.dataset.subjectOpen || profile.currentSubjectId || "";
      if (subjectId) {
        window.location.href = `/tutor?subject=${encodeURIComponent(subjectId)}`;
        return;
      }
      window.location.href = note.id ? `/tutor?note=${encodeURIComponent(note.id)}` : "/tutor";
      return;
    }
    if (action === "topic-placeholder") {
      const nextProfile = loadProfile();
      nextProfile.currentTopic = target?.dataset.topicName || "";
      saveProfile(nextProfile);
      renderPlaceholder(target?.dataset.topicName || "Topic");
      return;
    }
    const labels = {
      "flashcards-home": "Flashcards",
      "quiz-home": "Quiz Me",
      "youtube-summary": "YouTube Summary",
      "progress": "Progress",
      "achievements": "Achievements",
      "settings": "Settings",
      "notifications": "Notifications",
      "terms": "Terms of Service",
      "privacy": "Privacy Policy",
      "profile": profile.name ? `${profile.name}'s Profile` : "Profile",
      "subject-progress": "Subject Progress",
      "subject-menu": "Subject Options"
    };
    renderPlaceholder(labels[action] || target?.textContent?.trim() || "This feature");
  }

  function isNoteRoute() {
    return window.location.pathname.startsWith("/note/");
  }

  function wantsNotesView() {
    return new URLSearchParams(window.location.search).get("view") === "notes";
  }

  function initialiseProfileScreen() {
    const profile = loadProfile();
    const signedInNow = profile.signedIn || sessionStorage.getItem(sessionKey) === "1";
    if (!signedInNow) {
      renderLogin("login");
    } else if (isNoteRoute() || wantsNotesView()) {
      // A link straight to a note is a request to read that note. The personal
      // dashboard must not cover it, or the revision content is unreachable.
      showViewer();
    } else if (profile.completed) {
      renderPersonalDashboard();
    } else {
      if (!profile.yearGroup) renderYearGroup();
      else if (!(profile.subjects || []).length) renderSubjectSelection();
      else renderExamBoards();
    }
  }

  function getSet(key) {
    try {
      return new Set(JSON.parse(localStorage.getItem(storagePrefix + key) || "[]"));
    } catch {
      return new Set();
    }
  }

  function saveSet(key, values) {
    localStorage.setItem(storagePrefix + key, JSON.stringify(Array.from(values)));
  }

  function showToast(message) {
    if (!toast) return;
    toast.textContent = message;
    toast.hidden = false;
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => {
      toast.hidden = true;
    }, 2600);
  }

  function setMode(mode) {
    if (!content) return;
    document.body.dataset.mode = mode;
    if (mode === "notes") {
      content.querySelectorAll(".practice-view").forEach((el) => el.remove());
      const noteEl = content.querySelector(".note");
      if (noteEl) noteEl.hidden = false;
      return;
    }
    const noteEl = content.querySelector(".note");
    if (noteEl) noteEl.hidden = true;
    content.querySelectorAll(".practice-view").forEach((el) => el.remove());
  }

  function escapeText(value) {
    const span = document.createElement("span");
    span.textContent = value || "";
    return span.innerHTML;
  }

  function tutorHistoryKey() {
    return `${tutorHistoryPrefix}${note.id || note.subject || "general"}.${tutorSessionId()}`;
  }

  function tutorSessionKey() {
    return `${tutorSessionPrefix}${note.id || note.subject || "general"}`;
  }

  function lessonStateKey() {
    return `${lessonStatePrefix}${note.id || note.subject || "general"}`;
  }

  function tutorSessionId() {
    let id = sessionStorage.getItem(tutorSessionKey());
    if (!id) {
      id = `${Date.now()}`;
      sessionStorage.setItem(tutorSessionKey(), id);
    }
    return id;
  }

  function startNewTutorSession() {
    sessionStorage.setItem(tutorSessionKey(), `${Date.now()}`);
    activeTutorMode = "general";
    lastTutorReply = "";
    currentLesson = defaultLessonState();
    saveLessonState(currentLesson);
    setTutorError("");
    toggleFlashcardSave(false);
    renderLessonStage(null);
    updateLessonStatus();
    renderTutorHistory([]);
  }

  function loadTutorHistory() {
    try {
      return JSON.parse(localStorage.getItem(tutorHistoryKey()) || "[]");
    } catch {
      return [];
    }
  }

  function saveTutorHistory(history) {
    localStorage.setItem(tutorHistoryKey(), JSON.stringify(history.slice(-30)));
  }

  function defaultLessonState() {
    return {
      currentStep: 0,
      xp: 0,
      progress: 0,
      completedQuestions: 0,
      badges: [],
      streak: 1,
      lastLesson: null,
      completed: false
    };
  }

  function loadLessonState() {
    try {
      return { ...defaultLessonState(), ...JSON.parse(localStorage.getItem(lessonStateKey()) || "{}") };
    } catch {
      return defaultLessonState();
    }
  }

  function saveLessonState(state) {
    localStorage.setItem(lessonStateKey(), JSON.stringify(state));
  }

  function updateLessonStatus() {
    const state = currentLesson || loadLessonState();
    const xp = document.querySelector("[data-lesson-xp]");
    const title = document.querySelector("[data-lesson-title]");
    const step = document.querySelector("[data-lesson-step]");
    const progress = document.querySelector("[data-lesson-progress]");
    const streak = document.querySelector("[data-lesson-streak]");
    const ring = document.querySelector("[data-xp-ring]");
    if (xp) xp.textContent = state.xp || 0;
    if (title) title.textContent = (state.lastLesson && state.lastLesson.title) || note.topic || note.subject || "Choose a topic";
    if (step) step.textContent = state.completed ? "Mission complete" : `Step ${Math.max(1, state.currentStep || 1)} of 6`;
    if (progress) progress.style.width = `${Math.min(100, state.progress || 0)}%`;
    if (streak) streak.textContent = `${state.streak || 1} day streak`;
    if (ring) ring.style.setProperty("--lesson-progress", `${Math.min(100, state.progress || 0)}%`);
  }

  function parseLessonReply(text) {
    if (!text) return null;
    try {
      return JSON.parse(text);
    } catch {
      const match = text.match(/\{[\s\S]*\}/);
      if (!match) return null;
      try {
        return JSON.parse(match[0]);
      } catch {
        return null;
      }
    }
  }

  function looksLikeLessonJson(text) {
    const value = (text || "").trim();
    return value.startsWith("{") && value.includes('"title"');
  }

  function friendlyHistoryContent(item) {
    if (item.role === "assistant" && looksLikeLessonJson(item.content)) {
      return "Lesson card ready.";
    }
    return item.content || "";
  }

  function normaliseLesson(raw, fallbackText) {
    if (!raw) {
      return {
        title: note.topic || note.subject || "TutAIR Mission",
        step_label: "Formatting hiccup",
        difficulty: "easy",
        estimated_time: "2 minutes",
        robot_reaction: "TutAIR had trouble formatting this lesson.",
        explanation: "TutAIR had trouble formatting this lesson. Try again.",
        analogy: "",
        important_fact: "",
        example: "",
        picture_placeholder: "Picture placeholder",
        quiz: null,
        gcse_question: null,
        flashcards: [],
        xp: 0,
        progress_delta: 0,
        badge: "",
        next_step: "Try again",
        mission_complete: false,
        suggested_next_topic: ""
      };
    }
    return {
      title: raw.title || note.topic || note.subject || "TutAIR Mission",
      step_label: raw.step_label || "Tiny step",
      difficulty: raw.difficulty || "easy",
      estimated_time: raw.estimated_time || "2 minutes",
      robot_reaction: raw.robot_reaction || "Nice, tiny step ready.",
      explanation: raw.explanation || "",
      analogy: raw.analogy || "",
      important_fact: raw.important_fact || "",
      example: raw.example || "",
      picture_placeholder: raw.picture_placeholder || "Picture placeholder",
      quiz: raw.quiz || null,
      gcse_question: raw.gcse_question || null,
      flashcards: Array.isArray(raw.flashcards) ? raw.flashcards : [],
      xp: Number(raw.xp || 10),
      progress_delta: Number(raw.progress_delta || 12),
      badge: raw.badge || "",
      next_step: raw.next_step || "Continue",
      mission_complete: Boolean(raw.mission_complete),
      suggested_next_topic: raw.suggested_next_topic || ""
    };
  }

  function applyLessonReward(lesson) {
    const state = currentLesson || loadLessonState();
    state.currentStep = Math.min(6, (state.currentStep || 0) + 1);
    state.xp = (state.xp || 0) + Math.max(0, lesson.xp || 0);
    state.progress = Math.min(100, (state.progress || 0) + Math.max(0, lesson.progress_delta || 0));
    state.completedQuestions = (state.completedQuestions || 0) + (lesson.quiz ? 1 : 0);
    if (lesson.badge && !state.badges.includes(lesson.badge)) state.badges.push(lesson.badge);
    state.completed = lesson.mission_complete || state.progress >= 100 || state.currentStep >= 6;
    state.lastLesson = lesson;
    currentLesson = state;
    saveLessonState(state);
    updateLessonStatus();
  }

  function renderLessonStage(lesson) {
    const stage = document.querySelector("[data-learning-stage]");
    if (!stage) return;
    if (!lesson) {
      stage.innerHTML = `
        <article class="lesson-card start-card">
          <div class="robot-face" aria-hidden="true">TA</div>
          <p class="eyebrow">Step 1</p>
          <h2>What are we learning today?</h2>
          <p>${escapeText(note.topic || note.subject || "Choose a topic, then start a lesson.")}</p>
          <div class="lesson-meta"><span>Difficulty: Easy</span><span>Estimated: 2 minutes</span></div>
          <button class="primary-action" type="button" data-tutor-mode="lesson" data-prompt="Start an interactive tiny-step lesson for this topic.">Start</button>
        </article>`;
      return;
    }
    if (lesson.mission_complete || (currentLesson && currentLesson.completed)) {
      renderMissionComplete(stage, lesson);
      return;
    }
    const quiz = lesson.quiz && Array.isArray(lesson.quiz.choices) ? lesson.quiz : null;
    const gcse = lesson.gcse_question;
    const flashcards = lesson.flashcards || [];
    stage.innerHTML = `
      <article class="lesson-card">
        <div class="lesson-card-top">
          <div class="robot-face" aria-hidden="true">TA</div>
          <div>
            <p class="eyebrow">${escapeText(lesson.step_label)}</p>
            <h2>${escapeText(lesson.title)}</h2>
            <div class="lesson-meta"><span>${difficultyStars(lesson.difficulty)}</span><span>${escapeText(lesson.estimated_time)}</span><span>+${lesson.xp} XP</span></div>
          </div>
        </div>
        <p class="robot-reaction">${escapeText(lesson.robot_reaction)}</p>
        ${lesson.explanation ? `<section class="tiny-card"><h3>Quick Learn</h3><p>${escapeText(lesson.explanation)}</p></section>` : ""}
        <section class="picture-card"><span aria-hidden="true">□</span><p>${escapeText(lesson.picture_placeholder || "Picture placeholder")}</p></section>
        ${lesson.analogy ? `<section class="tiny-card analogy"><h3>Think of it like...</h3><p>${escapeText(lesson.analogy)}</p></section>` : ""}
        ${lesson.important_fact ? `<section class="tiny-card fact"><h3>Important fact</h3><p>${escapeText(lesson.important_fact)}</p></section>` : ""}
        ${lesson.example ? `<section class="tiny-card example"><h3>Example</h3><p>${escapeText(lesson.example)}</p></section>` : ""}
        ${quiz ? quizMarkup(quiz) : ""}
        ${gcse ? gcseMarkup(gcse) : ""}
        ${flashcards.length ? lessonFlashcardsMarkup(flashcards) : ""}
        <div class="lesson-actions">
          <button type="button" data-tutor-mode="explain" data-prompt="Explain this topic as one tiny lesson step.">Explain Simpler</button>
          <button type="button" data-tutor-mode="example" data-prompt="Give another example as a tiny lesson step.">Give Another Example</button>
          <button type="button" data-tutor-mode="youtube-summary" data-prompt="Explain my YouTube summary as a tiny lesson step.">Show Video</button>
          <button type="button" data-tutor-mode="flashcards" data-prompt="Create flashcards as an interactive lesson reward.">Create Flashcards</button>
          <button type="button" data-tutor-mode="exam-question" data-prompt="Give me one GCSE question as the next lesson step.">GCSE Question</button>
          <button type="button" data-tutor-mode="quiz" data-prompt="Test me with one mini question as the next lesson step.">Test Me</button>
          <button class="primary-action" type="button" data-tutor-mode="continue" data-prompt="Continue the lesson with the next tiny step.">${escapeText(lesson.next_step || "Continue")}</button>
        </div>
      </article>`;
  }

  function difficultyStars(level) {
    const label = (level || "easy").toLowerCase();
    if (label === "hard") return "Difficulty: ★★★ Hard";
    if (label === "medium") return "Difficulty: ★★ Medium";
    return "Difficulty: ★ Easy";
  }

  function quizMarkup(quiz) {
    return `
      <section class="mini-quiz" data-mini-quiz>
        <h3>${escapeText(quiz.question || "Mini question")}</h3>
        <div class="quiz-choice-grid">
          ${(quiz.choices || []).map((choice, index) => `<button type="button" data-quiz-choice="${index}" data-correct="${quiz.correct_index}">${escapeText(choice)}</button>`).join("")}
        </div>
        <p class="quiz-feedback" data-quiz-feedback hidden>${escapeText(quiz.explanation_if_wrong || "Good try. Check the key fact above.")}</p>
      </section>`;
  }

  function gcseMarkup(gcse) {
    return `
      <section class="gcse-card">
        <h3>GCSE Question (${Number(gcse.marks || 1)} marks)</h3>
        <p>${escapeText(gcse.question || "")}</p>
        <details>
          <summary>Model answer</summary>
          <p>${escapeText(gcse.model_answer || gcse.mark_scheme || "")}</p>
        </details>
      </section>`;
  }

  function lessonFlashcardsMarkup(cards) {
    return `
      <section class="lesson-flashcards">
        <h3>Flashcards</h3>
        <div class="lesson-flashcard-grid">
          ${cards.map((card) => `<article><strong>${escapeText(card.front || "")}</strong><p>${escapeText(card.back || "")}</p><span>${escapeText(card.difficulty || "Easy")}</span></article>`).join("")}
        </div>
      </section>`;
  }

  function renderMissionComplete(stage, lesson) {
    const state = currentLesson || loadLessonState();
    stage.innerHTML = `
      <article class="lesson-card mission-complete">
        <div class="confetti" aria-hidden="true"><span></span><span></span><span></span><span></span></div>
        <div class="robot-face level-up" aria-hidden="true">TA</div>
        <p class="eyebrow">Mission Complete</p>
        <h2>${escapeText(lesson.title || note.topic || note.subject || "Lesson complete")}</h2>
        <p>You earned ${state.xp || 0} XP and moved this topic forward.</p>
        <div class="badge-row">
          ${(state.badges && state.badges.length ? state.badges : ["Tiny Steps"]).map((badge) => `<span>${escapeText(badge)}</span>`).join("")}
        </div>
        <p><strong>Suggested next topic:</strong> ${escapeText(lesson.suggested_next_topic || "Review this again tomorrow")}</p>
        <button class="primary-action" type="button" data-tutor-action="new-chat">Start New Mission</button>
      </article>`;
  }

  function tutorProfile() {
    const profile = loadProfile();
    if (note.subject) profile.currentSubject = note.subject;
    if (note.topic) profile.currentTopic = note.topic === "Topic not selected yet" ? "" : note.topic;
    const yearField = document.querySelector('[data-context-field="year_group"]');
    const nameField = document.querySelector('[data-context-field="student_name"]');
    const subjectsField = document.querySelector('[data-context-field="selected_subjects"]');
    if (nameField && profile.name) nameField.textContent = profile.name;
    if (yearField && profile.yearGroup) yearField.textContent = profile.yearGroup;
    if (subjectsField && Array.isArray(profile.subjects) && profile.subjects.length) {
      subjectsField.textContent = profile.subjects.map((subject) => subject.replace(/-/g, " ")).join(", ");
    }
    return profile;
  }

  function displayTutorName() {
    const profile = loadProfile();
    return profile.name || "you";
  }

  function renderTutorHistory(history, loading = false) {
    const historyEl = document.querySelector("[data-chat-history]");
    if (!historyEl) return;
    if (!history.length && !loading) {
      historyEl.innerHTML = `
        <article class="chat-empty">
          <strong>Ready when ${escapeText(displayTutorName())} is.</strong>
          <p>Choose a study button or ask a question about the current topic.</p>
        </article>`;
      return;
    }
    historyEl.innerHTML = history.map((item) => `
      <article class="chat-message ${item.role === "user" ? "from-student" : "from-tutor"}" data-message-role="${item.role}">
        <span>${item.role === "user" ? "You" : "TutAIR"}</span>
        <p>${escapeText(friendlyHistoryContent(item))}</p>
      </article>
    `).join("") + (loading ? `
      <article class="chat-message from-tutor loading">
        <span>TutAIR</span>
        <p><i></i><i></i><i></i> TutAIR is thinking...</p>
      </article>` : "");
    window.requestAnimationFrame(() => {
      historyEl.scrollTop = historyEl.scrollHeight;
    });
  }

  function setTutorError(message) {
    const error = document.querySelector("[data-tutor-error]");
    if (!error) return;
    error.textContent = message || "";
    error.hidden = !message;
  }

  function nextModeAfterSend(mode) {
    if (mode === "exam-question") return "exam-answer";
    return mode;
  }

  function nextModeAfterReply(mode) {
    if (mode === "exam-answer") return "general";
    if (mode === "flashcards") return "general";
    if (mode === "revision-notes") return "general";
    return mode;
  }

  function toggleFlashcardSave(show) {
    const panel = document.querySelector("[data-tutor-save-panel]");
    if (panel) panel.hidden = !show;
  }

  function saveLatestFlashcards() {
    if (!lastTutorReply.trim()) {
      setTutorError("Generate flashcards first.");
      return;
    }
    const key = `${tutorSavedFlashcardsPrefix}${note.id || note.subject || "general"}`;
    const saved = JSON.parse(localStorage.getItem(key) || "[]");
    saved.push({
      savedAt: new Date().toISOString(),
      subject: note.subject || "",
      topic: note.topic || "",
      cards: lastTutorReply
    });
    localStorage.setItem(key, JSON.stringify(saved));
    toggleFlashcardSave(false);
    showToast("Flashcards saved locally for later revision.");
  }

  async function sendTutorMessage(message, mode = activeTutorMode) {
    const sendButton = document.querySelector("[data-tutor-send]");
    const input = document.getElementById("tutor-message");
    const history = loadTutorHistory();
    const nextHistory = history.concat({ role: "user", content: message });
    saveTutorHistory(nextHistory);
    setTutorError("");
    renderTutorHistory(nextHistory, true);
    activeTutorMode = nextModeAfterSend(mode);
    toggleFlashcardSave(false);
    if (sendButton) sendButton.disabled = true;
    if (input) input.disabled = true;
    try {
      const response = await fetch("/api/tutor/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          note_id: note.id || "",
          message,
          mode,
          history,
          profile: tutorProfile()
        })
      });
      const payload = await response.json();
      if (!response.ok || payload.error) throw new Error(payload.error || "TutAIR could not answer yet.");
      const finalHistory = nextHistory.concat({ role: "assistant", content: payload.reply });
      lastTutorReply = payload.reply || "";
      const parsedLesson = parseLessonReply(lastTutorReply);
      const lesson = normaliseLesson(parsedLesson, lastTutorReply);
      applyLessonReward(lesson);
      renderLessonStage(lesson);
      saveTutorHistory(finalHistory);
      renderTutorHistory(finalHistory);
      activeTutorMode = nextModeAfterReply(mode);
      toggleFlashcardSave(mode === "flashcards");
    } catch (error) {
      setTutorError(error.message || "Something went wrong. Try again in a moment.");
      renderTutorHistory(nextHistory);
    } finally {
      if (sendButton) sendButton.disabled = false;
      if (input) {
        input.disabled = false;
        input.focus();
      }
    }
  }

  function initialiseTutor() {
    const form = document.querySelector("[data-tutor-form]");
    if (!form) return;
    tutorProfile();
    currentLesson = loadLessonState();
    updateLessonStatus();
    renderLessonStage(currentLesson.lastLesson);
    renderTutorHistory(loadTutorHistory());
    const newChat = document.querySelector('[data-tutor-action="new-chat"]');
    if (newChat) newChat.addEventListener("click", startNewTutorSession);
    const clear = document.querySelector('[data-tutor-action="clear"]');
    if (clear) clear.addEventListener("click", () => {
      saveTutorHistory([]);
      setTutorError("");
      lastTutorReply = "";
      activeTutorMode = "general";
      toggleFlashcardSave(false);
      renderTutorHistory([]);
    });
    const saveCards = document.querySelector('[data-tutor-action="save-flashcards"]');
    if (saveCards) saveCards.addEventListener("click", saveLatestFlashcards);
    const input = document.getElementById("tutor-message");
    if (input) {
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.shiftKey) {
          event.preventDefault();
          form.requestSubmit();
        }
      });
    }
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const input = document.getElementById("tutor-message");
      const message = input ? input.value.trim() : "";
      if (!message) {
        setTutorError("Type a question first.");
        return;
      }
      if (input) input.value = "";
      sendTutorMessage(message, activeTutorMode);
    });
  }

  function renderFlashcards() {
    const cards = note.flashcards || [];
    if (!cards.length) {
      showToast("Coming Soon: this note has no flashcards yet.");
      return;
    }
    setMode("flashcards");
    flashIndex = Math.min(flashIndex, cards.length - 1);
    flashShowingAnswer = false;
    const view = document.createElement("article");
    view.className = "practice-view flashcard-practice";
    view.setAttribute("aria-live", "polite");
    view.innerHTML = flashcardMarkup(cards);
    content.appendChild(view);
  }

  function flashcardMarkup(cards) {
    const card = cards[flashIndex];
    const visibleText = flashShowingAnswer ? card.answer : card.question;
    return `
      <p class="eyebrow">${escapeText(note.subject || "TutAIR")}</p>
      <h2>Flashcards</h2>
      <div class="practice-card" tabindex="0">
        <span>Card ${flashIndex + 1} of ${cards.length}</span>
        <strong>${escapeText(flashShowingAnswer ? "Answer" : "Question")}</strong>
        <p>${escapeText(visibleText)}</p>
      </div>
      <div class="practice-controls">
        <button type="button" data-practice="prev">Previous</button>
        <button type="button" data-practice="flip">${flashShowingAnswer ? "Show Question" : "Flip Card"}</button>
        <button type="button" data-practice="next">Next</button>
        <button type="button" data-action="notes">Back to Notes</button>
      </div>`;
  }

  function rerenderFlashcards() {
    const view = content.querySelector(".flashcard-practice");
    if (view) view.innerHTML = flashcardMarkup(note.flashcards || []);
  }

  function quizAnswerMarkup(item) {
    const parts = [`<strong>${escapeText(item.answer || "")}</strong>`];
    if (item.timestamp) parts.push(`<em>taught at ${escapeText(item.timestamp)}</em>`);
    if (item.explanation) parts.push(escapeText(item.explanation));
    if (item.objective_id) parts.push(`<small>Specification objective: ${escapeText(item.objective_id)}</small>`);
    return parts.join("<br>");
  }

  function renderQuiz() {
    const questions = note.questions || [];
    if (!questions.length) {
      showToast("Coming Soon: this note has no quiz questions yet.");
      return;
    }
    setMode("quiz");
    const view = document.createElement("article");
    view.className = "practice-view quiz-practice";
    view.innerHTML = `
      <p class="eyebrow">${escapeText(note.subject || "TutAIR")}</p>
      <h2>Quiz Me</h2>
      <form class="quiz-form">
        ${questions.map((item, index) => `
          <section class="quiz-item">
            <label for="quiz-${index}"><strong>${index + 1}. ${escapeText(item.question)}</strong></label>
            ${(item.options || []).length
              ? `<div class="quiz-options" role="group" aria-labelledby="quiz-${index}">
                   ${item.options.map((option) => `
                     <label class="quiz-option">
                       <input type="radio" name="quiz-${index}" value="${escapeText(option.id)}">
                       <span>${escapeText(option.id)}. ${escapeText(option.text)}</span>
                     </label>
                   `).join("")}
                 </div>`
              : `<textarea id="quiz-${index}" rows="3" placeholder="Try your answer first"></textarea>`}
            <button type="button" data-reveal="${index}">Reveal</button>
            <p class="quiz-answer" id="answer-${index}" hidden>${quizAnswerMarkup(item)}</p>
          </section>
        `).join("")}
      </form>
      <div class="practice-controls">
        <button type="button" data-action="notes">Back to Notes</button>
      </div>`;
    content.appendChild(view);
  }

  function readAloud() {
    if (!("speechSynthesis" in window)) {
      showToast("Coming Soon: read aloud is not available in this browser.");
      return;
    }
    setMode("read");
    const text = Array.from(document.querySelectorAll(".note .revision-section"))
      .map((section) => section.innerText.trim())
      .filter(Boolean)
      .join("\n\n");
    if (!text) {
      showToast("Nothing to read yet.");
      return;
    }
    const view = document.createElement("article");
    view.className = "practice-view read-practice";
    view.innerHTML = `
      <p class="eyebrow">${escapeText(note.subject || "TutAIR")}</p>
      <h2>Read Aloud</h2>
      <p>The browser will read the current revision note aloud.</p>
      <div class="practice-controls">
        <button type="button" data-speech="play">Play</button>
        <button type="button" data-speech="pause">Pause</button>
        <button type="button" data-speech="stop">Stop</button>
        <button type="button" data-action="notes">Back to Notes</button>
      </div>`;
    content.appendChild(view);
    activeUtterance = new SpeechSynthesisUtterance(text);
    activeUtterance.rate = 0.92;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(activeUtterance);
  }

  function stopSpeech() {
    if ("speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
    activeUtterance = null;
  }

  function toggleFocus() {
    const enabled = document.body.classList.toggle("focus-mode");
    const button = document.querySelector('[data-action="focus"]');
    if (button) button.textContent = enabled ? "Exit Focus" : "Focus Mode";
    showToast(enabled ? "Focus Mode on" : "Focus Mode off");
  }

  function toggleReviewed() {
    if (!note.id) return;
    const reviewed = getSet("reviewed");
    if (reviewed.has(note.id)) {
      reviewed.delete(note.id);
    } else {
      reviewed.add(note.id);
    }
    saveSet("reviewed", reviewed);
    applyLocalState();
  }

  function toggleFavourite() {
    if (!note.id) return;
    const favourites = getSet("favourites");
    if (favourites.has(note.id)) {
      favourites.delete(note.id);
      showToast("Removed from favourites");
    } else {
      favourites.add(note.id);
      showToast("Saved to favourites");
    }
    saveSet("favourites", favourites);
    applyLocalState();
  }

  function applyLocalState() {
    if (!note.id) return;
    const reviewed = getSet("reviewed");
    const favourites = getSet("favourites");
    document.body.classList.toggle("is-reviewed", reviewed.has(note.id));
    document.body.classList.toggle("is-favourite", favourites.has(note.id));
    document.querySelectorAll(`[data-note-id="${CSS.escape(note.id)}"]`).forEach((el) => {
      el.classList.toggle("reviewed", reviewed.has(note.id));
      el.classList.toggle("favourite", favourites.has(note.id));
    });
    const reviewButton = document.querySelector('[data-action="mark-reviewed"]');
    if (reviewButton) reviewButton.textContent = reviewed.has(note.id) ? "Reviewed" : "Mark as Reviewed";
    const saveButton = document.querySelector('[data-action="save-topic"]');
    if (saveButton) saveButton.textContent = favourites.has(note.id) ? "Saved Topic" : "Save Topic";
    const status = document.querySelector(".status");
    if (status && reviewed.has(note.id) && !status.querySelector(".reviewed-pill")) {
      status.insertAdjacentHTML("beforeend", '<small class="reviewed-pill">reviewed locally</small>');
    }
    renderFavourites(favourites);
  }

  function renderFavourites(favourites) {
    const rail = document.querySelector(".side-rail");
    if (!rail) return;
    let box = rail.querySelector(".favourites-section");
    if (!box) {
      box = document.createElement("section");
      box.className = "rail-section favourites-section";
      const subjects = rail.querySelector(".rail-section");
      if (subjects) subjects.insertAdjacentElement("afterend", box);
    }
    if (!favourites.size) {
      box.innerHTML = '<h2>Favourites</h2><p class="rail-empty">No saved topics yet</p>';
      return;
    }
    const isCurrent = note.id && favourites.has(note.id);
    box.innerHTML = `
      <h2>Favourites</h2>
      ${isCurrent ? `<a class="subject-link active" href="/note/${encodeURIComponent(note.id)}"><span class="subject-icon">*</span><span>${escapeText(note.topic || "Saved topic")}</span></a>` : '<p class="rail-empty">Saved topics appear when opened</p>'}
    `;
  }

  document.addEventListener("click", (event) => {
    const target = event.target.closest("button, a");
    if (!target) return;
    const lessonMode = target.dataset.tutorMode;
    if (lessonMode && target.dataset.prompt) {
      event.preventDefault();
      activeTutorMode = lessonMode;
      sendTutorMessage(target.dataset.prompt, activeTutorMode);
      return;
    }
    const quizChoice = target.dataset.quizChoice;
    if (quizChoice !== undefined) {
      event.preventDefault();
      const correct = target.dataset.correct;
      const quizBox = target.closest("[data-mini-quiz]");
      const feedback = quizBox ? quizBox.querySelector("[data-quiz-feedback]") : null;
      const isCorrect = String(quizChoice) === String(correct);
      target.classList.add(isCorrect ? "correct" : "incorrect");
      if (feedback) {
        feedback.hidden = false;
        feedback.textContent = isCorrect ? "+10 XP. Nice work." : feedback.textContent;
      }
      const state = currentLesson || loadLessonState();
      state.xp = (state.xp || 0) + (isCorrect ? 10 : 3);
      state.progress = Math.min(100, (state.progress || 0) + (isCorrect ? 8 : 3));
      state.completedQuestions = (state.completedQuestions || 0) + 1;
      currentLesson = state;
      saveLessonState(state);
      updateLessonStatus();
      showToast(isCorrect ? "+10 XP" : "+3 XP for trying");
      return;
    }
    const profileAction = target.dataset.profileAction;
    if (profileAction) {
      event.preventDefault();
      routeProfileAction(profileAction, target);
      return;
    }
    const year = target.dataset.year;
    if (year) {
      const profile = loadProfile();
      profile.yearGroup = year;
      saveProfile(profile);
      renderYearGroup();
      return;
    }
    const subjectId = target.dataset.subject;
    if (subjectId) {
      const profile = loadProfile();
      const selected = new Set(profile.subjects || []);
      if (selected.has(subjectId)) selected.delete(subjectId);
      else selected.add(subjectId);
      profile.subjects = Array.from(selected);
      profile.examBoards = Object.fromEntries(Object.entries(profile.examBoards || {}).filter(([key]) => selected.has(key)));
      profile.completed = false;
      saveProfile(profile);
      renderSubjectSelection();
      return;
    }
    const boardSubject = target.dataset.boardButton;
    if (boardSubject) {
      const profile = loadProfile();
      profile.examBoards = { ...(profile.examBoards || {}), [boardSubject]: target.dataset.boardValue || "Unknown" };
      saveProfile(profile);
      renderExamBoards();
      return;
    }
    const action = target.dataset.action;
    if (action === "flashcards") renderFlashcards();
    if (action === "quiz") renderQuiz();
    if (action === "notes") {
      stopSpeech();
      setMode("notes");
    }
    if (action === "read-aloud") readAloud();
    if (action === "focus") toggleFocus();
    if (action === "mark-reviewed") toggleReviewed();
    if (action === "save-topic") toggleFavourite();
    if (action === "coming-soon") showToast(`Coming Soon: ${target.dataset.feature || "This feature"}`);

    const practice = target.dataset.practice;
    if (practice === "prev") {
      flashIndex = Math.max(0, flashIndex - 1);
      flashShowingAnswer = false;
      rerenderFlashcards();
    }
    if (practice === "next") {
      flashIndex = Math.min((note.flashcards || []).length - 1, flashIndex + 1);
      flashShowingAnswer = false;
      rerenderFlashcards();
    }
    if (practice === "flip") {
      flashShowingAnswer = !flashShowingAnswer;
      rerenderFlashcards();
    }

    const reveal = target.dataset.reveal;
    if (reveal !== undefined) {
      const answer = document.getElementById(`answer-${reveal}`);
      if (answer) answer.hidden = false;
    }

    const speech = target.dataset.speech;
    if (speech === "play") {
      if (window.speechSynthesis.paused) window.speechSynthesis.resume();
      else readAloud();
    }
    if (speech === "pause" && "speechSynthesis" in window) window.speechSynthesis.pause();
    if (speech === "stop") stopSpeech();
  });

  document.addEventListener("input", (event) => {
    const boardSelect = event.target.closest("select[data-board]");
    if (boardSelect) {
      const profile = loadProfile();
      profile.examBoards = { ...(profile.examBoards || {}), [boardSelect.dataset.board]: boardSelect.value || "Unknown" };
      saveProfile(profile);
      return;
    }
    if (event.target.closest(".quiz-item")) {
      const answer = event.target.closest(".quiz-item").querySelector(".quiz-answer");
      if (answer && event.target.value.trim().length > 0) answer.hidden = false;
    }
  });

  document.addEventListener("submit", (event) => {
    const form = event.target.closest("form[data-form]");
    if (!form) return;
    event.preventDefault();
    const formData = new FormData(form);
    const profile = loadProfile();
    profile.name = (formData.get("name") || profile.name || "").toString().trim();
    profile.email = (formData.get("email") || profile.email || "").toString().trim();
    profile.rememberMe = formData.get("remember") === "on";
    if (form.dataset.form === "forgot") {
      showToast("Password reset is Coming Soon in the local prototype.");
      renderLogin("login");
      return;
    }
    profile.signedIn = profile.rememberMe;
    sessionStorage.setItem(sessionKey, "1");
    saveProfile(profile);
    if (profile.completed) renderPersonalDashboard();
    else renderYearGroup();
  });

  applyLocalState();
  if (profileApp && app) initialiseProfileScreen();
  initialiseTutor();
})();
"""


CSS = """
:root {
  color-scheme: light;
  --nav: #121239;
  --nav-2: #191446;
  --ink: #171442;
  --muted: #6d6b8a;
  --panel: #ffffff;
  --line: #e4dcf5;
  --aqua: #18c7bd;
  --aqua-dark: #07959a;
  --purple: #a74ee8;
  --blue: #2d91e9;
  --green: #18a84f;
  --yellow: #ffcc29;
  --pink: #ed4f9b;
  --orange: #e19a00;
  --shadow: 0 14px 34px rgba(37, 29, 78, 0.12);
  --soft-shadow: 0 8px 22px rgba(24, 199, 189, 0.12);
}

* { box-sizing: border-box; }

[hidden] {
  display: none !important;
}

body {
  margin: 0;
  background:
    radial-gradient(circle at 60% 10%, rgba(167, 78, 232, 0.08), transparent 32%),
    linear-gradient(120deg, #fbfdff 0%, #fff8fc 48%, #f7fffd 100%);
  color: var(--ink);
  font-family: "Trebuchet MS", Arial, Helvetica, sans-serif;
  line-height: 1.5;
}

button,
a {
  font: inherit;
}

button:focus-visible,
a:focus-visible {
  outline: 4px solid rgba(24, 199, 189, 0.45);
  outline-offset: 3px;
}

button:disabled {
  cursor: not-allowed;
}

.app-shell {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  min-height: 100vh;
}

.side-rail {
  background: linear-gradient(180deg, #15123f 0%, #0c1031 100%);
  color: #f7f4ff;
  display: flex;
  flex-direction: column;
  gap: 28px;
  padding: 30px 24px;
  position: sticky;
  top: 0;
  height: 100vh;
}

.brand {
  align-items: center;
  color: #ffffff;
  display: flex;
  gap: 12px;
  text-decoration: none;
}

.brand-mark,
.subject-icon,
.topic-icon,
.section-icon {
  align-items: center;
  display: inline-flex;
  justify-content: center;
}

.brand-mark {
  background: linear-gradient(135deg, #d9a6ff, #55efe6);
  border-radius: 14px;
  box-shadow: 0 10px 26px rgba(85, 239, 230, 0.22);
  color: #14123d;
  font-weight: 900;
  height: 42px;
  width: 42px;
}

.brand strong {
  display: block;
  font-size: 2.15rem;
  letter-spacing: 0;
  line-height: 1;
}

.brand strong span { color: #35e5dc; }
.brand small { color: #c6c3e3; display: block; margin-top: 7px; }

.rail-section h2,
.side-card h2,
.topic-panel h2 {
  color: var(--aqua);
  font-size: 0.95rem;
  letter-spacing: 0;
  margin: 0 0 14px;
  text-transform: uppercase;
}

.rail-section {
  display: grid;
  gap: 10px;
}

.subject-link,
.rail-button,
.break-button {
  align-items: center;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(98, 67, 177, 0.74);
  border-radius: 8px;
  color: #ffffff;
  display: flex;
  gap: 14px;
  min-height: 46px;
  padding: 11px 14px;
  text-decoration: none;
  width: 100%;
}

.subject-link.active {
  background: linear-gradient(135deg, #16c9bd, #178f99);
  border-color: rgba(55, 238, 226, 0.74);
  box-shadow: var(--soft-shadow);
  font-weight: 800;
}

.subject-link.ghost,
.rail-button.placeholder {
  color: #e8e3ff;
}

.subject-icon {
  background: rgba(255, 255, 255, 0.12);
  border-radius: 7px;
  color: #61f1e8;
  font-weight: 900;
  height: 24px;
  min-width: 24px;
}

.plan label {
  align-items: center;
  color: #ffffff;
  display: flex;
  gap: 10px;
  min-height: 26px;
}

.plan input {
  accent-color: var(--aqua);
  height: 20px;
  width: 20px;
}

.tip-card {
  background: linear-gradient(145deg, rgba(24, 199, 189, 0.12), rgba(85, 58, 159, 0.34));
  border: 1px solid rgba(24, 199, 189, 0.20);
  border-radius: 8px;
  color: #ffffff;
  padding: 18px;
}

.tip-card h2 {
  color: var(--yellow);
  font-size: 1rem;
  margin: 0 0 10px;
}

.tip-card p,
.hero p,
.side-card p,
.help-card p {
  margin: 0;
}

.break-button {
  background: linear-gradient(135deg, #5d2fa4, #6b33bd);
  border: 0;
  font-weight: 800;
  justify-content: center;
  margin-top: auto;
}

.workspace {
  min-width: 0;
  padding: 24px 32px 12px;
}

.hero,
.crumb-bar,
.encouragement {
  align-items: center;
  display: flex;
  justify-content: space-between;
}

.hero {
  min-height: 84px;
}

.hero h1 {
  color: #161344;
  font-size: clamp(2rem, 4vw, 3rem);
  line-height: 1;
  margin: 0 0 8px;
  text-transform: uppercase;
}

.hero p {
  color: #a24ef0;
  font-size: 1.1rem;
  font-weight: 800;
}

.hero-actions {
  align-items: center;
  display: flex;
  gap: 14px;
}

.hero-actions button,
.streak,
.toolbar button {
  border-radius: 8px;
  border: 1px solid var(--line);
  box-shadow: 0 6px 16px rgba(28, 24, 72, 0.08);
  font-weight: 800;
  min-height: 42px;
  padding: 0 18px;
}

.hero-actions button {
  background: #ffffff;
  color: var(--aqua-dark);
}

.hero-actions button:nth-child(2) {
  color: #7358d9;
}

.hero-actions .sun {
  background: #ffffff;
  border-radius: 50%;
  min-width: 42px;
  padding: 0;
}

.hero-actions .sun::before {
  color: var(--yellow);
  content: "☼";
  font-size: 1.35rem;
}

.streak {
  align-items: center;
  background: #f1fff6;
  border-color: #c9efd7;
  color: #188f39;
  display: grid;
  min-width: 174px;
  padding: 10px 18px;
}

.crumb-bar {
  background: rgba(255, 255, 255, 0.70);
  border: 1px solid #cbeeed;
  border-radius: 8px;
  box-shadow: var(--shadow);
  gap: 16px;
  margin: 14px 0 22px;
  padding: 20px;
}

.crumbs {
  align-items: center;
  background: #f8ffff;
  border: 1px solid #d9eeee;
  border-radius: 7px;
  color: #26324f;
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  padding: 10px 14px;
}

.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.toolbar .save { background: var(--yellow); border-color: #f3be00; color: #1b1840; }
.toolbar .export { background: #e9f4ff; border-color: #9ac8f6; color: #162040; }
.toolbar .review { background: #0b9342; border-color: #0b9342; color: #ffffff; }

.study-grid {
  display: grid;
  grid-template-columns: 300px minmax(440px, 1fr) 240px;
  gap: 24px;
}

.topic-panel,
.side-card {
  background: rgba(255, 255, 255, 0.76);
  border: 1px solid var(--line);
  border-radius: 8px;
  box-shadow: 0 10px 28px rgba(27, 22, 68, 0.08);
  padding: 18px;
}

.topic-list {
  display: grid;
  gap: 14px;
}

.topic-link {
  align-items: center;
  background: #ffffff;
  border: 1px solid #e7e5ee;
  border-radius: 8px;
  color: var(--ink);
  display: grid;
  gap: 12px;
  grid-template-columns: 34px 1fr auto;
  min-height: 64px;
  padding: 12px;
  text-align: left;
  text-decoration: none;
  width: 100%;
}

.topic-link.active {
  background: linear-gradient(135deg, #0fa8a6, #17a3a6);
  border-color: #0fa8a6;
  color: #ffffff;
  font-weight: 800;
}

.topic-link.ghost {
  color: var(--ink);
}

.topic-link small {
  color: inherit;
  display: block;
  font-weight: 500;
  opacity: 0.76;
}

.topic-icon {
  background: #f5f7ff;
  border-radius: 50%;
  color: var(--purple);
  font-weight: 900;
  height: 34px;
  width: 34px;
}

.help-card {
  background: #f2ffff;
  border: 1px solid #c6eeee;
  border-radius: 8px;
  color: #26405e;
  margin-top: 56px;
  padding: 18px;
}

.help-card strong {
  color: var(--aqua-dark);
  display: block;
  font-size: 1.05rem;
  margin-bottom: 8px;
}

.help-card button {
  background: #f9ffff;
  border: 1px solid #97d7da;
  border-radius: 7px;
  color: var(--aqua-dark);
  font-weight: 800;
  margin-top: 14px;
  min-height: 42px;
  width: 100%;
}

.content {
  min-width: 0;
}

.note-heading {
  align-items: flex-start;
  display: flex;
  justify-content: space-between;
  margin-bottom: 16px;
}

.eyebrow {
  color: var(--aqua-dark);
  font-weight: 900;
  letter-spacing: 0;
  margin: 0 0 8px;
  text-transform: uppercase;
}

.note-heading h2 {
  color: var(--ink);
  font-size: clamp(2.1rem, 4vw, 3rem);
  line-height: 1;
  margin: 0;
}

.status {
  background: #11194a;
  border: 2px solid #08b1ab;
  border-radius: 7px;
  color: #ffffff;
  display: grid;
  min-width: 178px;
  padding: 12px;
  text-align: right;
}

.status span {
  font-weight: 900;
}

.status small {
  font-weight: 800;
  opacity: 0.9;
}

.revision-section {
  background: rgba(255, 255, 255, 0.70);
  border: 2px solid #9dd2ff;
  border-radius: 8px;
  margin-bottom: 12px;
  padding: 16px 48px 16px 18px;
  position: relative;
}

.revision-section h3 {
  align-items: center;
  color: var(--blue);
  display: flex;
  gap: 9px;
  font-size: 1.1rem;
  margin: 0 0 10px;
}

.revision-section p,
.revision-section li {
  color: #161b34;
  font-size: 0.95rem;
}

.revision-section p:last-child,
.revision-section ul:last-child {
  margin-bottom: 0;
}

.revision-section.key-facts {
  background: #f3fff6;
  border-color: #7ed497;
}

.revision-section.key-facts h3 { color: #219645; }

.revision-section.what-this-means {
  background: #fffcf1;
  border-color: #f4c647;
}

.revision-section.what-this-means h3 { color: var(--orange); }

.revision-section.exam-style-questions {
  background: #fbf5ff;
  border-color: #bc78ec;
}

.revision-section.exam-style-questions h3 { color: var(--purple); }

.revision-section.flashcards {
  background: #fff5fb;
  border-color: #ef8fc0;
}

.revision-section.flashcards h3 { color: var(--pink); }

.revision-section.next-revision-task,
.revision-section.exam-board-mapping {
  background: #f7ffff;
  border-color: #7bd8d5;
}

.revision-section.next-revision-task h3,
.revision-section.exam-board-mapping h3 {
  color: var(--aqua-dark);
}

.section-icon {
  border-radius: 50%;
  color: currentColor;
  font-size: 0.78rem;
  font-weight: 900;
  min-height: 22px;
  min-width: 22px;
}

.collapse-dot {
  background: var(--blue);
  border: 0;
  border-radius: 50%;
  height: 26px;
  position: absolute;
  right: 16px;
  top: 16px;
  width: 26px;
}

.collapse-dot::after {
  color: #ffffff;
  content: "⌄";
  font-weight: 900;
}

.key-facts .collapse-dot { background: var(--green); }
.what-this-means .collapse-dot { background: #f4b400; }
.exam-style-questions .collapse-dot { background: var(--purple); }
.flashcards .collapse-dot { background: var(--pink); }

.revision-section ul {
  margin: 0;
  padding-left: 24px;
}

.flashline {
  display: inline-block;
  margin: 0 28px 7px 0;
}

.source {
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid var(--line);
  border-radius: 8px;
  color: var(--muted);
  margin-top: 12px;
  padding: 14px;
}

.side-card {
  margin-bottom: 20px;
}

.quick-actions {
  display: grid;
  gap: 10px;
}

.quick-actions button {
  border-radius: 6px;
  font-weight: 900;
  min-height: 38px;
}

.quick-actions .flashcards { background: #fcf3ff; border: 1px solid #d997f6; color: var(--purple); }
.quick-actions .quiz { background: #fff2f6; border: 1px solid #f3a3c4; color: var(--pink); }
.quick-actions .mindmap { background: #eff8ff; border: 1px solid #a3d1f7; color: var(--blue); }
.quick-actions .notes { background: #fff9df; border: 1px solid #f0c54c; color: var(--orange); }
.quick-actions .read { background: #edfff1; border: 1px solid #a4dfa9; color: var(--green); }

.timer strong {
  color: #b163ef;
  font-size: 2.35rem;
}

.timer div {
  align-items: center;
  display: flex;
  justify-content: space-between;
}

.timer button {
  background: linear-gradient(135deg, #c64be7, #834ee9);
  border: 0;
  border-radius: 50%;
  color: #ffffff;
  height: 52px;
  width: 52px;
}

.timer a {
  color: var(--ink);
  font-size: 0.8rem;
}

.progress-row {
  align-items: center;
  display: flex;
  justify-content: space-between;
}

.progress-row strong {
  align-items: center;
  border: 7px solid #ffd5e6;
  border-top-color: #f490bd;
  border-radius: 50%;
  color: var(--pink);
  display: flex;
  height: 78px;
  justify-content: center;
  width: 78px;
}

.progress label {
  color: var(--aqua-dark);
  display: flex;
  font-size: 0.9rem;
  justify-content: space-between;
  margin-top: 14px;
}

.bar {
  background: #eef0ef;
  border-radius: 999px;
  height: 10px;
  margin-top: 6px;
  overflow: hidden;
}

.bar span {
  background: var(--aqua);
  display: block;
  height: 100%;
  width: 12%;
}

.empty {
  background: rgba(255, 255, 255, 0.78);
  border: 2px dashed #9ddbd8;
  border-radius: 8px;
  padding: 30px;
}

.muted,
.rail-empty {
  color: var(--muted);
}

code {
  background: #f1f2f8;
  border-radius: 6px;
  display: inline-block;
  max-width: 100%;
  overflow-wrap: anywhere;
  padding: 4px 6px;
}

.encouragement {
  background: rgba(247, 255, 255, 0.88);
  border: 1px solid #c7eded;
  border-radius: 8px;
  box-shadow: 0 10px 26px rgba(24, 199, 189, 0.12);
  color: #489399;
  gap: 16px;
  margin-top: 24px;
  padding: 16px 24px;
}

.encouragement span {
  white-space: nowrap;
}

.encouragement button {
  background: linear-gradient(135deg, #0fa8a6, #078f98);
  border: 0;
  border-radius: 6px;
  color: #ffffff;
  font-weight: 900;
  min-height: 36px;
  padding: 0 18px;
}

.toast {
  background: #11194a;
  border: 2px solid var(--aqua);
  border-radius: 8px;
  bottom: 22px;
  box-shadow: var(--shadow);
  color: #ffffff;
  font-weight: 800;
  left: 50%;
  max-width: min(90vw, 520px);
  padding: 12px 16px;
  position: fixed;
  transform: translateX(-50%);
  z-index: 20;
}

.practice-view {
  background: rgba(255, 255, 255, 0.82);
  border: 2px solid #9dd2ff;
  border-radius: 8px;
  box-shadow: var(--shadow);
  padding: 22px;
}

.practice-view h2 {
  color: var(--ink);
  font-size: clamp(2rem, 4vw, 2.8rem);
  line-height: 1;
  margin: 0 0 18px;
}

.practice-card {
  align-items: center;
  background: linear-gradient(145deg, #ffffff, #f8ffff);
  border: 2px solid var(--aqua);
  border-radius: 8px;
  display: grid;
  gap: 12px;
  min-height: 260px;
  padding: 26px;
  text-align: center;
}

.practice-card span {
  color: var(--muted);
  font-weight: 800;
}

.practice-card strong {
  color: var(--purple);
  font-size: 1.2rem;
  text-transform: uppercase;
}

.practice-card p {
  color: var(--ink);
  font-size: 1.35rem;
  font-weight: 800;
  margin: 0;
}

.practice-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 18px;
}

.practice-controls button,
.quiz-item button {
  background: #ffffff;
  border: 1px solid #9ac8f6;
  border-radius: 7px;
  color: var(--ink);
  font-weight: 900;
  min-height: 40px;
  padding: 0 16px;
}

.practice-controls button:nth-child(2),
.quiz-item button {
  background: var(--yellow);
  border-color: #f3be00;
}

.quiz-form {
  display: grid;
  gap: 14px;
}

.quiz-item {
  background: #fbf5ff;
  border: 1px solid #bc78ec;
  border-radius: 8px;
  display: grid;
  gap: 10px;
  padding: 16px;
}

.quiz-item label {
  color: var(--ink);
}

.quiz-options {
  display: grid;
  gap: 6px;
}

.quiz-option {
  align-items: flex-start;
  background: #ffffff;
  border: 1px solid var(--line);
  border-radius: 7px;
  cursor: pointer;
  display: flex;
  gap: 10px;
  padding: 10px 12px;
}

.quiz-option:hover {
  border-color: var(--purple);
}

.quiz-option input {
  margin-top: 3px;
}

.quiz-item textarea {
  border: 1px solid var(--line);
  border-radius: 7px;
  color: var(--ink);
  font: inherit;
  padding: 10px;
  resize: vertical;
}

.quiz-answer {
  background: #ffffff;
  border-left: 4px solid var(--purple);
  border-radius: 6px;
  margin: 0;
  padding: 10px;
}

.topic-link.reviewed::after {
  color: #ffffff;
  content: "Reviewed";
  font-size: 0.72rem;
  font-weight: 900;
}

.topic-link.favourite .topic-icon {
  background: #fff7cf;
  color: #c48b00;
}

.is-reviewed .status {
  border-color: var(--green);
}

.reviewed-pill {
  color: #a6ffbf;
}

.is-favourite .save {
  background: #fff7cf;
}

body.focus-mode .side-rail,
body.focus-mode .topic-panel,
body.focus-mode .action-panel,
body.focus-mode .crumb-bar,
body.focus-mode .encouragement {
  display: none;
}

body.focus-mode .app-shell,
body.focus-mode .study-grid {
  display: block;
}

body.focus-mode .workspace {
  margin: 0 auto;
  max-width: 980px;
  padding: 28px;
}

body.focus-mode .content {
  font-size: 1.12rem;
}

body.focus-mode .revision-section {
  padding: 24px 58px 24px 24px;
}

.profile-app {
  min-height: 100vh;
}

body[data-screen="profile"] {
  overflow-x: hidden;
}

body[data-profile-view="onboarding"] {
  overflow: hidden;
}

body[data-profile-view="onboarding"] .profile-app {
  height: 100vh;
  overflow: hidden;
}

body[data-profile-view="onboarding"] .auth-screen,
body[data-profile-view="onboarding"] .onboarding-screen,
body[data-profile-view="onboarding"] .setup-complete {
  height: 100vh;
  max-height: 100vh;
  overflow: hidden;
}

body[data-profile-view="dashboard"] {
  overflow-y: auto;
}

.auth-screen,
.onboarding-screen,
.setup-complete,
.placeholder-screen {
  align-items: center;
  display: grid;
  gap: 30px;
  min-height: 100vh;
  padding: 34px;
}

.auth-screen {
  grid-template-columns: minmax(260px, 0.78fr) minmax(320px, 520px);
}

.auth-brand,
.auth-card,
.complete-card,
.empty-panel {
  background: rgba(255, 255, 255, 0.82);
  border: 1px solid #d8f0ef;
  border-radius: 8px;
  box-shadow: var(--shadow);
}

.auth-brand {
  align-self: stretch;
  background:
    radial-gradient(circle at 26% 22%, rgba(85, 239, 230, 0.22), transparent 30%),
    linear-gradient(180deg, #15123f 0%, #0c1031 100%);
  color: #ffffff;
  display: grid;
  place-content: center;
  padding: 38px;
  text-align: center;
}

.auth-logo {
  align-items: center;
  background: linear-gradient(135deg, #d9a6ff, #55efe6);
  border-radius: 18px;
  color: #15123f;
  display: inline-flex;
  font-size: 1.3rem;
  font-weight: 900;
  height: 62px;
  justify-content: center;
  margin: 0 auto 18px;
  width: 62px;
}

.auth-brand h1,
.complete-card h1,
.personal-header h1,
.step-header h1,
.placeholder-screen h1 {
  color: var(--ink);
  font-size: clamp(2.1rem, 5vw, 3.4rem);
  line-height: 1;
  margin: 0 0 10px;
}

.auth-brand h1 {
  color: #ffffff;
}

.auth-brand h1 span,
.brand strong span {
  color: #35e5dc;
}

.auth-brand p,
.step-header p,
.personal-header p,
.complete-card p,
.placeholder-screen p,
.auth-card p {
  color: var(--muted);
  margin: 0;
}

.auth-brand p {
  color: #d7d2ff;
}

.auth-card {
  display: grid;
  gap: 16px;
  padding: 28px;
}

.auth-card label {
  color: #27224f;
  display: grid;
  font-weight: 800;
  gap: 7px;
}

.auth-card input,
.board-row select {
  background: #ffffff;
  border: 1px solid #d7d3eb;
  border-radius: 8px;
  color: var(--ink);
  min-height: 48px;
  padding: 10px 12px;
}

.inline-choice {
  align-items: center;
  display: flex !important;
  flex-direction: row;
  gap: 10px !important;
}

.inline-choice input {
  accent-color: var(--aqua);
  min-height: auto;
  width: 20px;
}

.primary-action,
.quiet-action,
.personal-nav button,
.dashboard-actions button,
.card-actions button,
.dashboard-strip button,
.bottom-nav button,
.auth-links button {
  border-radius: 8px;
  cursor: pointer;
  font-weight: 900;
  min-height: 44px;
  padding: 10px 16px;
}

.primary-action {
  background: linear-gradient(135deg, #17c9bd, #0a979a);
  border: 1px solid #0a979a;
  color: #ffffff;
  box-shadow: var(--soft-shadow);
}

.primary-action:disabled {
  background: #d9d6e8;
  border-color: #d9d6e8;
  color: #77718e;
}

.quiet-action,
.auth-links button {
  background: #ffffff;
  border: 1px solid #d7d3eb;
  color: #6550c8;
}

.auth-links,
.step-actions,
.card-actions,
.dashboard-actions,
.dashboard-strip,
.bottom-nav {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.onboarding-screen {
  align-items: stretch;
  max-width: 1180px;
  margin: 0 auto;
}

.step-header {
  align-items: center;
  display: flex;
  gap: 28px;
  justify-content: space-between;
}

.step-header .brand {
  background: linear-gradient(180deg, #15123f, #0c1031);
  border-radius: 8px;
  padding: 16px;
}

.choice-grid {
  display: grid;
  gap: 18px;
}

.year-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.subject-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.choice-card {
  background: #ffffff;
  border: 2px solid #e6e2f2;
  border-radius: 8px;
  box-shadow: 0 8px 18px rgba(27, 22, 68, 0.06);
  color: var(--ink);
  display: grid;
  gap: 9px;
  min-height: 138px;
  padding: 18px;
  text-align: left;
}

.choice-card:hover,
.choice-card.selected {
  border-color: var(--aqua);
  box-shadow: 0 14px 32px rgba(24, 199, 189, 0.18);
  transform: translateY(-1px);
}

.choice-card.selected {
  background: linear-gradient(145deg, #f0fffd, #fff8ff);
}

.choice-card > span:first-child {
  color: var(--aqua-dark);
  font-size: 1.6rem;
  font-weight: 900;
}

.choice-card strong {
  font-size: 1.25rem;
}

.choice-card small {
  color: var(--muted);
}

.subject-dot {
  align-items: center;
  border-radius: 12px;
  color: #14123d;
  display: inline-flex;
  font-weight: 900;
  height: 44px;
  justify-content: center;
  width: 44px;
}

.subject-dot.purple { background: #ead7ff; color: #7835c9; }
.subject-dot.yellow { background: #fff1b9; color: #9a6b00; }
.subject-dot.green { background: #dff9e7; color: #0c8740; }
.subject-dot.aqua { background: #d9fffb; color: #078f92; }
.subject-dot.blue { background: #ddecff; color: #1e6dc1; }
.subject-dot.pink { background: #ffe0ef; color: #c23678; }
.subject-dot.orange { background: #ffe7c2; color: #a65c00; }

.board-list {
  display: grid;
  gap: 14px;
}

.board-row {
  align-items: center;
  background: rgba(255, 255, 255, 0.86);
  border: 1px solid #e6e2f2;
  border-radius: 8px;
  box-shadow: 0 8px 18px rgba(27, 22, 68, 0.06);
  display: grid;
  gap: 16px;
  grid-template-columns: minmax(180px, 1fr) minmax(220px, 360px);
  padding: 16px;
}

.board-row div {
  align-items: center;
  display: flex;
  gap: 12px;
}

.setup-complete,
.placeholder-screen {
  place-items: center;
}

.complete-card {
  max-width: 680px;
  padding: 38px;
  text-align: center;
}

.personal-shell {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  min-height: 100vh;
}

.personal-rail {
  background: linear-gradient(180deg, #15123f 0%, #0c1031 100%);
  color: #f7f4ff;
  display: flex;
  flex-direction: column;
  gap: 24px;
  padding: 30px 24px;
}

.personal-nav {
  display: grid;
  gap: 10px;
}

.personal-nav button,
.bottom-nav button {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(98, 67, 177, 0.74);
  color: #ffffff;
  text-align: left;
}

.personal-nav button.active,
.bottom-nav button.active {
  background: linear-gradient(135deg, #16c9bd, #178f99);
  border-color: rgba(55, 238, 226, 0.74);
}

.personal-main {
  padding: 26px 32px;
}

.personal-header {
  align-items: center;
  display: flex;
  justify-content: space-between;
  margin-bottom: 24px;
}

.dashboard-actions button,
.dashboard-strip button,
.card-actions button {
  background: #ffffff;
  border: 1px solid #d7d3eb;
  color: #6550c8;
}

.subject-dashboard-grid {
  display: grid;
  gap: 18px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.dashboard-card {
  background: rgba(255, 255, 255, 0.88);
  border: 1px solid #e6e2f2;
  border-radius: 8px;
  box-shadow: var(--shadow);
  display: grid;
  gap: 13px;
  min-height: 252px;
  padding: 20px;
}

.dashboard-card.aqua { border-top: 5px solid var(--aqua); }
.dashboard-card.purple { border-top: 5px solid var(--purple); }
.dashboard-card.yellow { border-top: 5px solid var(--yellow); }
.dashboard-card.green { border-top: 5px solid var(--green); }
.dashboard-card.blue { border-top: 5px solid var(--blue); }
.dashboard-card.pink { border-top: 5px solid var(--pink); }
.dashboard-card.orange { border-top: 5px solid var(--orange); }

.dashboard-card-top {
  align-items: center;
  display: flex;
  justify-content: space-between;
}

.board-pill {
  background: #f7fbff;
  border: 1px solid #d7e5f5;
  border-radius: 999px;
  color: #48546f;
  font-size: 0.85rem;
  font-weight: 800;
  padding: 5px 10px;
}

.dashboard-card h2 {
  font-size: 1.65rem;
  margin: 0;
}

.dashboard-card p {
  color: var(--muted);
  margin: 0;
}

.subject-page {
  display: grid;
  gap: 22px;
}

.subject-page-header {
  background: rgba(255,255,255,0.72);
  border: 1px solid #e3def4;
  border-radius: 8px;
  padding: 20px;
}

.subject-search-panel {
  align-items: end;
  background: #ffffff;
  border: 1px solid #d9d4ef;
  border-radius: 8px;
  box-shadow: var(--shadow);
  display: grid;
  gap: 12px;
  grid-template-columns: minmax(0, 1fr) auto;
  padding: 18px;
}

.subject-search-panel label {
  color: #29234f;
  font-weight: 900;
  grid-column: 1 / -1;
}

.subject-search-panel input {
  border: 1px solid #d9d4ef;
  border-radius: 8px;
  font: inherit;
  min-height: 58px;
  padding: 0 18px;
}

.subject-topic-section {
  background: rgba(255,255,255,0.78);
  border: 1px solid #e8e3f4;
  border-radius: 8px;
  box-shadow: 0 12px 30px rgba(27, 22, 68, 0.06);
  padding: 18px;
}

.subject-area-grid,
.popular-searches {
  display: grid;
  gap: 12px;
}

.subject-area-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.subject-area-grid button,
.popular-searches button {
  background: #ffffff;
  border: 1px solid #d8d2ef;
  border-radius: 8px;
  color: #2b2456;
  min-height: 72px;
  padding: 14px;
  text-align: left;
}

.subject-area-grid button strong {
  display: block;
}

.subject-area-grid button span {
  color: var(--muted);
  display: block;
  font-size: 0.9rem;
  margin-top: 5px;
}

.popular-searches {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.progress-track {
  background: #eceaf2;
  border-radius: 999px;
  height: 12px;
  overflow: hidden;
}

.progress-track span {
  background: linear-gradient(90deg, var(--aqua), var(--purple));
  display: block;
  height: 100%;
}

.dashboard-strip {
  background: rgba(255, 255, 255, 0.74);
  border: 1px solid #d8f0ef;
  border-radius: 8px;
  box-shadow: var(--shadow);
  margin-top: 22px;
  padding: 16px;
}

.bottom-nav {
  display: none;
}

/* TutAIR approved onboarding/dashboard visual alignment */
.profile-app {
  background:
    radial-gradient(circle at 5% 5%, rgba(170, 120, 255, 0.24), transparent 28%),
    radial-gradient(circle at 95% 8%, rgba(74, 137, 255, 0.14), transparent 30%),
    linear-gradient(135deg, #f5edff 0%, #f7fbff 46%, #fbf7ff 100%);
  color: #11142f;
  font-family: "Inter", "Trebuchet MS", Arial, Helvetica, sans-serif;
}

.auth-logo-word {
  color: #11142f;
  font-size: clamp(2.8rem, 6vw, 4.9rem);
  font-weight: 1000;
  letter-spacing: -0.02em;
  line-height: 0.95;
  text-align: center;
}

.auth-logo-word span {
  background: linear-gradient(135deg, #7344f2, #4b4ff0);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

.auth-subtitle {
  color: #1f2544;
  font-size: 1.25rem;
  text-align: center;
}

.auth-screen {
  background: #ffffff;
  border-radius: 0;
  gap: 0;
  grid-template-columns: minmax(360px, 0.95fr) minmax(440px, 1.05fr);
  min-height: 100vh;
  padding: 0;
}

.auth-card {
  align-content: center;
  border: 0;
  border-radius: 0 34px 34px 0;
  box-shadow: 20px 0 48px rgba(79, 68, 158, 0.12);
  gap: 18px;
  min-height: 100vh;
  padding: clamp(32px, 6vw, 82px);
  position: relative;
  z-index: 2;
}

.auth-card h1 {
  color: #11142f;
  font-size: clamp(2rem, 4vw, 2.8rem);
  line-height: 1.05;
  margin: 20px 0 0;
  text-align: center;
}

.auth-card > p {
  color: #59607a;
  font-size: 1.08rem;
  text-align: center;
}

.auth-card label {
  color: #11142f;
  font-weight: 900;
}

.auth-card .optional-field {
  display: none;
}

.auth-card input {
  border: 1.5px solid #d6d9e8;
  border-radius: 13px;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.7);
  font-size: 1rem;
  min-height: 64px;
  padding: 0 20px;
}

.auth-card input:focus {
  border-color: #7048ed;
  box-shadow: 0 0 0 4px rgba(112, 72, 237, 0.12);
  outline: 0;
}

.auth-card .inline-choice {
  color: #11142f;
  font-weight: 700;
  justify-content: space-between;
}

.inline-choice input {
  border-radius: 6px;
  height: 24px;
  width: 24px;
}

.auth-card .primary-action,
.onboarding-screen .primary-action,
.mission-panel .primary-action {
  background: linear-gradient(135deg, #a448ea, #4d41e9);
  border: 0;
  border-radius: 14px;
  box-shadow: 0 18px 32px rgba(93, 65, 232, 0.28);
  font-size: 1.15rem;
  min-height: 66px;
}

.auth-links {
  display: grid;
  grid-template-columns: 1fr;
}

.auth-links button {
  background: #ffffff;
  border: 1.5px solid #7449ef;
  border-radius: 13px;
  color: #5c35e7;
  font-size: 1rem;
  min-height: 58px;
}

.auth-links button + button {
  border: 0;
  color: #5c35e7;
  min-height: 32px;
}

.auth-divider {
  align-items: center;
  color: #11142f;
  display: grid;
  font-weight: 900;
  gap: 14px;
  grid-template-columns: 1fr auto 1fr;
  margin: 8px 0;
}

.auth-divider::before,
.auth-divider::after {
  background: #d8dbe8;
  content: "";
  height: 1px;
}

.auth-card small {
  color: #68708b;
  text-align: center;
}

.auth-card a {
  color: #5c35e7;
  font-weight: 800;
}

.auth-hero {
  align-content: center;
  background:
    radial-gradient(circle at 45% 64%, rgba(57, 190, 255, 0.28), transparent 24%),
    radial-gradient(circle at 65% 20%, rgba(178, 76, 255, 0.22), transparent 28%),
    linear-gradient(145deg, #26116c 0%, #5b35db 48%, #3677f4 100%);
  color: #ffffff;
  display: grid;
  gap: 30px;
  justify-items: center;
  min-height: 100vh;
  overflow: hidden;
  padding: clamp(36px, 6vw, 92px);
  position: relative;
  text-align: center;
}

.auth-hero::before {
  background-image:
    radial-gradient(circle, rgba(255,255,255,0.85) 0 2px, transparent 2px),
    radial-gradient(circle, rgba(255,255,255,0.55) 0 1px, transparent 1px);
  background-position: 25px 22px, 82px 71px;
  background-size: 160px 150px, 190px 170px;
  content: "";
  inset: 0;
  opacity: 0.55;
  position: absolute;
}

.auth-hero h2 {
  font-size: clamp(2.5rem, 5vw, 4rem);
  line-height: 1.18;
  margin: 0;
  position: relative;
}

.auth-hero h2::after {
  background: #a65bff;
  border-radius: 999px;
  content: "";
  display: block;
  height: 7px;
  margin: 24px auto 0;
  width: 240px;
}

.auth-hero p {
  font-size: clamp(1.1rem, 2vw, 1.55rem);
  margin: 0;
  position: relative;
}

.float-token {
  align-items: center;
  backdrop-filter: blur(10px);
  background: rgba(255,255,255,0.17);
  border: 1px solid rgba(255,255,255,0.2);
  border-radius: 18px;
  box-shadow: 0 16px 34px rgba(11, 14, 54, 0.18);
  display: flex;
  font-size: 1.8rem;
  font-weight: 900;
  height: 72px;
  justify-content: center;
  position: absolute;
  transform: rotate(12deg);
  width: 72px;
}

.token-a { right: 10%; top: 12%; }
.token-b { bottom: 32%; right: 9%; }
.token-c { left: 11%; top: 48%; }

.auth-benefits {
  backdrop-filter: blur(16px);
  background: rgba(255,255,255,0.15);
  border: 1px solid rgba(255,255,255,0.2);
  border-radius: 18px;
  display: grid;
  gap: 18px;
  grid-template-columns: repeat(3, 1fr);
  max-width: 760px;
  padding: 24px;
  position: relative;
  text-align: left;
  width: 100%;
}

.auth-benefits span {
  border-right: 1px solid rgba(255,255,255,0.2);
  display: grid;
  gap: 8px;
  padding-right: 16px;
}

.auth-benefits span:last-child {
  border-right: 0;
}

.auth-benefits small {
  color: rgba(255,255,255,0.82);
}

.mascot {
  display: grid;
  justify-items: center;
  position: relative;
}

.mascot-face {
  background: radial-gradient(circle at 50% 35%, #12365c 0%, #081436 64%);
  border: 10px solid #ffffff;
  border-radius: 45% 45% 40% 40%;
  box-shadow: inset 0 -8px 18px rgba(0,0,0,0.28), 0 18px 40px rgba(25, 22, 86, 0.25);
  display: block;
  height: 112px;
  position: relative;
  width: 148px;
}

.mascot-face::before {
  color: #36e8ff;
  content: "⌒  ⌒";
  font-size: 34px;
  font-weight: 900;
  left: 28px;
  letter-spacing: 14px;
  position: absolute;
  top: 26px;
}

.mascot-face::after {
  background: #36e8ff;
  border-radius: 0 0 28px 28px;
  content: "";
  height: 10px;
  left: 61px;
  position: absolute;
  top: 70px;
  width: 30px;
}

.mascot-body {
  background: linear-gradient(180deg, #ffffff, #eee9ff);
  border-radius: 42% 42% 48% 48%;
  box-shadow: 0 18px 30px rgba(26, 19, 74, 0.18);
  display: block;
  height: 118px;
  margin-top: -8px;
  position: relative;
  width: 106px;
}

.mascot-body::after {
  align-items: center;
  background: linear-gradient(135deg, #8f55ff, #533eea);
  border-radius: 50%;
  color: #ffffff;
  content: "▣";
  display: flex;
  font-size: 22px;
  height: 48px;
  justify-content: center;
  left: 29px;
  position: absolute;
  top: 20px;
  width: 48px;
}

.mascot-cap {
  background: linear-gradient(135deg, #28106b, #5f35e9);
  clip-path: polygon(50% 0, 100% 28%, 50% 56%, 0 28%);
  display: block;
  height: 60px;
  margin-bottom: -28px;
  position: relative;
  width: 170px;
  z-index: 2;
}

.mascot.large { transform: scale(1.05); }
.mascot.giant { transform: scale(1.45); transform-origin: center; }
.mascot.medium { transform: scale(0.72); }
.mascot.small { transform: scale(0.52); margin: -40px 0; }
.mascot.avatar { transform: scale(0.55); margin: -28px auto -22px; }

.onboarding-screen {
  background: rgba(255,255,255,0.94);
  border: 1px solid rgba(126, 90, 240, 0.14);
  border-radius: 34px;
  box-shadow: 0 30px 80px rgba(80, 52, 176, 0.16);
  gap: 24px;
  margin: 22px auto;
  max-width: 1240px;
  min-height: calc(100vh - 44px);
  padding: clamp(28px, 5vw, 56px);
}

.step-header {
  display: grid;
  gap: 18px;
  grid-template-columns: 68px 1fr 150px;
  text-align: center;
}

.step-header > div:last-child {
  grid-column: 1 / -1;
}

.step-header h1 {
  font-size: clamp(2.4rem, 5vw, 4.3rem);
  letter-spacing: -0.03em;
  margin-top: 28px;
}

.step-header p {
  color: #68708b;
  font-size: clamp(1.1rem, 2vw, 1.55rem);
  margin-inline: auto;
  max-width: 720px;
}

.back-orb,
.step-pill {
  align-items: center;
  background: #efe7ff;
  border: 0;
  border-radius: 18px;
  color: #5d38df;
  display: flex;
  font-size: 1.35rem;
  font-weight: 1000;
  justify-content: center;
  min-height: 62px;
}

.back-orb {
  border-radius: 50%;
  width: 62px;
}

.setup-progress {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(3, 1fr);
  margin: 0 auto 18px;
  max-width: 1040px;
  position: relative;
  width: 100%;
}

.setup-progress-bar {
  background: #ebe9f5;
  border-radius: 999px;
  grid-column: 1 / -1;
  height: 14px;
  overflow: hidden;
}

.setup-progress-bar span {
  background: linear-gradient(90deg, #6c41e7, #934ff0);
  display: block;
  height: 100%;
}

.setup-step {
  color: #68708b;
  display: grid;
  gap: 8px;
  justify-items: center;
  text-align: center;
}

.setup-step span {
  align-items: center;
  background: #cfd1df;
  border-radius: 50%;
  color: #ffffff;
  display: flex;
  font-weight: 1000;
  height: 28px;
  justify-content: center;
  width: 28px;
}

.setup-step.active,
.setup-step.done {
  color: #5c35e7;
}

.setup-step.active span,
.setup-step.done span {
  background: linear-gradient(135deg, #7c43ec, #5b39e4);
}

.year-grid {
  gap: 40px;
  margin: 20px auto;
  max-width: 1060px;
  width: 100%;
}

.choice-card {
  border: 1.5px solid #dfe2ee;
  border-radius: 20px;
  box-shadow: 0 20px 34px rgba(26, 25, 66, 0.08);
  justify-items: center;
  min-height: 200px;
  padding: 28px;
  text-align: center;
  transition: transform 160ms ease, box-shadow 160ms ease, border-color 160ms ease;
}

.choice-card:hover {
  transform: translateY(-4px);
}

.choice-card.selected {
  background: linear-gradient(180deg, #ffffff, #fbf8ff);
  border-color: #7146eb;
  box-shadow: 0 22px 48px rgba(111, 70, 235, 0.20);
}

.year-choice {
  min-height: 450px;
  overflow: hidden;
  position: relative;
}

.year-choice em {
  align-self: end;
  background:
    radial-gradient(circle at 30% 80%, rgba(255,255,255,0.9), transparent 18%),
    linear-gradient(140deg, rgba(107, 67, 232, 0.45), rgba(255,255,255,0.4));
  border-radius: 80% 80% 0 0;
  display: block;
  height: 118px;
  margin: 6px -28px -28px;
  width: calc(100% + 56px);
}

.year-choice.green em { background: linear-gradient(145deg, #dff7e7, #6ac79d); }
.year-choice.purple em { background: linear-gradient(145deg, #ece5ff, #7961ee); }
.year-choice.red em { background: linear-gradient(145deg, #ffe9ef, #ed6570); }

.choice-orb {
  align-items: center;
  border-radius: 50%;
  box-shadow: 0 14px 24px rgba(42, 31, 105, 0.18);
  color: #ffffff;
  display: inline-flex;
  font-size: 0.9rem;
  font-weight: 1000;
  height: 94px;
  justify-content: center;
  width: 94px;
}

.choice-orb.green { background: linear-gradient(135deg, #64d08d, #209e66); }
.choice-orb.purple { background: linear-gradient(135deg, #8d67ff, #5138df); }
.choice-orb.red { background: linear-gradient(135deg, #ff6d75, #df2e43); }

.year-choice strong {
  font-size: clamp(2rem, 4vw, 3.4rem);
}

.subject-grid {
  gap: 20px;
  grid-template-columns: repeat(5, minmax(0, 1fr));
}

.subject-choice {
  min-height: 160px;
}

.subject-choice .subject-dot {
  border-radius: 50%;
  box-shadow: 0 14px 25px rgba(35, 28, 88, 0.15);
  color: #ffffff;
  font-size: 0.72rem;
  height: 70px;
  width: 70px;
}

.subject-choice.selected {
  border-color: #7146eb;
  box-shadow: 0 18px 42px rgba(111, 70, 235, 0.18);
}

.subject-choice small {
  color: #6f738a;
  font-weight: 800;
}

.select-note {
  color: #5c35e7;
  font-size: 1.1rem;
  font-weight: 900;
}

.helper-strip {
  align-items: center;
  background: #fbf8ff;
  border: 1px solid #d8ccff;
  border-radius: 20px;
  display: grid;
  gap: 20px;
  grid-template-columns: auto 1fr auto;
  margin-top: 8px;
  min-height: 118px;
  overflow: hidden;
  padding: 20px 34px;
}

.helper-strip strong {
  color: #5c35e7;
  font-size: 1.35rem;
}

.helper-strip p {
  color: #48506c;
  margin: 4px 0 0;
}

.helper-star {
  align-items: center;
  background: linear-gradient(135deg, #a448ea, #5a3ee8);
  border-radius: 50%;
  color: #ffffff;
  display: flex;
  font-size: 1.5rem;
  height: 72px;
  justify-content: center;
  width: 72px;
}

.step-actions {
  display: grid;
  grid-template-columns: 150px 1fr;
  margin-top: 6px;
}

.step-actions .primary-action {
  grid-column: 2;
}

.step-actions .quiet-action {
  background: #ffffff;
  border: 1px solid #d7cdf7;
  border-radius: 14px;
  color: #5c35e7;
}

.board-mode {
  display: grid;
  gap: 28px;
  grid-template-columns: repeat(2, 1fr);
}

.board-mode button,
.board-options button {
  background: #ffffff;
  border: 1.5px solid #dfe2ee;
  border-radius: 14px;
  color: #1d2443;
  font-weight: 900;
  min-height: 58px;
}

.board-mode button.selected,
.board-options button.selected {
  border-color: #7048ed;
  box-shadow: 0 0 0 4px rgba(112, 72, 237, 0.08);
  color: #5c35e7;
}

.section-intro {
  display: grid;
  gap: 5px;
}

.section-intro strong {
  font-size: 1.3rem;
}

.section-intro span {
  color: #58617f;
}

.board-list {
  gap: 8px;
}

.board-row {
  border-color: #ded7f5;
  border-radius: 12px;
  grid-template-columns: minmax(210px, 0.65fr) 1fr;
  padding: 14px 20px;
}

.board-row div:first-child span:last-child {
  display: grid;
}

.board-row small {
  color: #59607a;
  font-weight: 700;
}

.board-options {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  justify-content: flex-end;
}

.board-options button {
  min-height: 44px;
  min-width: 106px;
}

.setup-complete {
  background:
    radial-gradient(circle at 80% 22%, rgba(120, 75, 238, 0.16), transparent 28%),
    linear-gradient(180deg, #ffffff 0%, #faf8ff 100%);
  border: 14px solid #6442e8;
  border-radius: 0;
  gap: 22px;
  padding: clamp(30px, 5vw, 64px);
}

.complete-hero {
  align-items: center;
  display: grid;
  grid-template-columns: 1fr 420px;
  min-height: 360px;
  width: min(1120px, 100%);
}

.complete-hero h1 {
  color: #11142f;
  font-size: clamp(3rem, 7vw, 5.3rem);
  letter-spacing: -0.04em;
  line-height: 1.05;
  margin: 40px 0 20px;
}

.complete-hero h1 span {
  color: #6c41e7;
}

.complete-hero p {
  color: #59607a;
  font-size: 1.45rem;
}

.complete-card {
  max-width: 1120px;
  padding: 28px 42px;
  width: 100%;
}

.complete-card h2,
.mission-panel h2 {
  color: #11142f;
  margin: 0 0 22px;
  text-align: center;
}

.profile-summary {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
}

.profile-summary span {
  border-right: 1px solid #dcd8ec;
  display: grid;
  gap: 8px;
  justify-items: center;
  padding: 22px;
}

.profile-summary span:last-child {
  border-right: 0;
}

.profile-summary em {
  color: #5c35e7;
  font-style: normal;
  font-weight: 1000;
}

.mission-panel {
  background:
    radial-gradient(circle at 10% 60%, rgba(255,255,255,0.18), transparent 24%),
    linear-gradient(135deg, #6a36df, #4e3de8 55%, #8e57f2);
  border-radius: 18px;
  box-shadow: 0 22px 44px rgba(88, 58, 223, 0.24);
  color: #ffffff;
  max-width: 1120px;
  padding: 34px;
  text-align: center;
  width: 100%;
}

.mission-panel h2,
.mission-panel p {
  color: #ffffff;
}

.mission-panel .primary-action {
  background: #ffffff;
  color: #633deb;
  margin-top: 12px;
  min-width: 420px;
}

.capability-row {
  background: #ffffff;
  border: 1px solid #ded7f5;
  border-radius: 18px;
  display: grid;
  gap: 16px;
  grid-template-columns: repeat(5, 1fr);
  max-width: 1120px;
  padding: 22px;
  text-align: center;
  width: 100%;
}

.capability-row span {
  display: grid;
  gap: 7px;
}

.capability-row strong {
  color: #5c35e7;
}

.capability-row small {
  color: #59607a;
}

.personal-shell {
  background:
    radial-gradient(circle at 78% 9%, rgba(118, 77, 239, 0.18), transparent 20%),
    linear-gradient(180deg, #f7f2ff 0%, #ffffff 100%);
  grid-template-columns: 240px minmax(0, 1fr);
}

.personal-rail {
  background: rgba(255,255,255,0.76);
  border-right: 1px solid #e3dcf8;
  color: #11142f;
  gap: 22px;
}

.personal-rail .brand {
  color: #11142f;
}

.personal-rail .brand-mark {
  display: none;
}

.personal-rail .brand strong {
  font-size: 2.65rem;
}

.level-card,
.streak-card {
  background: #f4efff;
  border: 1px solid #dfd4ff;
  border-radius: 14px;
  color: #11142f;
  display: grid;
  gap: 8px;
  padding: 16px;
}

.level-card strong,
.streak-card strong {
  color: #5c35e7;
}

.personal-nav button {
  align-items: center;
  background: transparent;
  border: 0;
  border-radius: 12px;
  color: #11142f;
  display: flex;
  gap: 12px;
  min-height: 56px;
  padding: 0 14px;
  text-align: left;
}

.personal-nav button span {
  background: #e9e4ff;
  border-radius: 8px;
  height: 24px;
  width: 24px;
}

.personal-nav button.active {
  background: linear-gradient(135deg, #7b4cf0, #a447ea);
  border: 0;
  color: #ffffff;
  box-shadow: 0 16px 30px rgba(108, 65, 231, 0.23);
}

.personal-main {
  padding: 42px 48px 104px;
}

.personal-header h1 {
  font-size: clamp(2rem, 4vw, 3rem);
  letter-spacing: -0.03em;
}

.personal-header p {
  color: #59607a;
  font-size: 1.15rem;
}

.dashboard-actions button {
  background: #ffffff;
  border: 0;
  border-radius: 50%;
  box-shadow: 0 12px 28px rgba(58, 46, 130, 0.12);
  color: #5c35e7;
  height: 52px;
  overflow: hidden;
  padding: 0;
  text-indent: -999px;
  width: 52px;
}

.dashboard-actions button::before {
  content: "!";
  display: block;
  font-size: 1.4rem;
  line-height: 52px;
  text-indent: 0;
}

.dashboard-actions button:last-child::before {
  content: "◎";
}

.continue-panel {
  align-items: center;
  background: #ffffff;
  border: 1px solid #e2dcf6;
  border-radius: 22px;
  box-shadow: 0 18px 38px rgba(51, 41, 122, 0.10);
  display: grid;
  gap: 20px;
  grid-template-columns: 1fr 150px 160px;
  margin-bottom: 20px;
  max-width: 620px;
  min-height: 180px;
  padding: 26px;
}

.continue-panel strong {
  color: #5c35e7;
  font-size: 1.15rem;
}

.continue-panel h2 {
  margin: 20px 0 6px;
}

.continue-panel button {
  background: linear-gradient(135deg, #7b4cf0, #523be4);
  border: 0;
  border-radius: 12px;
  color: #ffffff;
  font-weight: 900;
  min-height: 58px;
}

.subject-section-header {
  align-items: center;
  background: rgba(255,255,255,0.72);
  border-radius: 26px 26px 0 0;
  display: flex;
  justify-content: space-between;
  margin-top: 16px;
  padding: 34px 34px 8px;
}

.subject-section-header h2 {
  color: #11142f;
  font-size: 2rem;
  margin: 0 0 5px;
}

.subject-section-header p {
  color: #59607a;
  margin: 0;
}

.subject-section-header button {
  background: #f6f1ff;
  border: 1px solid #e0d6ff;
  border-radius: 13px;
  color: #5c35e7;
  font-weight: 900;
  min-height: 48px;
  padding: 0 20px;
}

.subject-dashboard-grid {
  background: rgba(255,255,255,0.72);
  border-radius: 0 0 26px 26px;
  gap: 20px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  padding: 20px 34px 26px;
}

.dashboard-card {
  background: #ffffff;
  border: 1.5px dashed #b99cff;
  border-radius: 18px;
  box-shadow: 0 18px 34px rgba(54, 43, 123, 0.08);
  gap: 10px;
  justify-items: center;
  min-height: 292px;
  padding: 28px 24px;
  text-align: center;
}

.dashboard-card h2 {
  color: #11142f;
  font-size: 1.45rem;
}

.dashboard-card .subject-dot {
  border-radius: 50%;
  box-shadow: 0 18px 34px rgba(87, 55, 214, 0.18);
  color: #ffffff;
  height: 86px;
  width: 86px;
}

.dashboard-card-top {
  justify-content: center;
  position: relative;
  width: 100%;
}

.dashboard-card-top button {
  background: transparent;
  border: 0;
  color: #11142f;
  font-size: 1.5rem;
  position: absolute;
  right: 0;
  top: 0;
}

.dashboard-card .progress-track {
  width: 100%;
}

.dashboard-card small {
  color: #59607a;
  font-weight: 900;
}

.dashboard-card .board-pill {
  background: #f8f7ff;
  border: 0;
  color: #68708b;
}

.card-actions {
  display: grid;
  grid-template-columns: 1fr;
  width: 100%;
}

.card-actions button {
  background: linear-gradient(135deg, #63d28a, #36bf80);
  border: 0;
  border-radius: 12px;
  color: #ffffff;
  min-height: 52px;
}

.card-actions button + button {
  background: #f7f4ff;
  color: #5c35e7;
}

.dashboard-card.purple .card-actions button:first-child { background: linear-gradient(135deg, #9c6bf0, #6b45e9); }
.dashboard-card.blue .card-actions button:first-child { background: linear-gradient(135deg, #5f99ff, #3d79f0); }
.dashboard-card.orange .card-actions button:first-child { background: linear-gradient(135deg, #ff9f42, #fb7b2a); }
.dashboard-card.pink .card-actions button:first-child { background: linear-gradient(135deg, #f065a8, #e94b94); }
.dashboard-card.aqua .card-actions button:first-child { background: linear-gradient(135deg, #4ed5c0, #26bfa7); }
.dashboard-card.red .card-actions button:first-child { background: linear-gradient(135deg, #ff6d75, #df2e43); }

.dynamic-note {
  color: #737895;
  font-weight: 800;
  text-align: center;
}

.dashboard-strip {
  background: #f3edff;
  border: 1px solid #dfd4ff;
  border-radius: 18px;
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  padding: 22px;
}

.dashboard-strip button {
  background: #ffffff;
  border: 0;
  border-radius: 14px;
  display: grid;
  gap: 6px;
  min-height: 106px;
  text-align: left;
}

.dashboard-strip strong {
  color: #11142f;
}

.dashboard-strip span {
  color: #59607a;
  font-size: 0.9rem;
}

.dashboard-stats {
  display: grid;
  gap: 0;
  grid-template-columns: repeat(4, 1fr);
  margin-top: 20px;
}

.dashboard-stats button {
  background: #ffffff;
  border: 0;
  border-right: 1px solid #e4def6;
  display: grid;
  gap: 6px;
  min-height: 116px;
  padding: 22px;
  text-align: left;
}

.dashboard-stats button:first-child {
  border-radius: 18px 0 0 18px;
}

.dashboard-stats button:last-child {
  border-radius: 0 18px 18px 0;
  border-right: 0;
}

.dashboard-stats strong {
  color: #5c35e7;
  font-size: 1.5rem;
}

.dashboard-stats span {
  color: #59607a;
}

.subject-dot.green { background: linear-gradient(135deg, #65d68b, #2aa565); }
.subject-dot.purple { background: linear-gradient(135deg, #a879ff, #5b39e4); }
.subject-dot.blue { background: linear-gradient(135deg, #65a3ff, #3d6fed); }
.subject-dot.aqua { background: linear-gradient(135deg, #65d1e2, #25aabd); }
.subject-dot.yellow { background: linear-gradient(135deg, #f7c950, #e6a92f); }
.subject-dot.orange { background: linear-gradient(135deg, #ff9f42, #f07821); }
.subject-dot.pink { background: linear-gradient(135deg, #f36aad, #de438f); }
.subject-dot.red { background: linear-gradient(135deg, #ff6d75, #df2e43); }
.subject-dot.slate { background: linear-gradient(135deg, #b6bdce, #7f879c); }

.settings-screen {
  align-items: center;
  display: grid;
  min-height: 100vh;
  padding: clamp(22px, 5vw, 64px);
  place-items: center;
}

.settings-card {
  background: rgba(255,255,255,0.92);
  border: 1px solid #ded7f5;
  border-radius: 24px;
  box-shadow: 0 24px 60px rgba(68, 50, 156, 0.16);
  display: grid;
  gap: 18px;
  max-width: 560px;
  padding: clamp(26px, 5vw, 42px);
  width: min(100%, 560px);
}

.settings-card h1 {
  color: #11142f;
  font-size: clamp(2rem, 5vw, 3.2rem);
  letter-spacing: -0.03em;
  line-height: 1;
  margin: 0;
}

.settings-card p {
  color: #59607a;
  margin: 0;
}

.settings-list,
.settings-actions {
  display: grid;
  gap: 12px;
}

.settings-list button,
.settings-actions button,
.danger-action {
  border-radius: 14px;
  font-weight: 900;
  min-height: 56px;
  padding: 0 18px;
}

.settings-list button {
  background: #f8f5ff;
  border: 1px solid #ddd4fb;
  color: #5c35e7;
  text-align: left;
}

.danger-action {
  background: linear-gradient(135deg, #ff6d75, #df2e43) !important;
  border: 0 !important;
  color: #ffffff !important;
  box-shadow: 0 16px 28px rgba(223, 46, 67, 0.22);
}

.logout-card {
  text-align: center;
}

.logout-card .settings-actions {
  grid-template-columns: 1fr 1fr;
}

.tutor-shell {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  min-height: 100vh;
}

.tutor-rail {
  background: linear-gradient(180deg, #15123f 0%, #0c1031 100%);
  color: #ffffff;
  display: flex;
  flex-direction: column;
  gap: 22px;
  padding: 28px 22px;
}

.tutor-context-card,
.tutor-topic-picker,
.chat-window,
.chat-composer,
.suggested-prompts button,
.tutor-save-panel,
.tutor-error {
  border-radius: 8px;
}

.tutor-context-card,
.tutor-topic-picker {
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(98, 67, 177, 0.74);
  padding: 18px;
}

.tutor-context-card dl {
  display: grid;
  gap: 12px;
  margin: 0;
}

.tutor-context-card div {
  display: grid;
  gap: 2px;
}

.tutor-context-card dt {
  color: #9df4ec;
  font-size: 0.8rem;
  font-weight: 800;
  text-transform: uppercase;
}

.tutor-context-card dd {
  margin: 0;
}

.tutor-topic-picker {
  display: grid;
  gap: 10px;
}

.quiet-link {
  color: #9df4ec;
  font-weight: 800;
  margin-top: auto;
}

.tutor-main {
  display: grid;
  grid-template-rows: auto auto minmax(280px, 1fr) auto auto;
  gap: 16px;
  min-width: 0;
  padding: 28px;
}

.tutor-header {
  align-items: start;
  display: flex;
  gap: 18px;
  justify-content: space-between;
}

.tutor-header h1 {
  font-size: clamp(2rem, 4vw, 3.4rem);
  line-height: 1;
  margin: 0 0 8px;
}

.tutor-header p {
  color: var(--muted);
  margin: 0;
}

.tutor-header-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: flex-end;
}

.suggested-prompts {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.suggested-prompts button,
.secondary-action {
  background: #ffffff;
  border: 1px solid var(--line);
  color: var(--ink);
  font-weight: 800;
  min-height: 42px;
  padding: 0 14px;
}

.suggested-prompts button {
  background: linear-gradient(180deg, #ffffff, #f8f4ff);
  box-shadow: 0 8px 18px rgba(68, 50, 156, 0.08);
  min-height: 58px;
  text-align: left;
}

.chat-window {
  background: #ffffff;
  border: 1px solid var(--line);
  box-shadow: var(--shadow);
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 360px;
  overflow-y: auto;
  padding: 18px;
}

.chat-empty {
  align-self: center;
  color: var(--muted);
  margin: auto;
  max-width: 360px;
  text-align: center;
}

.chat-message {
  max-width: min(760px, 88%);
}

.chat-message span {
  color: var(--muted);
  display: block;
  font-size: 0.85rem;
  font-weight: 900;
  margin-bottom: 5px;
  text-transform: uppercase;
}

.chat-message p {
  background: #f5f8ff;
  border: 1px solid #dce9ff;
  border-radius: 8px 8px 8px 2px;
  box-shadow: 0 10px 24px rgba(39, 34, 79, 0.08);
  margin: 0;
  padding: 12px 14px;
  white-space: pre-wrap;
}

.chat-message.from-student {
  align-self: flex-end;
  text-align: right;
}

.chat-message.from-student p {
  background: linear-gradient(135deg, #19c7bd, #108f99);
  border-color: #108f99;
  border-radius: 8px 8px 2px 8px;
  color: #ffffff;
  text-align: left;
}

.chat-message.loading i {
  animation: tutorPulse 1s infinite ease-in-out;
  background: var(--aqua);
  border-radius: 999px;
  display: inline-block;
  height: 8px;
  margin-right: 4px;
  width: 8px;
}

.chat-message.loading i:nth-child(2) { animation-delay: 0.12s; }
.chat-message.loading i:nth-child(3) { animation-delay: 0.24s; }

.tutor-save-panel {
  align-items: center;
  background: #f4fff8;
  border: 1px solid #bde8c7;
  color: #176a36;
  display: flex;
  gap: 12px;
  justify-content: space-between;
  padding: 12px 14px;
}

.tutor-save-panel span {
  font-weight: 800;
}

.lesson-status {
  align-items: center;
  background: rgba(255, 255, 255, 0.86);
  border: 1px solid var(--line);
  border-radius: 8px;
  box-shadow: 0 10px 24px rgba(68, 50, 156, 0.08);
  display: grid;
  gap: 16px;
  grid-template-columns: 86px minmax(0, 1fr) auto;
  padding: 14px;
}

.xp-orb {
  --lesson-progress: 0%;
  align-items: center;
  background:
    radial-gradient(circle at center, #ffffff 58%, transparent 59%),
    conic-gradient(var(--aqua) var(--lesson-progress), #ece7fb 0);
  border-radius: 50%;
  display: grid;
  height: 72px;
  justify-items: center;
  line-height: 1;
  place-content: center;
  width: 72px;
}

.xp-orb strong {
  color: #5c35e7;
  font-size: 1.3rem;
}

.xp-orb span,
.lesson-progress-copy span,
.streak-chip {
  color: var(--muted);
  font-size: 0.86rem;
  font-weight: 900;
}

.lesson-progress-copy {
  display: grid;
  gap: 7px;
}

.lesson-progress-copy strong {
  color: var(--ink);
  font-size: 1.1rem;
}

.lesson-progress-bar {
  background: #ece7fb;
  border-radius: 999px;
  height: 10px;
  overflow: hidden;
}

.lesson-progress-bar span {
  background: linear-gradient(90deg, var(--aqua), #8e57f2);
  display: block;
  height: 100%;
  transition: width 0.45s ease;
}

.streak-chip {
  background: #fff7d7;
  border: 1px solid #f3d56c;
  border-radius: 999px;
  color: #8d6700;
  padding: 10px 12px;
}

.learning-stage {
  min-height: 360px;
}

.lesson-card {
  background: rgba(255,255,255,0.92);
  border: 1px solid #ded7f5;
  border-radius: 8px;
  box-shadow: 0 18px 42px rgba(68, 50, 156, 0.14);
  display: grid;
  gap: 14px;
  overflow: hidden;
  padding: clamp(18px, 3vw, 28px);
  position: relative;
}

.lesson-card h2 {
  color: #11142f;
  font-size: clamp(1.8rem, 4vw, 3rem);
  line-height: 1;
  margin: 0;
}

.lesson-card h3 {
  margin: 0 0 7px;
}

.lesson-card p {
  margin: 0;
}

.lesson-card-top {
  align-items: center;
  display: grid;
  gap: 16px;
  grid-template-columns: 74px minmax(0, 1fr);
}

.robot-face {
  align-items: center;
  background: linear-gradient(135deg, #d9a6ff, #55efe6);
  border: 4px solid #ffffff;
  border-radius: 22px;
  box-shadow: 0 14px 30px rgba(85, 58, 159, 0.22);
  color: #14123d;
  display: flex;
  font-weight: 1000;
  height: 68px;
  justify-content: center;
  width: 68px;
}

.robot-face.level-up {
  animation: levelPop 0.8s ease both;
  margin: 0 auto;
}

.robot-reaction {
  background: #f3ffff;
  border-left: 5px solid var(--aqua);
  border-radius: 8px;
  color: #21465c;
  font-weight: 900;
  padding: 12px 14px;
}

.lesson-meta,
.lesson-actions,
.badge-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.lesson-meta span,
.badge-row span {
  background: #f8f5ff;
  border: 1px solid #ddd4fb;
  border-radius: 999px;
  color: #5c35e7;
  font-weight: 900;
  padding: 7px 10px;
}

.tiny-card,
.picture-card,
.mini-quiz,
.gcse-card,
.lesson-flashcards {
  border-radius: 8px;
  padding: 14px;
}

.tiny-card {
  background: #f8fbff;
  border: 1px solid #dce9ff;
}

.tiny-card.analogy { background: #fffbeb; border-color: #f3d56c; }
.tiny-card.fact { background: #f4fff8; border-color: #bde8c7; }
.tiny-card.example { background: #fff5fb; border-color: #efb9d4; }

.picture-card {
  align-items: center;
  background: linear-gradient(135deg, #f8f4ff, #efffff);
  border: 1px dashed #a78bed;
  color: #66539c;
  display: grid;
  gap: 10px;
  grid-template-columns: 54px minmax(0, 1fr);
  min-height: 96px;
}

.picture-card span {
  align-items: center;
  background: #ffffff;
  border-radius: 8px;
  display: flex;
  font-size: 2rem;
  height: 54px;
  justify-content: center;
}

.mini-quiz {
  background: #f7ffff;
  border: 1px solid #bdeee8;
}

.quiz-choice-grid {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-top: 10px;
}

.quiz-choice-grid button,
.lesson-actions button {
  background: #ffffff;
  border: 1px solid var(--line);
  border-radius: 8px;
  color: var(--ink);
  font-weight: 900;
  min-height: 44px;
  padding: 0 12px;
}

.quiz-choice-grid button.correct {
  background: #e8fff0;
  border-color: #5bc986;
}

.quiz-choice-grid button.incorrect {
  background: #fff1f4;
  border-color: #ff9aae;
}

.quiz-feedback {
  background: #ffffff;
  border-radius: 8px;
  color: #176a36;
  font-weight: 900;
  margin-top: 10px !important;
  padding: 10px;
}

.gcse-card {
  background: #fbf5ff;
  border: 1px solid #bc78ec;
}

.lesson-flashcards {
  background: #fffdf2;
  border: 1px solid #f1d878;
}

.lesson-flashcard-grid {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.lesson-flashcard-grid article {
  background: #ffffff;
  border: 1px solid #eadfa8;
  border-radius: 8px;
  padding: 12px;
}

.lesson-flashcard-grid span {
  color: var(--orange);
  font-weight: 900;
}

.mission-complete {
  text-align: center;
}

.confetti span {
  animation: confettiDrop 1.1s ease-in-out infinite;
  background: var(--pink);
  border-radius: 2px;
  height: 12px;
  position: absolute;
  top: 12px;
  width: 8px;
}

.confetti span:nth-child(1) { left: 12%; }
.confetti span:nth-child(2) { animation-delay: 0.12s; background: var(--yellow); left: 36%; }
.confetti span:nth-child(3) { animation-delay: 0.24s; background: var(--aqua); left: 64%; }
.confetti span:nth-child(4) { animation-delay: 0.36s; background: var(--purple); left: 86%; }

@keyframes levelPop {
  0% { transform: scale(0.8); }
  55% { transform: scale(1.12); }
  100% { transform: scale(1); }
}

@keyframes confettiDrop {
  0% { opacity: 0; transform: translateY(-12px) rotate(0deg); }
  50% { opacity: 1; }
  100% { opacity: 0; transform: translateY(42px) rotate(120deg); }
}

.chat-composer {
  align-items: end;
  background: #ffffff;
  border: 1px solid var(--line);
  box-shadow: 0 8px 22px rgba(28, 24, 72, 0.08);
  display: grid;
  gap: 10px;
  grid-template-columns: minmax(0, 1fr) auto;
  padding: 12px;
}

.chat-composer label {
  clip: rect(0 0 0 0);
  clip-path: inset(50%);
  height: 1px;
  overflow: hidden;
  position: absolute;
  white-space: nowrap;
  width: 1px;
}

.chat-composer textarea {
  border: 0;
  font: inherit;
  min-height: 66px;
  outline: 0;
  resize: vertical;
}

.primary-action:disabled {
  opacity: 0.65;
}

.tutor-error {
  background: #fff1f4;
  border: 1px solid #ffc2cf;
  color: #8d1830;
  font-weight: 800;
  margin: 0;
  padding: 12px 14px;
}

@keyframes tutorPulse {
  0%, 100% { opacity: 0.35; transform: translateY(0); }
  50% { opacity: 1; transform: translateY(-2px); }
}

@media (max-width: 1180px) {
  .app-shell {
    grid-template-columns: 230px minmax(0, 1fr);
  }

  .study-grid {
    grid-template-columns: 260px minmax(0, 1fr);
  }

  .action-panel {
    display: grid;
    gap: 18px;
    grid-column: 1 / -1;
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .subject-grid,
  .subject-dashboard-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .auth-screen {
    grid-template-columns: 1fr;
  }

  .auth-card {
    border-radius: 0;
    min-height: auto;
  }

  .auth-hero {
    min-height: 720px;
  }

  .subject-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .personal-shell {
    grid-template-columns: 210px minmax(0, 1fr);
  }

  .personal-main {
    padding: 32px 28px 100px;
  }

  .dashboard-strip,
  .dashboard-stats {
    grid-template-columns: repeat(2, 1fr);
  }

  .suggested-prompts {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .side-card {
    margin-bottom: 0;
  }
}

@media (max-width: 900px) {
  .app-shell {
    display: block;
  }

  .tutor-shell {
    grid-template-columns: 1fr;
  }

  .tutor-rail {
    min-height: auto;
  }

  .side-rail {
    height: auto;
    position: static;
  }

  .workspace {
    padding: 18px;
  }

  .hero,
  .crumb-bar,
  .note-heading,
  .encouragement {
    align-items: stretch;
    display: grid;
  }

  .hero-actions,
  .toolbar {
    justify-content: flex-start;
  }

  .study-grid,
  .action-panel {
    display: grid;
    grid-template-columns: 1fr;
  }

  .topic-panel {
    order: 1;
  }

  .content {
    order: 2;
  }

  .action-panel {
    order: 3;
  }

  .status {
    text-align: left;
  }

  .auth-screen,
  .personal-shell,
  .step-header,
  .personal-header,
  .board-row {
    display: grid;
    grid-template-columns: 1fr;
  }

  .personal-rail {
    min-height: auto;
  }

  .auth-hero {
    display: none;
  }

  .auth-card {
    min-height: 100vh;
  }

  .onboarding-screen {
    border-radius: 0;
    margin: 0;
    min-height: 100vh;
  }

  .step-header {
    grid-template-columns: 58px 1fr 120px;
  }

  .step-header > div:last-child {
    grid-column: 1 / -1;
  }

  .setup-progress {
    font-size: 0.85rem;
  }

  .year-grid,
  .board-mode,
  .complete-hero,
  .profile-summary,
  .capability-row,
  .continue-panel {
    grid-template-columns: 1fr;
  }

  .year-choice {
    min-height: 260px;
  }

  .subject-grid,
  .subject-dashboard-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .helper-strip {
    grid-template-columns: 1fr;
    text-align: center;
  }

  .board-options {
    justify-content: flex-start;
  }

  .setup-complete {
    border-width: 8px;
  }

  .complete-hero {
    min-height: auto;
    text-align: center;
  }

  .mascot.giant {
    transform: scale(0.82);
  }

  .personal-rail {
    border-right: 0;
    display: grid;
    grid-template-columns: 1fr;
  }

  .personal-rail .brand,
  .level-card,
  .streak-card {
    max-width: none;
  }

  .subject-section-header {
    align-items: flex-start;
    display: grid;
    gap: 14px;
  }

  .personal-nav {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .bottom-nav {
    background: #121239;
    border-radius: 8px;
    bottom: 12px;
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    left: 12px;
    padding: 8px;
    position: sticky;
    right: 12px;
  }
}

@media (max-width: 560px) {
  .workspace,
  .side-rail {
    padding: 16px;
  }

  .hero h1 {
    font-size: 2rem;
  }

  .hero-actions,
  .toolbar {
    display: grid;
  }

  .hero-actions button,
  .toolbar button,
  .streak {
    width: 100%;
  }

  .crumbs {
    align-items: flex-start;
    display: grid;
  }

  .revision-section {
    padding-right: 42px;
  }

  .auth-screen,
  .onboarding-screen,
  .setup-complete,
  .placeholder-screen,
  .personal-main,
  .personal-rail {
    padding: 16px;
  }

  .year-grid,
  .subject-grid,
  .subject-dashboard-grid,
  .personal-nav {
    grid-template-columns: 1fr;
  }

  .auth-card {
    padding: 24px;
  }

  .auth-logo-word {
    font-size: 3rem;
  }

  .step-header {
    grid-template-columns: 48px 1fr;
  }

  .step-pill {
    grid-column: 1 / -1;
    min-height: 44px;
  }

  .back-orb {
    min-height: 48px;
    width: 48px;
  }

  .setup-progress {
    grid-template-columns: 1fr;
  }

  .setup-step {
    align-items: center;
    display: flex;
    justify-content: center;
  }

  .choice-card {
    min-height: 150px;
  }

  .year-choice {
    min-height: 230px;
  }

  .board-row {
    padding: 14px;
  }

  .board-options button {
    flex: 1 1 120px;
  }

  .mission-panel .primary-action {
    min-width: 0;
    width: 100%;
  }

  .dashboard-strip,
  .dashboard-stats {
    grid-template-columns: 1fr;
  }

  .dashboard-stats button,
  .dashboard-stats button:first-child,
  .dashboard-stats button:last-child {
    border-radius: 12px;
    border-right: 0;
  }

  .tutor-main,
  .tutor-rail {
    padding: 16px;
  }

  .tutor-header,
  .chat-composer {
    display: grid;
    grid-template-columns: 1fr;
  }

  .suggested-prompts {
    grid-template-columns: 1fr;
  }

  .lesson-status,
  .lesson-card-top,
  .picture-card,
  .quiz-choice-grid,
  .lesson-flashcard-grid {
    grid-template-columns: 1fr;
  }

  .xp-orb,
  .robot-face {
    justify-self: center;
  }

  .chat-message {
    max-width: 100%;
  }

  .auth-card,
  .complete-card {
    padding: 20px;
  }
}
"""


if __name__ == "__main__":
    raise SystemExit(main())
