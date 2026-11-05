<?php
/** Apply only the demo storefront; safe to run without reseeding stock or orders. */
if ( ! defined( 'ABSPATH' ) ) { exit( 1 ); }

if ( get_option( 'wrag_storefront_v1' ) ) {
	WP_CLI::success( 'Storefront Trama gia configurato; personalizzazioni conservate.' );
	return;
}
if ( ! wp_get_theme( 'trama' )->exists() || ! wp_get_theme( 'twentytwentyfive' )->exists() ) {
	WP_CLI::error( 'Servono i temi locali trama e twentytwentyfive. Controlla i mount Docker.' );
}
if ( ! class_exists( 'WC_Install' ) ) {
	WP_CLI::error( 'Attiva WooCommerce prima di configurare Trama.' );
}
WC_Install::create_pages(); // WooCommerce preserves existing assigned pages.
$home = get_page_by_path( 'trama-home', OBJECT, 'page' );
if ( ! $home ) {
	$home_id = wp_insert_post( array(
		'post_title' => 'Trama — essenziali per ogni giorno',
		'post_name' => 'trama-home',
		'post_content' => '',
		'post_status' => 'publish',
		'post_type' => 'page',
	), true );
	if ( is_wp_error( $home_id ) ) { WP_CLI::error( $home_id->get_error_message() ); }
} else {
	$home_id = $home->ID;
}
switch_theme( 'trama' );
update_option( 'blogname', 'Trama' );
update_option( 'blogdescription', 'Essenziali per ogni giorno' );
update_option( 'show_on_front', 'page' );
update_option( 'page_on_front', $home_id );
update_option( 'wrag_storefront_v1', 1 );
WP_CLI::success( 'Storefront Trama configurato.' );
