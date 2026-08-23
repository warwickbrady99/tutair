# TutAIR Course Map MVP

This folder is the canonical course-map layer for TutAIR Milestone 1.

It is separate from TutAIR learning resources. Learning resources, captures, notes, flashcards, questions, and future AI tutor context should link to course-map learning objective IDs. They should not copy the course-map hierarchy into their own files.

## What This MVP Contains

The first working slice is:

```text
Subject: Science
  -> Qualification: GCSE Combined Science: Trilogy
    -> Exam Board: AQA
      -> Tier: shared
        -> Paper: Biology Paper 1
          -> Topic: Cell biology
            -> Sub-topics
              -> Learning objectives
```

This is intentionally small. It proves the structure before TutAIR expands to more subjects, papers, tiers, and boards.

## Files

- `course-map-schema.md` - explains the hierarchy, fields, and ID rules.
- `beginner-instructions.md` - plain-English steps for editing and checking the course map.
- `quality-review.md` - source-check notes, assumptions, and gaps for the current MVP slice.
- `data/course-map-mvp.json` - the first structured course-map slice.
- `validate_course_map.py` - validates hierarchy, references, and stable learning-objective IDs.
- `test_course_map.py` - focused tests for the MVP data model.

## Source Rules

Official specifications are preferred as the source of truth. The MVP source is AQA GCSE Combined Science: Trilogy 8464, with the Department for Education GCSE subject-content collection as the wider GCSE context.

The course map can say what a specification contains. It must not say this is the student's confirmed personal course until school, teacher, timetable, or candidate-entry evidence confirms it.

## Stable Learning Objective IDs

Every learning objective has a stable ID:

```text
LO-<BOARD>-<QUALIFICATION>-<SUBJECT-AREA>-<PAPER>-<TOPIC>-<SUBTOPIC>-<NNN>
```

Example:

```text
LO-AQA-8464-BIO-B1-CELL-BIOLOGY-CELL-STRUCTURE-001
```

Future TutAIR captures should link to one or more of these IDs, for example:

```yaml
linked_learning_objectives:
  - LO-AQA-8464-BIO-B1-CELL-BIOLOGY-CELL-STRUCTURE-001
  - LO-AQA-8464-BIO-B1-CELL-BIOLOGY-MICROSCOPY-001
```

## Checks

From this folder:

```powershell
python -m unittest test_course_map.py
```

The checks confirm:

- required top-level fields exist
- learning objective IDs are unique
- learning objective IDs match the stable ID pattern
- learning objectives have traceable official-specification references
- capture-link examples only point to real objective IDs
- learning resources are not embedded inside the course map
