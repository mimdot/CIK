// Career Intelligence desktop shell.
//
// The packaged app embeds a FastAPI "cik-api" sidecar (a PyInstaller onefile)
// as a Tauri external binary. This module spawns it once at startup with the
// environment a desktop user needs (SQLite in the app-data dir, open
// registration, plain-HTTP cookies, Tauri CORS origins) and kills it on exit.
// No bash wrapper / openssl required, so it runs identically on Linux, macOS
// and Windows.

use std::fmt::Write; // random_hex writes hex into a String (fmt::Write, not io)
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

use tauri::Manager;

// Name of the bundled sidecar binary (externalBin basename). On Windows the
// bundle ships it as `cik-api.exe`; everywhere else plain `cik-api`.
#[cfg(target_os = "windows")]
const SIDECAR_NAME: &str = "cik-api.exe";
#[cfg(not(target_os = "windows"))]
const SIDECAR_NAME: &str = "cik-api";

static SIDECAR_CHILD: Mutex<Option<Child>> = Mutex::new(None);

/// Pick a port for the sidecar: prefer the conventional 8000, else let the OS
/// assign a free one — so a busy 8000 never leaves the app on a blank screen.
fn pick_port() -> u16 {
    use std::net::TcpListener;
    if TcpListener::bind(("127.0.0.1", 8000)).is_ok() {
        return 8000;
    }
    TcpListener::bind(("127.0.0.1", 0))
        .and_then(|l| l.local_addr())
        .map(|addr| addr.port())
        .unwrap_or(8000)
}

/// A small deterministic PRNG so the cookie-signing key doesn't need a C
/// dependency. The key only protects a local, single-user SQLite session.
fn random_hex(n: usize) -> String {
    use std::time::{SystemTime, UNIX_EPOCH};

    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    let mut seed = (nanos as u64) ^ (std::process::id() as u64).rotate_left(17)
        ^ 0x9e37_79b9_7f4a_7c15;
    let mut out = String::with_capacity(n * 2);
    for _ in 0..n {
        seed ^= seed << 13;
        seed ^= seed >> 7;
        seed ^= seed << 17;
        let _ = write!(out, "{:02x}", (seed & 0xff) as u8);
    }
    out
}

/// Resolve the bundled sidecar binary path. External binaries are placed next
/// to the main executable by Tauri on every platform (usr/bin for AppImage,
/// Contents/MacOS for .app, install dir on Windows).
fn sidecar_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    app.path()
        .resolve(SIDECAR_NAME, tauri::path::BaseDirectory::Executable)
        .map_err(|e| format!("cannot resolve sidecar path: {e}"))
}

/// Start the FastAPI sidecar against the app-data SQLite database.
fn spawn_sidecar(app: &tauri::AppHandle) -> Result<u16, String> {
    let app_data = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("cannot resolve app data dir: {e}"))?;
    std::fs::create_dir_all(&app_data).map_err(|e| format!("cannot create app data dir: {e}"))?;

    let db_path = app_data.join("phd_data.db");
    let log_path = app_data.join("api.log");

    let binary = sidecar_path(app)?;
    if !binary.exists() {
        return Err(format!(
            "sidecar binary not found at {} — rebuild the app so the API is bundled",
            binary.display()
        ));
    }

    // Stream API stdout/stderr to a rotating log in the app-data dir so
    // support issues can be diagnosed without a console (Windows release has
    // none).
    let log_file = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_path)
        .map_err(|e| format!("cannot open {}: {e}", log_path.display()))?;

    // Tauri webview origins per platform; http://localhost:3000 for web-dev.
    const CORS: &str = "http://tauri.localhost,tauri://localhost,http://localhost:3000";

    let port = pick_port();
    let port_str = port.to_string();

    let mut cmd = Command::new(&binary);
    cmd.current_dir(&app_data)
        .env("DATABASE_URL", format!("sqlite:///{}", db_path.display()))
        .env("CIK_SECRET_KEY", random_hex(32))
        .env("CIK_INVITE_REQUIRED", "0")
        .env("CIK_COOKIE_SECURE", "0")
        .env("CIK_SCHEDULER_ENABLED", "0")
        .env("CIK_JSON_LOGS", "0")
        .env("CORS_ORIGINS", CORS)
        .env("CIK_API_HOST", "127.0.0.1")
        .env("CIK_API_PORT", &port_str)
        .env("CIK_VERSION", env!("CARGO_PKG_VERSION"))
        .stdout(Stdio::from(log_file.try_clone().map_err(|e| e.to_string())?))
        .stderr(Stdio::from(log_file));

    // Forward a proxy if the user set one (e.g. V2RayN SOCKS for restricted
    // networks) — the packaged sidecar has no config.yaml on its CWD.
    if let Ok(proxy) = std::env::var("CIK_PROXY") {
        cmd.env("CIK_PROXY", proxy);
    }

    let child = cmd.spawn().map_err(|e| {
        format!(
            "failed to start sidecar {}: {e}",
            binary.display()
        )
    })?;

    let mut guard = SIDECAR_CHILD
        .lock()
        .unwrap_or_else(|p| p.into_inner());
    *guard = Some(child);
    Ok(port)
}

fn kill_sidecar() {
    if let Some(mut child) = SIDECAR_CHILD
        .lock()
        .unwrap_or_else(|p| p.into_inner())
        .take()
    {
        let _ = child.kill();
        let _ = child.wait();
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }
            match spawn_sidecar(app.handle()) {
                Ok(port) => {
                    log::info!("cik-api sidecar started on 127.0.0.1:{port}");
                    // Tell the static frontend which port to call — the shell
                    // may have picked a non-default one. The page also falls
                    // back to :8000 if this injection is missed.
                    if let Some(win) = app.get_webview_window("main") {
                        let js = format!(
                            "window.__CIK_API_BASE__ = 'http://127.0.0.1:{port}';"
                        );
                        let _ = win.eval(&js);
                    }
                }
                Err(err) => log::error!("{err}"),
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|_app_handle, event| {
        if let tauri::RunEvent::Exit = event {
            kill_sidecar();
        }
    });
}
