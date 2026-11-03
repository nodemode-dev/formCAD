# Branching

- One long-lived branch: `main`. Work lands on it directly.
- Release commits come last in a release: `chore(release): version x.y.z (x.y.z)`.
- Commit style: `type(scope): lowercase sentence describing the effect (x.y.z)`.
- Author and committer are `nodemode-ai <mackin@nodemode.ai>`.
- No `Co-Authored-By:` or other co-author trailers, and no generated-with lines in commits or pull requests.
- The family compiler builds from a `compile_vX.Y.Z` branch pushed by the owner; that branch is a release artifact, not a working branch.
