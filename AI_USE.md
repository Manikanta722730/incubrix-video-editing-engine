# AI_USE.md — Disclosure of AI Tool Usage

## AI Tools Used

| Tool | Provider | Purpose |
|------|----------|---------|
| **Antigravity** (AI coding assistant) | Google DeepMind | Assisted with code generation, debugging, architecture suggestions, documentation drafting |

## How AI Was Used

- **Code scaffolding**: Antigravity was used to help write initial structure for modules (engine, API, tests). All generated code was reviewed, understood, and validated by me.
- **Debugging**: AI suggestions helped diagnose edge cases (e.g., FFmpeg seek accuracy, redo snapshot storage, `&&` vs `;` in PowerShell).
- **Documentation**: AI helped draft README, REPORT, SOURCES, and this file. Final content was reviewed and edited by me.
- **Test design**: AI helped formulate test cases; all test logic was reviewed and adjusted to match the brief requirements exactly.

## What AI Did NOT Do

- No LLM API calls are made inside the submission itself. The instruction parser (`engine/parser.py`) is a deterministic regex/rule-based system — not a language model.
- No AI-generated media or voices were used. All test media is synthetically generated from pure NumPy/OpenCV code.
- No AI was used to fabricate results or generate false evidence.

## Understanding and Reproducibility

I can explain, modify, and reproduce every part of this solution during a live evaluation session. All design decisions are documented in `REPORT.md` and `README.md`.

## Declaration

All AI tool usage is fully disclosed above. The solution is my own individual work and all claims are supported by evidence in the test suite and batch runner outputs.

— **Manikanta** (mmuddana6@gmail.com), November 2026

