# Uptime Monitor — Instructions for Claude Code

## Context
- Project owner: Emir, a 3rd-year computer engineering student.
  He is learning Python and backend/DevOps, and his English is weak.
- Goal: a Backend + DevOps portfolio project for internship
  applications. Emir must be able to explain every decision in an
  interview.
- The plan lives in `local-docs/ROADMAP.md` (Turkish, git-ignored).
  Always follow its phase order, design and acceptance criteria.

## Mode: autonomous
- Work through the phases in order without asking for approval at
  every step.
- STOP and ask Emir only when:
  - a step needs him (admin rights, passwords, sudo, secrets/tokens,
    creating accounts, payments, GitHub settings) — see ROADMAP 4.3;
  - an action is destructive or irreversible;
  - a design decision in the roadmap must change (then also write
    an ADR in `docs/decisions/`);
  - something costs money.
- Never start a phase before the previous phase meets ALL of its
  acceptance criteria. Do not add features from later phases.

## Verification (strict)
- Write tests for every feature. Before every commit,
  `uv run pytest` and `uv run ruff check .` must pass.
- At the end of each phase, actually run and verify every
  acceptance criterion (start the services, call the endpoints,
  check the database). Fix problems before moving on.

## Git and GitHub
- Commit after each logical step. Commit messages in English,
  Conventional Commits style (`feat:`, `fix:`, `test:`, `docs:`,
  `ci:`, `build:`, `chore:`).
- Do NOT add `Co-Authored-By` or any AI attribution trailer to
  commits or PRs. AI use is disclosed in the README Acknowledgements
  section instead. In Phase 0, also turn off Claude Code's default
  commit attribution in the project settings (check the current
  Claude Code docs for the correct setting name).
- Push to `origin` at the end of each phase, after all checks pass.
- From Phase 9 on: one branch per phase, open a PR with `gh`, wait
  for CI to pass, then merge.
- Never force-push, rewrite history, run `git reset --hard`, or
  commit secrets.

## Language rules (strict)
- Talk to Emir in TURKISH. Keep technical terms in English.
- Everything written to the repository must be in ENGLISH: code,
  identifiers, comments, docstrings, README, ADRs, docs, commit
  messages, branch names, PRs, API errors, logs, status page text,
  Telegram messages, Grafana dashboards.
- Files in `local-docs/` are Turkish and never committed.

## Phase report (required)
At the end of every phase, append a Turkish section to
`local-docs/PROGRESS.md` containing:
1. What was built (files, endpoints, services).
2. Why it was built this way, and the alternatives considered.
3. New concepts used, each explained in 2-3 simple sentences.
4. Problems encountered and how they were solved.
5. Acceptance criteria checklist with verification results.
6. 3-5 interview-style check questions with short answers.
Then give Emir a short Turkish summary in chat.

## Final deliverables (Phase 12)
- `local-docs/PROJE_HIKAYESI.md` + PDF: the whole project explained
  from start to finish in Turkish, phase by phase, built from
  PROGRESS.md and the actual code.
- `local-docs/PROJE_REHBERI.md` + PDF: updated so every statement
  matches the actual code.

## Security
- Never write secrets into code or the repository. Use `.env` and
  keep `.env.example` up to date.
- User-supplied URLs must always pass the SSRF checks
  (ROADMAP section 3.4).

## Commands
- Tests: `uv run pytest`
- Lint/format: `uv run ruff check . --fix` and `uv run ruff format .`
- Local stack: `docker compose up -d`
- Migrations: `uv run alembic revision --autogenerate -m "..."`,
  `uv run alembic upgrade head`
