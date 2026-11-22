# HASHOUT_LOG · shell (src-tauri/)

Living record of decisions and removed context for the desktop shell, newest first. Read before editing.

## SH1 v0.20.1 the engine cannot outlive the shell on Windows, a failed spawn speaks, and a release build runs only its own engine (src/win_job.rs, src/main.rs, src/packaged.rs, Cargo.toml, tauri.conf.json)

Job object. `backend/formcad_engine.py` `watch_parent` returns at once where there is no POSIX parent to poll, so on Windows a shell that crashed or was ended in Task Manager left `formcad-engine.exe` running, and the next start made a second one. `win_job.rs` creates one job object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`; the shell holds its only handle, so Windows ends every process in the job when the shell goes, however it goes. The pattern is formtools's `win_job.rs` (Apache-2.0, same family). One difference: formtools spawns with `std::process` and passes the child's own handle, while formCAD spawns through `tauri-plugin-shell`, whose `CommandChild` gives only a process id, so `hold` opens the process by id with `PROCESS_SET_QUOTA | PROCESS_TERMINATE` (the two rights `AssignProcessToJobObject` asks for), assigns it and closes that handle. `kill_backend` calls `win_job::end()` before the plain kill, so a quit also ends anything the engine started. The engine is assigned right after the spawn; a process it starts in the few milliseconds before that would be outside the job. Nothing the engine starts that early is known.

Dependency: `windows-sys` 0.61.2 (MIT OR Apache-2.0), Windows only, already in `Cargo.lock` under Tauri; the lock gained one line. Features `Win32_Foundation`, `Win32_Security`, `Win32_System_JobObjects`, `Win32_System_Threading`.

Spawn. `engine.spawn().expect(...)` with `panic = "abort"` ended the process with no window and no word. A spawn error now takes the path the port wait already had: close the splash, show "The FormCAD engine failed to start. Please relaunch the app.", exit 1.

Development engine. `packaged::dev_backend` walks up to six parent folders for `backend/formcad_engine.py` and falls back to the system Python. That is right for `./formCAD desktop dev` and wrong for an installed app, where any such script in a parent folder would have been run. It is compiled only into debug builds now; a release build has a stub that answers `None`, so a missing engine folder reaches "The FormCAD engine is missing. Reinstall the app."

Bundle text. `longDescription` said "in the NodeMode design system" and `copyright` said "nodemode-ai"; `LICENSE` names NodeAgentc, Inc. Both follow it.

Checked here: `cargo check --locked` for `x86_64-pc-windows-msvc`, debug and release profiles, on Linux with Rust 1.97.0. Not checked: the macOS targets (a build script of `objc2-exception-helper` needs an Objective-C compiler this machine lacks; the new `shell` job in `ci.yml` does it on a Mac), the Linux target (no WebKitGTK development files here), and every behaviour on a real Windows machine. Those steps are in `TEST_PLAN.md` in the planning sidecar.
