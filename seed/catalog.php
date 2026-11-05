<?php
/** Local PNG media and additive categories for the six demo SKUs. */
if ( ! defined( 'ABSPATH' ) ) { exit( 1 ); }

function wrag_seed_product_assets( $product, $asset ) {
	$categories = array( 'abbigliamento' => 'Abbigliamento', 'scarpe' => 'Scarpe', 'accessori' => 'Accessori' );
	$slug = $asset['category'];
	$term = term_exists( $slug, 'product_cat' );
	if ( ! $term ) {
		$term = wp_insert_term( $categories[ $slug ], 'product_cat', array( 'slug' => $slug ) );
	}
	if ( is_wp_error( $term ) ) { WP_CLI::error( $term->get_error_message() ); }
	$category_ids = array_diff( $product->get_category_ids(), array( (int) get_option( 'default_product_cat' ) ) );
	$product->set_category_ids( array_unique( array_merge( $category_ids, array( (int) $term['term_id'] ) ) ) );

	$attachments = get_posts( array(
		'post_type' => 'attachment', 'post_status' => 'inherit', 'numberposts' => 1,
		'meta_key' => '_wrag_seed_asset', 'meta_value' => $asset['file'],
	) );
	if ( $attachments ) {
		$id = $attachments[0]->ID;
	} else {
		require_once ABSPATH . 'wp-admin/includes/file.php';
		require_once ABSPATH . 'wp-admin/includes/media.php';
		require_once ABSPATH . 'wp-admin/includes/image.php';
		$source = __DIR__ . '/assets/' . $asset['file'];
		$temp = wp_tempnam( $asset['file'] );
		if ( ! $temp || ! copy( $source, $temp ) ) {
			if ( $temp ) { unlink( $temp ); }
			WP_CLI::error( 'Cannot copy catalog asset: ' . $asset['file'] );
		}
		$id = media_handle_sideload( array( 'name' => $asset['file'], 'tmp_name' => $temp ), $product->get_id(), $product->get_name() );
		if ( is_wp_error( $id ) ) {
			if ( file_exists( $temp ) ) { unlink( $temp ); }
			WP_CLI::error( $id->get_error_message() );
		}
		update_post_meta( $id, '_wrag_seed_asset', $asset['file'] );
	}
	update_post_meta( $id, '_wp_attachment_image_alt', $asset['alt'] );
	$product->set_image_id( $id );
}
