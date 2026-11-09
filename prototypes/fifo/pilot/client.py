"""Server-side FIFO client and session state, independent of Streamlit widgets."""
from dataclasses import fields
import json
import threading
from urllib.parse import urlsplit
import urllib.error
import urllib.request

from data_crime_scene.results import ExperimentResult, VariantResult
from data_crime_scene.validation import validate_result


class ServiceError(Exception):
    def __init__(self, status, reason):
        super().__init__(reason)
        self.status, self.reason = status, reason


class Client:
    def __init__(self, url):
        parts = urlsplit(url)
        if (parts.scheme != "http" or parts.hostname != "127.0.0.1"
                or parts.username or parts.password or parts.path not in ("", "/")
                or parts.query or parts.fragment or not parts.port):
            raise ValueError("Use http://127.0.0.1:PORT for the local FIFO service")
        self.url = url.rstrip("/")

    def call(self, method, path, token=None, body=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer "+token
        request = urllib.request.Request(self.url+path, method=method, headers=headers,
                                        data=json.dumps(body).encode() if body is not None else None)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=3) as response:
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            # Do not propagate headers, URLs, request objects, or response bodies.
            reasons = {401: "session_lost", 404: "expired", 409: "not_ready", 429: "capacity"}
            reason = reasons.get(error.code, "unavailable")
            if error.code == 429:
                try:
                    named = json.loads(error.read()).get("error")
                    if named in {"queue_full", "session_interval", "retained_job_capacity", "session_capacity"}:
                        reason = named
                except (ValueError, AttributeError):
                    pass
            error.close()
            raise ServiceError(error.code, reason) from None
        except (OSError, TimeoutError):
            raise ServiceError(0, "unavailable") from None


def decode_result(raw, case, seed):
    """Reconstruct the existing result type and validate submitted identity."""
    value = json.loads(raw)
    variant_fields = {f.name for f in fields(VariantResult)}
    value["variants"] = {k: VariantResult(**{key: item for key, item in v.items() if key in variant_fields})
                         for k, v in value["variants"].items()}
    result = ExperimentResult(**value)
    validate_result(result, expected_case_id=case, expected_seed=seed)
    return result


class Session:
    """One instance per Streamlit session. Never cache or render this object."""
    def __init__(self, client):
        # Streamlit fast reruns can overlap an older script blocked on HTTP.
        # Serialize token creation, submission and polling within this session.
        self.lock = threading.RLock()
        self.client = client
        self.token = None
        self.job = None
        self.unconfirmed = None
        self.raw = None
        self.result = None
        self.revealed = False
        self.notice = None

    @property
    def pending(self):
        return self.unconfirmed is not None or (self.job is not None and self.job["state"] in {
            "queued", "waiting_budget", "running"})

    def submit(self, case, seed):
        with self.lock:
            self._submit(case, seed)

    def _submit(self, case, seed):
        config = {"case": case, "seed": seed}
        previous = (self.unconfirmed or {"case": self.job["case"], "seed": self.job["seed"]}
                    if self.job or self.unconfirmed else None)
        if self.pending and config != previous:
            self.notice = "pending_configuration"
            return
        try:
            if self.token is None:
                self.token = json.loads(self.client.call("POST", "/sessions"))["token"]
            self.unconfirmed = config  # preserve identity after an uncertain POST
            job = json.loads(self.client.call("POST", "/jobs", self.token, config))
            if self.job is None or self.job["id"] != job["id"]:
                self.raw = self.result = None
                self.revealed = False
            self.job = job
            self.unconfirmed = None
            self.notice = "duplicate" if job.get("duplicate") else None
        except ServiceError as error:
            if error.status:  # an explicit refusal did not accept a job
                self.unconfirmed = None
            self._error(error)

    def poll(self):
        with self.lock:
            self._poll()

    def _poll(self):
        if not self.job or self.job["state"] in {"expired", "session_lost"}:
            return
        try:
            job = json.loads(self.client.call("GET", "/jobs/"+self.job["id"], self.token))
            if (job["case"], job["seed"], job["id"]) != (self.job["case"], self.job["seed"], self.job["id"]):
                raise ValueError("Mismatched job identity")
            self.job = job
            if job["state"] in {"succeeded", "failed"} and self.notice == "pending_configuration":
                self.notice = None
            if job["state"] == "succeeded" and self.raw is None:
                raw = self.client.call("GET", "/jobs/"+job["id"]+"/result", self.token)
                result = decode_result(raw, job["case"], job["seed"])
                self.raw, self.result = raw, result
            if self.notice == "unavailable":
                self.notice = None
        except ServiceError as error:
            self._error(error)
        except (ValueError, TypeError, KeyError):
            self.raw = self.result = None
            self.notice = "invalid_result"

    def _error(self, error):
        self.notice = error.reason
        if error.status in (401, 404):
            self.raw = self.result = None
            if self.job:
                self.job = self.job | {"state": error.reason}
            if error.status == 401:
                self.token = None
