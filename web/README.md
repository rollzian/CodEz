# CodEz Web

PHP 8.3+ website for codez.auxia.space. The existing Go CLI and Python Cloud API remain unchanged. The current CLI requires https://auxia.space/codez-cloud and its existing device verification origin.

## Deployment

- PHP FPM with curl, pdo_pgsql and phpredis.
- PostgreSQL database dedicated to the marketplace.
- Private Redis instance, with authentication and network restrictions.
- HTTPS virtual host with document root web/public. Adapt deploy/nginx.conf to the installed PHP-FPM socket.
- Private PHP session directory with owner-only access. Shared session storage is required before deploying multiple web instances.

Apply the marketplace migration using the database owner:

    psql "$CODEZ_MIGRATION_DSN" -v ON_ERROR_STOP=1 -f web/db/001_marketplace.sql

Grant the restricted application database account SELECT, INSERT, UPDATE and DELETE on the marketplace tables and USAGE on identity sequences. Do not give it schema creation or administrative privileges.

Set PHP-FPM environment variables (not in the document root):

    CODEZ_WEB_DSN=pgsql:host=127.0.0.1;dbname=codez_market
    CODEZ_WEB_DB_USER=codez_web
    CODEZ_WEB_DB_PASSWORD=...
    CODEZ_REDIS_HOST=127.0.0.1
    CODEZ_REDIS_PORT=6379
    CODEZ_REDIS_PASSWORD=...
    CODEZ_RELEASE_DIR=/srv/codez/releases
    CODEZ_ADMIN_IDS=comma-separated-cloud-user-ids

Set upload_max_filesize=2M, post_max_size=3M, display_errors=Off and log_errors=On. Keep release directory writable only by the release publisher, not PHP. Set the HTTP vhost to redirect to HTTPS. Disable sensitive request logging, especially on the existing Cloud activation endpoint.

The configured local release filename is codez#1a-v1.deb; the URL is /downloads/codez%231a-v1.deb. The local download appears only if the file is present. Publish the real signed-off build separately; GitHub Releases remain independent. The website does not change release.env or claim that 0.7.8 has shipped.

The browser account uses the same existing device start/poll API as the CLI. The resulting bearer token remains in the server-side session. No separate password database is created. Live login requires an operational Cloud deployment and the actual Auxia OAuth authorization, token, userinfo and client registration settings documented in the root README. Do not infer OAuth support from the login URL alone.

Marketplace downloads are attachments and never executed server-side. Administrators must inspect untrusted packages offline in an isolated environment before approval. Compatibility and dependencies are publisher-supplied metadata, not an automatic compatibility guarantee. Download history tracks one distinct account per version, not confirmed CLI installations. Subscriptions are saved in the user library; external notifications are not implemented.

## Checks

    find web -name '*.php' -print0 | xargs -0 -n1 php -l
    php web/tests/releases.php
    node --check web/public/assets/site.js

Live database/Redis, OAuth, and HTTPS tests must pass against the target deployment before production rollout. Existing cloud data remains in the Python service's SQLite store; this change does not migrate it or add remote execution environments, WebSocket events, a hosted AI runtime, or CLI marketplace installation.
