# Branch Protection for `main`

Branch protection for `main` is configured and active. This document
describes the live setup and how to verify it; no manual admin setup is
pending.

## Current configuration

The repository uses a ruleset named `Protection`:

| Field | Value |
|-------|-------|
| ID | `27859908` |
| Name | `Protection` |
| Target | `branch` |
| Enforcement | `active` |
| Condition | `refs/heads/main` |
| Bypass actors | none |

Rules in effect:

- **Require a pull request before merging**, with squash as the only
  allowed merge method.
- **Require status checks to pass**, with
  `strict_required_status_checks_policy: true` (branches must be up to
  date before merging). The required contexts are the job `name:` values
  from `.github/workflows/ci.yml`, not the job ids:
  - `Lint & Format`
  - `Type Check (mypy)`
  - `Unit Tests`
  - `Integration Tests`
  - `Build Wheel`
- **Block deletion** of the branch.
- **Block non-fast-forward** pushes (force pushes).
- **Block creation** of a branch matching the condition.

`Coverage Report` is intentionally not a required check. It runs with
`if: always()` and its coverage step uses `continue-on-error: true`, so
it is report-only.

## Verify

Run:

```bash
gh api repos/sermelo/penpath/rulesets/27859908
```

Confirm `enforcement` is `active`, the condition includes
`refs/heads/main`, and the rules and required check contexts listed above
are present.

## Scope

Changes to the ruleset — its checks, contexts, or enforcement level —
are a separate decision for a repository admin. This document only
records the configuration that is already live.
