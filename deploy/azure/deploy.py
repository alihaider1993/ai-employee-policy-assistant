"""Create or update the public deployment on Azure Container Apps.

Run from the repo root, signed in with `az login`:

    python deploy/azure/deploy.py                        # create or update with the default image tag
    python deploy/azure/deploy.py --image-tag <sha>      # deploy another image version
    python deploy/azure/deploy.py --cache-version 2      # ignore answers cached by earlier versions
    python deploy/azure/deploy.py --dry-run              # show the az commands; reads nothing, changes nothing

Reads the Azure OpenAI and Azure AI Search settings from .env and asks for the
Neon DATABASE_URL with a hidden prompt. Secret values are never printed and
never passed on the command line: each resource is sent with `az rest` as a
JSON body in a temporary file that is deleted straight after the call. Both
resources are created with PUT (create or update), so the script is safe to
re-run.

Changing only a secret value on a re-run doesn't restart the running revision;
restart it afterwards with `az containerapp revision restart`.
"""

import argparse
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

RESOURCE_GROUP = "employee-policy-rg"
LOCATION = "uksouth"
ENVIRONMENT = "employee-policy-env"
APP = "employee-policy-api"
IMAGE_REPOSITORY = "ghcr.io/alihaider1993/employee-policy-assistant"
DEFAULT_IMAGE_TAG = "1910a8a"
# Docker tag rules: letters, digits, _ . -, up to 128 characters, not starting with . or -.
IMAGE_TAG_PATTERN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}")
DEFAULT_CACHE_VERSION = "1"
# Stored in conversations.cache_version, a String(32) column.
CACHE_VERSION_PATTERN = re.compile(r"[A-Za-z0-9_.-]{1,32}")
EXPECTED_SEARCH_SERVICE = "employee-policy-search"
API_VERSION = "2024-03-01"
POLL_SECONDS = 5
POLL_TIMEOUT_SECONDS = 15 * 60

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

# Container Apps secret name -> environment variable, for values read from .env.
ENV_FILE_SECRETS = {
    "openai-key": "AZURE_OPENAI_API_KEY",
    "embedding-key": "AZURE_OPENAI_EMBEDDING_KEY",
    "search-key": "AZURE_SEARCH_API_KEY",
}
ENV_FILE_PLAIN = (
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_DEPLOYMENT",
    "AZURE_OPENAI_EMBEDDING_ENDPOINT",
    "AZURE_OPENAI_EMBEDDING_DEPLOYMENT",
    "AZURE_SEARCH_ENDPOINT",
    "AZURE_SEARCH_INDEX",
)
FIXED_PLAIN = {
    "ENVIRONMENT": "production",
    "GRADIO_ANALYTICS_ENABLED": "False",
    # Trust the ingress proxy's X-Forwarded-* headers so the app (and Gradio's
    # links) see https rather than http.
    "FORWARDED_ALLOW_IPS": "*",
    "TRUSTED_PROXY_HOPS": "1",
    "RATE_LIMIT_PER_MINUTE": "5",
    "RATE_LIMIT_PER_DAY": "30",
}
MASK = "***"


class DeployError(Exception):
    """A failure whose message is safe to print."""


class Az:
    def __init__(self, dry_run, secrets=()):
        self.dry_run = dry_run
        self.secrets = [secret for secret in secrets if secret]
        self.executable = None if dry_run else shutil.which("az")
        if not dry_run and not self.executable:
            raise DeployError("The Azure CLI (az) was not found on PATH.")

    def redact(self, text):
        for secret in self.secrets:
            text = text.replace(secret, MASK)
        return text

    def run(self, *args, body=None, allow_not_found=False, quiet=False):
        """Run az and return parsed JSON output (None for no output or not found)."""
        shown = ["az", *args] + (["--body", "@<temp file>"] if body is not None else [])
        if not quiet:
            print("$ " + " ".join(shown))
        if body is not None and self.dry_run:
            print(json.dumps(mask_body(body), indent=2))
        if self.dry_run:
            return None

        body_path = None
        try:
            command = [self.executable, *args]
            if body is not None:
                handle, body_path = tempfile.mkstemp(suffix=".json")
                with os.fdopen(handle, "w", encoding="utf-8") as file:
                    json.dump(body, file)
                command += ["--body", f"@{body_path}"]
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        finally:
            if body_path:
                os.remove(body_path)

        if result.returncode != 0:
            error = self.redact(result.stderr.strip())
            if allow_not_found and ("ResourceNotFound" in error or "(404)" in error or "Not Found" in error):
                return None
            raise DeployError(f"az {args[0]} failed:\n{error}")
        output = result.stdout.strip()
        return json.loads(output) if output else None


def mask_body(body):
    """A copy of a request body with every secret value replaced by ***."""
    masked = json.loads(json.dumps(body))
    for secret in masked.get("properties", {}).get("configuration", {}).get("secrets", []):
        secret["value"] = MASK
    return masked


def load_settings(dry_run):
    """Return (plain env values, {secret name: value}) without printing any value."""
    if dry_run:
        plain = {name: f"<{name} from .env>" for name in ENV_FILE_PLAIN}
        secrets = {name: MASK for name in ("database-url", *ENV_FILE_SECRETS)}
        return plain, secrets

    from dotenv import dotenv_values

    if not ENV_FILE.exists():
        raise DeployError(f"{ENV_FILE} not found.")
    values = dotenv_values(ENV_FILE)
    needed = (*ENV_FILE_PLAIN, *ENV_FILE_SECRETS.values())
    missing = [name for name in needed if not (values.get(name) or "").strip()]
    if missing:
        raise DeployError(f"Missing or empty in .env: {', '.join(missing)}")

    plain = {name: values[name].strip() for name in ENV_FILE_PLAIN}
    secrets = {secret: values[variable].strip() for secret, variable in ENV_FILE_SECRETS.items()}

    search_host = urlsplit(plain["AZURE_SEARCH_ENDPOINT"]).hostname or ""
    if search_host.split(".")[0] != EXPECTED_SEARCH_SERVICE:
        print(f"Warning: AZURE_SEARCH_ENDPOINT in .env doesn't point at the free service {EXPECTED_SEARCH_SERVICE}.")
        if input("Continue anyway? [y/N] ").strip().lower() != "y":
            raise DeployError("Stopped: update AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_API_KEY in .env.")

    secrets["database-url"] = ask_database_url()
    return plain, secrets


def ask_database_url():
    url = getpass.getpass("Neon DATABASE_URL (hidden): ").strip()
    for scheme in ("postgresql://", "postgres://"):
        if url.startswith(scheme):
            url = "postgresql+psycopg://" + url[len(scheme):]
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
    except ValueError:
        raise DeployError("DATABASE_URL could not be parsed.") from None
    if parts.scheme != "postgresql+psycopg" or not host:
        raise DeployError("DATABASE_URL must look like postgresql+psycopg://user:password@host/db?sslmode=require")
    if host in ("localhost", "127.0.0.1", "::1", "host.docker.internal", "postgres"):
        raise DeployError("DATABASE_URL points at a local database; use the Neon URL.")
    if "sslmode=require" not in (parts.query or ""):
        raise DeployError("DATABASE_URL must include sslmode=require (Neon only accepts SSL connections).")
    return url


def arm_url(subscription_id, resource_type, name):
    return (
        f"https://management.azure.com/subscriptions/{subscription_id}/resourceGroups/{RESOURCE_GROUP}"
        f"/providers/Microsoft.App/{resource_type}/{name}?api-version={API_VERSION}"
    )


def environment_body():
    # No workloadProfiles: a Consumption-only environment. No appLogsConfiguration:
    # no Log Analytics workspace (console logs still stream with `az containerapp logs show`).
    return {"location": LOCATION, "properties": {"zoneRedundant": False}}


def app_body(environment_id, plain, secrets, image, cache_version):
    fixed = {**FIXED_PLAIN, "CACHE_VERSION": cache_version}
    env = [{"name": name, "value": value} for name, value in {**plain, **fixed}.items()]
    env += [
        {"name": "DATABASE_URL", "secretRef": "database-url"},
        *({"name": variable, "secretRef": secret} for secret, variable in ENV_FILE_SECRETS.items()),
    ]
    return {
        "location": LOCATION,
        "properties": {
            "managedEnvironmentId": environment_id,
            "configuration": {
                "activeRevisionsMode": "Single",
                "ingress": {
                    "external": True,
                    "targetPort": 8000,
                    "transport": "auto",
                    "allowInsecure": False,
                },
                "secrets": [{"name": name, "value": value} for name, value in secrets.items()],
            },
            "template": {
                "containers": [
                    {
                        "name": APP,
                        "image": image,
                        "resources": {"cpu": 0.5, "memory": "1Gi"},
                        "env": env,
                    }
                ],
                "scale": {
                    "minReplicas": 0,
                    "maxReplicas": 1,
                    "rules": [{"name": "http", "http": {"metadata": {"concurrentRequests": "10"}}}],
                },
            },
        },
    }


def wait_until_succeeded(az, url, label):
    if az.dry_run:
        print(f"# then repeat the GET above every {POLL_SECONDS}s until {label} reports provisioningState Succeeded")
        return None
    print(f"Waiting for {label} to finish provisioning...")
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    while True:
        resource = az.run("rest", "--method", "get", "--url", url, quiet=True)
        state = resource["properties"].get("provisioningState")
        if state == "Succeeded":
            return resource
        if state in ("Failed", "Canceled"):
            raise DeployError(f"{label} provisioning {state.lower()}. See the resource in the Azure portal.")
        if time.monotonic() > deadline:
            raise DeployError(f"Timed out waiting for {label}; it is still {state}. Re-run the script later.")
        time.sleep(POLL_SECONDS)


def ensure_environment(az, subscription_id):
    url = arm_url(subscription_id, "managedEnvironments", ENVIRONMENT)
    existing = az.run("rest", "--method", "get", "--url", url, allow_not_found=True)
    if existing:
        properties = existing["properties"]
        if existing["location"].replace(" ", "").lower() != LOCATION:
            raise DeployError(f"{ENVIRONMENT} exists in {existing['location']}, not {LOCATION}. Delete it or change LOCATION.")
        if properties.get("workloadProfiles"):
            raise DeployError(f"{ENVIRONMENT} exists but uses workload profiles, not Consumption only. Delete it first.")
        print(f"{ENVIRONMENT} already exists; reusing it.")
    else:
        az.run("rest", "--method", "put", "--url", url, body=environment_body())
    environment = wait_until_succeeded(az, url, ENVIRONMENT)
    return environment["id"] if environment else f"<{ENVIRONMENT} resource id>"


def deploy_app(az, subscription_id, environment_id, plain, secrets, image, cache_version):
    url = arm_url(subscription_id, "containerApps", APP)
    existing = az.run("rest", "--method", "get", "--url", url, allow_not_found=True)
    if existing and existing["properties"].get("managedEnvironmentId", "").lower() != environment_id.lower():
        raise DeployError(f"{APP} exists in a different environment. Delete it first.")
    if existing:
        print(f"{APP} already exists; updating it.")
    az.run("rest", "--method", "put", "--url", url, body=app_body(environment_id, plain, secrets, image, cache_version))
    app = wait_until_succeeded(az, url, APP)
    return app["properties"]["configuration"]["ingress"]["fqdn"] if app else "<app fqdn>"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="show the az commands without reading .env or calling Azure")
    parser.add_argument(
        "--image-tag",
        default=DEFAULT_IMAGE_TAG,
        help=f"tag of {IMAGE_REPOSITORY} to deploy, normally the short commit sha (default {DEFAULT_IMAGE_TAG})",
    )
    parser.add_argument(
        "--cache-version",
        default=DEFAULT_CACHE_VERSION,
        help="answer cache version; raise it after any prompt, model or index change "
        f"(default {DEFAULT_CACHE_VERSION})",
    )
    args = parser.parse_args(argv)
    if not IMAGE_TAG_PATTERN.fullmatch(args.image_tag):
        parser.error(f"--image-tag {args.image_tag!r} is not a valid Docker tag")
    if not CACHE_VERSION_PATTERN.fullmatch(args.cache_version):
        parser.error("--cache-version must be 1-32 letters, digits, _ . or -")
    image = f"{IMAGE_REPOSITORY}:{args.image_tag}"

    az = None
    try:
        plain, secrets = load_settings(args.dry_run)
        az = Az(args.dry_run, secrets.values())

        if not args.dry_run:
            print(f"About to create or update {ENVIRONMENT} and {APP} in {RESOURCE_GROUP} ({LOCATION}) from {image}, cache version {args.cache_version}.")
            if input("Continue? [y/N] ").strip().lower() != "y":
                print("Nothing changed.")
                return 1

        account = az.run("account", "show", "--query", "{id:id}", "-o", "json")
        subscription_id = account["id"] if account else "<subscription-id>"
        group = az.run("group", "show", "--name", RESOURCE_GROUP, "--query", "{location:location}", "-o", "json")
        if group and group["location"] != LOCATION:
            raise DeployError(f"{RESOURCE_GROUP} is in {group['location']}, not {LOCATION}.")

        environment_id = ensure_environment(az, subscription_id)
        fqdn = deploy_app(az, subscription_id, environment_id, plain, secrets, image, args.cache_version)
    except DeployError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted. Re-run the script to finish; it is safe to re-run.", file=sys.stderr)
        return 1
    except Exception as exc:  # never let a traceback print a secret
        message = az.redact(str(exc)) if az else "(details hidden)"
        print(f"Unexpected {type(exc).__name__}: {message}", file=sys.stderr)
        return 1

    print(f"https://{fqdn}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
