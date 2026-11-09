<?php
// Loaded only by the canonical bridge; WordPress owns settings capability/nonce checks.
defined('ABSPATH') || exit;

function wrag_sanitize_options($input) {
    $previous = get_option('wrag_options', []);
    if (!current_user_can('manage_options')) {
        return $previous;
    }
    if (!is_array($input)) {
        add_settings_error('wrag_options', 'invalid', 'Configurazione non valida.');
        return $previous;
    }
    foreach (['backend_url', 'bridge_secret', 'title', 'color', 'position'] as $key) {
        if (!isset($input[$key]) || !is_string($input[$key])) {
            add_settings_error('wrag_options', 'invalid', 'Configurazione non valida.');
            return $previous;
        }
        $input[$key] = trim($input[$key]);
    }
    $input['title'] = sanitize_text_field($input['title']);
    $url = wp_parse_url($input['backend_url']);
    if ($input['backend_url'] !== '' && (!$url || ($url['scheme'] ?? '') !== 'https'
        || isset($url['user']) || isset($url['pass'])
        || isset($url['query']) || isset($url['fragment']) || !wp_http_validate_url($input['backend_url']))) {
        add_settings_error('wrag_options', 'url', 'Usare un URL HTTPS pubblico senza credenziali o parametri; per reti private usare WRAG_BACKEND_URL sul server.');
        return $previous;
    }
    $secret = $input['bridge_secret'] === '' ? ($previous['bridge_secret'] ?? '') : $input['bridge_secret'];
    if (($secret !== '' && (strlen($secret) < 32 || strlen($secret) > 4096))
        || !preg_match('/^.{1,80}$/usD', $input['title'])
        || !preg_match('/^#[A-Fa-f0-9]{6}$/D', $input['color'])
        || !in_array($input['position'], ['left', 'right'], true)) {
        add_settings_error('wrag_options', 'invalid', 'Controllare secret (minimo 32 caratteri), titolo (massimo 80 caratteri), colore e posizione.');
        return $previous;
    }
    return ['backend_url' => rtrim($input['backend_url'], '/'), 'bridge_secret' => $secret,
        'title' => $input['title'], 'color' => $input['color'], 'position' => $input['position']];
}

function wrag_diagnostic() {
    if (!current_user_can('manage_options')) {
        return 'forbidden';
    }
    if (!wrag_ready()) {
        return 'unconfigured';
    }
    $response = wp_remote_get(rtrim(wrag_setting('backend_url'), '/') . '/ready',
        wrag_http_options() + ['timeout' => 5, 'limit_response_size' => 4096]);
    return !is_wp_error($response) && wp_remote_retrieve_response_code($response) === 200 ? 'ready' : 'unavailable';
}

add_action('admin_init', static function () {
    register_setting('wrag', 'wrag_options', ['type' => 'array', 'show_in_rest' => false,
        'sanitize_callback' => 'wrag_sanitize_options']);
});
add_action('admin_menu', static function () {
    add_options_page('Woo RAG', 'Woo RAG', 'manage_options', 'woo-rag', 'wrag_settings_page');
});
add_action('admin_post_wrag_diagnostic', static function () {
    if (!current_user_can('manage_options')) {
        wp_die('Accesso non consentito.', '', ['response' => 403]);
    }
    check_admin_referer('wrag_diagnostic');
    wp_safe_redirect(add_query_arg('wrag_status', wrag_diagnostic(), admin_url('options-general.php?page=woo-rag')));
    exit;
});

function wrag_settings_page() {
    if (!current_user_can('manage_options')) {
        return;
    }
    echo '<div class="wrap"><h1>Woo RAG</h1>';
    settings_errors('wrag_options');
    $statuses = ['ready' => 'Backend pronto.', 'unavailable' => 'Backend non disponibile.',
        'unconfigured' => 'Configurare backend e secret.'];
    $status = isset($_GET['wrag_status']) && is_string($_GET['wrag_status']) ? $_GET['wrag_status'] : '';
    if (isset($statuses[$status])) {
        echo '<p role="status">' . esc_html($statuses[$status]) . '</p>';
    }
    echo '<form method="post" action="options.php">';
    settings_fields('wrag');
    foreach (['backend_url' => 'URL backend HTTPS', 'bridge_secret' => 'Nuovo bridge secret (vuoto: conserva)',
        'title' => 'Titolo widget', 'color' => 'Colore widget', 'position' => 'Posizione widget'] as $key => $label) {
        echo '<p><label for="wrag-' . esc_attr($key) . '">' . esc_html($label) . '</label><br>';
        if ($key === 'position') {
            echo '<select id="wrag-position" name="wrag_options[position]">';
            foreach (['right' => 'Destra', 'left' => 'Sinistra'] as $value => $text) {
                echo '<option value="' . esc_attr($value) . '" ' . selected(wrag_setting($key), $value, false) . '>' . esc_html($text) . '</option>';
            }
            echo '</select>';
        } else {
            $type = ['bridge_secret' => 'password', 'backend_url' => 'url', 'color' => 'color'][$key] ?? 'text';
            // Never reflect secrets, even in an administrator response.
            $value = $key === 'bridge_secret' ? '' : ($key === 'backend_url'
                ? (get_option('wrag_options', [])['backend_url'] ?? '') : wrag_setting($key));
            echo '<input id="wrag-' . esc_attr($key) . '" type="' . esc_attr($type) . '" name="wrag_options[' . esc_attr($key)
                . ']" value="' . esc_attr($value) . '" autocomplete="off">';
        }
        if (in_array($key, ['backend_url', 'bridge_secret'], true) && getenv('WRAG_' . strtoupper($key))) {
            echo ' <em>Override ambiente attivo; il valore salvato non viene usato.</em>';
        }
        echo '</p>';
    }
    submit_button('Salva');
    echo '</form><form method="post" action="' . esc_url(admin_url('admin-post.php')) . '"><input type="hidden" name="action" value="wrag_diagnostic">';
    wp_nonce_field('wrag_diagnostic');
    submit_button('Verifica backend (nessuna chiamata al modello)', 'secondary');
    echo '</form></div>';
}
