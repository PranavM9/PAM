# Git guidelines

- Name branches `t<NN>/<slug>` for spec tasks and `p0/<slug>` for test data.
- Start each task from a fresh main:

  ```
  git checkout main && git pull && git checkout -b <branch>
  ```
- When done: rebase on main, push, and open a PR titled "T<NN>: <title>".
- No code review is required. PM runs the task's checks and the full test suite on the branch.
- Merge only when the task's *Done when* checks and the full test suite pass.
- Never mention Claude, AI tools, or agents anywhere in git or GitHub: commit messages, PR titles and descriptions, branch names, or comments. No `Co-Authored-By` or "Generated with" lines.
- Keep commit and PR messages short, technical, and direct: what changed, how it was verified, and anything pending. No narrative.
- If two branches both added lines to SPEC.md and the merge conflicts, keep both sides and delete nothing.
