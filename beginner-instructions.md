# TutAIR Beginner Instructions

TutAIR helps turn learning content into GCSE revision notes.

Use it when you find a useful educational YouTube video, copied transcript, textbook extract, lesson note, or pasted explanation.

## Step 1 - Save The Source

Create a new note under:

```text
Team Inbox/TutAIR/YYYY/MM/
```

Use `capture-note-template.md` as the shape.

You can also use the V1 command:

```powershell
python .\tutair_intake.py --text-file ".\my-learning-text.txt" --subject "Science" --topic "Cell division"
```

For YouTube, the current command records the URL and marks the capture as waiting for source content:

```powershell
python .\tutair_intake.py --url "https://www.youtube.com/watch?v=abcdefghijk" --subject "Science" --topic "Cell division"
```

Name it with the date and a short topic slug, for example:

```text
2026-07-09-gcse-biology-cell-division.md
```

When you use a text file, TutAIR also saves the raw source text under:

```text
Team Inbox/TutAIR/YYYY/MM/source-content/
```

## Step 2 - Fill In The Basics

Add what you know:

- subject
- topic
- source URL, if there is one
- date captured
- confidence level
- source-content status
- path to the raw source text when available
- pasted source text or transcript preview

If you are not sure about the exam board, write:

```yaml
possible_exam_board: unknown
exam_board_status: unconfirmed
exam_board_evidence: none
```

Do not process a YouTube URL-only capture yet. It needs transcript text first, either pasted manually or captured through TubeAIR.

## Step 3 - Make A Learning Note

Use `processed-learning-note-template.md`, or run the V2 processor on one capture:

```powershell
python .\tutair_process.py "C:\Users\Buggly\OneDrive\Desktop\MyPKA\Team Inbox\TutAIR\2026\07\your-capture.md"
```

The processed note is saved in:

```text
Team Inbox/TutAIR/YYYY/MM/processed/
```

Keep it small:

- tiny summary
- key facts
- what this means
- exam-style questions
- flashcards
- next revision task

## Step 4 - Be Careful With Exam Boards

Do not guess.

It is fine to write:

```text
This might be AQA, but it is not confirmed yet.
```

It is not fine to write:

```text
This is definitely AQA.
```

unless there is evidence from a teacher, official specification, school document, exam timetable, or confirmed course source.

## Step 5 - Pick The Next Tiny Task

End every learning note with one small task, such as:

- answer 3 flashcards
- explain the topic in 3 sentences
- do 5 practice questions
- watch the next 5 minutes of the video
- check the exam-board specification

The goal is to make revision easier to start.

## Step 6 - Open The Local Viewer

Run this from the TutAIR MVP folder:

```powershell
python .\tutair_viewer.py
```

Then open this address in your browser:

```text
http://127.0.0.1:8765
```

The viewer is read-only. It shows processed notes from:

```text
Team Inbox/TutAIR/YYYY/MM/processed/
```

The dashboard buttons are local browser tools:

- `Flashcards` lets you practise the note's flashcards one card at a time.
- `Quiz Me` lets you type an answer before revealing a simple answer prompt.
- `Notes` brings you back to the full note.
- `Read Aloud` uses your browser to read the note out loud.
- `Focus Mode` hides extra panels so the note is easier to read.
- `Mark as Reviewed` saves a reviewed marker in this browser.
- `Save Topic` saves the topic as a favourite in this browser.

These saved markers use browser storage on this computer. They do not edit the Markdown note.

The viewer also has a local setup flow before the revision note:

- Log in or create a local prototype account.
- Choose Year 9, Year 10, or Year 11.
- Select GCSE subjects by tapping the subject cards.
- Choose exam boards for the selected subjects, or skip and store `Unknown`.
- Start Today's Mission to open the personalised `My Subjects` dashboard.

This is still local-only. It remembers setup choices in this browser, but it is not real online login.

## Current Limits

- TutAIR is Markdown-first.
- TutAIR V3 has a local viewer and local onboarding prototype, not a public web dashboard.
- TutAIR does not change TubeAIR.
- TutAIR does not fetch YouTube transcripts itself yet. It can reuse TubeAIR transcript captures by linking or importing the transcript text as source content.
- TutAIR does not confirm exam boards without evidence.
- TutAIR button state is local browser state for now, not a shared account system.
