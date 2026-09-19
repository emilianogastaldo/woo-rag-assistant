"""Host harness: unique Compose project, audited isolation, explicit owned cleanup."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def validate_config(config, project, output, collection):
    assert set(config["services"]) == {"chroma", "runner"}
    assert config["name"] == project and project.startswith("woo-issue4-")
    assert set(config["volumes"]) == {"data"}
    assert config["volumes"]["data"]["name"] == f"{project}_data"
    assert not config["volumes"]["data"].get("external")
    assert set(config["networks"]) == {"default"}
    network = config["networks"]["default"]
    assert network["internal"] is True and not network.get("external")
    assert network["name"] == f"{project}_default"
    for service in config["services"].values():
        assert not any(service.get(k) for k in (
            "container_name", "ports", "env_file", "network_mode", "privileged", "devices",
        ))
        assert set(service["networks"]) == {"default"}
    mounts = config["services"]["runner"]["volumes"]
    expected = {"/app": ROOT / "chatbot", "/evals": ROOT / "evals", "/results": output}
    assert len(mounts) == len(expected)
    for mount in mounts:
        assert mount["type"] == "bind"
        assert Path(mount["source"]).resolve() == expected[mount["target"]].resolve()
        assert bool(mount.get("read_only")) == (mount["target"] != "/results")
    chroma_mounts = config["services"]["chroma"]["volumes"]
    assert len(chroma_mounts) == 1
    assert chroma_mounts[0]["type"] == "volume" and chroma_mounts[0]["source"] == "data"
    env = config["services"]["runner"]["environment"]
    assert env["CHROMA_HOST"] == "chroma" and env["CHROMA_COLLECTION"] == collection
    assert env["OPENAI_API_KEY"] == "" and env["WC_BASE_URL"] == "http://unused.invalid"
    assert env["WC_CONSUMER_KEY"] == env["WC_CONSUMER_SECRET"] == "synthetic"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit")
    args = parser.parse_args()
    run_id = uuid.uuid4().hex[:12]
    project, collection = f"woo-issue4-{run_id}", f"issue4-{run_id}"
    output = ROOT / "evals" / "results" / project
    output.mkdir(parents=True, exist_ok=False)
    # Keep Docker client context, omit demo/application variables and .env files.
    env = {k: v for k, v in os.environ.items() if k in {
        "PATH", "HOME", "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "XDG_RUNTIME_DIR",
    }}
    env.update(LOCAL_UID=str(os.getuid()), LOCAL_GID=str(os.getgid()),
               ISSUE4_RESULTS=str(output), TEST_COLLECTION=collection)
    base = ["docker", "compose", "--env-file", "/dev/null", "-f",
            str(ROOT / "evals" / "compose.integration.yml"), "-p", project]

    def command(command, *, capture=True, timeout=240):
        return subprocess.run(command, env=env, check=True, text=True,
                              capture_output=capture, timeout=timeout)

    config = json.loads(command([*base, "config", "--format", "json"]).stdout)
    validate_config(config, project, output, collection)
    # Collision check before any mutation.
    assert not command(["docker", "ps", "-aq", "--filter",
                        f"label=com.docker.compose.project={project}"]).stdout.strip()
    container_names = [f"{project}-chroma-1", f"{project}-runner"]
    existing = command(["docker", "ps", "-a", "--format", "{{.Names}}"]).stdout.splitlines()
    assert not set(container_names) & set(existing)
    volumes = command(["docker", "volume", "ls", "--format", "{{.Name}}"]).stdout.splitlines()
    assert f"{project}_data" not in volumes
    networks = command(["docker", "network", "ls", "--format", "{{.Name}}"]).stdout.splitlines()
    assert f"{project}_default" not in networks
    inventory = {
        "project": project, "collection": collection, "volume": f"{project}_data",
        "network": f"{project}_default", "ports": [], "internal_network": True,
        "containers": container_names,
        "images": {name: command(["docker", "image", "inspect", service["image"],
                                   "--format", "{{.Id}}"]).stdout.strip()
                   for name, service in config["services"].items()},
        "commit": args.commit, "status": "RUNNING",
    }
    print(json.dumps(inventory), flush=True)
    try:
        command([*base, "up", "-d", "--no-build", "chroma"], capture=False)
        network = json.loads(command(["docker", "network", "inspect",
                                      inventory["network"]]).stdout)[0]
        assert network["Internal"] and network["Labels"]["com.docker.compose.project"] == project
        command([*base, "run", "--rm", "--no-deps", "--name", container_names[1],
                 "-T", "runner", "python", "-m",
                 "evals.chroma_integration", *(["--commit", args.commit] if args.commit else [])],
                capture=False)
        inventory["status"] = "PASS"
    except Exception:
        inventory["status"] = "FAIL"
        raise
    finally:
        # The config was audited and these exact names were absent before this run.
        command([*base, "down", "--volumes", "--timeout", "10"], capture=False)
        assert not command(["docker", "ps", "-aq", "--filter",
                            f"label=com.docker.compose.project={project}"]).stdout.strip()
        assert inventory["volume"] not in command([
            "docker", "volume", "ls", "--format", "{{.Name}}",
        ]).stdout.splitlines()
        assert inventory["network"] not in command([
            "docker", "network", "ls", "--format", "{{.Name}}",
        ]).stdout.splitlines()
        inventory["cleanup"] = "PASS"
        (output / "inventory.json").write_text(json.dumps(inventory, indent=2) + "\n")
    print(f"Report: {output / 'integration.json'}")


if __name__ == "__main__":
    main()
