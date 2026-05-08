import time
import requests

from . import config


class _Response:
    __slots__ = ("success", "result", "latency_ms", "error", "error_type")

    def __init__(self, success, result=None, latency_ms=0, error=None, error_type=None):
        self.success = success
        self.result = result
        self.latency_ms = latency_ms
        self.error = error
        self.error_type = error_type

    def __repr__(self):
        return f"_Response(success={self.success}, latency_ms={self.latency_ms}, error_type={self.error_type})"


class CelestiaRPC:
    def __init__(self, url=None, token=None, timeout=20):
        self.url = url or config.CELESTIA_RPC
        self.token = token or config.get_celestia_token()
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        })
        self._req_id = 0

    def call(self, method, params=None):
        self._req_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._req_id,
            "method": method,
            "params": params if params is not None else [],
        }
        start = time.perf_counter()
        try:
            r = self._session.post(self.url, json=payload, timeout=self.timeout)
            latency = int((time.perf_counter() - start) * 1000)
        except requests.exceptions.Timeout as e:
            return _Response(False, latency_ms=int((time.perf_counter() - start) * 1000),
                             error=str(e), error_type="timeout")
        except requests.exceptions.ConnectionError as e:
            return _Response(False, latency_ms=int((time.perf_counter() - start) * 1000),
                             error=str(e), error_type="connection")
        except requests.RequestException as e:
            return _Response(False, latency_ms=int((time.perf_counter() - start) * 1000),
                             error=str(e), error_type="request")

        try:
            body = r.json()
        except ValueError:
            return _Response(False, latency_ms=latency,
                             error=f"non-json response (status={r.status_code})",
                             error_type="bad_response")

        if "error" in body:
            return _Response(False, latency_ms=latency,
                             error=str(body["error"]), error_type="rpc_error")

        if "result" not in body:
            return _Response(False, latency_ms=latency,
                             error="missing result", error_type="bad_response")

        return _Response(True, result=body["result"], latency_ms=latency)


class AvailLC:
    def __init__(self, base_url=None, timeout=20):
        self.base_url = (base_url or config.AVAIL_LC).rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()

    def get(self, path, params=None):
        if not path.startswith("/"):
            path = "/" + path
        url = f"{self.base_url}{path}"
        start = time.perf_counter()
        try:
            r = self._session.get(url, params=params, timeout=self.timeout)
            latency = int((time.perf_counter() - start) * 1000)
        except requests.exceptions.Timeout as e:
            return _Response(False, latency_ms=int((time.perf_counter() - start) * 1000),
                             error=str(e), error_type="timeout")
        except requests.exceptions.ConnectionError as e:
            return _Response(False, latency_ms=int((time.perf_counter() - start) * 1000),
                             error=str(e), error_type="connection")
        except requests.RequestException as e:
            return _Response(False, latency_ms=int((time.perf_counter() - start) * 1000),
                             error=str(e), error_type="request")

        if r.status_code == 404:
            return _Response(False, latency_ms=latency,
                             error="not found", error_type="not_found")
        if r.status_code >= 400:
            return _Response(False, latency_ms=latency,
                             error=f"http {r.status_code}: {r.text[:200]}",
                             error_type="http_error")

        try:
            body = r.json()
        except ValueError:
            return _Response(False, latency_ms=latency,
                             error="non-json response", error_type="bad_response")

        return _Response(True, result=body, latency_ms=latency)


__all__ = ["CelestiaRPC", "AvailLC"]
