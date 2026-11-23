# Contributing to FormCAD

Thank you for helping. FormCAD is the Form family's drafting and modelling app: 2D
drafting, parts, surfaces, assemblies, drawings, simulation and manufacturing in one
window with no account, running on your own computer, and open to agents over MCP.
It gets better through real use and real contributions.

## Where to start

- **Use it and report what goes wrong.** A clear bug report, with steps, the version,
  your platform and the file that shows the problem when you can share it, is one of
  the most useful things you can give.
- **Look at the open issues.** Comment on one before starting larger work, so nobody
  builds the same thing twice.
- **Read the laws first.** [CLAUDE.md](CLAUDE.md) and [AGENTS.md](AGENTS.md) bind
  every change, whether a person or an agent makes it. The wiki's
  [Contributing](.docs/wiki/Contributing.md) page lists them with the reasons.

## Setting up

Clone the repository and run `./formCAD install`, then `./formCAD` (on Windows,
`formCAD_oc_install.bat`, then `formCAD.bat`). The first installs the engine's Python
environment, the interface's packages and the kernel's development environment; the
second starts the engine on 127.0.0.1:8290 and the interface at
http://localhost:5290. `./formCAD doctor` checks the toolchain, the installs and the
ports, and `./formCAD desktop dev` opens the desktop window after
`./formCAD install-desktop`. The README's "Run it from source" section has the
requirements.

The code lives in:

| Folder | What is there |
| --- | --- |
| `backend/app` | the engine (Python, FastAPI): the drawing database, the command registry, every workspace's logic, the MCP server |
| `kernel` | the geometry kernel worker (OpenCascade), a separate program the engine talks to over JSON lines |
| `mesher` | the mesher worker (Netgen), a separate program too |
| `frontend/src` | the interface (TypeScript, Vite): it renders engine state and dispatches commands |
| `src-tauri` | the desktop shell (Rust, Tauri 2) |
| `setup` | the scripts behind `./formCAD` |
| `release` | signing scripts, the worker records and their tools, the SBOM tool |
| `skills` | agent skill packs |
| `fixtures`, `demos`, `demo` | sample documents and the browser demos |
| `docs` | the manual and the format contracts |
| `.docs/wiki` | the wiki's source |
| `apps` | the entries the family's compiler and portal read |

## Before you open a pull request

Run the same checks CI runs:

```sh
(cd frontend && npm ci && npx tsc --noEmit -p . && npm run build)
(cd backend && pip install --require-hashes -r requirements.lock \
  && python -m compileall -q app formcad_engine.py \
  && python formcad_engine.py --selfcheck)
./formCAD test
```

CI also boots the engine and probes it, runs `bash -n` over the shell scripts, fails
on a long dash in tracked Markdown or an emoji in tracked text, freezes the engine
and scans the result for licences that may not ship.

- Keep each pull request to one change.
- A change in behaviour updates its tests in the same pull request. [docs/TESTING.md](docs/TESTING.md)
  says how to run the tests and what a test must do to be accepted.
- Write commit subjects the way the history does:
  `type(scope): lowercase sentence describing the effect (x.y.z)`, for example
  `feat(sketch): ...`, `fix(kernel): ...`, `docs(readme): ...`. Leave the version
  alone; a maintainer bumps every version site together when releasing. See
  [BRANCHING.md](BRANCHING.md).
- The engine owns geometry and commands. A feature is a command in the engine's
  registry, so the window, the command line and the MCP server all get it; the
  interface renders and dispatches and never computes geometry.
- The engine never imports the kernel's or the mesher's libraries. 3D work goes to
  the worker programs, which stay separate and replaceable.
- Every new route asks for the session token, validates paths and forces output
  extensions. A subprocess takes an argument list, a timeout and bounded output.
  A job checks its size limits before it starts.
- The interface renders once and patches in place: no flash, no flicker, no
  re-render of a live container. Colours, spacing and `z-index` come from the token
  files, icons are inline `currentColor` SVG from the app's own icon module, and
  Vite stays on host false.
- No emoji anywhere, no long dash in Markdown (use the interpunct), and keep code
  comments to a minimum: decisions go to the `HASHOUT_LOG.md` beside the code, in
  the same change.
- Command names, routes, MCP tool names and the `.fcad` format stay as they are, so
  agents, scripts and saved files keep working.
- Data ships with a cited source for every value, or not at all (see
  [docs/DATA_PROVENANCE.md](docs/DATA_PROVENANCE.md)).

## How changes land

Only the maintainers push to `main`, and they do it through pull requests too.
Everyone else forks the repository and opens a pull request into `main`. A pull
request merges, with a merge commit, when every CI check passes on an up-to-date
branch and a maintainer has approved it after its last push.

## Releases

A release is a version, and only the maintainers make one: the version bump is the
last commit on `main`, a maintainer cuts a `compile_vX.Y.Z` branch from it, and every
build is compiled, signed and released from
[FormCompiler](https://github.com/nodemode-dev/formcompiler). The kernel and mesher
workers are built and signed there as well and published in
[formai-binaries](https://github.com/nodemode-dev/formai-binaries). This repository
holds the source and no signing value. See [docs/RELEASE.md](docs/RELEASE.md).

## Licensing

FormCAD is licensed under the Apache License 2.0 ([LICENSE](LICENSE), SPDX
`Apache-2.0`). By contributing, you agree that your contribution is licensed under the
same terms. Only add code you have the right to contribute, and name any third-party
code and its licence in the pull request.

## Clean room, patents and other people's IP

FormCAD is written from descriptions of what a feature does, never from another
product. The maintainers hold that line with counsel; contributors do not decide it,
and nobody here redesigns a feature on their own reading of a patent. This is
engineering diligence, not legal advice.

### Rules for every contribution

- Clean room: never open, fetch, quote or copy the source, the help text or the files of any other CAD, CAM, CAE or EDA product, and never name one in code, identifiers, comments or the interface. The only places a product name may appear are a file-format name and the README's "instead of" line.
- Patents: do not add a feature, or a dependency that provides one, that reproduces a method you know to be patented. If you are unsure, open an issue that describes what the feature does, not which patent it resembles. Patent numbers stay out of code, commits, comments, logs and changelogs.
- Copyright: never trace or import another vendor's icons, and never bundle another vendor's templates, standards tables, libraries, sample files, fonts or symbols. Sample documents and previews come from this repository's own scripts and the app's own captures.
- Licences: every new dependency, binary, font or data file gets a row in `NOTICE.md` in the same commit that adds it. GPL stays outside the distributed app, AGPL nowhere, LGPL only as a separate, replaceable, unpatched program, MPL files unedited. CC BY credited, CC BY-SA only unmodified, CC NC and ND never.
- No code from FormCompiler or FormPortal, which are GPL-3.0-only. FormCAD meets their data contracts and takes nothing else from them.

## Conduct

Everyone taking part follows the [code of conduct](CODE_OF_CONDUCT.md). Security
problems go through [SECURITY.md](SECURITY.md), never a public issue.
