"""Build unique standalone images, audit isolated Compose, exercise and clean owned resources."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    run_id = uuid.uuid4().hex[:12]
    project = f"woo-issue7-{run_id}"
    output = ROOT / "evals/results" / project
    output.mkdir(parents=True, exist_ok=False)
    env = {k: v for k, v in os.environ.items() if k in {
        "PATH", "HOME", "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "XDG_RUNTIME_DIR",
    }}
    images = {key: f"woo-issue7-{key.lower()}:{run_id}"
              for key in ("API", "INGEST", "RUNNER", "WP", "CLI")}
    env.update({f"{k}_IMAGE": v for k, v in images.items()})
    env.update(TEST_COLLECTION=f"issue7-{run_id}", ISSUE7_RESULTS=str(output))
    base = ["docker", "compose", "--env-file", "/dev/null", "-f",
            str(ROOT / "evals/compose.issue7.yml"), "-p", project]

    def run(command, timeout=180):
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=timeout)
        if result.returncode:
            # All commands use synthetic configuration; never invoke demo config/logs.
            print(result.stdout[-4000:], result.stderr[-6000:], flush=True)
            result.check_returncode()
        return result.stdout

    inventory = {"schema_version": 1, "status": "RUNNING", "project": project,
                 "collection_namespace": env["TEST_COLLECTION"], "images": images,
                 "commit": run(["git", "rev-parse", "HEAD"]).strip(),
                 "implementation_sha256": hashlib.sha256(b"".join(
                     p.read_bytes() for p in sorted((ROOT / "chatbot/app").rglob("*.py"))
                 )).hexdigest(), "dataset": "issue7-synthetic-v1", "external_calls": 0,
                 "volumes": [f"{project}_{v}" for v in ("db", "wp", "chroma", "state")],
                 "network": f"{project}_default", "ports": [], "phases": {}}
    (output / "inventory.json").write_text(json.dumps(inventory, indent=2))
    print(f"Building isolated images: {project}", flush=True)
    for command in (
        ["docker", "build", "-t", images["API"], "-t", images["INGEST"], str(ROOT / "chatbot")],
        ["docker", "build", "-f", str(ROOT / "evals/Dockerfile.issue7"), "--target", "wordpress",
         "-t", images["WP"], str(ROOT)],
        ["docker", "build", "-f", str(ROOT / "evals/Dockerfile.issue7"), "--target", "cli",
         "-t", images["CLI"], str(ROOT)],
        ["docker", "build", "-f", str(ROOT / "evals/Dockerfile.issue7-runner"),
         "--build-arg", f"API_IMAGE={images['API']}", "-t", images["RUNNER"], str(ROOT)],
    ):
        run(command, timeout=900)
    config = json.loads(run([*base, "config", "--format", "json"]))
    assert config["name"] == project
    assert set(config["services"]) == {
        "api", "ingest", "runner", "dev", "chroma", "upstream", "wordpress", "cli", "db"}
    assert config["networks"]["default"]["internal"] is True
    assert not config["networks"]["default"].get("external")
    assert set(config["volumes"]) == {"db", "wp", "chroma", "state"}
    for volume in config["volumes"].values():
        assert volume["name"] in inventory["volumes"] and not volume.get("external")
    expected_mounts = {
        "api": {"/state/knowledge": "state"}, "ingest": {"/state/knowledge": "state"},
        "runner": {"/state/knowledge": "state", "/results": str(output)},
        "dev": {"/state/knowledge": "state", "/app": str(ROOT / "chatbot")},
        "db": {"/var/lib/mysql": "db"}, "wordpress": {"/var/www/html": "wp"},
        "cli": {"/var/www/html": "wp"}, "chroma": {"/data": "chroma"}, "upstream": {},
    }
    for name, service in config["services"].items():
        assert not any(service.get(k) for k in (
            "container_name", "ports", "env_file", "network_mode", "privileged", "devices"))
        assert set(service["networks"]) == {"default"}
        mounts = {m["target"]: m["source"] for m in service.get("volumes", [])}
        assert mounts == expected_mounts[name]
        for mount in service.get("volumes", []):
            if mount["target"] in {"/app", "/results"}:
                assert mount["type"] == "bind"
                assert bool(mount.get("read_only")) == (mount["target"] == "/app")
            else:
                assert mount["type"] == "volume"
        if name in {"api", "ingest", "dev", "runner"}:
            app_env = service["environment"]
            assert app_env["CHROMA_COLLECTION"] == env["TEST_COLLECTION"]
            assert app_env["CHROMA_HOST"] == "chroma"
            assert app_env["KNOWLEDGE_STATE_DIR"] == "/state/knowledge"
            assert app_env["OPENAI_BASE_URL"] == "http://upstream:9000/v1"
            assert app_env["WC_BASE_URL"] == app_env["WC_SIGN_URL"] == (
                "http://wordpress/wp-json/wc/v3")
            assert app_env["OPENAI_API_KEY"] == "synthetic-secret"
            assert app_env["WC_CONSUMER_KEY"] == "ck_synthetic"
    assert not run(["docker", "ps", "-aq", "--filter",
                    f"label=com.docker.compose.project={project}"]).strip()
    for resource, names in (("volume", inventory["volumes"]), ("network", [inventory["network"]])):
        existing = run(["docker", resource, "ls", "--format", "{{.Name}}"]).splitlines()
        assert not set(names) & set(existing)
    inventory["image_ids"] = {k: run(["docker", "image", "inspect", v, "--format", "{{.Id}}"])
                              .strip() for k, v in images.items()}
    inventory["isolation_audit"] = "PASS"

    def phase(name):
        print(f"Phase: {name}", flush=True)
        result = run([*base, "run", "--rm", "--no-deps", "-T", "runner", "python", "-m",
                      "evals.issue7_integration", "--phase", name], timeout=240)
        print(result.strip(), flush=True)

    try:
        run([*base, "up", "-d", "--no-deps", "api"])
        phase("not-ready")
        inventory["phases"]["delayed_startup"] = "PASS"
        run([*base, "up", "-d", "--wait", "db", "chroma", "upstream"])
        run([*base, "up", "-d", "wordpress"])
        run([*base, "run", "--rm", "--no-deps", "-T", "cli"], timeout=240)
        run([*base, "run", "--rm", "--no-deps", "-T", "ingest"], timeout=120)
        run([*base, "up", "-d", "--no-deps", "dev"])
        phase("ready")
        phase("scenarios")
        inventory["phases"]["scenarios"] = "PASS"
        for service in ("wordpress", "chroma"):
            run([*base, "stop", "--timeout", "10", service])
            phase("not-ready")
            run([*base, "start", service])
            phase("ready")
            inventory["phases"][f"{service}_outage_recovery"] = "PASS"
        # Probe actual Docker healthchecks too; no inferred readiness from mocked code.
        run([*base, "up", "-d", "--wait", "api", "dev", "wordpress", "chroma", "db"])
        inventory["phases"]["docker_healthchecks"] = "PASS"
        inventory["status"] = "PASS"
    except (subprocess.SubprocessError, AssertionError):
        inventory["status"] = "FAIL"
        raise
    finally:
        # Validate ownership immediately before destructive cleanup; explicit test project only.
        existing = run(["docker", "volume", "ls", "--format", "{{.Name}}"]).splitlines()
        for volume in set(inventory["volumes"]) & set(existing):
            labels = json.loads(run(["docker", "volume", "inspect", volume,
                                     "--format", "{{json .Labels}} "]))
            assert labels["com.docker.compose.project"] == project
        run([*base, "down", "--volumes", "--timeout", "10"])
        assert not run(["docker", "ps", "-aq", "--filter",
                        f"label=com.docker.compose.project={project}"]).strip()
        remaining = run(["docker", "volume", "ls", "--format", "{{.Name}}"]).splitlines()
        assert not set(inventory["volumes"]) & set(remaining)
        inventory["cleanup"] = "PASS"
        (output / "inventory.json").write_text(json.dumps(inventory, indent=2) + "\n")
    print(f"Reports: {output}", flush=True)


if __name__ == "__main__":
    main()
