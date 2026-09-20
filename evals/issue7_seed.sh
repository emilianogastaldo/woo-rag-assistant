#!/bin/sh
set -eu
remaining=60
while [ ! -f wp-config.php ]; do
    remaining=$((remaining - 1))
    [ "$remaining" -gt 0 ] || exit 1
    sleep 1
done
wp core install --url=http://wordpress --title=Synthetic --admin_user=synthetic --admin_password=synthetic-password --admin_email=synthetic@example.invalid --skip-email
wp plugin activate woocommerce
wp rewrite structure '/%postname%/'
wp rewrite flush --hard
wp eval-file /seed.php
