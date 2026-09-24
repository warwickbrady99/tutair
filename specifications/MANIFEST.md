# GCSE Specifications — manifest

The specification PDFs are **not committed**. They are copyright AQA, OCR, Pearson and WJEC,
and together they are about 35MB. This file records what the set is and where each one came
from, so the folder can be rebuilt on any machine.

Downloaded 21 September 2026 from the awarding bodies' own sites. Student: Year 11, exams
summer 2027.

| Subject | Board | Code | Filename |
|---|---|---|---|
| English Language | AQA | 8700 | `AQA-GCSE-EnglishLanguage-8700.pdf` |
| English Literature | AQA | 8702 | `AQA-GCSE-EnglishLiterature-8702.pdf` |
| Mathematics | OCR | J560 | `OCR-GCSE-Mathematics-J560.pdf` |
| Combined Science (Trilogy) | AQA | 8464 | `AQA-GCSE-CombinedScience-Trilogy-8464.pdf` |
| History | Pearson Edexcel | 1HI0 | `Edexcel-GCSE-History-1HI0.pdf` |
| Computer Science | OCR | J277 | `OCR-GCSE-ComputerScience-J277.pdf` |
| Business — BTEC route | Pearson | Tech Award in Enterprise (2022) | `Pearson-BTEC-TechAward-Enterprise-2022.pdf` |
| Business — GCSE route | WJEC Eduqas | GCSE Business (from 2017) | `WJEC-Eduqas-GCSE-Business.pdf` |
| BTEC key dates 2026/27 | Pearson | — | `Pearson-BTEC-TechAward-KeyDates-2026-2027.pdf` |

## Filenames matter

`find_spec_pdf()` in `tutair_spec.py` matches the specification code inside the filename. The
AQA science one must contain `8464`, the OCR computing one `J277`, and so on. Keep these names.

## Rebuilding the folder

```bash
curl -L -o AQA-GCSE-CombinedScience-Trilogy-8464.pdf  "https://filestore.aqa.org.uk/resources/science/specifications/AQA-8464-SP-2016.PDF"
curl -L -o AQA-GCSE-EnglishLanguage-8700.pdf          "https://filestore.aqa.org.uk/resources/english/specifications/AQA-8700-SP-2015.PDF"
curl -L -o AQA-GCSE-EnglishLiterature-8702.pdf        "https://filestore.aqa.org.uk/resources/english/specifications/AQA-8702-SP-2015.PDF"
curl -L -o OCR-GCSE-ComputerScience-J277.pdf          "https://www.ocr.org.uk/Images/558027-specification-gcse-computer-science-j277.pdf"
curl -L -o OCR-GCSE-Mathematics-J560.pdf              "https://www.ocr.org.uk/Images/168982-specification-gcse-mathematics.pdf"
curl -L -o Edexcel-GCSE-History-1HI0.pdf              "https://qualifications.pearson.com/content/dam/pdf/GCSE/History/2016/specification-and-sample-assessments/gcse-9-1-history-specification.pdf"
curl -L -o WJEC-Eduqas-GCSE-Business.pdf              "https://www.eduqas.co.uk/media/qiobeu0d/eduqas-gcse-business-spec-from-2017.pdf"
curl -L -o Pearson-BTEC-TechAward-Enterprise-2022.pdf "https://qualifications.pearson.com/content/dam/pdf/btec-tec-awards/enterprise/2022/specification-and-sample-assessments/btec-tech-award-enterprise-2022-spec.pdf"
curl -L -o Pearson-BTEC-TechAward-KeyDates-2026-2027.pdf "https://qualifications.pearson.com/content/dam/pdf/btec-tec-awards/btec-tech-awards-2026-2027-key-dates-schedule.pdf"
```

Then point `--spec-dir` or `TUTAIR_SPEC_DIR` at this folder.

Two traps, both hit for real:

- **Pearson serves an HTML page** if the URL is wrong, with HTTP 200. Check the first four
  bytes are `%PDF` and the file is over 100KB before trusting a download.
- **AQA ship theirs AES-encrypted.** `pypdf` raises `DependencyError` without `cryptography`,
  which is why it is in `requirements.txt`. `tutair_spec.py` catches that and mints without the
  specification rather than losing the run, so a missing dependency shows up as weaker grounding
  rather than a crash — check the grounding line, not just the exit code.

## Open question: which Business qualification?

Both Business specifications are listed because the evidence conflicts. Neston High offers all
of these at KS4: Pearson BTEC Tech Award in Enterprise, WJEC Eduqas GCSE Business, and a
Cambridge National in Business. The school's own curriculum page describes KS4 Business as
following "the two components of the Eduqas GCSE specification", while Satchel One labels the
class `11D/Bt` as "Applied Business Studies" and one task was titled "In class CAE - BTEC
Business". Confirm with the Business teachers before building revision material against either.

Construction and Built Environment (`11C/Cm`) is timetabled three times a week but its awarding
body is unconfirmed, so no specification is listed for it.
