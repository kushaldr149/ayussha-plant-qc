import os
import re
import tempfile

# Configure a throwaway database before the app is imported.
_tmp = tempfile.mkdtemp(prefix="plantqc-test-")
os.environ["DATA_DIR"] = _tmp
os.environ["INITIAL_ADMIN_PASSWORD"] = "Bootstrap123A"
os.environ["PLANT_API_TOKEN"] = "test-token-123"
os.environ.pop("ANTHROPIC_API_KEY", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

CSRF = re.compile(r'name="csrf_token" value="([^"]+)"')


class Browser:
    """TestClient wrapper that picks up the CSRF token from the last page seen."""

    def __init__(self, client: TestClient):
        self.c = client
        self.token = ""

    def get(self, url, **kw):
        r = self.c.get(url, **kw)
        m = CSRF.search(r.text)
        if m:
            self.token = m.group(1)
        return r

    def post(self, url, data=None, files=None, follow=False):
        data = dict(data or {})
        data.setdefault("csrf_token", self.token)
        r = self.c.post(url, data=data, files=files, follow_redirects=follow)
        m = CSRF.search(r.text)
        if m:
            self.token = m.group(1)
        return r

    def login(self, username, password):
        self.get("/login")
        return self.post("/login", {"username": username, "password": password})


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def admin(client):
    b = Browser(client)
    r = b.login("admin", "Bootstrap123A")
    assert r.status_code == 303 and r.headers["location"] == "/account/password"
    b.get("/account/password")
    r = b.post("/account/password", {"current": "Bootstrap123A", "new": "AdminPass2026x", "confirm": "AdminPass2026x"})
    assert r.status_code == 303
    return b
