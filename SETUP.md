# Setting TutAIR up on a new machine

Everything needed to go from a bare Windows machine to a working YouTube-to-questions
pipeline. Written after doing it on three machines, so the traps listed here are ones that
actually happened rather than ones that might.

## 1. Prerequisites

- **Python 3.12 or newer.** Developed and tested on 3.13. There is a report that 3.11 fails
  outright with a `SyntaxError` in `tutair_viewer.py`, unverified.
- **git**.
- **The `claude` CLI**, if you want questions minted on a subscription rather than per-token.

### The Microsoft Store stub

On a fresh Windows machine `python --version` often prints *"Python was not found"* even after
a real install, because Windows ships an App Execution Alias that shadows it.

Fix: **Settings > Apps > Advanced app settings > App execution aliases**, turn off `python.exe`
and `python3.exe`, then open a **new** terminal. Also check `Python313\Scripts` is on `PATH`,
or pip-installed tools will not resolve.

## 2. Get the code

```powershell
git clone https://github.com/warwickbrady99/tutair.git
cd tutair
git checkout youtube-to-mcq
pip install -r requirements.txt
```

Check it:

```powershell
python -m unittest discover -p "test_*.py"
```

Expect `OK`. The test count tells you where you are — if it is much lower than the current
suite, you are on an older commit or on `main`.

An OpenAI `401` about a key `sk-test` in the output is a **test fixture** asserting the error
path. It is not a failure.

## 3. Specification PDFs

The PDFs are **not in the repo**: they are copyright AQA, OCR, Pearson and WJEC, and about
36MB. `specifications/MANIFEST.md` lists all nine with the exact public URL each came from and
a curl block that rebuilds the folder.

**The folder will be empty on a new machine. That is expected, not data loss.**

Two traps, both hit for real:

- **Pearson serves an HTML page with HTTP 200** if a URL is wrong. Check the first four bytes
  are `%PDF` and the file is over 100KB before trusting a download.
- **AQA ship theirs AES-encrypted.** `pypdf` raises `DependencyError` without `cryptography`,
  which is why it is in `requirements.txt`.

**Filenames matter.** `find_spec_pdf()` matches the specification code inside the filename, so
the science one must contain `8464` and the computing one `J277`. Use the names in the manifest.

## 4. Configure

```powershell
copy .env.example .env
```

| Setting | What it does |
|---|---|
| `TUTAIR_AI_PROVIDER=claude` | Mints questions through the Claude Code CLI. Preferred: session limits are what stopped this project the first time. |
| `TUTAIR_AI_PROVIDER=openai` | Uses `OPENAI_API_KEY` and `TUTAIR_AI_MODEL` instead. |
| `TUTAIR_SPEC_DIR` | Where the specification PDFs live. Or pass `--spec-dir`. |
| `TUTAIR_INBOX_ROOT` | Where notes are written. See below. |

`.env` is gitignored. Never paste an API key into a chat or a commit.

### Where notes are written

Resolved in this order, at the moment it is needed:

1. `TUTAIR_INBOX_ROOT`, if set.
2. `OneDrive\Desktop\MyPKA\Team Inbox\TutAIR` — **only if that folder already exists.** A
   machine already using it keeps working; a fresh machine is never sent into OneDrive, which
   may be signed out, unwanted, or quietly syncing a student's notes to the cloud.
3. `MyPKA\Team Inbox\TutAIR` under your home folder.

`--inbox-root` (pipeline, transcript, intake) and `--root` (viewer) override everything. Pass
the same folder to both, or the viewer will show nothing and give no error.

## 5. Prove it works

Installed and green is not the same as working. Run the reference pipeline once:

```powershell
python .\tutair_pipeline.py --url "https://www.youtube.com/watch?v=IX8ofg-WmvU" --subject "Science" --topic "Cell structure" --board AQA
```

Expected:

```
1/4  AQA GCSE Biology in 10 Minutes! | Topic 1 - Cell Biology
     Brainstorm - Maths and Science
2/4  222 caption segments
4/4  Specification grounding: course map (6 objectives);
     specification PDF (AQA-GCSE-CombinedScience-Trilogy-8464.pdf)
     Approved 3-5 of 8
```

### Reading the result

| What you see | What it means |
|---|---|
| `Specification grounding: none` | `--spec-dir` is wrong, or a filename is missing its code |
| `course map (6 objectives)` only | PDF found but unreadable — is `cryptography` installed? |
| Both listed | Correct |

**The approved count varies between runs** — 5, 4 and 3 have all been seen on the same video.
The writer samples, so the candidates differ each time. **Do not tune toward 8 of 8.** A run
where the reviewer rejects nothing is more suspicious than one where it rejects three.

Then:

```powershell
python .\tutair_viewer.py
```

Open the note and press **Quiz Me**. Choosing an option and pressing **Reveal** should show the
answer, the timestamp that taught it, and the specification objective it targets.

## 6. Known broken — deliberately left alone

None of this blocks the pipeline. It is listed so nobody spends an afternoon rediscovering it:

- The dashboard's **"Level 5 / 850 XP / 3 Day Streak" is hardcoded** and derived from nothing.
- Around **22 dashboard buttons** are disabled or route to a "Coming Soon" placeholder.
- The **sidebar subject list is hardcoded** and ignores the subjects chosen during onboarding.
- The **exam board picker has no BTEC or Pearson option**, though two vocational subjects are
  taken.
- The **login screen is cosmetic** — localStorage only, no authentication behind it.

Also: the course map currently holds **six Cell biology objectives only**. Every other topic
mints from the transcript alone and reports weaker grounding honestly rather than implying
exam-board coverage. Expanding it from the specification PDFs, starting with OCR J277, is the
obvious next job.
