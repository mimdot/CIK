// Career Intelligence desktop shell.
//
// The packaged app embeds a FastAPI "cik-api" sidecar (a PyInstaller onefile)
// as a Tauri external binary. This module spawns it once at startup with the
// environment a desktop user needs (SQLite in the app-data dir, open
// registration, plain-HTTP cookies, Tauri CORS origins) and kills it on exit.
// No bash wrapper / openssl required, so it runs identically on Linux, macOS
// and Windows.

use std::fmt::Write; // random_hex writes hex into a String (fmt::Write, not io)
use std::io::{Read, Write as IoWrite};
use std::net::TcpStream;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{Emitter, Manager};

// Name of the bundled sidecar binary (externalBin basename). On Windows the
// bundle ships it as `cik-api.exe`; everywhere else plain `cik-api`.
#[cfg(target_os = "windows")]
const SIDECAR_NAME: &str = "cik-api.exe";
#[cfg(not(target_os = "windows"))]
const SIDECAR_NAME: &str = "cik-api";

/// The shared code the desktop build ships with, used only when the user has
/// not set `CIK_ACCESS_CODE` themselves. Anyone can read it out of this binary;
/// that is understood and accepted, because it gates nothing that matters.
const DEFAULT_ACCESS_CODE: &str = "1819";

static SIDECAR_CHILD: Mutex<Option<Child>> = Mutex::new(None);
/// Resolved once the sidecar answers /health. Until then the frontend must not
/// be told a base URL, because a call to a port nobody is listening on fails as
/// "Cannot reach the API server" and looks like a broken app.
static API_PORT: Mutex<Option<u16>> = Mutex::new(None);
/// Why the backend is unavailable, in words the user can act on.
static API_ERROR: Mutex<Option<String>> = Mutex::new(None);
static SIDECAR_LOG: Mutex<Option<PathBuf>> = Mutex::new(None);

/// How long to wait for the sidecar to come up. A PyInstaller onefile has to
/// unpack itself before uvicorn binds, which is seconds, not milliseconds.
const HEALTH_TIMEOUT: Duration = Duration::from_secs(90);

/// Ask the sidecar's /health endpoint directly over TCP.
///
/// Deliberately hand-rolled rather than pulling in an HTTP client: this is one
/// request to localhost, and the desktop bundle does not need another
/// dependency (or another TLS stack) to make it.
fn probe_health(port: u16) -> Result<(), String> {
    let addr = format!("127.0.0.1:{port}");
    let sock = addr
        .parse()
        .map_err(|e| format!("bad address {addr}: {e}"))?;
    let mut stream = TcpStream::connect_timeout(&sock, Duration::from_millis(800))
        .map_err(|e| format!("connect: {e}"))?;
    stream
        .set_read_timeout(Some(Duration::from_millis(2500)))
        .ok();
    stream
        .write_all(
            format!("GET /health HTTP/1.0\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n")
                .as_bytes(),
        )
        .map_err(|e| format!("write: {e}"))?;
    let mut body = String::new();
    stream
        .read_to_string(&mut body)
        .map_err(|e| format!("read: {e}"))?;
    if !body.starts_with("HTTP/1.") || !body.contains(" 200 ") {
        let first = body.lines().next().unwrap_or("(empty response)");
        return Err(format!("/health said {first}"));
    }
    Ok(())
}

/// Poll /health until it answers or we give up. Returns the reason on failure,
/// including whether the child process died (the common case: an import error
/// or a missing bundled data file, which uvicorn never gets far enough to log).
fn wait_for_health(port: u16) -> Result<(), String> {
    let deadline = Instant::now() + HEALTH_TIMEOUT;
    let mut last = String::from("not started");
    while Instant::now() < deadline {
        if let Some(status) = child_exit_status() {
            return Err(format!(
                "the backend process exited ({status}) before it was ready.\n\n{}",
                log_tail(40)
            ));
        }
        match probe_health(port) {
            Ok(()) => return Ok(()),
            Err(e) => last = e,
        }
        std::thread::sleep(Duration::from_millis(300));
    }
    Err(format!(
        "the backend did not answer http://127.0.0.1:{port}/health within {}s ({last}).\n\n{}",
        HEALTH_TIMEOUT.as_secs(),
        log_tail(40)
    ))
}

/// None while the child is still running; Some(status) once it has exited.
fn child_exit_status() -> Option<String> {
    let mut guard = SIDECAR_CHILD.lock().unwrap_or_else(|p| p.into_inner());
    match guard.as_mut() {
        Some(child) => match child.try_wait() {
            Ok(Some(status)) => Some(status.to_string()),
            _ => None,
        },
        None => Some("never spawned".into()),
    }
}

/// The tail of the sidecar's own log — the only place the real reason lives
/// when Python dies on import.
fn log_tail(lines: usize) -> String {
    let path = {
        let guard = SIDECAR_LOG.lock().unwrap_or_else(|p| p.into_inner());
        guard.clone()
    };
    let Some(path) = path else {
        return String::new();
    };
    match std::fs::read_to_string(&path) {
        Ok(text) => {
            let tail: Vec<&str> = text.lines().rev().take(lines).collect();
            let tail: Vec<&str> = tail.into_iter().rev().collect();
            format!("Backend log ({}):\n{}", path.display(), tail.join("\n"))
        }
        Err(e) => format!("Backend log at {} is unreadable: {e}", path.display()),
    }
}

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

/// Resolve the bundled sidecar binary path: next to the *running executable*,
/// which is where Tauri places `externalBin` on every platform (usr/bin for the
/// deb and AppImage, Contents/MacOS for .app, the install dir on Windows, and
/// target/<profile> under `tauri dev`).
///
/// Deliberately NOT `BaseDirectory::Executable`. That resolves to
/// `dirs::executable_dir()` — the *user's* XDG binary directory, which has
/// nothing to do with this app. On Linux it sent the shell hunting for the
/// sidecar in ~/.local/bin and reporting it missing while the real one sat
/// right next to the binary; on macOS and Windows that directory does not
/// exist at all, so the same call failed outright.
fn sidecar_path() -> Result<PathBuf, String> {
    let exe = std::env::current_exe()
        .map_err(|e| format!("cannot locate the running executable: {e}"))?;
    exe.parent()
        .map(|dir| dir.join(SIDECAR_NAME))
        .ok_or_else(|| format!("{} has no parent directory", exe.display()))
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

    let binary = sidecar_path()?;
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
        // The shared entry code. NOT a secret — it lives in this binary and
        // `strings` will find it in seconds, so it is a front door, never a
        // security boundary. Taken from the environment when the user sets one,
        // so the code can be changed without rebuilding the app.
        .env(
            "CIK_ACCESS_CODE",
            std::env::var("CIK_ACCESS_CODE").unwrap_or_else(|_| DEFAULT_ACCESS_CODE.into()),
        )
        .env("CIK_COOKIE_SECURE", "0")
        .env("CIK_SCHEDULER_ENABLED", "0")
        .env("CIK_JSON_LOGS", "0")
        .env("CORS_ORIGINS", CORS)
        .env("CIK_API_HOST", "127.0.0.1")
        .env("CIK_API_PORT", &port_str)
        .env("CIK_VERSION", env!("CARGO_PKG_VERSION"))
        .stdout(Stdio::from(log_file.try_clone().map_err(|e| e.to_string())?))
        .stderr(Stdio::from(log_file));

    // Localhost must never go through the proxy. Users on restricted networks
    // run a system-wide SOCKS/HTTP proxy (V2RayN and friends), and a proxy set
    // for *all* traffic swallows 127.0.0.1 too — which is one of the ways this
    // app reports "Cannot reach the API server" while the backend is running
    // perfectly. Both spellings: Python's urllib honours the lowercase one,
    // most other stacks the uppercase.
    const NO_PROXY: &str = "localhost,127.0.0.1,::1,0.0.0.0";
    cmd.env("NO_PROXY", NO_PROXY).env("no_proxy", NO_PROXY);

    // Forward a proxy if the user set one (e.g. V2RayN SOCKS for restricted
    // networks) — the packaged sidecar has no config.yaml on its CWD.
    if let Ok(proxy) = std::env::var("CIK_PROXY") {
        cmd.env("CIK_PROXY", proxy);
    }

    {
        let mut guard = SIDECAR_LOG.lock().unwrap_or_else(|p| p.into_inner());
        *guard = Some(log_path.clone());
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

/// Push the current backend state into a page.
///
/// Called on EVERY page load, not once at startup: the old code injected
/// `window.__CIK_API_BASE__` a single time during setup, and any navigation
/// after that threw the global away. The frontend then fell back to :8000 —
/// which is the wrong port whenever 8000 was busy and the shell picked another,
/// and answers nothing, which surfaces as "Cannot reach the API server".
fn state_js() -> String {
    let port = *API_PORT.lock().unwrap_or_else(|p| p.into_inner());
    let error = API_ERROR
        .lock()
        .unwrap_or_else(|p| p.into_inner())
        .clone()
        .unwrap_or_default();
    // `__CIK_DESKTOP__` marks the webview for the frontend, which must know it
    // is not in a browser: a plain <a href> to an external site and the
    // blob-download trick both do nothing here, so those paths have to go
    // through the Tauri plugins instead. Set on every page load and never
    // cleared, because it is a fact about the host, not about the backend.
    let head = "window.__CIK_DESKTOP__=true;";
    match port {
        Some(p) => format!(
            "{head}window.__CIK_API_BASE__='http://127.0.0.1:{p}';\
             window.__CIK_API_READY__=true;window.__CIK_API_ERROR__=null;"
        ),
        None => format!(
            "{head}window.__CIK_API_READY__=false;window.__CIK_API_ERROR__={};",
            serde_json::to_string(&error).unwrap_or_else(|_| "\"\"".into())
        ),
    }
}

/// Write a text file the user has just chosen in a native save dialog.
///
/// Deliberately a command of our own rather than `tauri-plugin-fs`: the only
/// path this app ever writes is one the user picked seconds earlier in the OS
/// dialog, and an fs-plugin scope broad enough to cover "wherever they chose"
/// is no narrower than this — it just spreads the decision across a config
/// file. Here the grant is visible in one place and the failure is reported.
#[tauri::command]
fn write_text_file(path: String, contents: String) -> Result<String, String> {
    let path = PathBuf::from(path);
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir)
            .map_err(|e| format!("cannot create {}: {e}", dir.display()))?;
    }
    std::fs::write(&path, contents)
        .map_err(|e| format!("cannot write {}: {e}", path.display()))?;
    Ok(path.display().to_string())
}

/// Broadcast the state to any page already loaded, and remember it for the next.
fn publish_state(app: &tauri::AppHandle) {
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.eval(&state_js());
    }
    let port = *API_PORT.lock().unwrap_or_else(|p| p.into_inner());
    let error = API_ERROR
        .lock()
        .unwrap_or_else(|p| p.into_inner())
        .clone()
        .unwrap_or_default();
    let _ = app.emit(
        "cik://api-state",
        serde_json::json!({
            "ready": port.is_some(),
            "base": port.map(|p| format!("http://127.0.0.1:{p}")),
            "error": if error.is_empty() { None } else { Some(error) },
        }),
    );
}

/// Start the sidecar and wait until it genuinely answers /health.
fn boot_and_watch(app: tauri::AppHandle) {
    loop {
        {
            let mut err = API_ERROR.lock().unwrap_or_else(|p| p.into_inner());
            *err = None;
            let mut port = API_PORT.lock().unwrap_or_else(|p| p.into_inner());
            *port = None;
        }
        publish_state(&app);

        let outcome = spawn_sidecar(&app).and_then(|port| {
            wait_for_health(port)?;
            Ok(port)
        });

        match outcome {
            Ok(port) => {
                log::info!("cik-api sidecar healthy on 127.0.0.1:{port}");
                *API_PORT.lock().unwrap_or_else(|p| p.into_inner()) = Some(port);
                publish_state(&app);
            }
            Err(err) => {
                log::error!("cik-api sidecar unavailable: {err}");
                *API_ERROR.lock().unwrap_or_else(|p| p.into_inner()) = Some(err);
                publish_state(&app);
                return; // a start failure is not something retrying fixes
            }
        }

        // Supervise: if the backend dies while the app is open, say so and
        // bring it back rather than leaving every page silently failing.
        loop {
            std::thread::sleep(Duration::from_secs(2));
            if let Some(status) = child_exit_status() {
                log::warn!("cik-api sidecar exited ({status}) — restarting");
                break;
            }
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        // A webview cannot open a system browser or write a file by itself.
        // Without these two plugins every external link and every export in the
        // UI is a no-op that reports nothing — which is exactly how the app
        // behaved.
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![write_text_file])
        // Every page load gets the current backend state, so a navigation can
        // never leave the frontend guessing at the port.
        .on_page_load(|webview, _payload| {
            let _ = webview.eval(&state_js());
        })
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }
            // Boot off the UI thread: the window paints immediately and shows
            // "starting the backend" instead of freezing for the seconds a
            // PyInstaller onefile needs to unpack.
            let handle = app.handle().clone();
            std::thread::spawn(move || boot_and_watch(handle));
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
