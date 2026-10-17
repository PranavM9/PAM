# Git guidelines

- Name branches `t<NN>/<slug>` for spec tasks and `p0/<slug>` for test data.
- Start each task from a fresh main:

  ```
  git checkout main && git pull && git checkout -b <branch>
  ```
- When done: rebase on main, push, and open a PR titled "T<NN>: <title>".
- A teammate other than the implementer reviews it and runs PM's checklist. PM runs the task's checks and the full test suite on the branch.
- Merge only when all four checks pass.
- If two branches both added lines to SPEC.md and the merge conflicts, keep both sides and delete nothing.
