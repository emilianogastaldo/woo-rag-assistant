<?php
/** Real WordPress/WooCommerce check: wp eval-file /storefront-test.php. */
if ( ! defined( 'ABSPATH' ) ) { exit( 1 ); }
require_once '/seed/markdown.php';
function trama_check( $ok, $message ) {
	if ( ! $ok ) { WP_CLI::error( $message ); }
}
trama_check( get_stylesheet() === 'trama', 'Child theme active' );
trama_check( get_template() === 'twentytwentyfive', 'Parent theme reused' );
$front = (int) get_option( 'page_on_front' );
trama_check( $front > 0 && get_option( 'show_on_front' ) === 'page', 'Static homepage configured' );
foreach ( array( 'spedizioni', 'resi-e-rimborsi', 'domande-frequenti' ) as $slug ) {
	$page = get_page_by_path( $slug, OBJECT, 'page' );
	trama_check( $page && str_contains( $page->post_content, '<h2>' ), 'Formatted policy ' . $slug );
	trama_check( ! preg_match( '/^#+ |\*\*/m', $page->post_content ), 'No raw Markdown ' . $slug );
}
trama_check( str_contains( wrag_seed_markdown( "# Title\n\n## Heading\n\n- **Bold**\n- Other\n\n1. First\n2. Second\n\n<script>bad()</script>" ), '<ol><li>First</li>' ), 'Ordered lists' );
trama_check( str_contains( wrag_seed_markdown( '<script>bad()</script>' ), '&lt;script&gt;' ), 'HTML escaped' );
trama_check( wrag_seed_markdown( "# Page\n\n## Heading\nParagraph." ) === "<h2>Heading</h2>\n<p>Paragraph.</p>", 'Heading adjacent to paragraph' );
foreach ( array( 'spedizioni' => 'spedizioni', 'resi-e-rimborsi' => 'resi', 'domande-frequenti' => 'faq' ) as $slug => $file ) {
	$source = file_get_contents( '/seed/docs/' . $file . '.md' );
	$source = preg_replace( '/^# [^\r\n]+\R*/', '', $source );
	$source = preg_replace( '/^(?:## |- |\d+\. )/m', '', $source );
	$source = str_replace( '**', '', $source );
	$rendered = html_entity_decode( strip_tags( get_page_by_path( $slug, OBJECT, 'page' )->post_content ), ENT_QUOTES, 'UTF-8' );
	trama_check( preg_replace( '/\s+/u', ' ', trim( $source ) ) === preg_replace( '/\s+/u', ' ', trim( $rendered ) ), 'Policy text preserved ' . $slug );
}
$pages = wp_count_posts( 'page' )->publish;
$menus = count( wp_get_nav_menus() );
$title = get_option( 'blogname' );
update_option( 'blogname', 'Personalizzazione conservata' );
update_option( 'trama_unrelated_test', 'preserved' );
include '/seed/storefront.php';
trama_check( get_option( 'blogname' ) === 'Personalizzazione conservata', 'Repeat preserves title changes' );
trama_check( get_option( 'trama_unrelated_test' ) === 'preserved', 'Repeat preserves unrelated option' );
trama_check( (int) get_option( 'page_on_front' ) === $front, 'Same homepage' );
trama_check( wp_count_posts( 'page' )->publish === $pages && count( wp_get_nav_menus() ) === $menus, 'No duplicate pages or menus' );
update_option( 'blogname', $title );
delete_option( 'trama_unrelated_test' );
$navigation = do_shortcode( '[trama_navigation]' );
trama_check( substr_count( $navigation, '<a ' ) === 5, 'Five navigation destinations' );
trama_check( str_contains( $navigation, esc_url( wc_get_page_permalink( 'myaccount' ) ) ), 'Native account URL' );
WP_CLI::success( 'Trama: theme, Markdown semantics, safe repeat, navigation PASS.' );
