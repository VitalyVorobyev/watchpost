// Watchpost desktop shell.
//
// Deliberately thin. It supervises the Python host as a child process and points a window
// at the host's own /host layout — it does not reimplement any product logic, and the
// server remains fully usable without it. See ADR-0005.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use tauri::{Manager, WindowEvent};

const PORT: u16 = 8787;
const READY_TIMEOUT: Duration = Duration::from_secs(45);

/// Kills the server when the app exits, including on panic. Without this the host would
/// outlive the window and keep the camera open.
struct ServerGuard(Arc<Mutex<Option<Child>>>);

impl Drop for ServerGuard {
    fn drop(&mut self) {
        if let Ok(mut guard) = self.0.lock() {
            if let Some(mut child) = guard.take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    }
}

/// The repository root, as seen from the running binary.
///
/// In development the binary sits in `src-tauri/target/debug`; in a bundle it is inside
/// `Watchpost.app/Contents/MacOS`. Only the development layout can find the Python source,
/// which is why a bundled build still needs the packaging work deferred to Phase 2.
fn repo_root() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    for ancestor in exe.ancestors() {
        if ancestor.join("server/pyproject.toml").is_file() {
            return Some(ancestor.to_path_buf());
        }
    }
    None
}

fn spawn_server() -> std::io::Result<Child> {
    let root = repo_root().ok_or_else(|| {
        std::io::Error::new(
            std::io::ErrorKind::NotFound,
            "could not locate server/pyproject.toml relative to the executable",
        )
    })?;

    // `uv run` resolves the pinned interpreter and the locked dependencies, so the shell
    // does not need to know anything about the Python environment.
    let mut child = Command::new("uv")
        .args([
            "run",
            "watchpost",
            "serve",
            "--port",
            &PORT.to_string(),
            "--web",
        ])
        .arg(root.join("web/dist"))
        .current_dir(root.join("server"))
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()?;

    // Forward the server's output to this process's console so `cargo tauri dev` shows
    // camera and recording logs in one place.
    for stream in [
        child
            .stdout
            .take()
            .map(|s| Box::new(s) as Box<dyn std::io::Read + Send>),
        child
            .stderr
            .take()
            .map(|s| Box::new(s) as Box<dyn std::io::Read + Send>),
    ]
    .into_iter()
    .flatten()
    {
        thread::spawn(move || {
            for line in BufReader::new(stream).lines().map_while(Result::ok) {
                println!("[watchpost] {line}");
            }
        });
    }

    Ok(child)
}

/// The storage root the server keeps its token, config and certificates in.
fn storage_root() -> Option<PathBuf> {
    let home = std::env::var_os("HOME")?;
    Some(PathBuf::from(home).join("Library/Application Support/Watchpost"))
}

/// Whether the host is serving HTTPS, read from the same config.json the server reads.
///
/// A crude substring match rather than a JSON dependency: the shell needs exactly one
/// boolean out of this file, and the server remains the only writer.
fn tls_enabled() -> bool {
    storage_root()
        .and_then(|root| std::fs::read_to_string(root.join("config.json")).ok())
        .map(|text| {
            text.replace(char::is_whitespace, "")
                .contains("\"tls_enabled\":true")
        })
        .unwrap_or(false)
}

fn scheme() -> &'static str {
    if tls_enabled() {
        "https"
    } else {
        "http"
    }
}

/// The pairing token, read from the storage root the server writes it to.
///
/// The host screen is the one that *displays* the pairing QR, so it cannot acquire a token
/// by scanning one. The shell reads the same mode-0600 file the server created; it runs as
/// the same user on the same machine, so this grants it nothing it did not already have.
fn pairing_token() -> Option<String> {
    let path = storage_root()?.join("token");
    let token = std::fs::read_to_string(path).ok()?.trim().to_owned();
    (!token.is_empty()).then_some(token)
}

/// The host layout URL, carrying the token when one exists. Tokens come from Python's
/// `secrets.token_urlsafe`, which emits only `[A-Za-z0-9_-]`, so no percent-encoding is
/// needed. The client strips the query from the address bar once it has stored the token.
fn host_url() -> String {
    let base = format!("{}://127.0.0.1:{PORT}/host", scheme());
    match pairing_token() {
        Some(token) => format!("{base}?t={token}"),
        None => base,
    }
}

/// Poll `/healthz` until the host answers. The window stays hidden until then so the user
/// never sees a connection error that is really just startup.
fn wait_until_ready() -> bool {
    let deadline = Instant::now() + READY_TIMEOUT;
    while Instant::now() < deadline {
        let mut probe = Command::new("curl");
        probe.args(["-fsS", "-m", "2"]);
        // Verify against Watchpost's own CA rather than passing -k: the probe should fail
        // if the certificate is wrong, since that is exactly what would break the window.
        if let Some(ca) = storage_root().map(|root| root.join("tls/ca.crt")) {
            if tls_enabled() && ca.is_file() {
                probe.arg("--cacert").arg(ca);
            }
        }
        let ok = probe
            .arg(format!("{}://127.0.0.1:{PORT}/healthz", scheme()))
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .map(|status| status.success())
            .unwrap_or(false);
        if ok {
            return true;
        }
        thread::sleep(Duration::from_millis(400));
    }
    false
}

fn main() {
    let server = Arc::new(Mutex::new(None::<Child>));
    let guard = ServerGuard(Arc::clone(&server));

    match spawn_server() {
        Ok(child) => *server.lock().unwrap() = Some(child),
        Err(error) => eprintln!("[watchpost] could not start the server: {error}"),
    }

    let for_setup = Arc::clone(&server);
    let for_exit = Arc::clone(&server);

    tauri::Builder::default()
        .setup(move |app| {
            let window = app.get_webview_window("main").expect("main window");
            let has_server = for_setup.lock().unwrap().is_some();

            if !(has_server && wait_until_ready()) {
                eprintln!("[watchpost] host did not become ready in time");
                // Navigating anyway gives the user the client's own offline state, which
                // explains the situation better than a blank window would.
            }

            window.navigate(host_url().parse().expect("valid host url"))?;
            window.show()?;

            // The inverse of the Destroyed handler below. Without this, shutting the host
            // down from its own UI would leave a live window staring at a dead server.
            let watched = Arc::clone(&for_setup);
            let handle = app.handle().clone();
            thread::spawn(move || {
                loop {
                    thread::sleep(Duration::from_millis(500));
                    let exited = match watched.lock() {
                        Ok(mut guard) => match guard.as_mut() {
                            // try_wait reaps without blocking, so the lock is never held
                            // while the window-close path wants it.
                            Some(child) => matches!(child.try_wait(), Ok(Some(_)) | Err(_)),
                            None => break,
                        },
                        Err(_) => break,
                    };
                    if exited {
                        println!("[watchpost] the host exited; closing the window");
                        handle.exit(0);
                        break;
                    }
                }
            });
            Ok(())
        })
        .on_window_event(move |_window, event| {
            if let WindowEvent::Destroyed = event {
                if let Ok(mut child) = for_exit.lock() {
                    if let Some(mut process) = child.take() {
                        let _ = process.kill();
                        let _ = process.wait();
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("failed to run Watchpost");

    drop(guard);
}
