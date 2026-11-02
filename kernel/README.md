# formcad-kernel

The geometry worker of FormCAD. It is a separate program: the engine starts it as a child process and talks to it in JSON lines over stdin and stdout, one object per line. `{"id", "method", "params"}` goes in; `{"id", "result"}` or `{"id", "error": {"message"}}` comes back. This turn it answers `hello` (OpenCascade, OCP, build123d and Python versions) and `shutdown`.

## Why it is separate

The worker carries OpenCascade (OCCT), which is LGPL-2.1 with the OCCT exception. FormCAD itself stays permissively licensed, so the worker is never bundled in the app, the installers or the engine. It ships from the `formCAD-binaries` repository as release archives, one per platform, and the app downloads the one for its machine on first run, the way formcut fetches ffmpeg from `formcut-binaries`.

- Release tag: `occt-<release>`
- Archive: `occt-lgpl-<release>-<triple>.tar.gz`, holding one folder `occt-lgpl-<release>-<triple>/` with `formcad-kernel` (`formcad-kernel.exe` on Windows), the shared OpenCascade libraries beside it so they can be replaced, the LGPL text and the third-party notices
- Address: `https://github.com/nodemode-dev/formCAD-binaries/releases/download/occt-<release>/occt-lgpl-<release>-<triple>.tar.gz`
- The engine checks every file against the SHA-256 in `backend/app/data/kernel-licence.json` and installs to `<data>/kernel/<release>/` only if all of them match. No build is published yet, so the record holds `"release": null` and an empty file list.

## Dependencies

`requirements_kernel.txt` pins `cadquery-ocp-novtk` (Apache-2.0 wrapper around dynamically linked OCCT) and `build123d` (Apache-2.0), for Python 3.12.

## Running it from source

```
python3.12 -m venv kernel/venv
kernel/venv/bin/pip install -r kernel/requirements_kernel.txt
echo '{"id":1,"method":"hello"}' | kernel/venv/bin/python kernel/formcad_kernel.py
```

## How the engine finds it

In order: `FORMCAD_KERNEL` (a frozen `formcad-kernel` file, or `kernel/formcad_kernel.py`, which the engine runs with the `venv` python beside it); then `<data>/kernel/<release>/formcad-kernel` (`FORMCAD_KERNEL_RELEASE` picks the release, else the newest folder); then the repository's `kernel/venv` with `kernel/formcad_kernel.py`. With none of these the kernel is absent, which is a normal state: the app runs its 2D features.
