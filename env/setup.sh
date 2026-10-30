#!/usr/bin/env bash
#
# Setup script for the wporg-pipeline cloud environment. Paste it into the environment's
# "Setup script" field. It runs as root before each session and is cached as a snapshot,
# so keep it under about five minutes. Processes do not survive the snapshot; bin/cloud-setup
# starts dockerd per session.
#
# A failing step only warns: a setup failure would block every run, idle ones included, and
# bin/cloud-setup works around an old PHP or Node.
#
set -uo pipefail
export DEBIAN_FRONTEND=noninteractive

warn() { echo "setup: $*" >&2; }

# PHP 8.4: the repos' composer.lock files require it; the image ships 8.3.
# add-apt-repository is broken in the image (no apt_pkg), so the PPA is added by hand.
if ! php -r 'exit(PHP_VERSION_ID >= 80400 ? 0 : 1);' 2>/dev/null; then
	{
		curl -fsSL 'https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x14AA40EC0831756756D7F66C4F4EA0AAE5267A6C' \
			| gpg --batch --yes --dearmor -o /usr/share/keyrings/ondrej-php.gpg &&
		echo "deb [signed-by=/usr/share/keyrings/ondrej-php.gpg] https://ppa.launchpadcontent.net/ondrej/php/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") main" \
			> /etc/apt/sources.list.d/ondrej-php.list &&
		apt-get update -qq &&
		apt-get install -y -qq php8.4-cli php8.4-curl php8.4-intl php8.4-mbstring php8.4-mysql php8.4-xml php8.4-zip &&
		update-alternatives --set php /usr/bin/php8.4
	} || warn "PHP 8.4 install failed; composer runs with --ignore-platform-req=php"
fi

# Node 24: wordpress.org's environments/.nvmrc.
if [[ $(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0) -lt 24 ]]; then
	{ npm install -g n && n 24; } || warn "Node 24 install failed"
fi

command -v jq >/dev/null || apt-get install -y -qq jq || warn "jq install failed"

# Anonymous Docker Hub pulls from the shared egress are rate limited; use Google's mirror.
mkdir -p /etc/docker
echo '{"registry-mirrors":["https://mirror.gcr.io"]}' > /etc/docker/daemon.json

exit 0
