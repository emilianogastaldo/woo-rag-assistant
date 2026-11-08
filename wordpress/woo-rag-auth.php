<?php
/**
 * Plugin Name: Woo RAG authenticated bridge
 * Description: Same-origin chat proxy using the native WordPress login session.
 */
defined('ABSPATH') || exit;

function wrag_ready() {
    return strlen(trim((string) getenv('WRAG_BRIDGE_SECRET'))) >= 32
        && getenv('WRAG_BACKEND_URL');
}

function wrag_permission($request) {
    if (!wrag_ready()) {
        return new WP_Error('wrag_unavailable', 'Assistente non configurato', ['status' => 503]);
    }
    $nonce = $request->get_header('X-WP-Nonce');
    if ($nonce && !wp_verify_nonce($nonce, 'wp_rest')) {
        return new WP_Error('wrag_session', 'Ricarica la pagina per accedere', ['status' => 403]);
    }
    $session = wp_get_session_token();
    // Require the live cookie and nonce, including after logout/revocation in another tab.
    if (is_user_logged_in() || $session) {
        if (!$nonce || !$session || !is_user_logged_in()
            || (int) wp_validate_auth_cookie('', 'logged_in') !== get_current_user_id()) {
            return new WP_Error('wrag_session', 'Accedi nuovamente', ['status' => 401]);
        }
    }
    return true;
}

function wrag_session_key() {
    return hash_hmac('sha256', get_current_user_id() . ':' . wp_get_session_token(), getenv('WRAG_BRIDGE_SECRET'));
}

function wrag_config() {
    $logged_in = is_user_logged_in();
    $account = function_exists('wc_get_page_permalink') ? wc_get_page_permalink('myaccount', wp_login_url()) : wp_login_url();
    $response = new WP_REST_Response([
        'demo_enabled' => false,
        'wordpress' => true,
        'authenticated' => $logged_in,
        'session_key' => $logged_in ? wrag_session_key() : 'guest',
        'login_url' => $account,
        'logout_url' => $logged_in ? wp_specialchars_decode(wp_logout_url($account), ENT_QUOTES) : null,
    ]);
    $response->header('Cache-Control', 'no-store, private');
    return $response;
}

function wrag_backend_token() {
    $payload = wp_json_encode([
        'sub' => wp_get_current_user()->user_email,
        'uid' => get_current_user_id(),
        'exp' => time() + 30,
        'sid' => wrag_session_key(),
    ]);
    $encode = static function ($value) {
        return rtrim(strtr(base64_encode($value), '+/', '-_'), '=');
    };
    return 'wp.' . $encode($payload) . '.'
        . $encode(hash_hmac('sha256', $payload, getenv('WRAG_BRIDGE_SECRET'), true));
}

function wrag_visitor_assertion() {
    // REMOTE_ADDR must be set by the trusted web server, never a browser header.
    $identity = is_user_logged_in() ? 'auth:' . get_current_user_id()
        : 'guest:' . ($_SERVER['REMOTE_ADDR'] ?? 'unknown');
    $payload = wp_json_encode([
        'sub' => (is_user_logged_in() ? 'auth:' : 'guest:')
            . hash_hmac('sha256', $identity, getenv('WRAG_BRIDGE_SECRET')),
        'exp' => time() + 30,
    ]);
    $encode = static function ($value) {
        return rtrim(strtr(base64_encode($value), '+/', '-_'), '=');
    };
    return $encode($payload) . '.'
        . $encode(hash_hmac('sha256', 'rate-limit:' . $payload, getenv('WRAG_BRIDGE_SECRET'), true));
}

function wrag_chat($request) {
    if (strlen($request->get_body()) > 24000) {
        return new WP_Error('wrag_size', 'Richiesta troppo grande', ['status' => 413]);
    }
    $body = $request->get_json_params();
    if (!is_array($body) || array_diff(array_keys($body), ['message', 'conversation_id'])
        || !isset($body['message']) || !is_string($body['message'])
        || !trim($body['message']) || strlen($body['message']) > 4000
        || (isset($body['conversation_id']) && (!is_string($body['conversation_id'])
            || !preg_match('/^[A-Za-z0-9_-]{43}$/D', $body['conversation_id'])))) {
        return new WP_Error('wrag_request', 'Richiesta non valida', ['status' => 422]);
    }
    $headers = [
        'Content-Type' => 'application/json',
        'X-WRAG-Visitor' => wrag_visitor_assertion(),
    ];
    if (is_user_logged_in()) {
        $headers['Authorization'] = 'Bearer ' . wrag_backend_token();
    } elseif (isset($_COOKIE['wrag_guest'])
        && preg_match('/^[A-Za-z0-9_.-]{1,4096}$/D', $_COOKIE['wrag_guest'])) {
        $headers['Cookie'] = 'wrag_guest=' . $_COOKIE['wrag_guest'];
    }
    $upstream = wp_remote_post(rtrim(getenv('WRAG_BACKEND_URL'), '/') . '/chat', [
        'headers' => $headers,
        'body' => wp_json_encode($body),
        'timeout' => 35,
        'redirection' => 0,
        'limit_response_size' => 65536,
    ]);
    if (is_wp_error($upstream)) {
        return new WP_Error('wrag_upstream', 'Assistente non disponibile', ['status' => 503]);
    }
    $data = json_decode(wp_remote_retrieve_body($upstream), true);
    $status = wp_remote_retrieve_response_code($upstream);
    if (!is_array($data) || $status < 200 || $status > 599) {
        return new WP_Error('wrag_upstream', 'Assistente non disponibile', ['status' => 502]);
    }
    $response = new WP_REST_Response($data, $status);
    $response->header('Cache-Control', 'no-store, private');
    $retry = wp_remote_retrieve_header($upstream, 'retry-after');
    if (ctype_digit((string) $retry)) {
        $response->header('Retry-After', $retry);
    }
    $cookie = wp_remote_retrieve_header($upstream, 'set-cookie');
    if (is_string($cookie) && preg_match('/^wrag_guest=([A-Za-z0-9_.-]{1,4096});/', $cookie, $matches)) {
        // Backend Path=/chat does not cover the WordPress REST bridge.
        $path = wp_parse_url(rest_url('woo-rag/v1/'), PHP_URL_PATH) ?: '/';
        $response->header('Set-Cookie', 'wrag_guest=' . $matches[1] . '; Path=' . $path
            . '; HttpOnly; SameSite=Lax' . (is_ssl() ? '; Secure' : ''));
    }
    return $response;
}

add_action('rest_api_init', static function () {
    register_rest_route('woo-rag/v1', '/session/config', [
        'methods' => 'GET', 'callback' => 'wrag_config', 'permission_callback' => 'wrag_permission',
    ]);
    register_rest_route('woo-rag/v1', '/chat', [
        'methods' => 'POST', 'callback' => 'wrag_chat', 'permission_callback' => 'wrag_permission',
    ]);
});

add_action('wp_footer', static function () {
    if (!wrag_ready()) {
        return;
    }
    $src = content_url('woo-rag-widget/chat.js');
    printf('<script src="%s" data-api="%s" data-wp-nonce="%s"></script>',
        esc_url($src), esc_url(untrailingslashit(rest_url('woo-rag/v1'))),
        esc_attr(wp_create_nonce('wp_rest')));
});
