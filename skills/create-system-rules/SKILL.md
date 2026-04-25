---
name: create-system-rules
version: 2.0.0
description: >
  Create or update an AGENTS.md file optimized for AI coding agents. First inspect the
  repository to extract real project facts, commands, workflows, constraints, and tool
  boundaries. Then write a compact, high-signal AGENTS.md that is specific, verifiable,
  and low-cost to keep in persistent agent context.
  Chinese keywords: 创建 AGENTS.md、生成仓库代理文档、审查 AGENTS.md、压缩规则文档、项目规则。
---

# Create AI-agent-optimized `AGENTS.md`

## Purpose

Create an `AGENTS.md` file that helps coding agents work effectively in a repository.

This skill combines two goals:
- **Repository fidelity** — capture real project facts by inspecting the repo.
- **Persistent-context efficiency** — write only instructions worth their recurring token cost.

The result should be an `AGENTS.md` that is:
- accurate to the repository,
- actionable for agents,
- compact enough to remain useful in persistent context,
- specific enough to change behavior,
- structured enough to scan quickly.

## When to use

Use this skill when the task is to:
- create a new root-level `AGENTS.md`,
- refresh an outdated `AGENTS.md`,
- standardize agent instructions across a monorepo,
- compress a bloated agent doc into a high-signal version,
- review an `AGENTS.md` for vagueness, duplication, or token waste.

## What good `AGENTS.md` contains

A strong `AGENTS.md` should help an agent answer these questions fast:
- How do I install, run, build, lint, and test it?
- What directories, packages, or apps matter?
- What conventions must I follow?
- What must I not change without approval?
- What checks should I run before finishing?

If a section does not help an agent act, verify, or avoid damage, it likely does not belong.

## Core design rule

Write the **smallest complete operational document**.

Prefer:
- exact commands over prose,
- rules over background,
- scenario blocks over concept essays,
- repository facts over generic best practices,
- pointers over duplicated documentation,
- verifiable constraints over stylistic wishes.

## Two-phase workflow

### Phase 1 — Inspect the repository

Before writing `AGENTS.md`, inspect the repository for real facts.

Do not rely on a fixed file checklist. Discover the repository's real operational context by following the most informative artifacts it exposes.

Look for evidence from sources such as:
- `README.md`
- workspace manifests, package metadata, and orchestration config,
- build, test, lint, typecheck, and deploy automation,
- CI workflows and scripts,
- root docs plus package-local docs,
- supplemental notes with names like `gotchas`, `guide`, `runbook`, `notes`, or `contributing`,
- subproject boundaries in monorepos,
- env examples, generators, migrations, and release config.

Extract only facts that an agent will repeatedly need.

If the repo has large supplemental docs, do not paste them into `AGENTS.md`. Instead, record a short trigger-based rule telling the agent when to read which file.

### Phase 2 — Compress into persistent instructions

After inspection, write `AGENTS.md` as a compact operational surface.

Every line must pass these tests:
1. Will an agent likely need this across multiple tasks?
2. Is this more useful here than in an external source?
3. Would removing it make agent behavior worse?

If any answer is **no**, remove the line.

## Writing principles

### P0 — Token cost justification

Every line is recurring context cost.

Keep only:
- high-frequency commands,
- task-critical paths,
- workflow constraints,
- approval boundaries,
- project-specific conventions,
- finish criteria that affect execution.

Remove:
- project history,
- motivational language,
- generic engineering advice,
- duplicated README content,
- long explanations before a simple rule.

```markdown
# ❌
## Project Background
This is a user management system built with TypeScript and PostgreSQL...

# ✅
Import paths use @/ alias pointing to src/ — no relative paths
Test files colocate with source, named *.test.ts
```

### P1 — Proximity

Keep **condition + action + constraint** together.

```markdown
# ❌ Split logic
Run tests before merging
Do not modify lockfiles without approval
Use pnpm

# ✅ Scenario block
Dependency changes: use `pnpm`; do not modify lockfiles unless the task requires it and approval is given; run affected tests after changes.
```

Cluster by scenario, not by abstract category.

```markdown
# ❌ By concept
## Tools
Use bash for commands
Use edit for modifications
## Safety
Confirm before destructive ops
Read before modifying

# ✅ By scenario
## File Operations
Modify: read current content → edit → never skip read
Delete/overwrite: ls affected files → user confirm → execute
```

### P2 — Specificity

Use **verb + object**.

```markdown
# ❌ Vague
Handle migrations carefully
Keep code quality high

# ✅ Specific
Before schema changes: inspect migration history, update schema files, run migration tests, do not apply production-only changes.
```

"Don't X, use Y" is more precise than "do Y" alone.

```markdown
Don't use `any` — use `unknown` with type guards
Don't mutate state directly — dispatch through reducers
Don't call APIs in components — wrap in custom hooks
```

### P3 — Guardrails first

Boundaries > descriptions.

```markdown
# ❌
You are a coding assistant that writes high-quality TypeScript

# ✅
Do not modify dependency versions in package.json — suggest for user to decide
Do not touch CI/CD configs (.github/workflows/*)
Do not refactor outside current task scope — flag and suggest
```

Mandatory prerequisite steps > post-hoc checks.

```markdown
# ❌
Check for errors after modifying files

# ✅
File modification flow: read → confirm current content → edit → run related tests
```

### P4 — Density

Compress repeated patterns.

```markdown
# ❌
When you need to modify a file, you should first read the current content
of the file, and then perform the modification, and after that run tests.

# ✅
File modification: read → edit → run related tests
```

```markdown
# ❌
For unit tests use vitest.
For E2E tests use playwright.
For API tests use supertest.

# ✅
| Test type | Tool       |
| --------- | ---------- |
| Unit      | vitest     |
| E2E       | playwright |
| API       | supertest  |
```

Delete atmosphere statements such as:
- “Please remember”
- “Very important”
- “Make sure to be careful”

### P5 — Training alignment

Standard Markdown, backtick-wrapped commands/paths, short imperative sentences.

```markdown
# ✅
## Git Convention
Commit format: `type(scope): description`
- type: feat / fix / refactor / test / docs
- scope: module name, e.g. `auth`, `api`, `ui`
- Example: `feat(auth): add JWT refresh token rotation`
```

### P6 — Verifiability

Each rule should be checkable as **Yes/No**.

```markdown
# ❌ Not checkable
Keep files small
Use clear naming

# ✅ Checkable
Single file under `src/` should stay below 300 lines unless justified.
Test files use `*.test.ts` naming.
Run `pnpm lint` and affected tests before completion.
```

## Template

The final `AGENTS.md` should usually include these sections, but only when the repo supports them:

```markdown
# [Project] System Rules

## Identity & Boundaries
[1-3 line role definition]
[Negative capability list — what not to do]

## Core Behavior Rules
[High-frequency rules, condition → action → constraint]

## Code Standards
[Technical rules, commands in backticks, "Don't X, use Y"]

## Project Structure
[Directory layout, key paths]

## Extra Context Sources
[If supplemental docs exist: list trigger-based rules for when to read project docs, local guides, runbooks, gotcha notes, or other repo-specific references]
[Keep only path + when to consult it; do not duplicate long doc content]

## Tools & Workflows
[Task-specific flows, tabulated tool selection]
```

Do not force empty sections. If the repo has supplemental guidance files, include a short section that tells the agent to fetch them on demand.

## Decision rule

When forced to choose, prefer:
- concrete repo facts over general guidance,
- short commands over explanation,
- scenario rules over category essays,
- constraints over aspirations,
- compactness over completeness theater,
- accuracy over impressive-sounding coverage.

## Final self-check

Before finishing, verify:
- [ ] Removing any line causes behavior degradation? (P0)
- [ ] Condition and action adjacent for every rule? (P1)
- [ ] No vague words — "careful", "maintain"? (P2)
- [ ] Capability boundaries defined? (P3)
- [ ] Mandatory prerequisite steps specified? (P3)
- [ ] No atmosphere statements? (P4)
- [ ] Standard Markdown with code blocks? (P5)
- [ ] Every rule verifiable yes/no? (P6)
- [ ] Supplemental docs referenced by trigger/path instead of duplicated wholesale?
