import pytest

from utils.deployment import check_deployment


@pytest.mark.parametrize("deployment, is_mockup", [("real", True), ("mockup", False), (None, False)])
def test_check_deployment_rejects_mismatch(monkeypatch, deployment, is_mockup):
    monkeypatch.delenv("DEPLOYMENT", raising=False)
    if deployment:
        monkeypatch.setenv("DEPLOYMENT", deployment)
    with pytest.raises(SystemExit):
        check_deployment(is_mockup)


@pytest.mark.parametrize("is_mockup", [False, True])
def test_check_deployment_accepts_match(monkeypatch, is_mockup):
    monkeypatch.setenv("DEPLOYMENT", "mockup" if is_mockup else "real")
    check_deployment(is_mockup)
