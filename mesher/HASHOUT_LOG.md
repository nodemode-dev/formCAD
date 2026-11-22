# HASHOUT_LOG · mesher worker (mesher/)

Living record of decisions and removed context for the `formcad-mesher` worker, newest first. Read before editing.

Entries older than v0.21.0 are in `backend/HASHOUT_LOG.md` (search for "mesher"). From v0.21.0 a change to a file in `mesher/` is logged here.

## MW1 v0.21.0 this log exists

The mesher is a separate program and never shares a process with the kernel worker or the engine: Netgen is LGPL, so it stays replaceable. It is frozen on its own (`setup/freeze_mesher`), published in `nodemode-dev/formai-binaries` and checked file by file against `backend/app/data/mesher-licence.json` when the app installs it. `requirements_mesher.lock` pins it. Nothing in `mesher/` changed in v0.21.0.
