use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;
use tauri::{Manager, RunEvent};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

/// Utilisé seulement si le sidecar meurt sans jamais annoncer son port.
const FALLBACK_URL: &str = "http://127.0.0.1:5000";

#[tauri::command]
fn restart_app(app: tauri::AppHandle) {
    // request_restart emits RunEvent::Exit so the sidecar is stopped first.
    app.request_restart();
}

/// Extrait l'URL que `launcher.py` annonce sur sa sortie standard.
///
/// Le port n'est pas fixe : `find_free_port` prend le premier libre à partir de
/// 5000. Le supposer revient à afficher le serveur d'une *autre* instance encore
/// vivante — c'était le bug où l'application ouvrait une version précédente
/// d'elle-même après une mise à jour.
fn parse_server_url(line: &str) -> Option<String> {
    let start = line.find("http://127.0.0.1:")?;
    let url: String = line[start..]
        .chars()
        .take_while(|c| !c.is_whitespace() && *c != '"')
        .collect();

    // Une URL sans port exploitable ne nous apprend rien.
    let port = url.rsplit(':').next()?;
    if port.is_empty() || !port.chars().all(|c| c.is_ascii_digit()) {
        return None;
    }
    Some(url)
}

/// Attend que le serveur réponde, avec un plafond de temps.
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

/// Attend la disponibilité du serveur puis affiche la fenêtre dessus.
fn show_window_on(window: tauri::WebviewWindow, url: String) {
    thread::spawn(move || {
        if !wait_for_server(&url, Duration::from_secs(15)) {
            eprintln!("Flask server did not answer within 15 seconds at {url}");
        }
        match url.parse() {
            Ok(parsed) => {
                let _ = window.navigate(parsed);
                // Court délai pour que la page commence à peindre avant l'affichage.
                thread::sleep(Duration::from_millis(300));
            }
            Err(e) => eprintln!("unusable server URL {url}: {e}"),
        }
        let _ = window.show();
    });
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let sidecar_child: Arc<Mutex<Option<CommandChild>>> = Arc::new(Mutex::new(None));
    let child_for_setup = Arc::clone(&sidecar_child);
    let child_for_exit = Arc::clone(&sidecar_child);

    let app = tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![restart_app])
        .plugin(tauri_plugin_shell::init())
        .setup(move |app| {
            let shell = app.shell();
            let sidecar = shell
                .sidecar("flask-server")
                .expect("failed to create sidecar command")
                .env("ANKI_ESH_SIDECAR", "1");

            let (mut rx, child) = sidecar
                .spawn()
                .expect("failed to spawn flask-server sidecar");

            // Conservé pour pouvoir l'arrêter à la fermeture de l'application.
            *child_for_setup.lock().unwrap() = Some(child);

            let window = app
                .get_webview_window("main")
                .expect("failed to get main window");

            thread::spawn(move || {
                let mut located = false;

                // On continue de lire la sortie même après avoir trouvé l'URL :
                // cesser de consommer le canal finirait par bloquer le sidecar
                // sur ses propres écritures.
                while let Some(event) = rx.blocking_recv() {
                    if let CommandEvent::Stdout(bytes) = event {
                        if located {
                            continue;
                        }
                        let line = String::from_utf8_lossy(&bytes);
                        if let Some(url) = parse_server_url(&line) {
                            located = true;
                            show_window_on(window.clone(), url);
                        }
                    }
                }

                if !located {
                    eprintln!("sidecar exited without announcing a port; trying {FALLBACK_URL}");
                    show_window_on(window, FALLBACK_URL.to_string());
                }
            });

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Ankigen");

    app.run(move |_app_handle, event| {
        if let RunEvent::Exit = event {
            // Sans cet arrêt, le sidecar survit à la fenêtre et garde son port.
            // Au lancement suivant, `find_free_port` en prend un autre pendant
            // qu'un serveur périmé continue de répondre sur le premier.
            if let Some(child) = child_for_exit.lock().unwrap().take() {
                let _ = child.kill();
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::parse_server_url;

    #[test]
    fn reads_the_port_announced_by_the_launcher() {
        assert_eq!(
            parse_server_url("Ankigen running on http://127.0.0.1:5007"),
            Some("http://127.0.0.1:5007".to_string())
        );
    }

    #[test]
    fn default_port_is_read_like_any_other() {
        assert_eq!(
            parse_server_url("Ankigen running on http://127.0.0.1:5000"),
            Some("http://127.0.0.1:5000".to_string())
        );
    }

    #[test]
    fn trailing_text_is_not_swallowed() {
        assert_eq!(
            parse_server_url("running on http://127.0.0.1:5001 — close to stop"),
            Some("http://127.0.0.1:5001".to_string())
        );
    }

    #[test]
    fn unrelated_output_is_ignored() {
        assert_eq!(parse_server_url("[bootstrap] files copied"), None);
        assert_eq!(parse_server_url(""), None);
    }

    #[test]
    fn an_url_without_a_numeric_port_is_rejected() {
        assert_eq!(parse_server_url("see http://127.0.0.1:"), None);
        assert_eq!(parse_server_url("see http://127.0.0.1:abc"), None);
    }
}
