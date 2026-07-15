<?php
/**
 * Seed dati demo per woo-rag-assistant.
 * Eseguito via: wp eval-file /seed/seed.php  (dentro il container wpcli)
 *
 * Idempotente:
 *  - prodotti  -> chiave naturale SKU
 *  - pagine    -> chiave naturale slug
 *  - clienti   -> chiave naturale email
 *  - ordini    -> gate su option 'wrag_seed_orders_done'
 *  - API key   -> gate su description; alla creazione stampa le chiavi
 *
 * Stampa una riga marker "__WC_KEYS__ <ck> <cs>" alla prima generazione
 * della chiave API read-only (le chiavi in chiaro non sono recuperabili dopo).
 */

if ( ! defined( 'ABSPATH' ) ) { exit( 1 ); }

function wrag_log( $msg ) { WP_CLI::log( $msg ); }

/* -------------------------------------------------------------------------
 * 1. Prodotti (da products.csv, idempotenti per SKU)
 * ---------------------------------------------------------------------- */
wrag_log( '== Prodotti ==' );
$csv_path = '/seed/products.csv';
$lines    = array_map( 'str_getcsv', file( $csv_path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES ) );
$header   = array_shift( $lines );

foreach ( $lines as $row ) {
	$p        = array_combine( $header, $row );
	$existing = wc_get_product_id_by_sku( $p['sku'] );
	$product  = $existing ? wc_get_product( $existing ) : new WC_Product_Simple();

	$product->set_name( $p['name'] );
	$product->set_sku( $p['sku'] );
	$product->set_regular_price( $p['regular_price'] );
	$product->set_description( $p['description'] );
	$product->set_short_description( $p['short_description'] );
	$product->set_manage_stock( true );
	$product->set_stock_quantity( (int) $p['stock_quantity'] );
	$product->set_stock_status( ( (int) $p['stock_quantity'] ) > 0 ? 'instock' : 'outofstock' );
	$product->set_catalog_visibility( 'visible' );
	$product->set_status( 'publish' );
	$product->save();

	wrag_log( sprintf( '  %s %s (stock %d)', $existing ? '~' : '+', $p['sku'], (int) $p['stock_quantity'] ) );
}

/* -------------------------------------------------------------------------
 * 2. Pagine informative (da docs/*.md, idempotenti per slug) -> knowledge RAG
 * ---------------------------------------------------------------------- */
wrag_log( '== Pagine ==' );
$pages = array(
	array( 'slug' => 'spedizioni',        'title' => 'Spedizioni',           'file' => '/seed/docs/spedizioni.md' ),
	array( 'slug' => 'resi-e-rimborsi',   'title' => 'Resi e Rimborsi',      'file' => '/seed/docs/resi.md' ),
	array( 'slug' => 'domande-frequenti', 'title' => 'Domande Frequenti',    'file' => '/seed/docs/faq.md' ),
);
foreach ( $pages as $pg ) {
	$content  = file_get_contents( $pg['file'] );
	$existing = get_page_by_path( $pg['slug'], OBJECT, 'page' );
	$postarr  = array(
		'post_title'   => $pg['title'],
		'post_name'    => $pg['slug'],
		'post_content' => $content,
		'post_status'  => 'publish',
		'post_type'    => 'page',
	);
	if ( $existing ) {
		$postarr['ID'] = $existing->ID;
		wp_update_post( $postarr );
		wrag_log( '  ~ ' . $pg['slug'] );
	} else {
		wp_insert_post( $postarr );
		wrag_log( '  + ' . $pg['slug'] );
	}
}

/* -------------------------------------------------------------------------
 * 3. Clienti demo (idempotenti per email)
 * ---------------------------------------------------------------------- */
wrag_log( '== Clienti ==' );
$customers = array(
	'A' => array( 'email' => 'mario.rossi@example.com', 'first' => 'Mario', 'last' => 'Rossi',  'user' => 'mario.rossi' ),
	'B' => array( 'email' => 'luigi.verdi@example.com', 'first' => 'Luigi', 'last' => 'Verdi',  'user' => 'luigi.verdi' ),
);
$customer_ids = array();
foreach ( $customers as $key => $c ) {
	$u = get_user_by( 'email', $c['email'] );
	if ( $u ) {
		$customer_ids[ $key ] = $u->ID;
		wrag_log( '  ~ ' . $c['email'] . ' (ID ' . $u->ID . ')' );
		continue;
	}
	$uid = wc_create_new_customer( $c['email'], $c['user'], 'demo_secret_' . strtolower( $key ) );
	if ( is_wp_error( $uid ) ) {
		WP_CLI::warning( 'Cliente ' . $c['email'] . ': ' . $uid->get_error_message() );
		continue;
	}
	update_user_meta( $uid, 'first_name', $c['first'] );
	update_user_meta( $uid, 'last_name', $c['last'] );
	update_user_meta( $uid, 'billing_first_name', $c['first'] );
	update_user_meta( $uid, 'billing_last_name', $c['last'] );
	update_user_meta( $uid, 'billing_email', $c['email'] );
	$customer_ids[ $key ] = $uid;
	wrag_log( '  + ' . $c['email'] . ' (ID ' . $uid . ')' );
}

/* -------------------------------------------------------------------------
 * 4. Ordini demo (gate su option, per non duplicare a ogni run)
 * ---------------------------------------------------------------------- */
wrag_log( '== Ordini ==' );
if ( get_option( 'wrag_seed_orders_done' ) ) {
	wrag_log( '  (gia presenti, salto)' );
} else {
	// Cliente A: ordine completato ~25 giorni fa (utile per scenario reso).
	$specs = array(
		array(
			'customer' => 'A',
			'status'   => 'completed',
			'date'     => '2026-06-20 10:15:00',
			'items'    => array( array( 'TSHIRT-BIO', 2 ), array( 'BOTTLE-THERMO', 1 ) ),
		),
		// Cliente A: secondo ordine in lavorazione (spedizione in corso).
		array(
			'customer' => 'A',
			'status'   => 'processing',
			'date'     => '2026-07-11 09:30:00',
			'items'    => array( array( 'BACKPACK-URBAN', 1 ) ),
		),
		// Cliente B: ordine in lavorazione (serve per lo scenario "ordine altrui").
		array(
			'customer' => 'B',
			'status'   => 'processing',
			'date'     => '2026-07-12 16:45:00',
			'items'    => array( array( 'HOODIE-CLASSIC', 1 ) ),
		),
	);
	foreach ( $specs as $s ) {
		if ( empty( $customer_ids[ $s['customer'] ] ) ) { continue; }
		$order = wc_create_order( array( 'customer_id' => $customer_ids[ $s['customer'] ] ) );
		foreach ( $s['items'] as $it ) {
			$pid = wc_get_product_id_by_sku( $it[0] );
			if ( $pid ) { $order->add_product( wc_get_product( $pid ), $it[1] ); }
		}
		$cust = $customers[ $s['customer'] ];
		$order->set_address(
			array(
				'first_name' => $cust['first'],
				'last_name'  => $cust['last'],
				'email'      => $cust['email'],
				'country'    => 'IT',
			),
			'billing'
		);
		$order->set_date_created( $s['date'] );
		$order->calculate_totals();
		$order->set_status( $s['status'] );
		$order->save();
		wrag_log( sprintf( '  + ordine #%d cliente %s (%s)', $order->get_id(), $s['customer'], $s['status'] ) );
	}
	update_option( 'wrag_seed_orders_done', 1 );
}

/* -------------------------------------------------------------------------
 * 5. Chiave API REST read-only (idempotente per description)
 * ---------------------------------------------------------------------- */
wrag_log( '== API key read-only ==' );
global $wpdb;
$table       = $wpdb->prefix . 'woocommerce_api_keys';
$description = 'woo-rag-assistant read-only';
$exists      = $wpdb->get_var( $wpdb->prepare( "SELECT key_id FROM {$table} WHERE description = %s", $description ) );

if ( $exists ) {
	wrag_log( '  (chiave gia presente: per rigenerarla eliminala e riesegui)' );
} else {
	$admin           = get_user_by( 'login', 'admin' );
	$consumer_key    = 'ck_' . wc_rand_hash();
	$consumer_secret = 'cs_' . wc_rand_hash();
	$wpdb->insert(
		$table,
		array(
			'user_id'         => $admin ? $admin->ID : 1,
			'description'     => $description,
			'permissions'     => 'read',
			'consumer_key'    => wc_api_hash( $consumer_key ),
			'consumer_secret' => $consumer_secret,
			'truncated_key'   => substr( $consumer_key, -7 ),
		),
		array( '%d', '%s', '%s', '%s', '%s', '%s' )
	);
	wrag_log( '  + chiave read-only creata' );
	// Marker machine-readable: consumato dallo script che aggiorna .env.
	WP_CLI::log( '__WC_KEYS__ ' . $consumer_key . ' ' . $consumer_secret );
}

WP_CLI::success( 'Seed completato.' );
