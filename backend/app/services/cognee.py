"""Narrow synchronous REST client for the pinned cognee 1.4.1 bridge.

No caller may talk to cognee directly.  Keeping the wire protocol here makes
the project/role boundary testable and gives deployments one compatibility
point if their pinned image's response envelope differs.
"""

import json
import socket
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from ..config import get_settings
from ..errors import conflict


class CogneeClient:
    def __init__(self, base_url: str | None = None, timeout: float | None = None):
        settings = get_settings()
        self.base_url = (base_url or settings.cognee_base_url).rstrip("/")
        self.timeout = timeout or settings.cognee_timeout_seconds
        self.api_key = settings.cognee_service_api_key
        self.service_email = settings.cognee_service_email
        self.service_password = settings.cognee_service_password
        self._authorization: str | None = None

    def _authenticate(self) -> str:
        """Return a Cognee bearer token, registering the configured local
        service account once when it does not exist yet.

        Cognee's access-control mode makes an unauthenticated Dataset request
        fail before the application can record its project mapping.  Keeping
        this bootstrap here means the external service identity remains an
        implementation detail of Zeichen rather than a browser/MCP concern.
        """
        if self._authorization:
            return self._authorization

        try:
            result = self._request(
                "POST",
                "/auth/login",
                form={"username": self.service_email, "password": self.service_password},
                authenticate=False,
            )
        except HTTPError as login_error:
            if login_error.code != 400:
                detail = login_error.read().decode("utf-8", errors="replace")[:500]
                raise conflict(f"cognee 服务身份认证失败({login_error.code}): {detail}") from login_error
            try:
                self._request(
                    "POST",
                    "/auth/register",
                    {"email": self.service_email, "password": self.service_password},
                    authenticate=False,
                )
            except HTTPError as register_error:
                # A concurrent first request may have registered the account.
                # Re-attempting the login turns that race into a normal path.
                if register_error.code not in (400, 409):
                    detail = register_error.read().decode("utf-8", errors="replace")[:500]
                    raise conflict(
                        f"cognee 服务身份注册失败({register_error.code}): {detail}"
                    ) from register_error
            result = self._request(
                "POST",
                "/auth/login",
                form={"username": self.service_email, "password": self.service_password},
                authenticate=False,
            )

        token = result.get("access_token") if isinstance(result, dict) else None
        if not token:
            raise conflict("cognee 认证响应缺少 access_token")
        self._authorization = f"Bearer {token}"
        return self._authorization

    def _request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        *,
        form: dict[str, str] | None = None,
        query: dict[str, str] | None = None,
        authenticate: bool = True,
    ) -> Any:
        if query:
            path = f"{path}?{urlencode(query)}"
        headers: dict[str, str] = {}
        if form is not None:
            data = urlencode(form).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            data = json.dumps(body).encode() if body is not None else None
            if data:
                headers["Content-Type"] = "application/json"
        if authenticate:
            headers["X-Api-Key" if self.api_key else "Authorization"] = self.api_key or self._authenticate()
        request = Request(
            f"{self.base_url}{path}", data=data, method=method, headers=headers,
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:  # nosec B310: configured internal URL
                raw = response.read()
        except HTTPError as exc:
            if not authenticate:
                raise
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise conflict(f"cognee 请求失败({exc.code}): {detail}") from exc
        except (TimeoutError, socket.timeout) as exc:
            # Let the durable improve worker distinguish its own deadline
            # from a normal unavailable-service error.  Retrying is unsafe:
            # Cognee may continue the request after this client gives up.
            raise TimeoutError("cognee 请求超时") from exc
        except URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise TimeoutError("cognee 请求超时") from exc
            raise conflict("cognee 服务不可用") from exc
        return json.loads(raw) if raw else {}

    def _request_bytes(self, method: str, path: str) -> bytes:
        headers: dict[str, str] = {}
        headers["X-Api-Key" if self.api_key else "Authorization"] = self.api_key or self._authenticate()
        request = Request(f"{self.base_url}{path}", method=method, headers=headers)
        try:
            with urlopen(request, timeout=self.timeout) as response:  # nosec B310: configured internal URL
                return response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise conflict(f"cognee 请求失败({exc.code}): {detail}") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise TimeoutError("cognee 请求超时") from exc
        except URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise TimeoutError("cognee 请求超时") from exc
            raise conflict("cognee 服务不可用") from exc

    @staticmethod
    def _id(value: Any) -> str:
        if isinstance(value, dict):
            value = value.get("id") or value.get("dataset_id") or value.get("data_id")
        if not value:
            raise conflict("cognee 响应缺少标识")
        return str(value)

    def create_dataset(self, name: str) -> str:
        return self._id(self._request("POST", "/datasets", {"name": name}))

    def delete_dataset(self, dataset_id: str) -> None:
        self._request("DELETE", f"/datasets/{dataset_id}")

    def remember(self, *, dataset_name: str, session_id: str, content: str, metadata: dict) -> Any:
        # In cognee 1.4.1, session memory must be submitted as a typed entry.
        # The multipart /remember endpoint intentionally ignores uploaded
        # files when session_id is present, which otherwise reports success
        # without creating a session entry.
        context = json.dumps({
            "source_id": metadata["source_id"],
            "source_kind": metadata["source_kind"],
        })
        return self._request(
            "POST",
            "/remember/entry",
            {
                "dataset_name": dataset_name,
                "session_id": session_id,
                "entry": {
                    "type": "qa",
                    "question": f"Project memory submitted by {metadata['source_name']}",
                    "answer": content,
                    "context": context,
                },
            },
        )

    def recall(self, *, dataset_id: str, query: str, session_id: str | None = None) -> Any:
        body: dict[str, Any] = {"query": query, "datasetIds": [dataset_id]}
        if session_id:
            body["sessionId"] = session_id
        return self._request("POST", "/recall", body)

    def improve(self, *, dataset_id: str, session_id: str) -> Any:
        return self._request(
            "POST", "/improve", {"datasetId": dataset_id, "sessionIds": [session_id]}
        )

    def forget(self, *, dataset_id: str, data_id: str) -> Any:
        return self._request("POST", "/forget", {"datasetId": dataset_id, "dataId": data_id})

    def list_data(self, dataset_id: str) -> Any:
        return self._request("GET", f"/datasets/{dataset_id}/data")

    def get_data_raw(self, dataset_id: str, data_id: str) -> str:
        raw = self._request_bytes("GET", f"/datasets/{dataset_id}/data/{data_id}/raw")
        return raw.decode("utf-8", errors="replace")

    def list_sessions(self, dataset_id: str) -> Any:
        # Sessions belong to the authenticated service identity in cognee
        # 1.4.1.  Dataset membership is enforced by Zeichen before this call.
        result = self._request("GET", "/sessions", query={"range": "all", "limit": "500"})
        return result.get("sessions", result) if isinstance(result, dict) else result

    def get_session(self, session_id: str) -> Any:
        return self._request("GET", f"/sessions/{quote(session_id, safe='')}")

    def delete_session(self, session_id: str) -> None:
        self._request("DELETE", f"/sessions/{session_id}")
