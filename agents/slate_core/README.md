# slate_core

Framework-free logic for the MVP flow: resume parse, job matches, tailoring with claim check,
approval gate, roadmap, mock interview with memory. Standard library only, no LLM calls
(deterministic, so the demo is repeatable). Returns the shapes in `contracts/api-contracts.md`.

Run the tests (Python 3.10+):

    python3 -m unittest discover -s tests -v

`SlateService` in `service.py` is the one entry point. A FastAPI route, the CLI or the web app
can call it directly. State is in memory (resets on restart) until the DB from PR #4 is wired in.

Known limits: resume input is plain text (PDF extraction not done), job data is a small sample list,
and the interview "weak answer" rule is a simple length check meant to be swapped for an LLM later.
