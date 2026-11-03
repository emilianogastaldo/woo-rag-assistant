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
    variables = dict(
        LOCAL_UID=str(os.getuid()),
        LOCAL_GID=str(os.getgid()),
        ISSUE6_RESULTS=str(output),
        TEST_COLLECTION=collection,
    )
    # Explicit synthetic input also works when Compose drops inherited environment.
    env_file = output / "compose.env"
    env_file.write_text("".join(f"{key}={value}\n" for key, value in variables.items()))
    compose = ROOT / "evals" / "compose.issue6.yml"
    base = ["docker", "compose", "--env-file", str(env_file), "-f", str(compose), "-p", project]

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
    assert set(config["volumes"]) == {"data", "conversations"}
    for name, volume in config["volumes"].items():
        assert volume["name"] == f"{project}_{name}"
        assert not volume.get("external")
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
            persistent = name in {"api", "disabled", "limits"}
            assert len(service["volumes"]) == len(mounts[name]) + persistent
            for mount in service["volumes"]:
                if mount["type"] == "volume":
                    assert name in {"api", "disabled", "limits"}
                    assert mount["source"] == "conversations" and mount["target"] == "/state"
                    assert not mount.get("read_only")
                    continue
                assert mount["type"] == "bind"
                assert Path(mount["source"]).resolve() == mounts[name][mount["target"]].resolve()
                assert bool(mount.get("read_only")) == (mount["target"] != "/results")
        else:
            assert len(service["volumes"]) == 1
            assert service["volumes"][0]["source"] == "data"
            assert service["volumes"][0]["type"] == "volume"
    for name in ("api", "disabled", "limits"):
        assert config["services"][name]["environment"]["CONVERSATION_DB_PATH"] == (
            f"/state/{name}.sqlite3"
        )
    api_env = config["services"]["api"]["environment"]
    assert api_env["CHROMA_COLLECTION"] == collection
    assert api_env["OPENAI_BASE_URL"] == "http://upstream:9000/v1"
    assert api_env["WC_BASE_URL"] == "http://upstream:9000/wp-json/wc/v3"
    assert api_env["OPENAI_API_KEY"] == api_env["WC_CONSUMER_SECRET"] == "synthetic-secret"
    assert not run(
        ["docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={project}"]
    ).stdout.strip()
    for resource, name in (
        ("volume", f"{project}_data"),
        ("volume", f"{project}_conversations"),
        ("network", f"{project}_default"),
    ):
        assert (
            name not in run(["docker", resource, "ls", "--format", "{{.Name}}"]).stdout.splitlines()
        )
    inventory = {
        "project": project,
        "collection": collection,
        "network": f"{project}_default",
        "volumes": [f"{project}_data", f"{project}_conversations"],
        "ports": [],
        "internal_network": True,
        "credentials": "synthetic",
        "status": "RUNNING",
        "schema_version": 2,
        "harness_sha256": hashlib.sha256(
            b"".join(
                (ROOT / "evals" / name).read_bytes()
                for name in (
                    "run_issue6_integration.py",
                    "issue6_integration.py",
                    "compose.issue6.yml",
                )
            )
        ).hexdigest(),
        "working_tree_dirty": bool(run(["git", "status", "--porcelain"]).stdout.strip()),
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

        def snapshot():
            return json.loads(
                run(
                    [
                        *base,
                        "exec",
                        "-T",
                        "api",
                        "python",
                        "-c",
                        "import json, sqlite3; "
                        "db = sqlite3.connect('file:/state/api.sqlite3?mode=ro', uri=True); "
                        "print(json.dumps(db.execute("
                        "'SELECT id, owner, expires, turns, history FROM conversations ORDER BY id'"
                        ").fetchall()))",
                    ]
                ).stdout
            )

        log_command = [*base, "logs", "--no-log-prefix", "--no-color", "api", "disabled", "limits"]
        previous_logs = ""
        for phase in ("healthy", "restarted", "recreated"):
            if phase != "healthy":
                before = snapshot()
                assert before
                old_id = run([*base, "ps", "-q", "api"]).stdout.strip()
                if phase == "restarted":
                    run([*base, "restart", "api", "limits"], capture=False)
                else:
                    previous_logs = run(log_command).stdout
                    run(
                        [
                            *base,
                            "up",
                            "-d",
                            "--no-deps",
                            "--no-build",
                            "--force-recreate",
                            "api",
                            "limits",
                        ],
                        capture=False,
                    )
                new_id = run([*base, "ps", "-q", "api"]).stdout.strip()
                assert (old_id == new_id) == (phase == "restarted")
                assert snapshot() == before
                inventory[phase + "_unchanged_database"] = "PASS"
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
            if phase != "healthy":
                after = {row[0]: row for row in snapshot()}
                assert all(after[row[0]][1:3] == row[1:3] for row in before)
                inventory[phase + "_absolute_expiry"] = "PASS"
        try:
            widget = run([*base, "run", "--rm", "--no-deps", "-T", "widget"])
        except subprocess.CalledProcessError as exc:
            print(exc.stderr)
            raise
        (output / "widget.json").write_text(widget.stdout)
        print(widget.stdout.strip())
        logs = previous_logs + "\n" + run(log_command).stdout
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
        for resource, name in [
            *(("volume", v) for v in inventory["volumes"]),
            ("network", inventory["network"]),
        ]:
            assert (
                name
                not in run(["docker", resource, "ls", "--format", "{{.Name}}"]).stdout.splitlines()
            )
        inventory["cleanup"] = "PASS"
        (output / "inventory.json").write_text(json.dumps(inventory, indent=2) + "\n")
    print(f"Reports: {output}")


if __name__ == "__main__":
    main()
