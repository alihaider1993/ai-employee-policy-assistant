import importlib.util
from pathlib import Path

import pytest

# deploy/azure isn't a package, so load the script by path.
_spec = importlib.util.spec_from_file_location(
    "deploy_azure", Path(__file__).resolve().parents[1] / "deploy" / "azure" / "deploy.py"
)
deploy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(deploy)


def app_with_env(*env):
    return {"properties": {"template": {"containers": [{"name": "employee-policy-api", "env": list(env)}]}}}


def test_explicit_cache_version_wins_over_the_live_one():
    live = app_with_env({"name": "CACHE_VERSION", "value": "3"})

    assert deploy.resolve_cache_version("4", live) == ("4", "from --cache-version")


def test_existing_app_keeps_its_live_cache_version():
    live = app_with_env({"name": "ENVIRONMENT", "value": "production"}, {"name": "CACHE_VERSION", "value": "3"})

    assert deploy.resolve_cache_version(None, live) == ("3", "kept from the live app")


def test_new_app_gets_the_default_cache_version():
    assert deploy.resolve_cache_version(None, None) == ("1", "default for a new app")


def test_existing_app_without_cache_version_gets_the_default():
    live = app_with_env({"name": "ENVIRONMENT", "value": "production"})

    assert deploy.resolve_cache_version(None, live)[0] == "1"


def test_secret_or_invalid_live_cache_version_stops_the_deploy():
    with pytest.raises(deploy.DeployError):
        deploy.resolve_cache_version(None, app_with_env({"name": "CACHE_VERSION", "secretRef": "x"}))
    with pytest.raises(deploy.DeployError):
        deploy.resolve_cache_version(None, app_with_env({"name": "CACHE_VERSION", "value": "bad value!"}))


def test_app_body_sets_cache_version_and_keeps_secrets_as_references():
    secrets = {"database-url": "db-secret", "openai-key": "k1", "embedding-key": "k2", "search-key": "k3"}
    plain = {name: "x" for name in deploy.ENV_FILE_PLAIN}

    body = deploy.app_body("/env", plain, secrets, "image:tag", "3")
    env = {item["name"]: item for item in body["properties"]["template"]["containers"][0]["env"]}

    assert env["CACHE_VERSION"] == {"name": "CACHE_VERSION", "value": "3"}
    assert env["DATABASE_URL"] == {"name": "DATABASE_URL", "secretRef": "database-url"}
    assert "db-secret" not in str(deploy.mask_body(body))
