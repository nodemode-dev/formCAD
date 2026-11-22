use std::path::PathBuf;

const ENGINE: &str = if cfg!(windows) { "formcad-engine.exe" } else { "formcad-engine" };

pub fn engine_folder() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    let dir = exe.parent()?;
    [
        dir.join("../Resources/engine/formcad-engine"),
        dir.join("../Resources/engine"),
        dir.join("engine/formcad-engine"),
        dir.join("engine"),
        dir.join("resources/engine/formcad-engine"),
        dir.join("resources/engine"),
        dir.join("../lib/FormCAD/engine/formcad-engine"),
        dir.join("../lib/FormCAD/engine"),
        dir.join("../lib/formcad/engine/formcad-engine"),
        dir.join("../lib/formcad/engine"),
    ]
    .into_iter()
    .map(|folder| folder.join(ENGINE))
    .find(|program| program.is_file())
}

#[cfg(not(debug_assertions))]
pub fn dev_backend() -> Option<(PathBuf, PathBuf)> {
    None
}

#[cfg(debug_assertions)]
pub fn dev_backend() -> Option<(PathBuf, PathBuf)> {
    let exe = std::env::current_exe().ok()?;
    let mut dir = exe.parent()?.to_path_buf();
    for _ in 0..6 {
        let backend = dir.join("backend");
        let script = backend.join("formcad_engine.py");
        if script.is_file() {
            let (scripts, name) = if cfg!(windows) { ("Scripts", "python.exe") } else { ("bin", "python") };
            let python = [".venv", "venv"]
                .into_iter()
                .map(|venv| backend.join(venv).join(scripts).join(name))
                .find(|path| path.is_file())
                .unwrap_or_else(|| PathBuf::from(if cfg!(windows) { "python" } else { "python3" }));
            return Some((python, script));
        }
        dir = dir.parent()?.to_path_buf();
    }
    None
}
