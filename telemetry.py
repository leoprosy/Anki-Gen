"""Statistiques volontaires : champs limités, file locale et envoi hors requête.

Le dossier DATA_DIR survit aux mises à jour. Les UUID et dates des événements
restent identiques en cas de nouvelle tentative. Aucun document n'entre ici.
"""

import json
import os
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

import paths
import settings
from analytics_config import INGESTION_HOSTS, load_configuration

MAX_EVENTS = 500
MAX_AGE = 7 * 86400
BATCH_SIZE = 50
RETRY_SECONDS = 60
EVENT_FIELDS = {
    "first_launch": {},
    "app_opened": {},
    "project_created": {"chunk_count": int},
    "cards_saved": {"card_count": int},
    "export_completed": {"card_count": int, "format": str},
}


def _safe_properties(event, properties):
    if event not in EVENT_FIELDS:
        return None
    clean = {}
    for name, kind in EVENT_FIELDS[event].items():
        value = properties.get(name)
        if type(value) is not kind:
            return None
        if kind is int and not 0 <= value <= 1_000_000:
            return None
        if name == "format" and value not in ("tsv", "zip"):
            return None
        clean[name] = value
    return clean


def send_batch(config, batch):
    payload = json.dumps({"api_key": config["project_token"], "batch": batch}).encode("utf-8")
    request = Request(INGESTION_HOSTS[config["region"]] + "/batch/", data=payload,
                      headers={"Content-Type": "application/json", "User-Agent": "Ankigen-Analytics/1"})
    with urlopen(request, timeout=5) as response:
        if not 200 <= response.status < 300:
            raise OSError("Analytics upload was not accepted")


class Telemetry:
    def __init__(self, state_file, settings_loader, config_loader, sender=send_batch, clock=time.time):
        self.state_file = Path(state_file)
        self.settings_loader = settings_loader
        self.config_loader = config_loader
        self.sender = sender
        self.clock = clock
        self._lock = threading.RLock()
        self._upload_lock = threading.Lock()
        self._worker = None
        self._consent_generation = 0

    def _enabled_config(self):
        if self.settings_loader().get("analytics_enabled") is not True:
            return None
        config = self.config_loader()
        return config if self.settings_loader().get("analytics_enabled") is True else None

    def _read(self):
        if not self.state_file.exists():
            return None
        state = json.loads(self.state_file.read_text(encoding="utf-8"))
        if not isinstance(state, dict) or not isinstance(state.get("queue"), list):
            raise ValueError("Invalid analytics state")
        uuid.UUID(state["installation_id"])
        if not isinstance(state.get("first_seen"), (int, float)):
            raise ValueError("Invalid first observation")
        return state

    def _write(self, state):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=self.state_file.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle, separators=(",", ":"))
            os.replace(temporary, self.state_file)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def _event(self, state, config, event, properties, timestamp, event_id=None):
        return {
            "uuid": event_id or str(uuid.uuid4()),
            "event": event,
            "distinct_id": state["installation_id"],
            "timestamp": datetime.fromtimestamp(timestamp, timezone.utc).isoformat(),
            "properties": {
                **properties,
                "app_version": config.get("app_version", "unknown"),
                "os": {"win32": "windows", "darwin": "macos", "linux": "linux"}.get(sys.platform, "other"),
                "schema_version": 1,
                "$process_person_profile": False,
                "$geoip_disable": True,
            },
        }

    def _prune(self, state):
        cutoff = self.clock() - MAX_AGE
        state["queue"] = [e for e in state["queue"]
                          if datetime.fromisoformat(e["timestamp"]).timestamp() >= cutoff][-MAX_EVENTS:]

    def track(self, event, **properties):
        """Persiste sans réseau ; tout échec reste sans effet sur l'action métier."""
        try:
            clean = _safe_properties(event, properties)
            if clean is None:
                return False
            with self._lock:
                config = self._enabled_config()
                if not config:
                    return False
                now = self.clock()
                state = self._read() or {"installation_id": str(uuid.uuid4()), "first_seen": now,
                                         "announced": False, "queue": []}
                self._prune(state)
                if not state.get("announced") and not any(e["event"] == "first_launch" for e in state["queue"]):
                    # Stable même si la file a été vidée par un retrait du consentement.
                    event_id = str(uuid.uuid5(uuid.UUID(state["installation_id"]), "first_launch"))
                    state["queue"].append(self._event(state, config, "first_launch", {}, state["first_seen"], event_id))
                # Chaque interaction réelle est horodatée. PostHog peut ainsi
                # regrouper les installations uniques dans le fuseau du projet.
                state["queue"].append(self._event(state, config, "app_opened", {}, now))
                if event not in ("first_launch", "app_opened"):
                    state["queue"].append(self._event(state, config, event, clean, now))
                self._prune(state)
                self._write(state)
                self._start_worker()
            return True
        except Exception:
            # Ne pas journaliser les exceptions : elles peuvent contenir des chemins.
            return False

    def preferences_changed(self):
        try:
            with self._lock:
                if self.settings_loader().get("analytics_enabled") is not True:
                    self._consent_generation += 1
                    state = self._read()
                    if state is not None:
                        state["queue"] = []
                        self._write(state)
                    return
            self.track("app_opened")
        except Exception:
            pass

    def save_preferences(self, partial):
        # Même verrou pour retirer le consentement et autoriser un envoi.
        # Aucune attente réseau sous ce verrou.
        with self._lock:
            saved = settings.save_settings(partial)
            self.preferences_changed()
            return saved

    def flush_once(self):
        """Un lot par tentative ; retire uniquement les événements acquittés."""
        if not self._upload_lock.acquire(blocking=False):
            return False
        try:
            with self._lock:
                config = self._enabled_config()
                if not config:
                    self.preferences_changed()
                    return False
                state = self._read()
                if state is None:
                    return False
                self._prune(state)
                self._write(state)
                batch = state["queue"][:BATCH_SIZE]
                generation = self._consent_generation
            with self._lock:
                if not batch or not self._enabled_config() or generation != self._consent_generation:
                    return False
                # Point de départ logique de la requête : un retrait antérieur
                # invalide ce lot ; un retrait ultérieur ne peut plus le rappeler.
            self.sender(config, batch)
            with self._lock:
                # Une révocation ou de nouveaux événements ont pu modifier la file.
                state = self._read()
                if state is not None:
                    sent_ids = {e["uuid"] for e in batch}
                    state["queue"] = [e for e in state["queue"] if e["uuid"] not in sent_ids]
                    if any(e["event"] == "first_launch" for e in batch):
                        state["announced"] = True
                    self._write(state)
            return True
        except Exception:
            return False
        finally:
            self._upload_lock.release()

    def _start_worker(self):
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(target=self._run, name="ankigen-analytics", daemon=True)
            self._worker.start()

    def _run(self):
        time.sleep(2)
        while True:
            sent = self.flush_once()
            time.sleep(2 if sent else RETRY_SECONDS)


client = Telemetry(paths.DATA_DIR / "analytics-state.json", settings.load_settings, load_configuration)
