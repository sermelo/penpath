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

## Dependencies

Add a dependency only when the standard library and existing
dependencies can't do the job. Say why in the pull request, and follow
"Dependency Management" in `docs/CONVENTIONS.md`.

## Safety

- Never commit secrets, tokens or keys.
- Call external tools (for example vpype) with explicit arguments,
  never through a shell.