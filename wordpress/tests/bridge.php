<?php
// Synthetic trust-boundary checks; native WordPress authentication needs integration.
define('ABSPATH', __DIR__);
putenv('WRAG_BRIDGE_SECRET=synthetic-wordpress-bridge-secret-32chars');
putenv('WRAG_BACKEND_URL=http://backend.internal:8000');
$uid = 101;
$session = 'native-session-a';
$valid_cookie = 101;
$valid_nonce = true;
$forwarded = null;
$upstream = ['body' => '{"reply":"ok"}', 'status' => 200, 'set-cookie' => 'wrag_guest=abc.def; Path=/chat; HttpOnly'];
class WP_Error {
    public function __construct(public $code, public $message, public $data) {}
}
class WP_REST_Response {
    public $headers = [];
    public function __construct(public $data, public $status = 200) {}
    public function header($key, $value) { $this->headers[$key] = $value; }
}
class Request {
    public function __construct(public $body = '{"message":"21"}', public $nonce = 'nonce') {}
    public function get_header($name) { return $this->nonce; }
    public function get_body() { return $this->body; }
    public function get_json_params() { return json_decode($this->body, true); }
}
function add_action(...$args) {}
function wp_verify_nonce(...$args) { global $valid_nonce; return $valid_nonce; }
function wp_get_session_token() { global $session; return $session; }
function is_user_logged_in() { global $uid; return $uid > 0; }
function get_current_user_id() { global $uid; return $uid; }
function wp_validate_auth_cookie(...$args) { global $valid_cookie; return $valid_cookie; }
function wp_get_current_user() { return (object) ['user_email' => 'a@example.test']; }
function wp_json_encode($value) { return json_encode($value); }
function wp_remote_post($url, $options) {
    global $forwarded, $upstream; $forwarded = [$url, $options]; return $upstream;
}
function is_wp_error($value) { return $value instanceof WP_Error; }
function wp_remote_retrieve_body($value) { return $value['body']; }
function wp_remote_retrieve_response_code($value) { return $value['status']; }
function wp_remote_retrieve_header($value, $name) { return $value[$name] ?? ''; }
function wp_parse_url($value, $part) { return parse_url($value, $part); }
function rest_url($path) { return 'https://store.test/wp-json/' . $path; }
function wc_get_page_permalink($page, $fallback = '') {
    global $account_page;
    return $account_page ?: ($fallback ?: 'https://store.test/');
}
function wp_login_url() { return 'https://store.test/wp-login.php'; }
function wp_logout_url($redirect) { return 'https://store.test/wp-login.php?action=logout'; }
function wp_specialchars_decode($value, $flags) { return htmlspecialchars_decode($value, $flags); }
function is_ssl() { return true; }
function check($value, $label) { if (!$value) { throw new Exception($label); } }
require dirname(__DIR__) . '/woo-rag-auth.php';

check(wrag_permission(new Request()) === true, 'logged-in cookie+nonce accepted');
check(wrag_permission(new Request(nonce: ''))->data['status'] === 401, 'missing nonce rejected');
$valid_nonce = false;
check(wrag_permission(new Request())->data['status'] === 403, 'expired nonce rejected');
$valid_nonce = true;
$valid_cookie = false;
check(wrag_permission(new Request())->data['status'] === 401, 'revoked cookie rejected');
$valid_cookie = 101;
$uid = 102;
check(wrag_permission(new Request())->data['status'] === 401, 'mismatched identity rejected');
$uid = 101;
$account_page = null;
check(wrag_config()->data['login_url'] === wp_login_url(), 'missing Woo account page uses native login');
$account_page = 'https://store.test/my-account/';
check(wrag_config()->data['login_url'] === $account_page, 'configured Woo account page preserved');
$config = wrag_config();
check($config->data['authenticated'] && !isset($config->data['token']), 'no browser bearer');
$key = $config->data['session_key'];
$token = wrag_backend_token();
[$prefix, $payload, $signature] = explode('.', $token);
$decode = static fn($v) => base64_decode(strtr($v, '-_', '+/'));
$data = json_decode($decode($payload), true);
check($prefix === 'wp' && $data['sub'] === 'a@example.test' && $data['uid'] === 101
    && $data['exp'] <= time() + 30, 'assertion identity/ttl');
check(hash_equals(hash_hmac('sha256', $decode($payload), getenv('WRAG_BRIDGE_SECRET'), true), $decode($signature)), 'assertion signature');
$session = 'native-session-b';
check(wrag_session_key() !== $key, 'separate native logins');
$response = wrag_chat(new Request());
check($forwarded[0] === 'http://backend.internal:8000/chat', 'fixed server destination');
check(str_starts_with($forwarded[1]['headers']['Authorization'], 'Bearer wp.'), 'server assertion');
check($forwarded[1]['redirection'] === 0 && $forwarded[1]['limit_response_size'] === 65536, 'bounded upstream');
$visitor = $forwarded[1]['headers']['X-WRAG-Visitor'];
[$visitor_payload, $visitor_signature] = explode('.', $visitor);
$visitor_data = json_decode($decode($visitor_payload), true);
check($visitor_data['sub'] === 'auth:' . hash_hmac('sha256', 'auth:101', getenv('WRAG_BRIDGE_SECRET')), 'native account quota');
check($visitor_data['exp'] > time() && $visitor_data['exp'] <= time() + 30, 'quota ttl');
check(hash_equals(hash_hmac('sha256', 'rate-limit:' . $decode($visitor_payload), getenv('WRAG_BRIDGE_SECRET'), true), $decode($visitor_signature)), 'quota purpose-separated signature');
$quota_subject = static fn() => json_decode($decode(explode('.', wrag_visitor_assertion())[0]), true)['sub'];
$session = 'another-native-login';
$_SERVER['REMOTE_ADDR'] = '192.0.2.1';
check($quota_subject() === $visitor_data['sub'], 'relogin and IP changes preserve account quota');
$uid = 102;
check($quota_subject() !== $visitor_data['sub'], 'accounts have independent quotas');
$uid = 101;
check(!isset($response->headers['X-WRAG-Visitor']) && !isset($response->data['X-WRAG-Visitor']), 'quota assertion stays server-side');
check(str_contains($response->headers['Set-Cookie'], 'Path=/wp-json/woo-rag/v1/; HttpOnly; SameSite=Lax; Secure'), 'guest cookie rewritten safely');
check(wrag_chat(new Request('{"message":"21","email":"b@example.test"}'))->data['status'] === 422, 'client email rejected');
check(wrag_chat(new Request('{"message":"21","customer_id":102}'))->data['status'] === 422, 'client ID rejected');
check(wrag_chat(new Request(str_repeat('x', 24001)))->data['status'] === 413, 'body bounded');
$uid = 0;
// Native logout with the old nonce/cookie cannot replay the authenticated session.
$valid_nonce = false;
check(wrag_permission(new Request())->data['status'] === 403, 'logout stale nonce rejected');
check(wrag_permission(new Request(nonce: ''))->data['status'] === 401, 'logout missing nonce rejected');
$session = '';
$valid_nonce = true;
check(wrag_permission(new Request(nonce: '')) === true, 'real guest accepted');
$_COOKIE['wrag_guest'] = 'guest.signature';
wrag_chat(new Request());
check(!isset($forwarded[1]['headers']['Authorization']), 'guest has no order assertion');
check($forwarded[1]['headers']['Cookie'] === 'wrag_guest=guest.signature', 'guest continuity');
$guest_subject = $quota_subject();
check($guest_subject === 'guest:' . hash_hmac('sha256', 'guest:192.0.2.1', getenv('WRAG_BRIDGE_SECRET')), 'guest quota uses socket address');
$_SERVER['HTTP_X_WRAG_VISITOR'] = 'forged-client-identity';
$_SERVER['HTTP_X_FORWARDED_FOR'] = '192.0.2.99';
unset($_COOKIE['wrag_guest']);
check($quota_subject() === $guest_subject, 'browser headers and clearing cookie cannot reset quota');
$_SERVER['REMOTE_ADDR'] = '192.0.2.2';
check($quota_subject() !== $guest_subject, 'guest addresses have independent quotas');
$upstream['status'] = 429;
$upstream['retry-after'] = '37';
check(wrag_chat(new Request())->headers['Retry-After'] === '37', 'quota response retry forwarded');
$upstream['status'] = 200;
$upstream['set-cookie'] = 'arbitrary=secret; Path=/';
check(!isset(wrag_chat(new Request())->headers['Set-Cookie']), 'no arbitrary cookie passthrough');
$upstream['body'] = 'truncated';
check(wrag_chat(new Request())->data['status'] === 502, 'bad upstream fails closed');
putenv('WRAG_BRIDGE_SECRET=');
check(wrag_permission(new Request())->data['status'] === 503, 'disabled without secret');
echo "PASS: WP bridge synthetic permissions, assertions, guests, isolation and boundaries\n";
