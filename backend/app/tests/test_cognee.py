import io
import json
import socket
from pathlib import Path
from urllib.error import HTTPError

import pytest

from app.services.cognee import CogneeClient


def test_compose_qualifies_the_deepseek_model_for_litellm():
    compose = Path(__file__).resolve().parents[3] / "docker-compose.yml"

    content = compose.read_text(encoding="utf-8")
    # The default remains provider-qualified while Zeichen may override it via
    # the runtime env file during an administrator-requested recreate.
    assert "LLM_MODEL-deepseek/deepseek-v4-flash" in content
    assert ".scratch/cognee-runtime.env" in content


def test_deploy_overlays_allow_cognee_own_local_file_paths_for_session_distillation():
    """契约:生产/环境覆盖层不得关闭 ACCEPT_LOCAL_FILE_PATH。

    cognee 1.4.1 的 improve→persist_sessions 蒸馏流程会把自身生成的会话文本
    先落盘为 DATA_ROOT 本地文件、再经 data_item_to_text_file 重新摄取;该开关为
    false 时内部文件路径被拒绝,抛 415 Local files are not accepted,蒸馏永久
    失败(REQ bc36ae8b 原始症状)。Zeichen 从不向 cognee 传客户端文件路径。
    """
    root = Path(__file__).resolve().parents[3]
    for overlay in ("deploy/docker-compose.prod.yml", "deploy/docker-compose.ip.yml"):
        content = (root / overlay).read_text(encoding="utf-8")
        assert 'ACCEPT_LOCAL_FILE_PATH: "false"' not in content, (
            f"{overlay} 关闭 ACCEPT_LOCAL_FILE_PATH 会阻断 cognee 1.4.1 会话蒸馏"
            f"(415 Local files are not accepted),必须放开(REQ bc36ae8b)"
        )


def test_cognee_image_build_installs_fastembed_for_the_configured_provider():
    root = Path(__file__).resolve().parents[3]
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
    dockerfile = root / "Dockerfile.cognee"

    assert "dockerfile: Dockerfile.cognee" in compose
    content = dockerfile.read_text(encoding="utf-8")
    assert "fastembed" in content
    assert "--target /app/.venv/lib/python3.12/site-packages" in content


class Response:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class BytesResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def read(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_client_bootstraps_service_identity_and_sends_bearer(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        if request.full_url.endswith('/auth/login') and len(calls) == 1:
            raise HTTPError(request.full_url, 400, 'bad credentials', {}, io.BytesIO(b'{"detail":"LOGIN_BAD_CREDENTIALS"}'))
        if request.full_url.endswith('/auth/register'):
            return Response({"id": "service-user"})
        if request.full_url.endswith('/auth/login'):
            return Response({"access_token": "service-token"})
        return Response({"id": "dataset-1"})

    monkeypatch.setattr('app.services.cognee.urlopen', fake_urlopen)
    client = CogneeClient(base_url='http://cognee/api/v1')

    assert client.create_dataset('zeichen:project-1') == 'dataset-1'
    assert [request.full_url for request in calls] == [
        'http://cognee/api/v1/auth/login',
        'http://cognee/api/v1/auth/register',
        'http://cognee/api/v1/auth/login',
        'http://cognee/api/v1/datasets',
    ]
    assert calls[-1].get_header('Authorization') == 'Bearer service-token'


def test_client_uses_cognee_141_payload_names(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        if request.full_url.startswith('http://cognee/api/v1/sessions'):
            return Response({'sessions': [{'id': 'session-1'}]})
        return Response({"ok": True})

    monkeypatch.setattr('app.services.cognee.urlopen', fake_urlopen)
    client = CogneeClient(base_url='http://cognee/api/v1')
    client.api_key = 'service-key'

    client.remember(dataset_name='zeichen:project-1', session_id='session-1', content='A remembered fact', metadata={'source_id': 'agent-1', 'source_name': 'Agent', 'source_kind': 'agent'})
    client.recall(dataset_id='dataset-1', query='fact', session_id='session-1')
    client.improve(dataset_id='dataset-1', session_id='session-1')
    client.forget(dataset_id='dataset-1', data_id='data-1')
    assert client.list_sessions('dataset-1') == [{'id': 'session-1'}]

    remember = calls[0]
    assert remember.full_url.endswith('/remember/entry')
    assert remember.get_header('X-api-key') == 'service-key'
    assert remember.get_header('Content-type') == 'application/json'
    assert json.loads(remember.data) == {
        'dataset_name': 'zeichen:project-1',
        'session_id': 'session-1',
        'entry': {
            'type': 'qa',
            'question': 'Project memory submitted by Agent',
            'answer': 'A remembered fact',
            'context': '{"source_id": "agent-1", "source_kind": "agent"}',
        },
    }

    assert json.loads(calls[1].data) == {'query': 'fact', 'datasetIds': ['dataset-1'], 'sessionId': 'session-1'}
    assert json.loads(calls[2].data) == {'datasetId': 'dataset-1', 'sessionIds': ['session-1']}
    assert json.loads(calls[3].data) == {'datasetId': 'dataset-1', 'dataId': 'data-1'}


def test_client_exposes_network_timeout_to_the_durable_worker(monkeypatch):
    def fake_urlopen(request, timeout):
        raise socket.timeout("timed out")

    monkeypatch.setattr('app.services.cognee.urlopen', fake_urlopen)
    client = CogneeClient(base_url='http://cognee/api/v1', timeout=0.01)
    client.api_key = 'service-key'

    with pytest.raises(TimeoutError, match='cognee 请求超时'):
        client.improve(dataset_id='dataset-1', session_id='session-1')


class TestCogneeErrorPaths:
    def test_login_failure_other_than_400_is_conflict(self, monkeypatch):
        def fake_urlopen(request, timeout):
            raise HTTPError(request.full_url, 500, 'boom', {}, io.BytesIO(b'{"detail":"down"}'))

        monkeypatch.setattr('app.services.cognee.urlopen', fake_urlopen)
        client = CogneeClient(base_url='http://cognee/api/v1')

        with pytest.raises(Exception) as e:
            client.create_dataset('zeichen:p1')
        assert 'cognee 服务身份认证失败(500)' in str(e.value)

    def test_register_failure_other_than_400_409_is_conflict(self, monkeypatch):
        calls = []

        def fake_urlopen(request, timeout):
            calls.append(request)
            if request.full_url.endswith('/auth/login') and len(calls) == 1:
                raise HTTPError(request.full_url, 400, 'bad', {}, io.BytesIO(b'{"detail":"no user"}'))
            if request.full_url.endswith('/auth/register'):
                raise HTTPError(request.full_url, 502, 'gateway', {}, io.BytesIO(b'{}'))
            raise AssertionError('should not reach login')

        monkeypatch.setattr('app.services.cognee.urlopen', fake_urlopen)
        client = CogneeClient(base_url='http://cognee/api/v1')

        with pytest.raises(Exception) as e:
            client.create_dataset('zeichen:p1')
        assert 'cognee 服务身份注册失败(502)' in str(e.value)

    def test_register_conflict_retries_login(self, monkeypatch):
        calls = []

        def fake_urlopen(request, timeout):
            calls.append(request)
            if request.full_url.endswith('/auth/login') and len(calls) == 1:
                raise HTTPError(request.full_url, 400, 'bad', {}, io.BytesIO(b'{}'))
            if request.full_url.endswith('/auth/register'):
                raise HTTPError(request.full_url, 409, 'exists', {}, io.BytesIO(b'{}'))
            if request.full_url.endswith('/auth/login'):
                return Response({"access_token": "token-2"})
            return Response({"id": "dataset-x"})

        monkeypatch.setattr('app.services.cognee.urlopen', fake_urlopen)
        client = CogneeClient(base_url='http://cognee/api/v1')

        assert client.create_dataset('zeichen:p1') == 'dataset-x'
        assert [request.full_url for request in calls] == [
            'http://cognee/api/v1/auth/login',
            'http://cognee/api/v1/auth/register',
            'http://cognee/api/v1/auth/login',
            'http://cognee/api/v1/datasets',
        ]

    def test_missing_access_token_is_conflict(self, monkeypatch):
        def fake_urlopen(request, timeout):
            return Response({"id": "no-token"})

        monkeypatch.setattr('app.services.cognee.urlopen', fake_urlopen)
        client = CogneeClient(base_url='http://cognee/api/v1')

        with pytest.raises(Exception) as e:
            client.create_dataset('zeichen:p1')
        assert '缺少 access_token' in str(e.value)

    def test_authenticated_request_http_error_is_conflict(self, monkeypatch):
        def fake_urlopen(request, timeout):
            raise HTTPError(request.full_url, 404, 'missing', {}, io.BytesIO(b'{"detail":"nope"}'))

        monkeypatch.setattr('app.services.cognee.urlopen', fake_urlopen)
        client = CogneeClient(base_url='http://cognee/api/v1')
        client.api_key = 'service-key'

        with pytest.raises(Exception) as e:
            client.recall(dataset_id='d', query='q')
        assert 'cognee 请求失败(404)' in str(e.value)

    def test_urlerror_is_conflict_unless_timeout(self, monkeypatch):
        from urllib.error import URLError

        def fake_urlopen(request, timeout):
            raise URLError("connection refused")

        monkeypatch.setattr('app.services.cognee.urlopen', fake_urlopen)
        client = CogneeClient(base_url='http://cognee/api/v1')
        client.api_key = 'service-key'

        with pytest.raises(Exception) as e:
            client.list_sessions('d')
        assert 'cognee 服务不可用' in str(e.value)

    def test_urlerror_wrapping_timeout_reports_timeout(self, monkeypatch):
        from urllib.error import URLError

        def fake_urlopen(request, timeout):
            raise URLError(socket.timeout("slow"))

        monkeypatch.setattr('app.services.cognee.urlopen', fake_urlopen)
        client = CogneeClient(base_url='http://cognee/api/v1')
        client.api_key = 'service-key'

        with pytest.raises(TimeoutError, match='cognee 请求超时'):
            client.list_sessions('d')

    def test_raw_bytes_requests_and_their_errors(self, monkeypatch):
        from urllib.error import URLError

        state = {"mode": "ok"}

        def fake_urlopen(request, timeout):
            if state["mode"] == "ok":
                return BytesResponse(b"raw \xe4\xb8\xad\xe6\x96\x87 body")
            if state["mode"] == "http":
                raise HTTPError(request.full_url, 500, 'x', {}, io.BytesIO(b'{}'))
            raise URLError("refused")

        monkeypatch.setattr('app.services.cognee.urlopen', fake_urlopen)
        client = CogneeClient(base_url='http://cognee/api/v1')
        client.api_key = 'service-key'

        assert client.get_data_raw('d', 'data-1') == 'raw 中文 body'

        state["mode"] = "http"
        with pytest.raises(Exception) as e:
            client.get_data_raw('d', 'data-1')
        assert 'cognee 请求失败(500)' in str(e.value)

        state["mode"] = "url"
        with pytest.raises(Exception) as e:
            client.get_data_raw('d', 'data-1')
        assert 'cognee 服务不可用' in str(e.value)

    def test_delete_and_read_endpoints(self, monkeypatch):
        calls = []

        def fake_urlopen(request, timeout):
            calls.append(request)
            if request.full_url.endswith('/sessions/session-1'):
                return Response({"session_id": "session-1", "qas": []})
            if request.full_url.endswith('/data-1/raw'):
                return BytesResponse(b"raw")
            return Response({"id": "x"})

        monkeypatch.setattr('app.services.cognee.urlopen', fake_urlopen)
        client = CogneeClient(base_url='http://cognee/api/v1')
        client.api_key = 'service-key'

        assert client.delete_dataset('d') is None
        assert client.list_data('d') == {"id": "x"}
        assert client.get_data_raw('d', 'data-1') == "raw"
        assert client.get_session('session-1')["session_id"] == "session-1"
        assert client.delete_session('session-1') is None
        assert [request.full_url for request in calls] == [
            'http://cognee/api/v1/datasets/d',
            'http://cognee/api/v1/datasets/d/data',
            'http://cognee/api/v1/datasets/d/data/data-1/raw',
            'http://cognee/api/v1/sessions/session-1',
            'http://cognee/api/v1/sessions/session-1',
        ]

    def test_id_required_in_create_dataset_response(self, monkeypatch):
        def fake_urlopen(request, timeout):
            return Response({})

        monkeypatch.setattr('app.services.cognee.urlopen', fake_urlopen)
        client = CogneeClient(base_url='http://cognee/api/v1')
        client.api_key = 'service-key'

        with pytest.raises(Exception) as e:
            client.create_dataset('zeichen:p1')
        assert '缺少标识' in str(e.value)

    def test_cached_authorization_skips_second_login(self, monkeypatch):
        calls = []

        def fake_urlopen(request, timeout):
            calls.append(request)
            if request.full_url.endswith('/auth/login'):
                return Response({"access_token": "t"})
            return Response({"id": f"ds-{len(calls)}"})

        monkeypatch.setattr('app.services.cognee.urlopen', fake_urlopen)
        client = CogneeClient(base_url='http://cognee/api/v1')

        client.create_dataset('p1')
        client.create_dataset('p2')
        assert len([c for c in calls if c.full_url.endswith('/auth/login')]) == 1
