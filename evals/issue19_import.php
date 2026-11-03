<?php
// Invoked only by run_issue19_import.py in a disposable, network-isolated store.
function issue19_check( $condition, $message ) {
    if ( ! $condition ) { throw new RuntimeException( $message ); }
}
issue19_check( WC_VERSION === '10.0.4', 'Expected WooCommerce 10.0.4' );
issue19_check( count( wc_get_products( [ 'limit' => -1 ] ) ) === 6, 'Seed must contain six products after two runs' );
issue19_check( count( wc_get_orders( [ 'limit' => -1 ] ) ) === 3, 'Seed must contain three orders after two runs' );
issue19_check( wc_get_product( wc_get_product_id_by_sku( 'SHOES-RUN-X' ) )->get_stock_status() === 'outofstock', 'Missing out-of-stock fixture' );
issue19_check( wc_get_product( wc_get_product_id_by_sku( 'TSHIRT-BIO' ) )->get_stock_quantity() === 42, 'Seed rerun must reset stock' );
foreach ( [ 'spedizioni', 'resi-e-rimborsi', 'domande-frequenti' ] as $slug ) {
    issue19_check( (bool) get_page_by_path( $slug ), 'Missing knowledge page: ' . $slug );
}
foreach ( [ 'mario.rossi@example.com', 'luigi.verdi@example.com' ] as $email ) {
    issue19_check( (bool) get_user_by( 'email', $email ), 'Missing customer' );
}
$delivered = wc_get_orders( [ 'status' => 'completed', 'limit' => -1 ] );
issue19_check( count( $delivered ) === 1 && $delivered[0]->get_meta( '_wrag_delivery_date' ) === '2026-06-22T14:30:00Z', 'Missing verified delivery fixture' );

require_once ABSPATH . 'wp-admin/includes/class-wp-importer.php';
require_once WC_ABSPATH . 'includes/import/class-wc-product-csv-importer.php';
require_once WC_ABSPATH . 'includes/admin/importers/class-wc-product-csv-importer-controller.php';
class Issue19_Mapping extends WC_Product_CSV_Importer_Controller {
    public function columns( $headers ) { return $this->auto_map_columns( $headers, false ); }
}
$csv = WC_ABSPATH . 'sample-data/sample_products.csv';
issue19_check( hash_file( 'sha256', $csv ) === '1d6f48b6f33fdc04615a9722c59f8cb8a07ed62e94a1dc3237313983d1884721', 'Official sample checksum mismatch' );
$handle = fopen( $csv, 'r' );
$headers = fgetcsv( $handle );
$headers[0] = ltrim( $headers[0], "\xEF\xBB\xBF" );
fclose( $handle );
$mapping = ( new Issue19_Mapping() )->columns( $headers );
// Source IDs and remote assets do not belong to this disposable store.
$mapping['ID'] = '';
$mapping['Images'] = '';
foreach ( $headers as $header ) {
    if ( preg_match( '/^Download [12] (name|URL)$/', $header ) ) { $mapping[ $header ] = ''; }
}
$http_attempts = 0;
add_filter( 'pre_http_request', function () use ( &$http_attempts ) {
    ++$http_attempts;
    return new WP_Error( 'issue19_network_forbidden', 'External HTTP disabled during import' );
}, 1 );
$runs = [];
foreach ( [ false, false, true ] as $update ) {
    $importer = new WC_Product_CSV_Importer( $csv, [ 'mapping' => $mapping, 'parse' => true, 'update_existing' => $update, 'prevent_timeouts' => false ] );
    $result = $importer->import();
    issue19_check( ! $result['failed'], 'Native importer failed: ' . wp_json_encode( $result['failed'] ) );
    $runs[] = array_map( 'count', $result );
}
issue19_check( $runs[0]['imported'] === 18 && $runs[0]['imported_variations'] === 7, 'Unexpected first import totals: ' . wp_json_encode( $runs ) );
issue19_check( $runs[1]['skipped'] === 25, 'Second create-only import must skip duplicate SKUs' );
issue19_check( $runs[2]['updated'] === 25, 'Update import must match all SKUs' );
issue19_check( count( wc_get_products( [ 'limit' => -1 ] ) ) === 24, 'Expected six seed plus eighteen official products' );
$parents = [ 'woo-vneck-tee' => 3, 'woo-hoodie' => 4 ];
foreach ( $parents as $sku => $count ) {
    $parent = wc_get_product( wc_get_product_id_by_sku( $sku ) );
    issue19_check( $parent->is_type( 'variable' ) && count( $parent->get_children() ) === $count, 'Variation relationship mismatch' );
}
$beanie = wc_get_product( wc_get_product_id_by_sku( 'woo-beanie' ) );
issue19_check( $beanie->get_regular_price() === '20' && $beanie->get_sale_price() === '18' && $beanie->get_price() === '18', 'Sale price mismatch' );
issue19_check( ! $beanie->get_manage_stock() && $beanie->get_stock_quantity() === null && $beanie->get_stock_status() === 'instock', 'Official sample should not imply numeric stock' );
$variation = wc_get_product( wc_get_product_id_by_sku( 'woo-hoodie-red' ) );
issue19_check( $variation->is_type( 'variation' ) && $variation->get_price() === '42', 'Variation sale price mismatch' );
foreach ( [ 'woo-album', 'woo-single' ] as $sku ) {
    $product = wc_get_product( wc_get_product_id_by_sku( $sku ) );
    issue19_check( $product->is_downloadable() && $product->is_virtual() && ! $product->get_downloads(), 'Expected downloadable flag without remote files' );
}
issue19_check( $http_attempts === 0, 'Import attempted HTTP calls' );
echo wp_json_encode( [ 'status' => 'PASS', 'woocommerce' => WC_VERSION, 'seed_runs' => 2, 'official_sha256' => hash_file( 'sha256', $csv ), 'imports' => $runs, 'products' => 24, 'variations' => 7, 'external_http_attempts' => $http_attempts ], JSON_PRETTY_PRINT ) . "\n";
