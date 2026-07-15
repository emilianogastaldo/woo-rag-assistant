#!/bin/sh
# =============================================================
# Seed dell'ambiente demo woo-rag-assistant.
# Va eseguito DENTRO il container wpcli:
#   docker compose run --rm wpcli /seed/setup.sh
# Idempotente: si puo rilanciare senza duplicare i dati.
# =============================================================
set -eu

export WP_CLI_CACHE_DIR=/tmp/wpcache
URL="http://localhost:8080"

log() { printf '\n\033[1;34m==> %s\033[0m\n' "$1"; }

# --- 1. WordPress core ---
if wp core is-installed 2>/dev/null; then
	log "WordPress gia installato"
else
	log "Installazione WordPress"
	wp core install --url="$URL" \
		--title="Demo Store — woo-rag-assistant" \
		--admin_user=admin --admin_password=admin_secret \
		--admin_email=admin@example.com --skip-email
fi

# --- 2. WooCommerce ---
if wp plugin is-active woocommerce 2>/dev/null; then
	log "WooCommerce gia attivo"
else
	log "Installazione WooCommerce"
	wp plugin install woocommerce --activate
fi

# --- 3. Permalink (necessari per /wp-json/wc/v3) ---
log "Permalink"
wp rewrite structure '/%postname%/' >/dev/null
wp rewrite flush >/dev/null || true

# --- 4. Configurazione base dello store ---
log "Configurazione store"
wp option update woocommerce_store_address "Via Roma 1" >/dev/null
wp option update woocommerce_store_city "Milano" >/dev/null
wp option update woocommerce_default_country "IT:MI" >/dev/null
wp option update woocommerce_store_postcode "20100" >/dev/null
wp option update woocommerce_currency "EUR" >/dev/null
wp option update woocommerce_price_num_decimals "2" >/dev/null
# Salta la procedura guidata di onboarding.
wp option update woocommerce_onboarding_profile '{"completed":true}' --format=json >/dev/null 2>&1 || true

# --- 5. Dati demo (prodotti, pagine, clienti, ordini, API key) ---
log "Seed dati demo"
wp eval-file /seed/seed.php

log "Fatto."
