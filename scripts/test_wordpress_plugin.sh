#!/usr/bin/env bash
# Only disposable containers/volumes in this dedicated project; no host ports or provider config.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 scripts/build_wordpress_plugin.py
plugin_project="wrag-plugin-$(python3 -c 'import uuid; print(uuid.uuid4().hex[:12])')"
plugin_compose=(docker compose --env-file /dev/null -p "$plugin_project" -f wordpress/tests/compose.yml)
trap '"${plugin_compose[@]}" down --volumes --remove-orphans' EXIT
"${plugin_compose[@]}" up -d --wait db wordpress
wp_test() { "${plugin_compose[@]}" run --rm -T wpcli wp "$@"; }
wp_test core install --url=http://wordpress --title=Plugin-test --admin_user=plugin-admin \
  --admin_password=synthetic-admin-password --admin_email=admin@example.invalid --skip-email
wp_test plugin install /source/dist/woo-rag-assistant.zip --activate
wp_test eval-file /source/wordpress/tests/native-plugin.php
wp_test plugin deactivate woo-rag-assistant
wp_test eval 'if (function_exists("wrag_ready") || !get_option("wrag_options")) { throw new Exception("deactivation failed"); }'
wp_test plugin activate woo-rag-assistant
wp_test eval 'if (!wrag_ready()) { throw new Exception("reactivation lost configuration"); }'
wp_test plugin uninstall woo-rag-assistant --deactivate
wp_test eval 'if (!get_option("wrag_options")) { throw new Exception("uninstall removed configuration"); }'
