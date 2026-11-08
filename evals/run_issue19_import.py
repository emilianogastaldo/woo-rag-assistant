"""Check the existing seed and native WooCommerce CSV importer in disposable volumes.

Uses local issue7 images; no builds, downloads, demo config or external providers.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--demo-final", action="store_true", help="Also verify theme, assets, returns and ingestion"
    )
    parser.add_argument("--mcp", action="store_true", help="Also test the optional MCP adapter")
    args = parser.parse_args()
    final = args.demo_final or args.mcp
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

    def run(command, timeout=180, input=None):
        result = subprocess.run(
            command, env=env, capture_output=True, text=True, timeout=timeout, input=input
        )
        if result.returncode:
            # Do not print seed output: first run creates a disposable read-only key.
            raise RuntimeError(f"Command failed: {command[:5]}\n{result.stderr[-4000:]}")
        return result.stdout

    # Reuse already built, version-pinned issue7 images by immutable local image ID.
    images = {}
    for name, tag in {
        "wordpress": "woo-mcp-wp:11.2.2-0.7.1" if args.mcp else "woo-issue19-wp:11.2.2",
        "cli": "woo-issue19-cli:11.2.2",
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
                "volumes": [
                    "wp:/var/www/html",
                    f"{ROOT / 'wordpress/trama'}:/var/www/html/wp-content/themes/trama:ro",
                ],
            },
            "cli": {
                "image": images["cli"],
                "user": "33:33",
                "environment": wp_env,
                "volumes": [
                    "wp:/var/www/html",
                    f"{ROOT / 'seed'}:/seed:ro",
                    f"{ROOT / 'wordpress/trama'}:/var/www/html/wp-content/themes/trama:ro",
                    f"{ROOT / 'evals/issue19_import.php'}:/issue19.php:ro",
                    f"{ROOT / 'wordpress/tests/storefront.php'}:/storefront-test.php:ro",
                    f"{ROOT / 'evals/issue24_returns.php'}:/returns-test.php:ro",
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
    if final:
        images["api"] = run(
            ["docker", "image", "inspect", "woo-rag-api:issue7", "--format", "{{.Id}}"]
        ).strip()
        images["chroma"] = run(
            [
                "docker",
                "image",
                "inspect",
                "chromadb/chroma@sha256:1e0b73a187a28757c572acba508c46f48c9e8b0acaf5c20e6d95cdedce1acdf6",
                "--format",
                "{{.Id}}",
            ]
        ).strip()
        config["services"]["chroma"] = {
            "image": images["chroma"],
            "environment": {"ANONYMIZED_TELEMETRY": "false"},
            "volumes": ["chroma:/data"],
        }
        config["services"]["upstream"] = {
            "image": images["api"],
            "volumes": [f"{ROOT / 'evals'}:/evals:ro"],
            "environment": {"PYTHONPATH": "/"},
            "command": [
                "uvicorn",
                "evals.issue6_fake_upstream:app",
                "--host",
                "0.0.0.0",
                "--port",
                "9000",
            ],
        }
        config["services"]["ingest-check"] = {
            "image": images["api"],
            "volumes": [
                f"{ROOT / 'chatbot'}:/app:ro",
                f"{ROOT / 'evals'}:/evals:ro",
                "state:/state/knowledge",
            ],
            "environment": {
                "PYTHONPATH": "/app:/",
                "WC_BASE_URL": "http://wordpress/wp-json/wc/v3",
                "WC_SIGN_URL": "http://wordpress/wp-json/wc/v3",
                "CHROMA_HOST": "chroma",
                "KNOWLEDGE_STATE_DIR": "/state/knowledge",
                "OPENAI_API_KEY": "synthetic-secret",
                "OPENAI_BASE_URL": "http://upstream:9000/v1",
                "OPENAI_MODEL": "synthetic-chat",
                "EMBEDDING_MODEL": "synthetic-embedding",
                "EMBEDDING_DIMENSIONS": "8",
                "ANONYMIZED_TELEMETRY": "false",
                "LANGCHAIN_TRACING_V2": "false",
            },
            "command": ["python", "-m", "evals.issue25_ingestion"],
        }
        config["volumes"].update({"chroma": {}, "state": {}})
    if args.mcp:
        config["services"]["cli"]["volumes"].append(
            f"{ROOT / 'evals/mcp_setup.php'}:/mcp-setup.php:ro"
        )
    compose = output / "compose.json"
    compose.write_text(json.dumps(config, indent=2) + "\n")
    base = ["docker", "compose", "--env-file", "/dev/null", "-f", str(compose), "-p", project]
    resolved = json.loads(run([*base, "config", "--format", "json"]))
    assert resolved["name"] == project and resolved["networks"]["default"]["internal"]
    volumes = {f"{project}_{name}" for name in config["volumes"]}
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
        if final:
            # Capture the new disposable key in memory; never persist or print seed output.
            bootstrap = config["services"]["cli"]["command"][2].split("sh /seed/setup.sh")[0]
            bootstrap = bootstrap.replace("$$", "$")
            cli = [*base, "run", "--rm", "--no-deps", "-T", "cli"]
            evaluate = [*cli, "wp", "eval-file"]
            seeded = run([*cli, "sh", "-ec", bootstrap + "sh /seed/setup.sh"], timeout=240)
            key, secret = re.search(r"__WC_KEYS__ (ck_\w+) (cs_\w+)", seeded).groups()
            first = run([*evaluate, "/seed/tests/catalog.php"])
            run([*cli, "sh", "-ec", "sh /seed/setup.sh >/dev/null"])
            second = run([*evaluate, "/seed/tests/catalog.php"])
            assert first == second, "Repeated setup changed catalog IDs or counts"
            report["catalog"] = json.loads(first.splitlines()[0])
            report["storefront"] = run([*evaluate, "/storefront-test.php"]).strip()
            run([*base, "up", "-d", "chroma", "upstream"])
            ingestion = run([
                *base, "run", "--rm", "--no-deps", "-T",
                "-e", f"WC_CONSUMER_KEY={key}", "-e", f"WC_CONSUMER_SECRET={secret}",
                "ingest-check",
            ], timeout=240)
            report["ingestion"] = json.loads(ingestion.split("__ISSUE25__", 1)[1])
            if args.mcp:
                from mcp_probe import probe

                run([*cli, "wp", "plugin", "activate", "mcp-adapter"])
                report["mcp"] = probe(cli, run)
            result = run([*evaluate, "/issue19.php"], timeout=240)
            returns = run([*evaluate, "/returns-test.php"])
            report["returns"] = json.loads(returns[returns.index("{"):])
        else:
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
