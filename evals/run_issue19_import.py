"""Check the existing seed and native WooCommerce CSV importer in disposable volumes.

Uses local issue7 WordPress/CLI images; no builds, downloads, demo config or providers.
"""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    project = f"woo-issue19-{uuid.uuid4().hex[:12]}"
    output = ROOT / "evals/results" / project
    output.mkdir(parents=True)
    env = {
        k: v
        for k, v in os.environ.items()
        if k
        in {
            "PATH",
            "HOME",
            "DOCKER_HOST",
            "DOCKER_CONTEXT",
            "DOCKER_CONFIG",
            "XDG_RUNTIME_DIR",
        }
    }

    def run(command, timeout=180):
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=timeout)
        if result.returncode:
            # Do not print seed output: first run creates a disposable read-only key.
            raise RuntimeError(f"Command failed: {command[:5]}\n{result.stderr[-4000:]}")
        return result.stdout

    # Reuse already built, version-pinned issue7 images by immutable local image ID.
    images = {}
    for name, tag in {
        "wordpress": "woo-issue19-wp:10.0.4",
        "cli": "woo-issue19-cli:10.0.4",
        "db": "mariadb@sha256:efb4959ef2c835cd735dbc388eb9ad6aab0c78dd64febcd51bc17481111890c4",
    }.items():
        images[name] = run(["docker", "image", "inspect", tag, "--format", "{{.Id}}"]).strip()
    wp_env = {
        "WORDPRESS_DB_HOST": "db",
        "WORDPRESS_DB_NAME": "synthetic",
        "WORDPRESS_DB_USER": "synthetic",
        "WORDPRESS_DB_PASSWORD": "synthetic-password",
        "WORDPRESS_CONFIG_EXTRA": (
            "define('WP_HTTP_BLOCK_EXTERNAL', true); "
            "define('DISABLE_WP_CRON', true); "
            "define('AUTOMATIC_UPDATER_DISABLED', true);"
        ),
    }
    config = {
        "services": {
            "db": {
                "image": images["db"],
                "environment": {
                    "MARIADB_DATABASE": "synthetic",
                    "MARIADB_USER": "synthetic",
                    "MARIADB_PASSWORD": "synthetic-password",
                    "MARIADB_ROOT_PASSWORD": "synthetic-root",
                },
                "volumes": ["db:/var/lib/mysql"],
                "healthcheck": {
                    "test": ["CMD", "healthcheck.sh", "--connect", "--innodb_initialized"],
                    "interval": "2s",
                    "timeout": "3s",
                    "retries": 45,
                },
            },
            "wordpress": {
                "image": images["wordpress"],
                "environment": wp_env,
                "volumes": ["wp:/var/www/html"],
            },
            "cli": {
                "image": images["cli"],
                "user": "33:33",
                "environment": wp_env,
                "volumes": [
                    "wp:/var/www/html",
                    f"{ROOT / 'seed'}:/seed:ro",
                    f"{ROOT / 'evals/issue19_import.php'}:/issue19.php:ro",
                ],
                "command": [
                    "sh",
                    "-ec",
                    """
remaining=60
while [ ! -f wp-config.php ]; do
    remaining=$$((remaining - 1))
    [ $$remaining -gt 0 ] || exit 1
    sleep 1
done
wp core install --url=http://wordpress --title=Synthetic --admin_user=admin \
  --admin_password=synthetic-password --admin_email=synthetic@example.invalid \
  --skip-email >/dev/null
wp plugin activate woocommerce >/dev/null
sh /seed/setup.sh >/dev/null
wp eval-file /seed/seed.php >/dev/null
wp eval-file /issue19.php
""",
                ],
            },
        },
        "networks": {"default": {"internal": True}},
        "volumes": {"db": {}, "wp": {}},
    }
    compose = output / "compose.json"
    compose.write_text(json.dumps(config, indent=2) + "\n")
    base = ["docker", "compose", "--env-file", "/dev/null", "-f", str(compose), "-p", project]
    resolved = json.loads(run([*base, "config", "--format", "json"]))
    assert resolved["name"] == project and resolved["networks"]["default"]["internal"]
    volumes = {f"{project}_db", f"{project}_wp"}
    assert {v["name"] for v in resolved["volumes"].values()} == volumes
    for service in resolved["services"].values():
        assert not any(
            service.get(k)
            for k in ("ports", "container_name", "env_file", "network_mode", "privileged")
        )
    assert not run(
        ["docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={project}"]
    ).strip()
    assert not volumes.intersection(
        run(["docker", "volume", "ls", "--format", "{{.Name}}"]).splitlines()
    )
    report = {"project": project, "images": images, "isolation_audit": "PASS", "status": "RUNNING"}
    print(f"Isolated import check: {project}", flush=True)
    try:
        run([*base, "up", "-d", "--wait", "db"])
        run([*base, "up", "-d", "wordpress"])
        result = run([*base, "run", "--rm", "--no-deps", "-T", "cli"], timeout=240)
        report["checks"] = json.loads(result)
        report["status"] = "PASS"
    except Exception:
        report["status"] = "FAIL"
        raise
    finally:
        # Delete only volumes owned by this unique test project.
        existing = run(["docker", "volume", "ls", "--format", "{{.Name}}"]).splitlines()
        for volume in volumes.intersection(existing):
            labels = json.loads(
                run(["docker", "volume", "inspect", volume, "--format", "{{json .Labels}} "])
            )
            assert labels["com.docker.compose.project"] == project
        run([*base, "down", "--volumes", "--timeout", "10"])
        assert not run(
            ["docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={project}"]
        ).strip()
        assert not volumes.intersection(
            run(["docker", "volume", "ls", "--format", "{{.Name}}"]).splitlines()
        )
        report["cleanup"] = "PASS"
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    print(f"Report: {output / 'report.json'}")


if __name__ == "__main__":
    main()
