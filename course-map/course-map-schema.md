# TutAIR Course Map Schema

## Purpose

The course map is TutAIR's curriculum spine. It says what a course contains and gives each learning objective a stable identifier that future captures and resources can link to.

The course map is not a revision note, flashcard deck, question bank, lesson, or AI tutor prompt. Those are learning resources and must live separately.

## Hierarchy

TutAIR course maps use this hierarchy:

```text
Subject
  -> Qualification
    -> Exam Board
      -> Tier
        -> Paper
          -> Topic
            -> Sub-topic
              -> Learning Objective
```

## Core Fields

### Course Map

- `schema_version` - current schema version.
- `map_id` - stable ID for this course-map file.
- `status` - `draft`, `mvp`, `active`, or `retired`.
- `source_policy` - how sources are selected and trusted.
- `subjects` - list of subject objects.
- `capture_link_examples` - examples showing how future TutAIR captures can link to objectives.

### Subject

- `subject_id` - stable subject key, for example `SCI`.
- `name` - human-readable subject name.
- `qualifications` - list of qualifications under this subject.

### Qualification

- `qualification_id` - stable key for a qualification, preferably including the specification code where known.
- `name` - qualification name.
- `level` - for example `GCSE`.
- `exam_boards` - list of exam-board course variants.

### Exam Board

- `board_id` - short board key, for example `AQA`, `EDEXCEL`, `OCR`, or `EDUQAS`.
- `name` - exam board name.
- `specification_code` - official specification code where known.
- `source_status` - `official_specification`, `school_confirmed`, `draft_school_page`, or `needs_confirmation`.
- `sources` - source objects.
- `tiers` - list of tier objects.

### Tier

- `tier_id` - `foundation`, `higher`, `shared`, or another board-specific value.
- `name` - display name.
- `applies_to` - what the tier means in this course map.
- `papers` - list of papers.

### Paper

- `paper_id` - stable paper key.
- `name` - official or plain-English paper name.
- `assessment_type` - for example `written_exam`.
- `duration` - known duration or `needs_confirmation`.
- `topics` - list of topics.

### Topic

- `topic_id` - stable topic key.
- `name` - topic name.
- `spec_reference` - official topic reference where known.
- `coverage_status` - `complete`, `partial_mvp`, or `needs_review`.
- `coverage_note` - short explanation of the current coverage boundary.
- `known_gaps` - list of official specification sections deliberately not mapped yet.
- `subtopics` - list of sub-topics.

### Sub-topic

- `subtopic_id` - stable sub-topic key.
- `name` - sub-topic name.
- `spec_reference` - official sub-topic reference where known.
- `learning_objectives` - list of learning objectives.

### Learning Objective

- `objective_id` - globally unique stable ID.
- `statement` - what the student should know, understand, or be able to do.
- `source_ref` - official specification reference where known.
- `source_trace` - machine-readable source pointer with `source_id`, `section`, `page`, optional `pdf_lines`, and `trace_status`.
- `status` - `verified_official_specification`, `derived_from_specification`, `needs_review`, or `retired`.
- `tier_scope` - `foundation`, `higher`, `shared`, or `needs_confirmation`.

## Stable ID Rule

Learning objective IDs are immutable after release. If a statement is improved later, keep the ID when the intended objective is the same. If the meaning changes, retire the old objective and create a new ID.

Pattern:

```text
LO-<BOARD>-<QUALIFICATION>-<SUBJECT-AREA>-<PAPER>-<TOPIC>-<SUBTOPIC>-<NNN>
```

Example:

```text
LO-AQA-8464-BIO-B1-CELL-BIOLOGY-CELL-STRUCTURE-001
```

## Expansion Rules

- Add one paper or topic at a time.
- Prefer official specification references.
- Keep student-specific confirmation separate in `docs/exam-board-map.md`.
- Do not put revision notes, flashcards, question attempts, or generated explanations inside the course map.
- Link learning resources to objectives with `linked_learning_objectives`.
