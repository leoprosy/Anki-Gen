use tauri::Manager;
use tauri_plugin_shell::ShellExt;
use std::time::Duration;
use std::thread;

const FLASK_URL: &str = "http://127.0.0.1:5000";

/// Wait for the Flask server to respond, with a timeout.
fn wait_for_server(url: &str, timeout: Duration) -> bool {
    let start = std::time::Instant::now();
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_millis(500))
        .build()
        .unwrap();

    while start.elapsed() < timeout {
        if let Ok(resp) = client.get(url).send() {
            if resp.status().is_success() || resp.status().is_redirection() {
                return true;
            }
        }
        thread::sleep(Duration::from_millis(200));
    }
    false
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            // Spawn the Flask sidecar
            let shell = app.shell();
            let sidecar = shell.sidecar("flask-server")
                .expect("failed to create sidecar command")
                .env("ANKI_ESH_SIDECAR", "1");

            let (_rx, _child) = sidecar
                .spawn()
                .expect("failed to spawn flask-server sidecar");

            // Wait for Flask to be ready in a background thread, then show the window
            let window = app.get_webview_window("main")
                .expect("failed to get main window");

            let url = FLASK_URL.to_string();
            thread::spawn(move || {
                if wait_for_server(&url, Duration::from_secs(15)) {
                    let _ = window.navigate(url.parse().unwrap());
                    // Short delay so the page starts rendering before we show
                    thread::sleep(Duration::from_millis(300));
                    let _ = window.show();
                } else {
                    eprintln!("Flask server did not start within 15 seconds");
                    let _ = window.show();
                }
            });

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running Ankigen");
}
