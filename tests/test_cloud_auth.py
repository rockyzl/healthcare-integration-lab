from fastapi.testclient import TestClient
from app import cloud_auth
from app.main import app


def test_gateway_requires_expected_audience_verified_service_account(monkeypatch):
    monkeypatch.setenv('LAB_TOKEN_AUDIENCE', 'expected-audience')
    monkeypatch.setenv('LAB_GATEWAY_EMAIL', 'expected@example.com')
    monkeypatch.setattr(cloud_auth, 'certificate_request', lambda: None)
    seen = {}
    def verify(token, request, audience):
        seen['audience'] = audience
        return {'email': 'expected@example.com', 'email_verified': True}
    monkeypatch.setattr(cloud_auth.id_token, 'verify_oauth2_token', verify)
    assert cloud_auth.verify_gateway('Bearer token')
    assert seen['audience'] == 'expected-audience'
    monkeypatch.setattr(cloud_auth.id_token, 'verify_oauth2_token', lambda *a, **kw: {'email': 'someone-else@example.com', 'email_verified': True})
    assert not cloud_auth.verify_gateway('Bearer token')
    assert not cloud_auth.verify_gateway('')


def test_cloud_guard_rejects_direct_unauthenticated_calls(monkeypatch):
    monkeypatch.setenv('LAB_CLOUD', 'true')
    with TestClient(app) as client:
        assert client.get('/api/status').status_code == 401
        assert client.post('/api/import/fixture', headers={'X-Lab-Request': 'demo'}).status_code == 401
