<?php
require __DIR__ . '/bridge.php';
$admin = true;
$settings_errors = [];
function current_user_can($capability) { global $admin; return $admin; }
function add_settings_error(...$args) { global $settings_errors; $settings_errors[] = $args; }
function sanitize_text_field($text) { return strip_tags($text); }
function wp_http_validate_url($url) { return str_starts_with($url, 'https://public.example') ? $url : false; }
function wp_remote_get($url, $options) { return wp_remote_post($url, $options); }
function check_admin_referer($action) { throw new Exception('nonce check reached:' . $action); }
function wp_die(...$args) { throw new Exception('forbidden'); }
function esc_attr($value) { return htmlspecialchars($value, ENT_QUOTES); }
function esc_html($value) { return htmlspecialchars($value, ENT_QUOTES); }
function esc_url($value) { return htmlspecialchars($value, ENT_QUOTES); }
function settings_errors(...$args) {}
function settings_fields($group) { echo 'nonce-field'; }
function submit_button(...$args) {}
function wp_nonce_field(...$args) {}
function admin_url($path) { return 'https://store.test/wp-admin/' . $path; }
function selected($a, $b, $echo) { return $a === $b ? 'selected' : ''; }

putenv('WRAG_BACKEND_URL');
putenv('WRAG_BRIDGE_SECRET');
$valid = ['backend_url' => 'https://public.example/api/', 'bridge_secret' => str_repeat('s', 32),
    'title' => 'Store assistant', 'color' => '#123456', 'position' => 'left'];
$stored_options = wrag_sanitize_options($valid);
check($stored_options['backend_url'] === 'https://public.example/api', 'normalizes URL');
check(wrag_ready(), 'saved options configure bridge');
check(wrag_http_options()['reject_unsafe_urls'], 'saved URL revalidated on every HTTP request');
wrag_chat(new Request());
check($forwarded[0] === 'https://public.example/api/chat', 'saved backend used');
check($forwarded[1]['reject_unsafe_urls'] && $forwarded[1]['redirection'] === 0, 'safe transport prevents rebinding/redirects');
foreach (['http://public.example', 'https://127.0.0.1', 'https://public.example?x=1',
    'https://user:pass@public.example', 'https://public.example/#fragment', 'https://[::1]'] as $url) {
    check(wrag_sanitize_options(array_replace($valid, ['backend_url' => $url])) === $stored_options, 'unsafe URL rejected:' . $url);
}
foreach ([['color' => 'red;display:none'], ['position' => 'top'], ['title' => ''],
    ['bridge_secret' => 'short'], ['title' => []], ['backend_url' => []]] as $invalid) {
    check(wrag_sanitize_options(array_replace($valid, $invalid)) === $stored_options, 'invalid setting preserves prior config');
}
check(wrag_sanitize_options('bad') === $stored_options, 'invalid form shape rejected');
check(wrag_sanitize_options(array_replace($valid, ['bridge_secret' => '']))['bridge_secret'] === str_repeat('s', 32), 'blank secret preserved');
$admin = false;
check(wrag_sanitize_options($valid) === $stored_options, 'non admin cannot save');
check(wrag_diagnostic() === 'forbidden', 'non admin cannot probe');
try { $hooks['admin_post_wrag_diagnostic'][0](); throw new Exception('should forbid'); }
catch (Exception $error) { check($error->getMessage() === 'forbidden', 'diagnostic checks capability'); }
ob_start(); wrag_settings_page(); check(ob_get_clean() === '', 'no settings page for non admin');
$admin = true;
try { $hooks['admin_post_wrag_diagnostic'][0](); throw new Exception('should check nonce'); }
catch (Exception $error) { check($error->getMessage() === 'nonce check reached:wrag_diagnostic', 'diagnostic CSRF checked before network'); }
$upstream['body'] = '{"secret":"not reflected"}';
check(wrag_diagnostic() === 'ready', 'readiness GET succeeds without model');
check($forwarded[0] === 'https://public.example/api/ready' && !isset($forwarded[1]['headers']), 'diagnostic sends no auth/secret');
$upstream['status'] = 503;
check(wrag_diagnostic() === 'unavailable', 'readiness fails closed');
putenv('WRAG_BACKEND_URL=http://backend.internal:8000');
putenv('WRAG_BRIDGE_SECRET=' . str_repeat('e', 32));
check(wrag_setting('bridge_secret') === str_repeat('e', 32), 'environment secret wins');
check(!wrag_http_options()['reject_unsafe_urls'], 'environment retains private demo backend');
ob_start(); wrag_settings_page(); $html = ob_get_clean();
check(!str_contains($html, str_repeat('s', 32)) && !str_contains($html, str_repeat('e', 32)), 'no stored or environment secret in admin HTML');
check(!str_contains(json_encode(wrag_config()->data), str_repeat('s', 32)), 'no secret in public config');
$before = count($hooks['wp_footer']);
require dirname(__DIR__) . '/woo-rag-auth.php';
check(count($hooks['wp_footer']) === $before, 'MU plus regular copy cannot register twice');
echo "PASS: plugin settings, permissions, diagnostics, environment and duplicate loading\n";
