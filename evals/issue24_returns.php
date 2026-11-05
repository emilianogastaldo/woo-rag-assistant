<?php
// Eseguire dopo il seed ordinario, soltanto in un ambiente di prova isolato.
function issue24_check( $condition, $message ) {
	if ( ! $condition ) { throw new RuntimeException( $message ); }
}
function issue24_snapshot() {
	$orders = array();
	foreach ( wc_get_orders( array( 'limit' => -1, 'orderby' => 'ID', 'order' => 'ASC' ) ) as $order ) {
		$orders[ $order->get_id() ] = $order->get_data();
	}
	return wp_json_encode( $orders );
}
$before = wc_get_orders( array( 'limit' => -1 ) );
$stock = wc_get_product( wc_get_product_id_by_sku( 'TSHIRT-BIO' ) )->get_stock_quantity();
issue24_check( count( $before ) === 3, 'Start with exactly the three historical orders' );
$historic = array();
foreach ( $before as $order ) { $historic[ $order->get_id() ] = wp_json_encode( $order->get_data() ); }
$args = array( '2026-12-18' );
ob_start();
include '/seed/demo-returns.php';
ob_end_clean();
$first_run = issue24_snapshot();
ob_start();
include '/seed/demo-returns.php';
ob_end_clean();
issue24_check( issue24_snapshot() === $first_run, 'Rerun changed order dates, data or count' );
delete_option( 'wrag_demo_returns_reference' );
ob_start();
include '/seed/demo-returns.php';
ob_end_clean();
issue24_check( issue24_snapshot() === $first_run, 'Partial-run recovery duplicated or changed an order' );
issue24_check( wc_get_product( wc_get_product_id_by_sku( 'TSHIRT-BIO' ) )->get_stock_quantity() === $stock, 'Returns fixture changed catalog stock' );
issue24_check( get_option( 'wrag_demo_returns_reference' ) === '2026-12-18', 'Reference was not restored' );
$result = array( 'status' => 'PASS', 'reference' => '2026-12-18', 'orders' => array() );
$all = wc_get_orders( array( 'limit' => -1 ) );
issue24_check( count( $all ) === 4, 'Expected just one additional order' );
foreach ( $all as $order ) {
	if ( isset( $historic[ $order->get_id() ] ) ) {
		issue24_check( wp_json_encode( $order->get_data() ) === $historic[ $order->get_id() ], 'Historical order changed' );
	}
	$marker = $order->get_meta( '_wrag_demo_returns_fixture' );
	if ( $marker ) {
		issue24_check( $marker === 'v1' && $order->get_meta( '_wrag_delivery_date' ) === '2026-11-19T14:30:00Z', 'Wrong synthetic delivery' );
		issue24_check( $order->get_status() === 'completed' && count( $order->get_items() ) === 1, 'Incomplete synthetic order' );
		issue24_check( $order->get_date_created()->date( DATE_ATOM ) === '2026-11-17T10:15:00+00:00', 'Wrong synthetic creation date' );
		issue24_check( $order->get_date_completed()->date( DATE_ATOM ) === '2026-11-19T14:30:00+00:00', 'Completion date must be fixed, not the run clock' );
	}
	$result['orders'][] = array(
		'id' => $order->get_id(), 'customer_id' => $order->get_customer_id(),
		'status' => $order->get_status(),
		'date_created' => $order->get_date_created()->date( DATE_ATOM ),
		'date_completed' => $order->get_date_completed() ? $order->get_date_completed()->date( DATE_ATOM ) : null,
		'meta_data' => array( array( 'key' => '_wrag_delivery_date', 'value' => $order->get_meta( '_wrag_delivery_date' ) ) ),
		'fixture' => $marker,
	);
}
echo wp_json_encode( $result, JSON_PRETTY_PRINT ) . "\n";
