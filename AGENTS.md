# penpath

Instructions for anyone working on penpath, people and AI agents alike.
Read this first, then the documents in `docs/` it points to.

## Vision

Free software that takes anyone from an image to a finished pen plot,
smoothly and quickly: simple by default, customizable when needed. It
works as a Python library, from the command line in a pipeline, or
through AI agents.

The path is: image → SVG → G-code → pen plotter. The SVG is the step
you review and adjust before plotting; it stays a plain, standard SVG
that other tools can use. G-code is a later goal, through machine
profiles (bed size, pen up/down, speeds). The core never depends on one
machine.

## Mission

We build penpath in small, tested, reviewed steps. Each step makes the
path from image to pen plot work better for a real user, keeps the
default simple, and leaves the code easier for the next person or agent
to work on.

What good work means:

1. **It plots well, not just looks right on screen.** Two checks:
   - **Likeness:** simulate the finished plot and compare it with the
     original image. The original must be recognizable.
   - **Machine cost:** pen-up travel, number of pen lifts, tiny
     segments.
2. **Small, finished steps.** Every change lands as a pull request that
   works. No half-done features on `main`.
3. **Library first.** Every feature is a documented Python function in
   `penpath.core` first, and a CLI option second. The CLI stays a thin
   layer.
4. **Built for people and for agents.** Sane defaults, errors that say
   what to fix, output a program can read (clear exit codes, no
   surprises on stdout), and a README example for each feature.

**Tie-breaker:** when two good options conflict, choose the one that
keeps the default path simple. A new option is fine; making the default
harder is not.

## Where things are

- `docs/FEATURES.md`: what penpath does, and what is planned or out.
- `docs/PLAN.md`: architecture and the order of work.
- `docs/CONVENTIONS.md`: tooling, code style, typing, tests, versions.
- `docs/TESTING.md`: how we prove features work, test data, tolerances.
- `docs/CLI.md`: every command and option.
- `BRANCH_PROTECTION_SETUP.md`: the branch protection ruleset on `main` and how to verify it.
- `src/penpath/core/`: the library (no CLI code). `src/penpath/cli/`: the command line, on top of `core`.

## Before you open a pull request

Run the checks from `docs/CONVENTIONS.md` and make sure all pass:
formatting (`ruff format --check`), lint (`ruff check`), types (`mypy`)
and tests (`pytest`). Add tests for every change in behaviour. Update
`--help`, `docs/CLI.md` and the README when a user-facing option
changes.

## Git and pull requests

- Never push to `main`. Work on a branch and merge by pull request only.
- **Commits:** Conventional Commits, with the task or issue id when
  there is one:

  ```
  <type>(<scope>): <summary> (<id>)

  <body: what changed and why, wrapped at 72 characters>
  ```

  `type` is `feat`, `fix`, `test`, `docs`, `refactor`, `perf` or
  `chore`. `scope` is the area touched (`image`, `drawing`, `geometry`,
  `output`, `cli`, `core`, `docs`, `ci`). The summary is imperative,
  lower case, no full stop, first line at most 72 characters. One
  logical change per commit; no "wip" or "fix stuff".
- **Pull request title:** same format as a commit's first line.
- **Pull request description:** Summary (what and why), Changes, How it
  was tested (commands and results), Out of scope / follow-ups.
- Keep a pull request to one goal and under about 400 changed lines.
- **Fixes after review** go in as `git commit --fixup=<sha>`. Don't
  rewrite or force-push a branch under review.
- Pull requests are **squash-merged**, so each lands on `main` as one
  commit with the PR title.

## CI and branch protection

`main` is protected on GitHub. A pull request can merge only when these
CI checks pass: `Lint & Format`, `Type Check (mypy)`, `Unit Tests`,
`Integration Tests` and `Build Wheel` (job names in
`.github/workflows/ci.yml`), and only when its branch is up
to date with `main` (strict required status checks; green checks alone
don't unblock a branch that is behind). Nobody can push to
`main` or bypass the checks, agents and people alike. The `Coverage Report`
job reports but doesn't block.

- **Passing on your machine is not enough.** Before you hand a pull
  request to the next role, run `gh pr checks <number>` and read the
  result. All five checks must be green. Don't hand it on while a check
  fails or is still running.
- **All checks green is not enough: the branch must also be up to date
  with `main`.** GitHub's setting "Require branches to be up to date
  before merging" is on. If another PR merged first, yours shows as
  blocked (`gh pr view <number> --json mergeStateStatus` says `BEHIND`
  or `BLOCKED`) even though every check is green, until the branch
  contains the latest `main` and the checks pass again on that state.
  Update it with `gh pr update-branch <number>` (or merge `origin/main`
  into the branch), wait for the checks to run again, and re-read
  `gh pr checks <number>`. Never rebase or force-push a branch under
  review. Updating the branch is the fix, not a workaround.
- **A red check is the author's to fix**, with a new commit on the same
  branch (see "Fixes after review"). Quote the failing job and the exact
  error line in the task.
- **The reviewer merges only after confirming every check is green and
  `mergeStateStatus` is not `BEHIND`/`BLOCKED`**, with `gh pr checks <number>` and
  `gh pr view <number> --json mergeStateStatus`, then `gh pr merge <number> --squash`.
- **If GitHub refuses a merge for another reason, don't work around it.** No admin
  override, no changing branch protection or the workflow, no disabling
  a check. Write the exact error in the task and hand it back to sergio.
- **If CI fails for a reason outside your change** (broken `main`, a
  flaky test, a missing dependency), say so in the task with the failing
  job and error line. Don't merge anyway. Fixing a red `main` comes
  before new feature work.
- Don't weaken CI to make a check pass (skipping tests, loosening
  lint, removing a job) unless sergio asks for it in a task.

## Dependencies

Add a dependency only when the standard library and existing
dependencies can't do the job. Say why in the pull request, and follow
"Dependency Management" in `docs/CONVENTIONS.md`.

## Safety

- Never commit secrets, tokens or keys.
- Call external tools (for example vpype) with explicit arguments,
  never through a shell.