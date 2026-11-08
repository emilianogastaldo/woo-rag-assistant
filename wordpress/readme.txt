=== Woo RAG Assistant ===
Requires at least: 6.8
Requires PHP: 8.2
Stable tag: 0.1.0
License: GPL-2.0-or-later
License URI: https://www.gnu.org/licenses/gpl-2.0.html

Same-origin WooCommerce assistant bridge with the bundled chat widget.
Requires a separately configured Woo RAG backend; no model calls during setup or diagnostics.

== Installation ==
Upload woo-rag-assistant.zip under Plugins > Add New, activate, then open Settings > Woo RAG.
Set the backend URL and the same bridge secret configured on the backend (at least 32 characters).
Use server WRAG_BACKEND_URL and WRAG_BRIDGE_SECRET overrides for private backend deployments.
Only administrators can save settings or run the readiness diagnostic.
Never expose backend credentials to visitors. Existing WordPress login authorizes private orders.

== Lifecycle ==
Activation and deactivation create no data, cron jobs or backend calls.
Deactivation hides the widget and unregisters bridge routes on the next request.
Settings and backend conversations are preserved on deactivation and uninstall.
An installed MU bridge remains active: remove its file to complete deactivation.
See docs/wordpress-plugin.md in the source repository for rollout and rollback.
