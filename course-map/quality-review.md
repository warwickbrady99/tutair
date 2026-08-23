# Course Map Quality Review - AQA Combined Science Biology Paper 1 MVP

## Scope

This review covers only the existing TutAIR course-map MVP slice:

```text
Science -> GCSE Combined Science: Trilogy -> AQA 8464 -> Biology Paper 1 -> Cell biology
```

It does not add new subjects, exam boards, papers, dashboards, AI tutoring, or revision features.

## Official Source Checked

- AQA GCSE Combined Science: Trilogy 8464 specification, version 1.1, 04 October 2019.
- Department for Education GCSE subject-content collection for wider GCSE context.

## Verification Summary

The six existing learning objectives were kept as the MVP slice, but their statements and traceability were improved.

| Objective ID | Review result | Official specification trace |
|---|---|---|
| `LO-AQA-8464-BIO-B1-CELL-BIOLOGY-CELL-STRUCTURE-001` | Improved to cover animal, plant, and bacterial cell structures/functions more accurately. | AQA 8464 section 4.1.1.2 |
| `LO-AQA-8464-BIO-B1-CELL-BIOLOGY-CELL-STRUCTURE-002` | Improved to explicitly cover eukaryotic and prokaryotic structural differences. | AQA 8464 section 4.1.1.1 |
| `LO-AQA-8464-BIO-B1-CELL-BIOLOGY-MICROSCOPY-001` | Kept; now traced to the magnification/image size/real size calculation requirement. | AQA 8464 section 4.1.1.5 |
| `LO-AQA-8464-BIO-B1-CELL-BIOLOGY-MICROSCOPY-002` | Improved to match the specification wording around microscopy development and electron microscopy. | AQA 8464 section 4.1.1.5 |
| `LO-AQA-8464-BIO-B1-CELL-BIOLOGY-CELL-DIVISION-001` | Improved from a narrow mitosis statement to the overall cell-cycle requirement. | AQA 8464 section 4.1.2.2 |
| `LO-AQA-8464-BIO-B1-CELL-BIOLOGY-CELL-DIVISION-002` | Improved to include embryos, adult animals, plant meristems, uses, and risks. | AQA 8464 section 4.1.2.3 |

## Schema Improvements

Backward-compatible fields were added:

- `coverage_status`
- `coverage_note`
- `known_gaps`
- sub-topic-level `spec_reference`
- learning-objective-level `source_trace`

These fields strengthen traceability without changing the existing hierarchy or learning objective ID format.

## Assumptions

- The MVP remains a partial Cell biology slice, not a full Biology Paper 1 map.
- The `shared` tier label remains appropriate for this MVP until a later tier-specific review is performed.
- The student's personal Science route and tier are still unconfirmed.

## Known Gaps

The current Cell biology MVP does not yet cover every part of AQA 8464 section 4.1. Known unmapped areas include:

- `4.1.1.3 Cell specialisation`
- `4.1.1.4 Cell differentiation`
- `4.1.3 Transport in cells`

This is acceptable for the MVP quality pass because the task was to strengthen the existing slice rather than expand its size.
