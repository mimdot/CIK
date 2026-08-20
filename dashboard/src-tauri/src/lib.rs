// Astra desktop shell.
//
// The packaged app embeds a FastAPI "astra-api" sidecar (a PyInstaller onefile)
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
// bundle ships it as `astra-api.exe`; everywhere else plain `astra-api`.
#[cfg(target_os = "windows")]
const SIDECAR_NAME: &str = "astra-api.exe";
#[cfg(not(target_os = "windows"))]
const SIDECAR_NAME: &str = "astra-api";

/// The single shared entry code. It is fixed at 1819, not user-definable:
/// the desktop app is a local, single-user tool and this code is a front door,
/// never a security boundary. Anyone can read it out of this binary with
/// `strings`; that is understood and accepted.
const ACCESS_CODE: &str = "1819";

/// Windows: the job object the sidecar is confined to, as a raw handle value.
///
/// A PyInstaller onefile is TWO processes here. The bootloader unpacks the
/// bundle into `%TEMP%\_MEIxxxxxx` and then launches the real application as
/// its own child; `Child` refers only to the bootloader. `Child::kill()` is
/// `TerminateProcess`, which ends that parent and leaves the child running —
/// verified, not theorised: after killing the parent, the orphan was still
/// answering `/health` an hour later, still holding port 8000, the SQLite
/// database, and 389 MB of extracted files.
///
/// Every launch therefore left another live backend behind. The next start
/// found 8000 busy, picked a random port, and added one more. Worse, it
/// silently defeated `sweep_stale_extractions`, whose whole design is to
/// delete only directories nobody has open — and somebody always did.
///
/// A job object fixes it at the OS level: processes started by a member of a
/// job join that job automatically, and `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`
/// makes Windows terminate every member when the last handle to the job goes
/// away. That covers the ordinary exit AND the case no handler can: Astra
/// being force-quit, since closing the handle is something the kernel does for
/// us when the process dies.
#[cfg(windows)]
static SIDECAR_JOB: Mutex<isize> = Mutex::new(0);

static SIDECAR_CHILD: Mutex<Option<Child>> = Mutex::new(None);
/// The sidecar pid, readable from a signal handler (which must not take a lock).
#[cfg(unix)]
static SIDECAR_PID: std::sync::atomic::AtomicI32 = std::sync::atomic::AtomicI32::new(0);
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

/// Put a freshly spawned process, and everything it goes on to start, into a
/// kill-on-close job object.
///
/// Best-effort by design: if any step fails the app still works, it just falls
/// back to the old single-process kill. Losing the backend is not worth a
/// failed launch.
#[cfg(windows)]
fn confine_to_job(child: &Child) {
    use std::os::windows::io::AsRawHandle;

    use windows_sys::Win32::Foundation::{CloseHandle, HANDLE};
    use windows_sys::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
        SetInformationJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };

    // SAFETY: all four calls are plain Win32 FFI over locally owned arguments.
    // On every failure path the handle is closed before returning; on success
    // it is stored in SIDECAR_JOB and closed only by kill_sidecar. Closing a
    // job that has no members yet terminates nothing.
    unsafe {
        let job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
        if job.is_null() {
            log::warn!("could not create a job object; the sidecar's child process \
                        will have to be killed by hand");
            return;
        }

        let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        // addr_of!, not `&raw const`: the latter needs Rust 1.82 and this
        // crate declares rust-version = "1.77.2".
        let ok = SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            std::ptr::addr_of!(info).cast(),
            std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
        );
        if ok == 0 {
            log::warn!("could not set kill-on-close on the job object");
            CloseHandle(job);
            return;
        }

        // Assigned immediately after spawn, and that timing matters: only
        // processes started AFTER this call inherit the job. The bootloader
        // spends seconds unpacking ~150 MB before it launches anything, so the
        // window is comfortable, but it is not infinite.
        if AssignProcessToJobObject(job, child.as_raw_handle() as HANDLE) == 0 {
            log::warn!("could not assign the sidecar to the job object");
            CloseHandle(job);
            return;
        }

        *SIDECAR_JOB.lock().unwrap_or_else(|p| p.into_inner()) = job as isize;
    }
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

/// The app-data identity before the Astra rename. Tauri derives the app-data
/// directory name from the bundle identifier, so changing the identifier to
/// `com.astra.app` would otherwise have stranded every existing install's
/// account, database and saved items in a directory the app no longer reads.
const LEGACY_APP_DIR: &str = "com.careerintelligence.kit";
const LEGACY_DB_NAME: &str = "phd_data.db";

/// Rename `from` to `to`, but only when `from` exists and `to` does not.
///
/// Returns true when a rename actually happened, so the caller can log the one
/// launch that migrates rather than every launch afterwards.
fn rename_if_absent(from: &std::path::Path, to: &std::path::Path) -> bool {
    if !from.exists() || to.exists() {
        return false;
    }
    match std::fs::rename(from, to) {
        Ok(()) => true,
        Err(e) => {
            log::error!("could not move {} to {}: {e}", from.display(), to.display());
            false
        }
    }
}

/// Carry a pre-Astra app-data directory over to the current one, once.
///
/// Called from `setup` before the sidecar thread starts, so the backend only
/// ever opens the migrated database. Nothing is deleted — everything is
/// *renamed*, so a failure leaves the old data intact and recoverable by hand.
/// Each step is skipped when its target already exists, making a normal launch
/// a handful of `exists()` calls.
fn migrate_legacy_app_data(app: &tauri::AppHandle) {
    let Ok(new_dir) = app.path().app_data_dir() else {
        return;
    };
    let Some(legacy_dir) = new_dir.parent().map(|p| p.join(LEGACY_APP_DIR)) else {
        return;
    };
    // Tauri v2 uses the identifier verbatim on every platform, so an identical
    // path means the identifier was never actually renamed. Nothing to do.
    if legacy_dir == new_dir {
        return;
    }

    // The whole directory when the new one has not been created yet. If a
    // launch already created an empty new directory, fall through and move the
    // database out of the old one instead, so data is never left behind.
    if rename_if_absent(&legacy_dir, &new_dir) {
        log::info!("migrated app data from {} to {}", legacy_dir.display(), new_dir.display());
    } else if legacy_dir.join(LEGACY_DB_NAME).exists() && !new_dir.join("astra.db").exists() {
        let _ = std::fs::create_dir_all(&new_dir);
        for suffix in ["", "-wal", "-shm"] {
            rename_if_absent(
                &legacy_dir.join(format!("{LEGACY_DB_NAME}{suffix}")),
                &new_dir.join(format!("astra.db{suffix}")),
            );
        }
        log::info!("migrated database out of {}", legacy_dir.display());
    }

    // The database keeps its own name inside whichever directory it now sits
    // in. SQLite's write-ahead log and shared-memory files must travel with
    // it, or SQLite treats a stale -wal as belonging to a different database.
    for suffix in ["", "-wal", "-shm"] {
        rename_if_absent(
            &new_dir.join(format!("{LEGACY_DB_NAME}{suffix}")),
            &new_dir.join(format!("astra.db{suffix}")),
        );
    }

    // Exported run artefacts. Regenerated on the next run, but renaming them
    // keeps the folder from showing two products' worth of filenames.
    for ext in ["csv", "html", "json"] {
        rename_if_absent(
            &new_dir.join(format!("phd_positions.{ext}")),
            &new_dir.join(format!("astra_positions.{ext}")),
        );
    }
}

/// Start the FastAPI sidecar against the app-data SQLite database.
fn spawn_sidecar(app: &tauri::AppHandle) -> Result<u16, String> {
    let app_data = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("cannot resolve app data dir: {e}"))?;
    std::fs::create_dir_all(&app_data).map_err(|e| format!("cannot create app data dir: {e}"))?;

    let db_path = app_data.join("astra.db");
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
        .env("ASTRA_SECRET_KEY", random_hex(32))
        .env("ASTRA_INVITE_REQUIRED", "0")
        // The shared entry code is fixed at 1819, not read from the
        // environment, so no environment setting can change what a user must
        // type to get in.
        .env("ASTRA_ACCESS_CODE", ACCESS_CODE)
        .env("ASTRA_COOKIE_SECURE", "0")
        .env("ASTRA_SCHEDULER_ENABLED", "0")
        // CV reading is the only feature that can reach an AI provider, and it
        // is off in the desktop build so nobody spends tokens on it yet. The
        // code is all still there: set CV_PARSING_ENABLED=1 in the environment
        // to bring it back, no rebuild needed.
        .env(
            "CV_PARSING_ENABLED",
            std::env::var("CV_PARSING_ENABLED").unwrap_or_else(|_| "0".into()),
        )
        // The other AI spender: cover letters, application emails and CV
        // suggestions, reachable from every opportunity card. Off for the same
        // reason and by the same switch style.
        .env(
            "ASSISTANT_ENABLED",
            std::env::var("ASSISTANT_ENABLED").unwrap_or_else(|_| "0".into()),
        )
        .env("ASTRA_JSON_LOGS", "0")
        .env("CORS_ORIGINS", CORS)
        .env("ASTRA_API_HOST", "127.0.0.1")
        .env("ASTRA_API_PORT", &port_str)
        .env("ASTRA_VERSION", env!("CARGO_PKG_VERSION"))
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

    // The sidecar is a console-subsystem binary (astra-api.spec sets
    // console=True so uvicorn's stdio can be redirected into api.log). On
    // Windows that means spawning it pops a black console window next to the
    // app and leaves it there for the session. main.rs already hides the
    // shell's own console via `windows_subsystem`, but that says nothing about
    // a child.
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    // Forward a proxy if the user set one (e.g. V2RayN SOCKS for restricted
    // networks) — the packaged sidecar has no config.yaml on its CWD.
    if let Ok(proxy) = std::env::var("ASTRA_PROXY") {
        cmd.env("ASTRA_PROXY", proxy);
    }

    // Have the KERNEL kill the sidecar when this process dies, whatever the
    // reason. kill_sidecar() only runs from RunEvent::Exit, which never fires
    // on SIGKILL, a panic, or the OOM killer — and an orphan there is not a
    // tidy-up detail: it keeps the port and the SQLite file, so the NEXT launch
    // picks a different port and two backends share one database. PDEATHSIG is
    // the Linux counterpart of the KILL_ON_JOB_CLOSE job object Windows uses.
    //
    // The signal is delivered when the parent THREAD exits, not the process.
    // That is fine here: the sidecar is spawned from boot_and_watch's thread,
    // which parks for the life of a healthy app, and its only early return is
    // the give-up path — where killing an unreachable backend is what we want.
    #[cfg(target_os = "linux")]
    unsafe {
        use std::os::unix::process::CommandExt;
        cmd.pre_exec(|| {
            libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGTERM);
            Ok(())
        });
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

    // Before anything else touches the child: the PyInstaller bootloader is
    // about to start a second process, and that one is the real backend.
    #[cfg(windows)]
    confine_to_job(&child);
    // Record the pid in a plain atomic as well as the Mutex. A signal handler
    // may not lock a Mutex — that is a deadlock waiting for the wrong moment —
    // so the handler reads this instead.
    #[cfg(unix)]
    SIDECAR_PID.store(child.id() as i32, std::sync::atomic::Ordering::SeqCst);

    let mut guard = SIDECAR_CHILD
        .lock()
        .unwrap_or_else(|p| p.into_inner());
    *guard = Some(child);
    Ok(port)
}

/// Stop the sidecar, giving it the chance to clean up after itself.
///
/// SIGTERM first, SIGKILL only as a fallback. This is not politeness — the
/// sidecar is a PyInstaller onefile, and the bootloader unpacks ~389 MB into
/// `/tmp/_MEIxxxxxx` on every launch. It removes that directory when it is
/// allowed to shut down, and cannot when it is SIGKILLed.
///
/// `Child::kill()` is SIGKILL on Unix, so the previous version leaked a full
/// extraction on EVERY exit. On most Linux systems /tmp is a RAM-backed tmpfs,
/// so those leaks are RAM: 24 of them had accumulated here, filling a 7.5 GB
/// tmpfs completely and making every subsequent launch die with
/// "Failed to extract … decompression resulted in return code -1".
fn kill_sidecar() {
    // Windows first, and unconditionally: the job holds the REAL backend (the
    // bootloader's child), so terminating it is the part that actually stops
    // the server. Doing it before the Child handling below means the orphan is
    // gone even if `take()` finds nothing.
    #[cfg(windows)]
    {
        use windows_sys::Win32::Foundation::{CloseHandle, HANDLE};
        use windows_sys::Win32::System::JobObjects::TerminateJobObject;

        let mut guard = SIDECAR_JOB.lock().unwrap_or_else(|p| p.into_inner());
        let job = *guard;
        if job != 0 {
            *guard = 0;
            // SAFETY: `job` is the handle stored by confine_to_job and is
            // cleared here, so it is terminated and closed exactly once.
            unsafe {
                TerminateJobObject(job as HANDLE, 0);
                CloseHandle(job as HANDLE);
            }
        }
    }

    let Some(mut child) = SIDECAR_CHILD
        .lock()
        .unwrap_or_else(|p| p.into_inner())
        .take()
    else {
        return;
    };

    #[cfg(unix)]
    {
        // SAFETY: `child.id()` is this process's own child; the worst case for
        // a stale pid is ESRCH, which we ignore.
        unsafe { libc::kill(child.id() as libc::pid_t, libc::SIGTERM) };
        // Wait up to 2s for the bootloader to unlink its directory.
        for _ in 0..40 {
            if matches!(child.try_wait(), Ok(Some(_))) {
                return;
            }
            std::thread::sleep(Duration::from_millis(50));
        }
    }

    let _ = child.kill();
    let _ = child.wait();
}

/// Delete PyInstaller extraction directories that no live process is using.
///
/// The SIGTERM path above stops the routine leak, but nothing can clean up
/// after the app itself is killed (a crash, a force-quit, the OOM killer). So
/// sweep once at startup, before spawning: any `_MEI*` directory not mapped by
/// a running process belonged to a run that is already over.
#[cfg(target_os = "linux")]
fn sweep_stale_extractions() {
    use std::collections::HashSet;

    // Every _MEI path currently mapped by any process. Reading another user's
    // maps is denied, which just means we skip it — we only ever delete
    // directories we can prove nobody has open.
    let mut live: HashSet<String> = HashSet::new();
    if let Ok(procs) = std::fs::read_dir("/proc") {
        for entry in procs.flatten() {
            let maps = entry.path().join("maps");
            let Ok(text) = std::fs::read_to_string(&maps) else {
                continue;
            };
            for line in text.lines() {
                if let Some(idx) = line.find("/tmp/_MEI") {
                    let rest = &line[idx..];
                    let end = rest[5..]
                        .find('/')
                        .map(|i| i + 5)
                        .unwrap_or(rest.len());
                    live.insert(rest[..end].to_string());
                }
            }
        }
    }

    let Ok(entries) = std::fs::read_dir("/tmp") else {
        return;
    };
    let mut freed = 0u64;
    for entry in entries.flatten() {
        let path = entry.path();
        let name = entry.file_name();
        let name = name.to_string_lossy();
        if !name.starts_with("_MEI") || !path.is_dir() {
            continue;
        }
        if live.contains(path.to_string_lossy().as_ref()) {
            continue;
        }
        if std::fs::remove_dir_all(&path).is_ok() {
            freed += 1;
        }
    }
    if freed > 0 {
        log::info!("swept {freed} stale PyInstaller extraction dir(s) from /tmp");
    }
}

/// The Windows half of the same problem, and here it is the *only* half.
///
/// `kill_sidecar` sends SIGTERM on Unix so the PyInstaller bootloader can
/// unlink its own extraction directory. Windows has no SIGTERM: `Child::kill`
/// is `TerminateProcess`, which gives the child no chance to run anything. So
/// on Windows the ~389 MB `%TEMP%\_MEIxxxxxx` directory is left behind on
/// EVERY exit, not just after a crash — and unlike Linux's tmpfs it is on
/// disk, so nothing reclaims it at reboot either. A few weeks of daily use is
/// several gigabytes of C: drive.
///
/// Deleting straight away would be reckless: a second Astra window, or any
/// other PyInstaller app on the machine, has a live `_MEI` directory in the
/// same place, and `remove_dir_all` would delete whatever files were not
/// currently open before failing partway through — corrupting a running app.
///
/// So: rename first. Windows refuses to rename a directory that has open
/// handles beneath it, which makes the rename a lock test that costs nothing
/// and cannot half-succeed. Only a directory we managed to move out of the
/// way is one nobody is using, and only that one is deleted.
#[cfg(target_os = "windows")]
fn sweep_stale_extractions() {
    let tmp = std::env::temp_dir();
    let Ok(entries) = std::fs::read_dir(&tmp) else {
        return;
    };
    let mut freed = 0u64;
    for (n, entry) in entries.flatten().enumerate() {
        let path = entry.path();
        let name = entry.file_name();
        let name = name.to_string_lossy();
        if !name.starts_with("_MEI") || !path.is_dir() {
            continue;
        }
        // A distinctive staging name: if this process dies between the rename
        // and the delete, the leftover is obviously ours and the next run
        // sweeps it (it still starts with _MEI).
        let staged = tmp.join(format!("_MEI-astra-sweep-{}-{n}", std::process::id()));
        if std::fs::rename(&path, &staged).is_err() {
            continue; // in use by a live process — leave it alone
        }
        if std::fs::remove_dir_all(&staged).is_ok() {
            freed += 1;
        }
    }
    if freed > 0 {
        log::info!("swept {freed} stale PyInstaller extraction dir(s) from %TEMP%");
    }
}

#[cfg(not(any(target_os = "linux", target_os = "windows")))]
fn sweep_stale_extractions() {}

/// Push the current backend state into a page.
///
/// Called on EVERY page load, not once at startup: the old code injected
/// `window.__ASTRA_API_BASE__` a single time during setup, and any navigation
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
    // `__ASTRA_DESKTOP__` marks the webview for the frontend, which must know it
    // is not in a browser: a plain <a href> to an external site and the
    // blob-download trick both do nothing here, so those paths have to go
    // through the Tauri plugins instead. Set on every page load and never
    // cleared, because it is a fact about the host, not about the backend.
    let head = "window.__ASTRA_DESKTOP__=true;";
    match port {
        Some(p) => format!(
            "{head}window.__ASTRA_API_BASE__='http://127.0.0.1:{p}';\
             window.__ASTRA_API_READY__=true;window.__ASTRA_API_ERROR__=null;"
        ),
        // Clear the base as well as flagging not-ready. The sidecar is
        // restarted on a FRESHLY PICKED port, so a base left over from the
        // previous one points at a port nobody is listening on — and every
        // request made during the restart fails as "Cannot reach the API
        // server" while the shell is busy bringing the backend back. Undefined
        // is the honest answer here: not ready, and no address to try.
        None => format!(
            "{head}window.__ASTRA_API_BASE__=undefined;\
             window.__ASTRA_API_READY__=false;window.__ASTRA_API_ERROR__={};",
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
/// Kill the sidecar from a signal handler, then die the way we were asked to.
///
/// Only async-signal-safe work happens here: an atomic load and kill(2).
/// kill_sidecar() takes a Mutex and must never be called from this context.
/// Restoring the default disposition and re-raising keeps the exit status a
/// shell or init sees honest — the process still dies *of the signal*.
#[cfg(unix)]
extern "C" fn on_fatal_signal(sig: libc::c_int) {
    let pid = SIDECAR_PID.load(std::sync::atomic::Ordering::SeqCst);
    if pid > 0 {
        // SAFETY: our own child; a stale pid yields ESRCH, which we ignore.
        unsafe { libc::kill(pid, libc::SIGTERM) };
    }
    unsafe {
        libc::signal(sig, libc::SIG_DFL);
        libc::raise(sig);
    }
}

/// Catch the terminal-shaped exits RunEvent::Exit never sees.
///
/// The app is normally started from a terminal by run.sh, so Ctrl+C (SIGINT),
/// a closed terminal (SIGHUP) and `kill` (SIGTERM) are ordinary ways to stop
/// it — and none of them fire Tauri's Exit event. Without this each one leaked
/// a backend holding port 8000.
#[cfg(unix)]
fn install_signal_handlers() {
    for sig in [libc::SIGINT, libc::SIGTERM, libc::SIGHUP] {
        // SAFETY: installing a handler that is itself async-signal-safe. The
        // cast goes through a pointer rather than straight to the integer
        // sighandler_t, which is what `function_casts_as_integer` asks for.
        unsafe { libc::signal(sig, on_fatal_signal as *const () as libc::sighandler_t) };
    }
}

/// Quit Astra completely: stop the backend, then exit.
///
/// Exposed to the UI so there is a deliberate way out that does not depend on
/// the window manager's close button, and that never leaves the backend behind.
/// Ordering matters — the sidecar is stopped BEFORE app.exit(), because exit
/// tears down the runtime that would otherwise have run kill_sidecar for us.
#[tauri::command]
fn quit_app(app: tauri::AppHandle) {
    kill_sidecar();
    app.exit(0);
}

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
        "astra://api-state",
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
                log::info!("astra-api sidecar healthy on 127.0.0.1:{port}");
                *API_PORT.lock().unwrap_or_else(|p| p.into_inner()) = Some(port);
                publish_state(&app);
            }
            Err(err) => {
                log::error!("astra-api sidecar unavailable: {err}");
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
                log::warn!("astra-api sidecar exited ({status}) — restarting");
                break;
            }
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // A system-wide proxy (common on restricted networks) must never swallow
    // the loopback traffic between this app's webview and its own sidecar —
    // that is exactly how the UI reports "Cannot reach the API server" while
    // the backend is healthy. The sidecar gets the same bypass in
    // spawn_sidecar(); set it for THIS process too so the webview (which
    // inherits this process's env) and any helper it spawns skip the proxy
    // for localhost.
    let no_proxy = "localhost,127.0.0.1,127.0.0.0/8,::1,0.0.0.0";
    std::env::set_var("NO_PROXY", no_proxy);
    std::env::set_var("no_proxy", no_proxy);

    // ...and on Linux those variables do not reach the part that matters.
    //
    // WebKitGTK does not read NO_PROXY. It asks GLib's GProxyResolver, which on
    // a GNOME desktop is backed by GSettings (org.gnome.system.proxy) — so the
    // bypass above covers the sidecar and every helper we spawn, and misses the
    // webview itself, the one client that has to reach 127.0.0.1.
    //
    // That is not hypothetical. With the desktop set to a manual proxy, GNOME
    // stores the bypass list as
    //     ignore-hosts=['localhost,127.0.0.0/8,::1']
    // a ONE-element list holding a comma-joined string, where GLib wants three
    // separate entries. It matches no host at all, so the webview's fetch to
    // its own sidecar is handed to the proxy, the proxy refuses to route
    // loopback, fetch() throws, and the UI says "Cannot reach the API server"
    // while curl -- which honours NO_PROXY -- gets 200 from the same URL.
    // Diagnosed on a machine running a local V2Ray proxy: zero connections to
    // :8000 before this line, an established connection immediately after.
    //

    let app = tauri::Builder::default()
        // A webview cannot open a system browser or write a file by itself.
        // Without these two plugins every external link and every export in the
        // UI is a no-op that reports nothing — which is exactly how the app
        // behaved.
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![write_text_file, quit_app])
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
            // Reclaim anything a previous run could not clean up before we
            // add another 389 MB of our own.
            sweep_stale_extractions();
            // Ctrl+C / SIGHUP / SIGTERM never reach RunEvent::Exit.
            #[cfg(unix)]
            install_signal_handlers();
            // Before anything can open the database: carry over the app data
            // from the pre-Astra bundle identifier.
            migrate_legacy_app_data(app.handle());
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
