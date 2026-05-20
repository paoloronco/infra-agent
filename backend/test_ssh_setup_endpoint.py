"""Regression test for public SSH setup script delivery."""
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.ssh import router


def test_ssh_setup_endpoint_returns_shell_script_not_html():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    key_entry = {
        "username": "aiagent",
        "public_key": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKey ai-agent",
    }

    with patch("routers.ssh.get_ssh_key_by_setup_token", return_value=key_entry):
        response = client.get("/ssh-setup/test-token-with-enough-length.sh")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/x-shellscript"
    assert response.headers["content-disposition"] == "inline"
    assert response.text.startswith("#!/bin/bash")
    assert not response.text.lstrip().lower().startswith("<!doctype html")
    assert "<html" not in response.text.lower()


if __name__ == "__main__":
    test_ssh_setup_endpoint_returns_shell_script_not_html()
    print("ssh_setup_endpoint_ok")
