# HASHOUT_LOG · kernel worker (kernel/)

Living record of decisions and removed context for the `formcad-kernel` worker, newest first. Read before editing.

Entries older than v0.21.0 are in `backend/HASHOUT_LOG.md`, which logged the engine and the kernel together; look there for anything this file does not hold. From v0.21.0 a change to a file in `kernel/` is logged here.

## KW1 v0.21.0 this log exists

The kernel is a separate program: the engine never imports OCP or build123d, and talks to the worker in JSON lines on stdio. It is frozen on its own (`setup/freeze_kernel`), published in `nodemode-dev/formai-binaries` and checked file by file against `backend/app/data/kernel-licence.json` when the app installs it. `requirements_kernel.lock` pins it for every platform. Nothing in `kernel/` changed in v0.21.0.
