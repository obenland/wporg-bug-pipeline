#!/usr/bin/env bash
#
# Setup script for the wporg-pipeline cloud environment. Paste it into the environment's
# "Setup script" field. It runs as root before each session and is cached as a snapshot,
# so keep it under about five minutes. Processes do not survive the snapshot; bin/cloud-setup
# starts dockerd per session.
#
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

# PHP 8.4: the repos' composer.lock files require it; the image ships 8.3.
if ! php -r 'exit(PHP_VERSION_ID >= 80400 ? 0 : 1);' 2>/dev/null; then
	add-apt-repository -y ppa:ondrej/php
	apt-get update -qq
	apt-get install -y -qq php8.4-cli php8.4-curl php8.4-intl php8.4-mbstring php8.4-mysql php8.4-xml php8.4-zip
	update-alternatives --set php /usr/bin/php8.4
fi

# Node 24: wordpress.org's environments/.nvmrc.
if [[ $(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0) -lt 24 ]]; then
	npm install -g n
	n 24
fi

# Anonymous Docker Hub pulls from the shared egress are rate limited (429); use Google's mirror.
mkdir -p /etc/docker
echo '{"registry-mirrors":["https://mirror.gcr.io"]}' > /etc/docker/daemon.json
