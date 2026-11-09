<?php
// Executed only by the disposable WP-CLI fixture; HTTP is intercepted before transport.
require_once ABSPATH . 'wp-admin/includes/plugin.php';
function plugin_check($condition, $message) {
    if (!$condition) { throw new Exception($message); }
}
wp_set_current_user(get_user_by('login', 'plugin-admin')->ID);
$settings = ['backend_url' => '', 'bridge_secret' => str_repeat('s', 32),
    'title' => 'Native plugin test', 'color' => '#ffffff', 'position' => 'left'];
putenv('WRAG_BACKEND_URL=http://backend.internal:8000');
update_option('wrag_options', wrag_sanitize_options($settings), false);
plugin_check(wrag_ready(), 'configured plugin ready');
$subscriber = wp_create_user('subscriber', 'synthetic-subscriber-password', 'subscriber@example.invalid');
wp_set_current_user($subscriber);
plugin_check(wrag_sanitize_options(array_replace($settings, ['title' => 'forbidden']))['title'] === $settings['title'], 'subscriber rejected');
plugin_check(wrag_diagnostic() === 'forbidden', 'subscriber diagnostic rejected');
wp_set_current_user(get_user_by('login', 'plugin-admin')->ID);
// Actual WordPress validation, including loopback, metadata IP and credentialed URLs.
foreach (['http://example.com', 'https://127.0.0.1', 'https://169.254.169.254',
    'https://[::1]', 'https://user:pass@example.com'] as $url) {
    plugin_check(wrag_sanitize_options(array_replace($settings, ['backend_url' => $url]))['backend_url'] === '', 'unsafe saved URL rejected');
}
$requests = [];
add_filter('pre_http_request', static function ($pre, $args, $url) use (&$requests) {
    $requests[] = [$url, $args];
    return ['headers' => [], 'body' => '{"reply":"synthetic answer"}',
        'response' => ['code' => 200, 'message' => 'OK'], 'cookies' => []];
}, 10, 3);
plugin_check(wrag_diagnostic() === 'ready', 'readiness works');
plugin_check($requests[0][0] === 'http://backend.internal:8000/ready'
    && $requests[0][1]['method'] === 'GET', 'diagnostic GET only');
$session = WP_Session_Tokens::get_instance(get_current_user_id())->create(time() + 300);
$_COOKIE[LOGGED_IN_COOKIE] = wp_generate_auth_cookie(get_current_user_id(), time() + 300, 'logged_in', $session);
$request = new WP_REST_Request('POST', '/woo-rag/v1/chat');
$request->set_header('X-WP-Nonce', wp_create_nonce('wp_rest'));
plugin_check(wrag_permission($request) === true, 'native login cookie and nonce accepted');
$request->set_header('Content-Type', 'application/json');
$request->set_body('{"message":"synthetic question"}');
plugin_check(wrag_chat($request)->get_status() === 200, 'chat bridge response');
plugin_check(isset($requests[1][1]['headers']['Authorization']), 'server assertion forwarded');
$routes = rest_get_server()->get_routes();
plugin_check(isset($routes['/woo-rag/v1/chat']), 'routes registered');
ob_start(); do_action('wp_footer'); $html = ob_get_clean();
plugin_check(str_contains($html, '/plugins/woo-rag-assistant/widget/chat.js'), 'bundled asset URL');
plugin_check(!str_contains($html, str_repeat('s', 32)), 'secret absent from frontend');
$before = has_action('wp_footer');
require WP_PLUGIN_DIR . '/woo-rag-assistant/woo-rag-auth.php';
plugin_check(has_action('wp_footer') === $before, 'duplicate bridge load harmless');
// Persist a public placeholder for the reactivation check; never perform its HTTP request.
$options = get_option('wrag_options');
$options['backend_url'] = 'https://example.com';
update_option('wrag_options', $options, false);
echo "PASS: native WordPress install, permissions, login, routes, asset and HTTP stubs\n";
