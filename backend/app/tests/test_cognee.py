import io
import json
import socket
from pathlib import Path
from urllib.error import HTTPError

import pytest

from app.services.cognee import CogneeClient


def test_compose_qualifies_the_deepseek_model_for_litellm():
    compose = Path(__file__).resolve().parents[3] / "docker-compose.yml"

    assert "LLM_MODEL: deepseek/deepseek-v4-flash" in compose.read_text(encoding="utf-8")


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
