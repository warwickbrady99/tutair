# Beginner Instructions - TutAIR Course Map

Use this when adding or checking GCSE course-map content.

## What The Course Map Is

The course map is the list of what a GCSE course contains.

It answers:

- Which subject is this?
- Which qualification is it?
- Which exam board is it?
- Which tier, if any?
- Which paper?
- Which topic?
- Which sub-topic?
- What exact learning objectives can a TutAIR note link to?

## What The Course Map Is Not

Do not put these in the course map:

- revision notes
- flashcards
- exam-style questions
- student answers
- AI explanations
- confidence scores
- study plans

Those will come later as learning resources.

## How To Add A New Objective

1. Find the right official specification.
2. Add the objective under the correct subject, qualification, board, tier, paper, topic, and sub-topic.
3. Give it a stable `objective_id`.
4. Add a short `statement`.
5. Add `source_ref` so someone can trace where it came from.
6. Run the tests.

## How To Check The MVP

From this folder:

```powershell
python -m unittest test_course_map.py
```

If the test passes, the course map is structurally valid.

## How Future Captures Will Link To It

A future TutAIR capture or processed note should link to objectives like this:

```yaml
linked_learning_objectives:
  - LO-AQA-8464-BIO-B1-CELL-BIOLOGY-CELL-STRUCTURE-001
```

That means the capture is about that exact objective. The capture should not copy the whole course-map branch into itself.
