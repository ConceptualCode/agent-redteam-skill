# Contributing

Changes to `main` go through a pull request. Direct pushes are blocked, for everyone including the owner.

## Flow
1. Branch from `main` and make the change.
2. Run the checks locally (see "Before every commit" in the README): `ruff check .`, `pytest`, `tools/mutation_all.py` (must say
   "all mutations caught") and the demos. CI runs the same four.
3. Open a pull request. The CI checks must pass, and the branch must be up to date with `main`, before it can be merged.
4. Keep commit messages short and plain.

## Changing the skill
- New or changed module: add tests, a mutation file and a manifest entry (README, "Common changes").
- A skill change that affects how an agent is red-teamed should say what real run showed the need for it.
- Do not name third-party projects or include their findings in this repo.
- Never commit API keys. `.env` is git-ignored; keep it that way.
