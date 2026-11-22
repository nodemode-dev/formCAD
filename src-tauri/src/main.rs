#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;

use tauri::{Emitter, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder, WindowEvent};
use tauri_plugin_dialog::DialogExt;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

mod packaged;
mod reveal;
mod text_edit;
mod traffic_lights;
#[cfg(windows)]
mod win_job;
mod window_state;

struct Backend(Mutex<Option<CommandChild>>);

#[derive(Default)]
struct Opens {
    ready: bool,
    paths: Vec<String>,
}

struct OpenQueue(Mutex<Opens>);

struct ExitGate(AtomicBool);

const FALLBACK_SIZE: (f64, f64) = (1323.0, 860.0);
const MIN_SIZE: (f64, f64) = (980.0, 640.0);
const SCREEN_FRACTION: f64 = 0.9;

fn kill_backend(handle: &tauri::AppHandle) {
    let state = handle.state::<Backend>();
    let child = state.0.lock().ok().and_then(|mut slot| slot.take());
    if let Some(child) = child {
        #[cfg(unix)]
        {
            let pid = child.pid().to_string();
            let signal = |sig: &str| {
                std::process::Command::new("kill")
                    .args([sig, pid.as_str()])
                    .stdout(std::process::Stdio::null())
                    .stderr(std::process::Stdio::null())
                    .status()
                    .is_ok_and(|s| s.success())
            };
            if signal("-TERM") {
                for _ in 0..30 {
                    std::thread::sleep(std::time::Duration::from_millis(50));
                    if !signal("-0") {
                        return;
                    }
                }
            }
        }
        #[cfg(windows)]
        win_job::end();
        let _ = child.kill();
    }
}

fn renderer_choice(handle: &tauri::AppHandle, choice: window_state::Choice) {
    open_exit_gate(handle);
    match choice {
        window_state::Choice::Restart => {
            kill_backend(handle);
            handle.restart();
        }
        window_state::Choice::Quit => handle.exit(0),
    }
}

fn stays_home(target: &tauri::Url, home: &str) -> bool {
    match target.scheme() {
        "data" | "about" => true,
        _ => target.origin().ascii_serialization() == home,
    }
}

fn close_splash(handle: &tauri::AppHandle) {
    if let Some(splash) = handle.get_webview_window("splash") {
        let _ = splash.close();
    }
}

fn open_exit_gate(handle: &tauri::AppHandle) {
    handle.state::<ExitGate>().0.store(true, Ordering::SeqCst);
}

fn ask_page_to_quit(handle: &tauri::AppHandle) -> bool {
    if handle.state::<ExitGate>().0.load(Ordering::SeqCst) || window_state::loop_page_shown() {
        return false;
    }
    let ready = handle.state::<OpenQueue>().0.lock().map(|opens| opens.ready).unwrap_or(false);
    if !ready || handle.get_webview_window("main").is_none() {
        return false;
    }
    handle.emit("formcad://exit-requested", ()).is_ok()
}

fn show_main_window(handle: &tauri::AppHandle) {
    if let Some(window) = handle.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn open_paths(handle: &tauri::AppHandle, paths: Vec<String>) {
    if paths.is_empty() {
        return;
    }
    let send = match handle.state::<OpenQueue>().0.lock() {
        Ok(mut opens) => {
            if opens.ready {
                Some(paths)
            } else {
                opens.paths.extend(paths);
                None
            }
        }
        Err(_) => None,
    };
    if let Some(paths) = send {
        let _ = handle.emit("formcad://open-paths", paths);
        show_main_window(handle);
    }
}

fn paths_from_args(args: &[String], cwd: Option<&str>) -> Vec<String> {
    args.iter()
        .skip(1)
        .filter(|arg| !arg.starts_with('-'))
        .filter_map(|arg| {
            let path = std::path::PathBuf::from(arg);
            let full = match cwd {
                Some(dir) if path.is_relative() => std::path::Path::new(dir).join(path),
                _ => path,
            };
            full.is_file().then(|| full.to_string_lossy().into_owned())
        })
        .collect()
}

#[tauri::command]
fn take_pending_opens(queue: tauri::State<OpenQueue>) -> Vec<String> {
    match queue.0.lock() {
        Ok(mut opens) => {
            opens.ready = true;
            std::mem::take(&mut opens.paths)
        }
        Err(_) => Vec::new(),
    }
}

#[tauri::command]
fn confirm_exit(app: tauri::AppHandle, cancel: Option<bool>) {
    if cancel == Some(true) {
        return;
    }
    open_exit_gate(&app);
    app.exit(0);
}

#[cfg(windows)]
fn portable_web_view_data() {
    let Ok(exe) = std::env::current_exe() else { return };
    let Some(dir) = exe.parent() else { return };
    if dir.join("portable").is_file() || dir.join("portable.txt").is_file() {
        std::env::set_var("WEBVIEW2_USER_DATA_FOLDER", dir.join("FormCADData").join("WebView2"));
    }
}

fn user_data_dir_arg(args: &[String]) -> Option<String> {
    args.iter()
        .enumerate()
        .find_map(|(i, a)| {
            a.strip_prefix("--user-data-dir=")
                .map(str::to_string)
                .or_else(|| (a == "--user-data-dir").then(|| args.get(i + 1).cloned()).flatten())
        })
        .filter(|dir| !dir.is_empty())
}

#[cfg(target_os = "linux")]
fn data_folder() -> std::path::PathBuf {
    use std::path::PathBuf;
    let args: Vec<String> = std::env::args().collect();
    let var = |name: &str| std::env::var(name).ok().filter(|v| !v.is_empty());
    let home = || var("HOME").map(PathBuf::from).unwrap_or_default();
    let explicit = user_data_dir_arg(&args).or_else(|| var("FORMCAD_DATA_DIR"));
    let beside = std::env::current_exe().ok().and_then(|exe| exe.parent().map(PathBuf::from)).unwrap_or_default();
    let portable = args.iter().any(|a| a == "--portable")
        || var("FORMCAD_PORTABLE").as_deref() == Some("1")
        || ["portable", "portable.txt"].iter().any(|name| beside.join(name).is_file());
    let folder = if let Some(dir) = explicit {
        match dir.strip_prefix("~/") {
            Some(rest) => home().join(rest),
            None => PathBuf::from(dir),
        }
    } else if portable {
        beside.join("FormCADData")
    } else {
        match var("XDG_DATA_HOME").map(PathBuf::from).filter(|p| p.is_absolute()) {
            Some(base) => base.join("FormCAD"),
            None => home().join(".local").join("share").join("FormCAD"),
        }
    };
    let absolute = if folder.is_absolute() { folder } else { std::env::current_dir().unwrap_or_default().join(folder) };
    std::fs::canonicalize(&absolute).unwrap_or(absolute)
}

fn single_instance() -> tauri::plugin::TauriPlugin<tauri::Wry> {
    let plugin = tauri_plugin_single_instance::Builder::<tauri::Wry>::new().callback(|app, args, cwd| {
        open_paths(app, paths_from_args(&args, Some(&cwd)));
        show_main_window(app);
    });
    #[cfg(target_os = "linux")]
    let plugin = {
        let hash = data_folder().to_string_lossy().bytes().fold(0xcbf29ce484222325u64, |h, b| (h ^ u64::from(b)).wrapping_mul(0x100000001b3));
        plugin.dbus_id(format!("ai.nodemode.formcad.d{hash:016x}"))
    };
    plugin.build()
}

fn main() {
    reveal::mark_launch();
    #[cfg(windows)]
    portable_web_view_data();
    let builder = tauri::Builder::default();
    #[cfg(target_os = "macos")]
    let builder = builder.on_web_content_process_terminate(window_state::on_renderer_stopped);
    let app = builder
        .plugin(single_instance())
        .manage(OpenQueue(Mutex::new(Opens::default())))
        .manage(ExitGate(AtomicBool::new(false)))
        .manage(window_state::Memory::default())
        .on_window_event(|window, event| {
            window_state::track(window, event);
            if window.label() == "main"
                && matches!(event, WindowEvent::Resized(_) | WindowEvent::Focused(_) | WindowEvent::ThemeChanged(_) | WindowEvent::ScaleFactorChanged { .. })
            {
                traffic_lights::place(window);
            }
            if let WindowEvent::CloseRequested { api, .. } = event {
                if window.label() == "main" && ask_page_to_quit(window.app_handle()) {
                    api.prevent_close();
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            take_pending_opens,
            confirm_exit,
            traffic_lights::set_window_title,
            reveal::app_ready,
            text_edit::text_edit
        ])
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(Backend(Mutex::new(None)))
        .setup(|app| {
            let handle = app.handle().clone();
            reveal::round_splash(&handle);
            let launch_args: Vec<String> = std::env::args().collect();
            open_paths(&handle, paths_from_args(&launch_args, None));
            let engine = match (packaged::engine_folder(), packaged::dev_backend()) {
                (Some(program), _) => app.shell().command(program),
                (None, Some((python, script))) => app.shell().command(python).args([script]),
                (None, None) => {
                    close_splash(&handle);
                    handle
                        .dialog()
                        .message("The FormCAD engine is missing. Reinstall the app.")
                        .title("FormCAD")
                        .blocking_show();
                    handle.exit(1);
                    return Ok(());
                }
            };
            let mut engine = engine
                .env("FORMCAD_PORT", "0")
                .env("FORMCAD_DESKTOP", "1")
                .env("FORMCAD_WINDOW_KEY_STDOUT", "1")
                .env("FORMCAD_SHELL_PID", std::process::id().to_string());
            if let Some(dir) = user_data_dir_arg(&launch_args) {
                engine = engine.env("FORMCAD_DATA_DIR", dir);
            }
            if launch_args.iter().any(|a| a == "--portable") {
                engine = engine.env("FORMCAD_PORTABLE", "1");
            }
            let (mut rx, child) = match engine.spawn() {
                Ok(pair) => pair,
                Err(_) => {
                    close_splash(&handle);
                    handle
                        .dialog()
                        .message("The FormCAD engine failed to start. Please relaunch the app.")
                        .title("FormCAD")
                        .blocking_show();
                    handle.exit(1);
                    return Ok(());
                }
            };
            #[cfg(windows)]
            win_job::hold(child.pid());
            *app.state::<Backend>().0.lock().unwrap() = Some(child);

            tauri::async_runtime::spawn(async move {
                let pattern = regex::Regex::new(r"http://127\.0\.0\.1:(\d+)").unwrap();
                let key_pattern = regex::Regex::new(r"formcad-window-key: ([A-Za-z0-9_-]{32,})").unwrap();
                let mut port: Option<u16> = None;
                let mut key: Option<String> = None;
                while let Some(event) = rx.recv().await {
                    let text = match event {
                        CommandEvent::Stdout(bytes) | CommandEvent::Stderr(bytes) => String::from_utf8_lossy(&bytes).into_owned(),
                        CommandEvent::Terminated(_) => break,
                        _ => continue,
                    };
                    if key.is_none() {
                        key = key_pattern.captures(&text).map(|c| c[1].to_string());
                    }
                    if let Some(found) = pattern.captures(&text).and_then(|c| c[1].parse::<u16>().ok()) {
                        port = Some(found);
                        break;
                    }
                }
                match port {
                    Some(port) => {
                        let url = format!("http://127.0.0.1:{port}");
                        let place = window_state::load(&handle);
                        let (width, height) = if place.width > 0.0 {
                            (place.width, place.height)
                        } else {
                            handle
                                .primary_monitor()
                                .ok()
                                .flatten()
                                .map(|monitor| {
                                    let logical = monitor.size().to_logical::<f64>(monitor.scale_factor());
                                    (logical.width * SCREEN_FRACTION, logical.height * SCREEN_FRACTION)
                                })
                                .unwrap_or(FALLBACK_SIZE)
                        };
                        let builder = WebviewWindowBuilder::new(&handle, "main", WebviewUrl::External(url.parse().unwrap()))
                            .title("FormCAD")
                            .visible(reveal::BUILD_VISIBLE)
                            .background_color(reveal::BACKGROUND)
                            .inner_size(width, height)
                            .min_inner_size(MIN_SIZE.0, MIN_SIZE.1)
                            .disable_drag_drop_handler()
                            .initialization_script(match &key {
                                Some(value) => format!("if (window.location.origin === {url:?}) {{ window.__FORMCAD_TOKEN = {value:?}; }}"),
                                None => String::new(),
                            })
                            .on_navigation({
                                let handle = handle.clone();
                                let home = url.clone();
                                move |target| match window_state::shell_choice(target) {
                                    Some(choice) => {
                                        renderer_choice(&handle, choice);
                                        false
                                    }
                                    None => stays_home(target, &home),
                                }
                            });
                        let builder = if place.width > 0.0 {
                            builder.position(place.x, place.y)
                        } else {
                            builder.center()
                        };
                        #[cfg(target_os = "macos")]
                        let builder = builder.title_bar_style(tauri::TitleBarStyle::Overlay).hidden_title(true);
                        let builder = builder.on_page_load(|window, payload| {
                            if matches!(payload.event(), tauri::webview::PageLoadEvent::Finished) {
                                traffic_lights::place(&window.as_ref().window());
                            }
                        });
                        if let Ok(window) = builder.build() {
                            reveal::conceal(&window);
                            traffic_lights::place(&window.as_ref().window());
                            window_state::restore(&window, &place);
                        } else {
                            close_splash(&handle);
                        }
                    }
                    None => {
                        close_splash(&handle);
                        let _ = handle
                            .dialog()
                            .message("The FormCAD engine failed to start. Please relaunch the app.")
                            .title("FormCAD")
                            .blocking_show();
                        kill_backend(&handle);
                        handle.exit(1);
                    }
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building the FormCAD app");

    app.run(|handle, event| match event {
        RunEvent::Exit => {
            window_state::flush(handle);
            kill_backend(handle);
        }
        RunEvent::ExitRequested { api, .. } => {
            if ask_page_to_quit(handle) {
                api.prevent_exit();
            }
        }
        #[cfg(target_os = "macos")]
        RunEvent::Opened { urls } => {
            let paths = urls
                .iter()
                .filter_map(|url| url.to_file_path().ok())
                .map(|path| path.to_string_lossy().into_owned())
                .collect();
            open_paths(handle, paths);
            show_main_window(handle);
        }
        _ => {}
    });
}
