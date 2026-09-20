<?php
// Only the isolated test project invokes this file. No real customer/order data.
wp_insert_post(['post_type'=>'page', 'post_status'=>'publish', 'post_name'=>'spedizioni',
    'post_title'=>'Spedizioni sintetiche', 'post_content'=>'Spedizione versione A in tre giorni.']);
$product = new WC_Product_Simple();
$product->set_name('Prodotto sintetico');
$product->set_sku('SYN-007');
$product->set_status('publish');
$product->set_description('Descrizione sintetica versione A.');
$product->set_regular_price('10');
$product->save();
global $wpdb;
if (false === $wpdb->insert($wpdb->prefix . 'woocommerce_api_keys', [
    'user_id'=>1, 'description'=>'issue7 synthetic read only', 'permissions'=>'read',
    'consumer_key'=>wc_api_hash('ck_synthetic'), 'consumer_secret'=>'cs_synthetic',
    'truncated_key'=>'nthetic',
])) {
    throw new RuntimeException('Synthetic API key insert failed');
}
