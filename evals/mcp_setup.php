<?php
/** Disposable MCP fixture: no administrator credentials passed to the client. */
if ( ! get_role( 'mcp_catalog_reader' ) ) {
    add_role( 'mcp_catalog_reader', 'MCP catalog reader', array( 'read' => true, 'read_private_products' => true ) );
}
foreach ( array( 'mcp-reader' => 'mcp_catalog_reader', 'mcp-denied' => 'subscriber' ) as $login => $role ) {
    if ( ! username_exists( $login ) ) {
        $id = wp_insert_user( array( 'user_login' => $login, 'user_pass' => wp_generate_password( 48 ), 'role' => $role ) );
        if ( is_wp_error( $id ) ) { WP_CLI::error( 'Cannot create MCP fixture user' ); }
    }
}
$products = array();
foreach ( wc_get_products( array( 'limit' => -1, 'status' => 'publish' ) ) as $product ) {
    $products[ $product->get_sku() ] = array(
        'id' => $product->get_id(), 'name' => $product->get_name(),
        'price' => $product->get_price(), 'stock_quantity' => $product->get_stock_quantity(),
        'stock_status' => $product->get_stock_status(),
    );
}
ksort( $products );
echo wp_json_encode( $products );
