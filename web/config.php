<?php
declare(strict_types=1);
return [
    'version' => '0.7.8',
    'vbuild' => '1a',
    'vrelease' => 'v1',
    'origin' => 'https://codez.auxia.space',
    'cloud' => 'https://auxia.space/codez-cloud',
    'repository' => 'https://github.com/rollzian/CodEz',
    'release_dir' => getenv('CODEZ_RELEASE_DIR') ?: dirname(__DIR__).'/releases',
    'db_dsn' => getenv('CODEZ_WEB_DSN') ?: '',
    'db_user' => getenv('CODEZ_WEB_DB_USER') ?: '',
    'db_password' => getenv('CODEZ_WEB_DB_PASSWORD') ?: '',
    'redis_host' => getenv('CODEZ_REDIS_HOST') ?: '127.0.0.1',
    'redis_port' => (int)(getenv('CODEZ_REDIS_PORT') ?: 6379),
    'redis_password' => getenv('CODEZ_REDIS_PASSWORD') ?: '',
    'admins' => array_filter(explode(',',getenv('CODEZ_ADMIN_IDS') ?: '')),
];
