# Lessons

One line each, added through PRs by pipeline runs and curated by a maintainer. Workers read this before every run.

- wporg-theme-directory: as root, Composer skips plugins, so phpcs has no WordPress sniffs. Run `COMPOSER_ALLOW_SUPERUSER=1 composer run-script post-install-cmd` and `TEXTDOMAIN=wporg-themes composer exec update-configs` before `composer lint`.
