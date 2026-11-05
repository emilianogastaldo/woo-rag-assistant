<?php
/** wp eval-file /seed/tests/catalog.php; compare output across two seed runs. */
if ( ! defined( 'ABSPATH' ) ) { exit( 1 ); }
require_once '/seed/catalog.php';
function catalog_check( $ok, $message ) {
	if ( ! $ok ) { WP_CLI::error( $message ); }
}
$assets = json_decode( file_get_contents( '/seed/assets/products.json' ), true, 512, JSON_THROW_ON_ERROR );
$rows = array_map( 'str_getcsv', file( '/seed/products.csv', FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES ) );
$header = array_shift( $rows );
$snapshot = array();
foreach ( $rows as $row ) {
	$p = array_combine( $header, $row );
	$product = wc_get_product( wc_get_product_id_by_sku( $p['sku'] ) );
	catalog_check( $product, 'Missing product ' . $p['sku'] );
	foreach ( array( 'name', 'regular_price', 'description', 'short_description' ) as $field ) {
		catalog_check( $product->{ 'get_' . $field }() === $p[ $field ], 'CSV invariant ' . $p['sku'] . ' ' . $field );
	}
	catalog_check( $product->get_stock_quantity() === (int) $p['stock_quantity'], 'CSV stock ' . $p['sku'] );
	catalog_check( $product->get_stock_status() === ( (int) $p['stock_quantity'] > 0 ? 'instock' : 'outofstock' ), 'Stock status ' . $p['sku'] );
	$asset = $assets[ $p['sku'] ];
	$id = $product->get_image_id();
	catalog_check( get_post_meta( $id, '_wrag_seed_asset', true ) === $asset['file'], 'Asset marker ' . $p['sku'] );
	catalog_check( get_post_meta( $id, '_wp_attachment_image_alt', true ) === $asset['alt'], 'Alt ' . $p['sku'] );
	catalog_check( get_post_mime_type( $id ) === 'image/png', 'Raster media ' . $p['sku'] );
	catalog_check( is_file( get_attached_file( $id ) ) && hash_file( 'sha256', get_attached_file( $id ) ) === hash_file( 'sha256', '/seed/assets/' . $asset['file'] ), 'Local original ' . $p['sku'] );
	$meta = wp_get_attachment_metadata( $id );
	catalog_check( $meta['width'] === 800 && $meta['height'] === 800, 'Dimensions ' . $p['sku'] );
	$term = get_term_by( 'slug', $asset['category'], 'product_cat' );
	catalog_check( $term && in_array( $term->term_id, $product->get_category_ids(), true ), 'Category ' . $p['sku'] );
	catalog_check( ! in_array( (int) get_option( 'default_product_cat' ), $product->get_category_ids(), true ), 'No default category ' . $p['sku'] );
	$snapshot[ $p['sku'] ] = array( $product->get_id(), $id, $term->term_id );
}

// A merchant category survives repeated demo updates.
$extra = wp_insert_term( 'Catalog preservation test', 'product_cat', array( 'slug' => 'wrag-catalog-preservation-test' ) );
catalog_check( ! is_wp_error( $extra ), 'Create test category' );
$before = $product->get_category_ids();
$product->set_category_ids( array_merge( $before, array( $extra['term_id'] ) ) );
for ( $i = 0; $i < 2; $i++ ) {
	wrag_seed_product_assets( $product, $asset );
	$product->save();
}
$preserved = in_array( $extra['term_id'], wc_get_product( $product->get_id() )->get_category_ids(), true );
$product->set_category_ids( $before );
$product->save();
wp_delete_term( $extra['term_id'], 'product_cat' );
catalog_check( $preserved, 'Custom category preserved' );

$snapshot['counts'] = array(
	'products' => (int) wp_count_posts( 'product' )->publish,
	'media' => (int) wp_count_posts( 'attachment' )->inherit,
	'categories' => (int) wp_count_terms( array( 'taxonomy' => 'product_cat', 'hide_empty' => false ) ),
);
WP_CLI::log( wp_json_encode( $snapshot ) );
WP_CLI::success( 'Catalog media, categories, CSV invariants and custom category preservation PASS.' );
