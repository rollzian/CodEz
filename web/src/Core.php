<?php
declare(strict_types=1);
final class HttpError extends RuntimeException {
    public function __construct(public readonly int $status, string $message) { parent::__construct($message); }
}
function e(mixed $value): string { return htmlspecialchars((string)$value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8'); }
function fail(int $status, string $message): never { throw new HttpError($status,$message); }
function post(string $key, int $max=1000, bool $required=true): string {
    $v=$_POST[$key] ?? '';
    if (!is_string($v) || strlen($v)>$max || ($required && trim($v)==='')) fail(400,'Invalid '.$key);
    return trim($v);
}
function go(string $path): never { header('Location: '.$path,true,303); exit; }
function jsonResponse(array $data, int $status=200): never {
    http_response_code($status); header('Content-Type: application/json; charset=utf-8');
    echo json_encode($data,JSON_THROW_ON_ERROR|JSON_UNESCAPED_SLASHES); exit;
}
function sessionStart(): void {
    ini_set('session.use_strict_mode','1');
    ini_set('session.use_only_cookies','1');
    session_name('__Host-codez');
    session_set_cookie_params(['lifetime'=>0,'path'=>'/','secure'=>true,'httponly'=>true,'samesite'=>'Lax']);
    session_start();
    $_SESSION['csrf'] ??= bin2hex(random_bytes(32));
}
function csrf(): void {
    $value=$_POST['csrf'] ?? ($_SERVER['HTTP_X_CSRF_TOKEN'] ?? '');
    if (!is_string($value) || !hash_equals($_SESSION['csrf'],$value)) fail(403,'Invalid request token');
}
function csrfField(): string { return '<input type="hidden" name="csrf" value="'.e($_SESSION['csrf']).'">'; }
function redis(array $cfg): Redis {
    static $r=null;
    if ($r!==null) return $r;
    if (!class_exists('Redis')) fail(503,'Rate limit service unavailable');
    try {
        $client=new Redis();
        if (!$client->connect($cfg['redis_host'],$cfg['redis_port'],1.5)) throw new RuntimeException();
        if ($cfg['redis_password']!=='' && !$client->auth($cfg['redis_password'])) throw new RuntimeException();
        $client->setOption(Redis::OPT_READ_TIMEOUT,1.5);
        return $r=$client;
    } catch (Throwable $ex) { error_log('CodEz Redis unavailable'); fail(503,'Rate limit service unavailable'); }
}
function limit(array $cfg,string $scope,string $identity,int $max,int $seconds=60): void {
    $key='codez:web:limit:'.$scope.':'.hash('sha256',$identity);
    $n=redis($cfg)->eval("local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end; return n",[$key,$seconds],1);
    if (!is_int($n)) fail(503,'Rate limit service unavailable');
    if ($n>$max) { header('Retry-After: '.$seconds); fail(429,'Too many requests'); }
}
function db(array $cfg): PDO {
    static $pdo=null;
    if ($pdo!==null) return $pdo;
    if (!str_starts_with($cfg['db_dsn'],'pgsql:')) fail(503,'Marketplace unavailable');
    return $pdo=new PDO($cfg['db_dsn'],$cfg['db_user'],$cfg['db_password'],[
        PDO::ATTR_ERRMODE=>PDO::ERRMODE_EXCEPTION,PDO::ATTR_DEFAULT_FETCH_MODE=>PDO::FETCH_ASSOC,
        PDO::ATTR_EMULATE_PREPARES=>false,
    ]);
}
function query(PDO $db,string $sql,array $args=[]): PDOStatement {
    $s=$db->prepare($sql); $s->execute($args); return $s;
}
function upstream(string $url,string $method='GET',?array $data=null,?string $token=null,int $cap=1048576): array {
    $body=''; $headers=['Accept: application/json','User-Agent: CodEz-Web/1'];
    if ($token!==null) $headers[]='Authorization: Bearer '.$token;
    if ($data!==null) $headers[]='Content-Type: application/json';
    $ch=curl_init($url);
    curl_setopt_array($ch,[CURLOPT_CUSTOMREQUEST=>$method,CURLOPT_HTTPHEADER=>$headers,
        CURLOPT_PROTOCOLS=>CURLPROTO_HTTPS,CURLOPT_FOLLOWLOCATION=>false,CURLOPT_CONNECTTIMEOUT=>4,
        CURLOPT_TIMEOUT=>12,CURLOPT_SSL_VERIFYPEER=>true,CURLOPT_SSL_VERIFYHOST=>2,
        CURLOPT_WRITEFUNCTION=>static function($ch,string $chunk) use (&$body,$cap):int {
            if (strlen($body)+strlen($chunk)>$cap) return 0;
            $body.=$chunk; return strlen($chunk);
        }]);
    if ($data!==null) curl_setopt($ch,CURLOPT_POSTFIELDS,json_encode((object)$data,JSON_THROW_ON_ERROR));
    $ok=curl_exec($ch); $status=(int)curl_getinfo($ch,CURLINFO_RESPONSE_CODE);
    curl_close($ch);
    if ($ok===false) fail(502,'Upstream unavailable');
    try { $result=json_decode($body,true,64,JSON_THROW_ON_ERROR); } catch (JsonException) { fail(502,'Invalid upstream response'); }
    if (!is_array($result)) fail(502,'Invalid upstream response');
    return [$status,$result];
}
function cloud(array $cfg,string $path,string $method='GET',?array $data=null,?string $token=null): array {
    return upstream($cfg['cloud'].'/v1'.$path,$method,$data,$token);
}
function token(): ?string {
    $v=$_SESSION['token'] ?? null;
    return is_string($v) && preg_match('/\A[A-Za-z0-9_-]{43}\z/',$v) ? $v : null;
}
function me(array $cfg): ?array {
    if (!token()) return null;
    [$status,$user]=cloud($cfg,'/me','GET',null,token());
    if ($status===401) { unset($_SESSION['token']); return null; }
    if ($status!==200 || !is_string($user['id']??null) || !preg_match('/\A[a-f0-9]{24}\z/',$user['id']) || !is_string($user['name']??null)) fail(502,'Account unavailable');
    return $user;
}
function requireUser(array $cfg): array { return me($cfg) ?? throw new HttpError(401,'Connect your Auxia account'); }
function admin(array $cfg,array $u): bool { return in_array($u['id'],$cfg['admins'],true); }
function packageName(array $cfg): string {
    foreach (['vbuild','vrelease'] as $k) if (!preg_match('/\A[a-zA-Z0-9.-]{1,32}\z/',$cfg[$k])) throw new LogicException('Invalid release config');
    return 'codez#'.$cfg['vbuild'].'-'.$cfg['vrelease'].'.deb';
}
function releasePath(array $cfg,string $name): ?string {
    if ($name!==packageName($cfg)) return null;
    $root=realpath($cfg['release_dir']); if ($root===false) return null;
    $path=realpath($root.'/'.$name);
    return $path!==false && dirname($path)===$root && is_file($path) && is_readable($path) ? $path : null;
}
function releaseUrl(string $name): string { return '/downloads/'.rawurlencode($name); }
