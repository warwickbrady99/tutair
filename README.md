# TutAIR MVP

TutAIR is a small GCSE revision helper for myPKA.

It starts simple:

```text
YouTube link or pasted learning text -> raw source content -> TutAIR capture -> ADHD-friendly revision note
```

This MVP keeps TutAIR local and Markdown-first. It gives TutAIR a safe intake and processing path, plus a local browser viewer for the approved revision dashboard and onboarding prototype.

Milestone 2 adds the source-content foundation: raw source text is stored separately, capture Markdown records metadata and readiness, and processed resources are generated only when source content is ready.

## Files In This Folder

- `capture-note-template.md` - use this when saving a new learning source.
- `processed-learning-note-template.md` - use this when turning a source into a revision resource.
- `beginner-instructions.md` - plain-English steps for using TutAIR.
- `tutair_intake.py` - small V1 command that creates a TutAIR capture note.
- `test_tutair_intake.py` - checks for the V1 intake command.
- `tutair_process.py` - small V2 command that creates an ADHD-friendly processed learning note from one capture.
- `test_tutair_process.py` - checks for the V2 processor.
- `tutair_viewer.py` - small V3 local web viewer for processed TutAIR notes.
- `tutair_transcript.py` - verifies a YouTube video and rips its captions into a ready capture.
- `test_tutair_transcript.py` - checks verification, timestamps and the capture handoff.
- `tutair_questions.py` - writes multiple-choice questions and has them independently reviewed.
- `test_tutair_questions.py` - checks parsing, structural rules and the review gate.
- `tutair_spec.py` - supplies course-map objectives and specification wording for minting.
- `test_tutair_spec.py` - checks objective lookup, excerpting and spec-PDF selection.
- `tutair_pipeline.py` - runs the whole chain from a YouTube URL to reviewed questions.
- `test_tutair_viewer.py` - checks for the V3 viewer.
- `course-map/` - Milestone 1 GCSE course-map MVP, kept separate from learning resources.

## Whole Pipeline (YouTube URL to MCQs)

One command that runs the whole chain:

```powershell
python .\tutair_pipeline.py --url "https://www.youtube.com/watch?v=abcdefghijk" --subject "Science" --topic "Cell structure" --board AQA
```

It verifies the video, rips the transcript, builds the revision note, then writes and reviews
the questions. It stops at the first honest failure: an unverifiable URL or a video with no
captions ends the run before anything is written.

Add `--spec-dir` to point at your folder of official specification PDFs, and `--no-spec` to
mint from the transcript alone.

## Where Notes Live

Captures and notes default to `MyPKA/Team Inbox/TutAIR` under the **current user's home
folder**, so the same checkout works on a second machine with a different Windows login.

Override it for a different location by setting `TUTAIR_INBOX_ROOT`, or per command with
`--inbox-root` (intake, transcript, pipeline) and `--root` (viewer). Pass the same folder to
both, or the viewer will show nothing.

## Specification Grounding

Questions written from a video alone test whatever the video happened to say. Questions written
against the specification test what the exam board will actually ask. TutAIR uses both.

Two sources, in order of authority:

1. The **course map** (`course-map/data/course-map-mvp.json`) - the curriculum spine, where every
   learning objective already has a stable ID and a spec reference. Matching objectives are given
   to the writer, and an approved question records the `objective_id` it targets.
2. The **official specification PDF**, searched for the topic and used as authority on scope.
   Point `--spec-dir` at the folder holding them, or set `TUTAIR_SPEC_DIR`.

The transcript decides what is answerable. The specification decides what is worth asking. The
reviewer additionally rejects a question that goes beyond the specification, or that claims an
objective it does not test.

Where a topic is not in the course map and no specification is readable, TutAIR says so
(`Specification grounding: none`) and mints from the transcript alone rather than pretending to
exam-board coverage. Extracted specification text is cached in `.spec-cache/`.

## Transcript Command (YouTube)

Verify a YouTube video and rip its captions into a capture that is ready to process:

```powershell
python .\tutair_transcript.py --url "https://www.youtube.com/watch?v=abcdefghijk" --subject "Science" --topic "Ecology"
```

Nothing is ingested until the video has been fetched and confirmed to exist. The real title
and channel are read from YouTube, not taken from whoever supplied the link. A video with no
usable captions is reported and nothing is written.

It saves three things: the plain transcript as source content, a timestamped transcript
(`...-timestamped.md`), and a capture marked `ready_for_processing`.

## Questions Command (multiple choice)

Write multiple-choice questions from a processed note, then have them independently reviewed:

```powershell
python .\tutair_questions.py ".\path\to\processed-note.md" --count 8
```

Two model calls with different instructions. A **writer** produces candidates grounded in the
transcript, each citing the timestamp that taught it. A **reviewer** then tries to prove each
one unfair - more than one defensible answer, a key you can spot from the wording, a claim the
transcript does not support. Only approved questions are shown for revision; rejected drafts
are kept with the reviewer's objection in `<note>-questions.json`.

Set the provider in `.env`. `TUTAIR_AI_PROVIDER=claude` runs on the Claude Code CLI;
`openai` uses `OPENAI_API_KEY` and `TUTAIR_AI_MODEL`.

The approved questions appear in the note under `Multiple Choice Questions`, and the viewer's
**Quiz Me** button turns them into a real multiple-choice quiz with reveal-answer.

## V1 Intake Command

From this folder, capture a YouTube educational URL:

```powershell
python .\tutair_intake.py --url "https://www.youtube.com/watch?v=abcdefghijk" --subject "Science" --topic "Cell division"
```

Or capture pasted learning text from a UTF-8 `.txt` file:

```powershell
python .\tutair_intake.py --text-file ".\my-learning-text.txt" --subject "History" --topic "Cold War"
```

The command saves Markdown under:

```text
Team Inbox/TutAIR/YYYY/MM/
```

For YouTube URLs, TutAIR records the URL and video ID, then marks the capture as `needs_source_content`. For useful processed notes today, paste transcript or lesson text through `--text-file`.

When you use `--text-file`, TutAIR also saves the raw source text under:

```text
Team Inbox/TutAIR/YYYY/MM/source-content/
```

## V2 Processor Command

Turn one TutAIR capture into an ADHD-friendly learning note:

```powershell
python .\tutair_process.py "C:\Users\Buggly\OneDrive\Desktop\MyPKA\Team Inbox\TutAIR\2026\07\2026-07-09-gcse-science-cell-division.md"
```

By default, the processed note is saved beside the capture in:

```text
Team Inbox/TutAIR/YYYY/MM/processed/
```

The processor fills:

- Tiny Summary
- Key Facts
- What This Means
- Exam-Style Questions
- Flashcards
- Next Revision Task
- Exam Board Mapping

It keeps exam-board mapping unconfirmed unless the capture has both `exam_board_status: confirmed` and real evidence in `exam_board_evidence`.

URL-only captures are blocked from processing until transcript, lesson text, or another raw source-content file is attached. This prevents TutAIR from turning a bare URL into a weak learning resource.

Exam-board mapping is unconfirmed by default. You can record a possible board, but that still stays unconfirmed:

```powershell
python .\tutair_intake.py --url "https://www.youtube.com/watch?v=abcdefghijk" --subject "Science" --topic "Cell division" --possible-exam-board "AQA"
```

## V3 Local Web Viewer

Run the read-only revision viewer from this folder:

```powershell
python .\tutair_viewer.py
```

Then open:

```text
http://127.0.0.1:8765
```

The first AI Tutor page is available at:

```text
http://127.0.0.1:8765/tutor
```

The viewer reads processed notes from:

```text
Team Inbox/TutAIR/YYYY/MM/processed/
```

It shows the processed TutAIR sections in a revision-friendly page:

- Tiny Summary
- Key Facts
- What This Means
- Exam-Style Questions
- Flashcards
- Next Revision Task
- Exam Board Mapping

The viewer is local and read-only. It does not edit notes, publish anything online, or change TubeAIR.

The viewer UI follows the approved TutAIR revision dashboard mockup: dark subject navigation, topic cards, colourful revision sections, study controls, and responsive panels. The backend and Markdown reading path are unchanged.

The viewer now also includes a local onboarding and personalised `My Subjects` dashboard prototype:

- Login, Create Account, Forgot Password, and Remember Me controls are interactive in the browser.
- Year Group selection supports Year 9, Year 10, and Year 11.
- GCSE Subject selection stores selected cards locally and highlights the cards without floating tick icons.
- Exam Board selection shows only the subjects selected by the student and can store `Unknown` when skipped.
- Setup Complete routes into the personalised dashboard.
- The `My Subjects` dashboard is generated from the student's selected subjects rather than hardcoded example cards.
- Clicking a subject card opens that subject context first. If no topic has been chosen, TutAIR shows a subject page and records the topic as `Topic not selected yet` instead of guessing.
- The Maths subject page includes search, main areas, popular searches, recently studied, and continue panels.
- Dashboard controls that are not fully built yet route to local `Coming Soon` placeholder pages instead of doing nothing.

This onboarding state is local browser `localStorage`. It is not real authentication and does not create a database or publish anything online.

Interactive controls now work locally in the browser:

- `Flashcards` opens a practice view using the current note's flashcards, with Previous, Next, and Flip Card controls.
- `Quiz Me` turns the current note's exam-style questions into a simple answer-and-reveal quiz.
- `Notes` returns to the full revision note.
- `Read Aloud` uses the browser's built-in SpeechSynthesis API and includes Play, Pause, and Stop controls.
- `Focus Mode` hides side panels and distractions until you switch back.
- `Mark as Reviewed` stores reviewed status in browser `localStorage`.
- `Save Topic` stores favourites in browser `localStorage` and shows a Favourites section in the sidebar.
- Controls that are not ready yet show `Coming Soon`.

All viewer controls stay local to the browser. They do not publish anything online or change the Markdown files.

## V4 AI Tutor Page

The AI Tutor page adds a chat-based tutoring surface while keeping the local viewer architecture intact.

It includes:

- A dedicated `/tutor` page.
- New Chat and Clear Chat controls.
- Conversation history for the current browser session and topic.
- Suggested one-click study actions.
- Send button, typing/thinking loading state, and visible error messages.
- Auto-scroll, Enter to send, and Shift + Enter for a new line.
- Automatic context from the current processed note: subject, topic, note summary, key facts, flashcards, questions, and exam-board status.
- Automatic student context from the local profile where available: name, year group, selected subjects, and selected exam board.
- Automatic current subject context from the clicked subject card. If the student has not selected a topic yet, the tutor receives `Topic not selected yet`.

The one-click study actions are:

- Explain this topic.
- Test Me.
- GCSE Exam Question.
- Generate Flashcards.
- Give me Revision Notes.
- Give me an Example.
- Quiz Me.
- Explain my YouTube Summary.

Tutor modes are prompt-driven in this local milestone:

- `GCSE Exam Question` asks the AI to generate one realistic GCSE question and wait for the student's answer.
- The next student reply is treated as an exam answer; TutAIR is prompted to mark it, score it, explain strengths, explain improvements, and show a model answer.
- `Generate Flashcards` asks for cards with Front, Back, and Difficulty. The latest generated flashcard response can be saved locally in browser `localStorage` for later revision.
- `Give me Revision Notes` asks for concise GCSE-friendly notes with headings, bullets, examples, and memory tips.
- `Quiz Me` asks the AI to run a one-question-at-a-time quiz, keep score in conversation, and finish with score, strengths, weak areas, and suggested next topic.
- `Explain my YouTube Summary` uses the current processed note as the available summary context.

The tutor endpoint is:

```text
POST /api/tutor/chat
```

It uses the configured provider adapter. For this first version, set:

```powershell
$env:OPENAI_API_KEY="your-api-key"
$env:TUTAIR_AI_PROVIDER="openai"
$env:TUTAIR_AI_MODEL="gpt-4o-mini"
```

`TUTAIR_AI_PROVIDER` defaults to `openai`, and `TUTAIR_AI_MODEL` defaults to `gpt-4o-mini`.

You can also store these values in a `.env` file in the TutAIR MVP root folder:

```text
Deliverables/2026-07-09-tutair-mvp/.env
```

Example `.env` file:

```text
OPENAI_API_KEY=your-api-key
TUTAIR_AI_PROVIDER=openai
TUTAIR_AI_MODEL=gpt-4o-mini
```

Install the optional environment-file dependency from this folder if your Python environment does not already have it:

```powershell
python -m pip install -r requirements.txt
```

TutAIR logs whether `python-dotenv` is installed, which `.env` path was checked, and whether `OPENAI_API_KEY` was found. It never prints the API key itself.

If OpenAI returns `HTTP 401 Unauthorized`, TutAIR now logs the sanitized OpenAI response body and shows a clearer authentication error. The request uses:

```text
https://api.openai.com/v1/chat/completions
Authorization: Bearer <your API key>
```

The `.env` path should normally be a file, not a folder. TutAIR includes a compatibility fallback for an accidental `.env/` folder, but a real `.env` file at the path above is the intended setup.

Voice, image upload, camera homework help, PDF analysis, whiteboard drawing, and maths equation solving are intentionally not implemented yet. The tutor has a separate message-building, mode, and provider layer so future interfaces can reuse the same context and conversation path.

## V5 Learning Engine v1

The AI Tutor now renders responses as interactive learning missions instead of a plain chatbot transcript.

The learning engine keeps the same backend, OpenAI provider, onboarding prototype, data model, course map, and Markdown pipeline. It changes the learning experience only.

Learning Engine v1 includes:

- A mission status bar with XP, progress, and streak.
- A dedicated lesson stage above the compact chat history.
- AI responses requested as strict JSON, not HTML or long prose.
- Tiny explanation cards with short text, picture placeholder, analogy, key fact, and example.
- Mini multiple-choice questions with immediate feedback and XP.
- GCSE question cards with marks and model-answer reveal.
- Flashcard cards rendered from structured AI output.
- Mission Complete screen with XP, progress, badges, suggested next topic, and confetti animation.
- Local browser state for current lesson, current step, XP, completed questions, progress, badges, and return-to-lesson.

The JSON shape requested from the AI includes:

```text
title, step_label, difficulty, estimated_time, robot_reaction,
explanation, analogy, important_fact, example, picture_placeholder,
quiz, gcse_question, flashcards, xp, progress_delta, badge,
next_step, mission_complete, suggested_next_topic
```

The frontend renders the JSON. The AI should not generate HTML.

If lesson JSON cannot be parsed, the student sees a friendly fallback card:

```text
TutAIR had trouble formatting this lesson. Try again.
```

Raw JSON is never shown directly in the student-facing lesson or compact chat history.

## Checks

Run the focused tests from this folder:

```powershell
python -m unittest test_tutair_intake.py test_tutair_process.py test_tutair_viewer.py
```

Run the course-map MVP checks from `course-map/`:

```powershell
python -m unittest test_course_map.py
```

## Important Rule

TutAIR can write a possible exam board, but it must not treat that as fact unless there is evidence.

Good:

```yaml
possible_exam_board: AQA
exam_board_status: unconfirmed
exam_board_evidence: none
```

Only mark something as confirmed when it comes from a reliable source such as a teacher, official specification, school document, exam timetable, or confirmed course source.

## Milestone 1 Course Map

The course map is TutAIR's curriculum spine. It lives separately from captures and learning resources in:

```text
Deliverables/2026-07-09-tutair-mvp/course-map/
```

The first MVP slice maps a small official-specification-backed AQA GCSE Combined Science: Trilogy Biology Paper 1 / Cell biology branch. Future captures should link to one or more stable learning objective IDs instead of copying the course-map hierarchy.

## Source Content Pipeline

TutAIR now uses three distinct layers:

```text
Raw source content -> TutAIR capture metadata -> Processed learning resource
```

### Raw source

Raw source is the actual transcript, lesson text, textbook extract, or copied note. It is evidence. For pasted text intake, it is stored as a `.txt` file in `Team Inbox/TutAIR/YYYY/MM/source-content/`.

TubeAIR already captures YouTube transcripts into `Team Inbox/TubeAIR/YYYY/MM/`. TutAIR should reuse that capability by linking or importing the resulting transcript text into the TutAIR source-content layer, rather than rebuilding the TubeAIR Telegram/transcript listener.

### Extracted content

The TutAIR capture Markdown is the extracted/handoff record. It stores subject, topic, source URL, source-content status, processing readiness, and future course-map links. It should stay light and point back to the raw source.

### Processed learning resources

Processed resources live under `Team Inbox/TutAIR/YYYY/MM/processed/` for the MVP. They are student-facing revision notes generated from ready source content. They should later link to stable course-map learning objective IDs.
