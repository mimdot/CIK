// Career Intelligence desktop shell.
//
// The packaged app embeds a FastAPI "cik-api" sidecar (a PyInstaller onefile)
// as a Tauri external binary. This module spawns it once at startup with the
// environment a desktop user needs (SQLite in the app-data dir, open
// registration, plain-HTTP cookies, Tauri CORS origins) and kills it on exit.
// No bash wrapper / openssl required, so it runs identically on Linux, macOS
// and Windows.

use std::io::Write;
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

const API_PORT: &str = "8000";

static SIDECAR_CHILD: Mutex<Option<Child>> = Mutex::new(None);

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
fn spawn_sidecar(app: &tauri::AppHandle) -> Result<(), String> {
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
        .env("CIK_API_PORT", API_PORT)
        .env("CIK_VERSION", env!("CARGO_PKG_VERSION"))
        .stdout(Stdio::from(log_file.try_clone().map_err(|e| e.to_string())?))
        .stderr(Stdio::from(log_file));

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
    Ok(())
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
                Ok(()) => log::info!("cik-api sidecar started on 127.0.0.1:{API_PORT}"),
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
