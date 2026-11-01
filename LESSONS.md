# Lessons

One line each, added through PRs by pipeline runs and curated by a maintainer. Workers read this before every run.

- wporg-theme-directory: as root, Composer skips plugins, so phpcs has no WordPress sniffs. Run `COMPOSER_ALLOW_SUPERUSER=1 composer run-script post-install-cmd` and `TEXTDOMAIN=wporg-themes composer exec update-configs` before `composer lint`.
- wordpress.org: as root, Composer skips plugins, so `bin/test-wordpress-org` phpcs fails with "Referenced sniff WordPress does not exist". Run `COMPOSER_ALLOW_SUPERUSER=1 composer run-script post-install-cmd` in the checkout first. The wp-env image build (`apk update`) cannot resolve dl-cdn.alpinelinux.org in the cloud sandbox, so PHPUnit/smoke cannot run there; say so in Testing.
