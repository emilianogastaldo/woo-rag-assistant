<?php
/**
 * Opt-in: wp eval-file /seed/demo-returns.php 2026-12-18
 * Un solo ordine sintetico, valido anche il giorno dopo (confine dei 30 giorni).
 * Il riferimento resta immutabile: per una nuova data usare un nuovo ambiente demo.
 */
if ( ! defined( 'ABSPATH' ) ) { exit( 1 ); }

$reference = count( $args ) === 1 ? $args[0] : '';
$date = DateTimeImmutable::createFromFormat( '!Y-m-d', $reference, new DateTimeZone( 'UTC' ) );
if ( ! $date || $date->format( 'Y-m-d' ) !== $reference ) {
	WP_CLI::error( 'Specificare una data demo valida: wp eval-file /seed/demo-returns.php YYYY-MM-DD' );
}
$saved_reference = get_option( 'wrag_demo_returns_reference' );
if ( $saved_reference && $saved_reference !== $reference ) {
	WP_CLI::error( 'Riferimento esistente: ' . $saved_reference . '. Per una nuova prova usare un nuovo ambiente demo; le date non vengono spostate.' );
}
$customer = get_user_by( 'email', 'mario.rossi@example.com' );
$product = wc_get_product( wc_get_product_id_by_sku( 'TSHIRT-BIO' ) );
if ( ! $customer || ! $product || ! get_option( 'wrag_seed_orders_done' ) ) {
	WP_CLI::error( 'Eseguire prima il seed ordinario: mancano cliente, prodotto o ordini storici.' );
}

// Il marker nell'ordine recupera anche una run interrotta prima dell'option finale.
$matches = array_filter(
	wc_get_orders( array( 'customer_id' => $customer->ID, 'limit' => -1 ) ),
	static function ( $order ) { return $order->get_meta( '_wrag_demo_returns_fixture' ) === 'v1'; }
);
if ( count( $matches ) > 1 ) {
	WP_CLI::error( 'Più ordini con marker demo resi: verificare il dataset prima di proseguire.' );
}
$delivery = $date->modify( '-29 days' )->format( 'Y-m-d' ) . 'T14:30:00Z';
if ( $matches ) {
	$order = reset( $matches );
	if ( $order->get_meta( '_wrag_demo_returns_reference' ) !== $reference || $order->get_meta( '_wrag_delivery_date' ) !== $delivery ) {
		WP_CLI::error( 'La fixture resi esistente ha date diverse: verificare il dataset, senza riscriverlo.' );
	}
} else {
	// Le fixture sintetiche non devono inviare notifiche email.
	add_filter( 'pre_wp_mail', '__return_false' );
	$order = new WC_Order();
	$order->set_customer_id( $customer->ID );
	$order->set_address( array( 'first_name' => 'Mario', 'last_name' => 'Rossi', 'email' => $customer->user_email, 'country' => 'IT' ), 'billing' );
	$order->set_date_created( $date->modify( '-31 days' )->format( 'Y-m-d' ) . 'T10:15:00Z' );
	$order->set_status( 'completed' );
	$order->set_date_completed( $delivery );
	$order->update_meta_data( '_wrag_delivery_date', $delivery );
	$order->update_meta_data( '_wrag_demo_returns_fixture', 'v1' );
	$order->update_meta_data( '_wrag_demo_returns_reference', $reference );
	// La fixture non è una vendita e deve conservare lo stock del catalogo.
	$skip_stock = static function () { return false; };
	add_filter( 'woocommerce_can_reduce_order_stock', $skip_stock );
	$order->save();
	remove_filter( 'woocommerce_can_reduce_order_stock', $skip_stock );
}
if ( $order->get_meta( '_wrag_demo_returns_ready' ) !== 'yes' ) {
	if ( ! $order->get_items() ) { $order->add_product( $product, 1 ); }
	$order->calculate_totals();
	$order->update_meta_data( '_wrag_demo_returns_ready', 'yes' );
	$order->save();
}
update_option( 'wrag_demo_returns_reference', $reference );
WP_CLI::success( sprintf( 'Demo resi: ordine #%d, riferimento %s, consegna %s. Date e ID conservati alle riesecuzioni.', $order->get_id(), $reference, $delivery ) );
