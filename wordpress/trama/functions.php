<?php
defined( 'ABSPATH' ) || exit;

add_action( 'wp_enqueue_scripts', static function () {
	wp_enqueue_style( 'trama', get_stylesheet_uri(), array(), wp_get_theme()->get( 'Version' ) );
} );
add_action( 'after_setup_theme', static function () {
	add_theme_support( 'woocommerce' );
} );

add_shortcode( 'trama_navigation', static function () {
	$links = array( wc_get_page_permalink( 'shop' ) => 'Negozio' );
	foreach ( array( 'spedizioni' => 'Spedizioni', 'resi-e-rimborsi' => 'Resi', 'domande-frequenti' => 'FAQ' ) as $slug => $label ) {
		$page = get_page_by_path( $slug, OBJECT, 'page' );
		if ( $page ) { $links[ get_permalink( $page ) ] = $label; }
	}
	$links[ wc_get_page_permalink( 'myaccount' ) ] = 'Il mio account';
	$html = '<nav class="trama-nav" aria-label="Navigazione principale">';
	foreach ( $links as $url => $label ) {
		$html .= '<a href="' . esc_url( $url ) . '">' . esc_html( $label ) . '</a>';
	}
	return $html . '</nav>';
} );
add_shortcode( 'trama_shop_link', static function () {
	return '<a class="trama-cta" href="' . esc_url( wc_get_page_permalink( 'shop' ) ) . '">Esplora il negozio <span aria-hidden="true">↗</span></a>';
} );
