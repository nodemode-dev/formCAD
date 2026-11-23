# Testing FormCAD

FormCAD's tests run the app and check what a user or a calling program would notice. This page says how to run them, where they live and what a test must do to be accepted.

## Running the tests

```sh
./formCAD test                       # every layer
./formCAD test engine                # one layer: unit, engine, workers, browser or scripts
./formCAD test engine -k offset      # the rest of the line goes to the runner
```

On Windows use `formCAD.bat test`. Run `./formCAD install` first. The worker tests need the kernel and the mesher (`./formCAD install-kernel`, `./formCAD install-mesher`); without them those tests are skipped with a line that says so. The browser tests need Playwright and a Chromium:

```sh
backend/venv/bin/python -m pip install -r backend/requirements-test.txt
backend/venv/bin/python -m playwright install chromium
```

## The layers

| Layer | Tool | Where | What it runs against |
| --- | --- | --- | --- |
| unit | vitest, happy-dom | `frontend/tests/unit/` | exported interface functions and stores, no browser |
| engine | pytest | `backend/tests/` (tests without a worker marker) | the real FastAPI app in process, with a temporary data folder and a fresh document for each test |
| workers | pytest | `backend/tests/` (tests marked `kernel` or `mesher`) | the same app with the kernel and mesher worker programs running |
| browser | pytest, Playwright | `e2e/` | the dev build on 5290 and a live engine on 8290 that the run starts itself, a fresh browser context for each test |
| scripts | pytest | `setup/tests/` | the `./formCAD` dispatcher and the setup scripts |

The engine tests are grouped by area: `core`, `drawing`, `modify`, `annotation`, `interchange`, `solids`, `meshsim`, `assembly`, `manufacture`, `electronics`, `automation`.

## What the shared base gives a test

`backend/tests/conftest.py` provides `engine` (the client), `doc` (a fresh empty document, closed afterwards), `docs` (a factory for several), `kernel` and `mesher` (the worker services), `fixtures` (the repository's `fixtures/` folder) and pytest's `tmp_path`. A document types on the command line the way a user does:

```python
def test_a_line_typed_on_the_command_line_lands_in_the_document(doc):
    doc.type("LINE", "0,0", "30,40", "")
    line = doc.only("line")
    assert geometry.close(geometry.dist(line["start"], line["end"]), 50.0)
```

`backend/tests/support/` holds helpers that do not depend on the app: `geometry.py` (lengths, areas, centroids, mesh volume), `dxf.py` (an independent DXF reader) and `gcode.py` (an independent G-code walker). They exist so that an exported file is judged by the rules of its format and not by the code that wrote it.

`e2e/conftest.py` provides `page` (the app loaded in a fresh context; the test fails on any page error or any 5xx answer), `api` (reads the engine behind the page) and the helpers `throttle`, `watch_dom` and `dom_report` for the no-flash checks.

Markers: `kernel`, `mesher`, `live` (starts the real engine process on a free port) and `slow`.

## The five rules

1. The test runs the app through a public surface: an HTTP route, a command through the command runner, an MCP tool, a worker request, an exported interface function, or the visible interface in a browser.
2. It checks a result a user or a calling program would notice: geometry, a number, a saved or exported file, a refusal, an undo, something on screen.
3. Its expected value comes from outside the code under test: mathematics, the rules of a file format checked by an independent reader, the manual and the format documents in `docs/`, an invariant (undo then redo, save then open, export then import), two independent paths that must agree, or a fixture that states its own content.
4. It can fail. Change the expected value once, see the test fail, and change it back.
5. Its name says the behaviour in plain words.

Not accepted:

- reading source files to check text, spelling, comments or formatting;
- checks that a file, function, class or route merely exists;
- a check of the status code alone, with nothing checked in the answer (the two sweeps in `backend/tests/core` are the one stated exception: they exist to catch server errors across every command and every read route);
- snapshot files made by running the code and saving what came out;
- replacing the thing under test with a stand-in and testing the stand-in;
- a skip or an expected failure without a written reason.

## When a test shows the app is wrong

Do not bend the test. Keep it and mark it as a strict expected failure with a reason that starts with `DEFECT:` and says what the app does, what it should do and where that is stated. `git grep -n "DEFECT:" backend/tests e2e frontend/tests` lists the known ones. When the app is fixed, the strict mark makes the test fail until the mark is removed, so a fix cannot go unnoticed.

## Changing behaviour

A change in behaviour updates its tests in the same pull request. New test data is made by hand or by FormCAD itself and gets a line in `docs/DATA_PROVENANCE.md`. The clean-room rule holds in tests as in code: no other CAD product is named, and only file-format names appear.

## CI

Every pull request runs `test-unit`, `test-engine` (engine, workers and scripts on Linux; engine and workers also on macOS and Windows) and `test-browser` (three shards on Linux). The worker tests in CI install the kernel and the mesher from the published releases through the app's own install check, so a worker that does not match its record fails the run.
