#!/bin/sh
# Render squid.conf from template, then run squid in foreground.
set -e
GATEWAY_URL="${GATEWAY_URL:-http://192.168.1.8:8080}"
sed "s|__GATEWAY_URL__|${GATEWAY_URL}|g" /etc/squid/squid.conf.template > /etc/squid/squid.conf
exec squid -N -f /etc/squid/squid.conf
