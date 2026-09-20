"""Create, audit, exercise and remove an isolated issue #6 Compose project."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    run_id = uuid.uuid4().hex[:12]
    project = f"woo-issue6-{run_id}"
    collection = f"issue6-{run_id}"
    output = ROOT / "evals" / "results" / project
    output.mkdir(parents=True, exist_ok=False)
    env = {
        key: value
        for key, value in os.environ.items()
        if key
        in {
            "PATH",
            "HOME",
            "DOCKER_HOST",
            "DOCKER_CONTEXT",
            "DOCKER_CONFIG",
            "XDG_RUNTIME_DIR",
        }
    }
    env.update(
        LOCAL_UID=str(os.getuid()),
        LOCAL_GID=str(os.getgid()),
        ISSUE6_RESULTS=str(output),
        TEST_COLLECTION=collection,
    )
    compose = ROOT / "evals" / "compose.issue6.yml"
    base = ["docker", "compose", "--env-file", "/dev/null", "-f", str(compose), "-p", project]

    def run(command, *, capture=True, timeout=180):
        return subprocess.run(
            command, env=env, check=True, text=True, capture_output=capture, timeout=timeout
        )

    config = json.loads(run([*base, "config", "--format", "json"]).stdout)
    assert config["name"] == project and set(config["services"]) == {
        "api",
        "chroma",
        "runner",
        "upstream",
        "disabled",
        "limits",
        "widget",
    }
    assert config["networks"]["default"]["internal"] is True
    assert not config["networks"]["default"].get("external")
    assert set(config["volumes"]) == {"data"}
    assert config["volumes"]["data"]["name"] == f"{project}_data"
    assert not config["volumes"]["data"].get("external")
    mounts = {
        "widget": {"/widget": ROOT / "widget", "/evals": ROOT / "evals"},
        "api": {"/app": ROOT / "chatbot", "/widget": ROOT / "widget"},
        "disabled": {"/app": ROOT / "chatbot", "/widget": ROOT / "widget"},
        "limits": {"/app": ROOT / "chatbot", "/widget": ROOT / "widget"},
        "upstream": {"/evals": ROOT / "evals"},
        "runner": {
            "/app": ROOT / "chatbot",
            "/evals": ROOT / "evals",
            "/widget": ROOT / "widget",
            "/results": output,
        },
    }
    for name, service in config["services"].items():
        assert not any(
            service.get(key)
            for key in (
                "container_name",
                "ports",
                "env_file",
                "network_mode",
                "privileged",
                "devices",
            )
        )
        assert set(service["networks"]) == {"default"}
        if name in mounts:
            assert len(service["volumes"]) == len(mounts[name])
            for mount in service["volumes"]:
                assert mount["type"] == "bind"
                assert Path(mount["source"]).resolve() == mounts[name][mount["target"]].resolve()
                assert bool(mount.get("read_only")) == (mount["target"] != "/results")
        else:
            assert len(service["volumes"]) == 1
            assert service["volumes"][0]["source"] == "data"
            assert service["volumes"][0]["type"] == "volume"
    api_env = config["services"]["api"]["environment"]
    assert api_env["CHROMA_COLLECTION"] == collection
    assert api_env["OPENAI_BASE_URL"] == "http://upstream:9000/v1"
    assert api_env["WC_BASE_URL"] == "http://upstream:9000/wp-json/wc/v3"
    assert api_env["OPENAI_API_KEY"] == api_env["WC_CONSUMER_SECRET"] == "synthetic-secret"
    assert not run(
        ["docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={project}"]
    ).stdout.strip()
    for resource, name in (("volume", f"{project}_data"), ("network", f"{project}_default")):
        assert (
            name not in run(["docker", resource, "ls", "--format", "{{.Name}}"]).stdout.splitlines()
        )
    inventory = {
        "project": project,
        "collection": collection,
        "network": f"{project}_default",
        "volume": f"{project}_data",
        "ports": [],
        "internal_network": True,
        "credentials": "synthetic",
        "status": "RUNNING",
        "schema_version": 1,
        "implementation_sha256": hashlib.sha256(
            b"".join(p.read_bytes() for p in sorted((ROOT / "chatbot" / "app").rglob("*.py")))
        ).hexdigest(),
        "fixture_sha256": hashlib.sha256(
            (ROOT / "evals" / "issue6_fake_upstream.py").read_bytes()
        ).hexdigest(),
        "commit": run(["git", "rev-parse", "HEAD"]).stdout.strip(),
        "containers": [
            f"{project}-{name}-1" for name in ("api", "chroma", "upstream", "disabled", "limits")
        ],
        "images": {
            name: run(
                ["docker", "image", "inspect", service["image"], "--format", "{{.Id}}"]
            ).stdout.strip()
            for name, service in config["services"].items()
        },
    }
    print(json.dumps(inventory), flush=True)
    try:
        for secret in ("", "change-me-in-production"):
            invalid = subprocess.run(
                [
                    *base,
                    "run",
                    "--rm",
                    "--no-deps",
                    "-T",
                    "-e",
                    "APP_ENV=production",
                    "-e",
                    "DEMO_ENABLED=false",
                    "-e",
                    f"SESSION_SECRET={secret}",
                    "api",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "0.0.0.0",
                    "--port",
                    "8000",
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert invalid.returncode != 0
            assert "Production requires" in invalid.stderr
        inventory["invalid_production_startup"] = "PASS"
        run(
            [*base, "up", "-d", "--no-build", "chroma", "upstream", "api", "disabled", "limits"],
            capture=False,
        )
        for phase in ("healthy", "restarted"):
            if phase == "restarted":
                run([*base, "restart", "api"], capture=False)
            run(
                [
                    *base,
                    "run",
                    "--rm",
                    "--no-deps",
                    "-T",
                    "runner",
                    "python",
                    "-m",
                    "evals.issue6_integration",
                    "--phase",
                    phase,
                ],
                capture=False,
            )
        try:
            widget = run([*base, "run", "--rm", "--no-deps", "-T", "widget"])
        except subprocess.CalledProcessError as exc:
            print(exc.stderr)
            raise
        (output / "widget.json").write_text(widget.stdout)
        print(widget.stdout.strip())
        logs = run(
            [*base, "logs", "--no-log-prefix", "--no-color", "api", "disabled", "limits"]
        ).stdout
        assert not any(
            value in logs
            for value in (
                "synthetic-secret",
                "oauth_signature",
                "Traceback",
                "Bearer ",
                "@example.com",
                "78101",
                "78102",
                "PRIVATE-A",
                "Ignore system",
            )
        )
        events = [json.loads(line) for line in logs.splitlines() if line.startswith("{")]
        assert events and any(event["event"] == "tool" for event in events)
        assert all(
            {"request_id", "conversation_id", "duration_ms", "outcome"} <= event.keys()
            for event in events
        )
        inventory["redacted_logging"] = "PASS"
        inventory["status"] = "PASS"
    except (subprocess.CalledProcessError, AssertionError, subprocess.TimeoutExpired):
        inventory["status"] = "FAIL"
        raise
    finally:
        run([*base, "down", "--volumes", "--timeout", "10"], capture=False)
        assert not run(
            ["docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={project}"]
        ).stdout.strip()
        for resource, name in (("volume", inventory["volume"]), ("network", inventory["network"])):
            assert (
                name
                not in run(["docker", resource, "ls", "--format", "{{.Name}}"]).stdout.splitlines()
            )
        inventory["cleanup"] = "PASS"
        (output / "inventory.json").write_text(json.dumps(inventory, indent=2) + "\n")
    print(f"Reports: {output}")


if __name__ == "__main__":
    main()
