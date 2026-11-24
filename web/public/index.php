<?php
declare(strict_types=1);
$cfg=require dirname(__DIR__).'/config.php';
foreach (['Core','Auth','Releases','Marketplace','Views'] as $file) require dirname(__DIR__).'/src/'.$file.'.php';
header("Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'");
header('X-Content-Type-Options: nosniff'); header('Referrer-Policy: no-referrer'); header('Cache-Control: no-store');
header('Permissions-Policy: camera=(), microphone=(), geolocation=()');
$path=parse_url($_SERVER['REQUEST_URI']??'/',PHP_URL_PATH);
$method=$_SERVER['REQUEST_METHOD']??'GET';
try {
    if (!is_string($path)||!in_array($method,['GET','POST'],true)) fail(405,'Method not allowed');
    if ($path==='/api/v1') {
        if ($method!=='GET') fail(405,'Method not allowed');
        jsonResponse(['cloud'=>$cfg['cloud'].'/v1','version'=>$cfg['version'],'device_flow'=>['start'=>'/device/start','poll'=>'/device/poll'],'collections'=>['workspaces','teams','friends','projects']]);
    }
    if (preg_match('~\A/api/v1(/(?:me|logout|device/(?:start|poll)|(?:workspaces|teams|friends|projects)(?:/[a-f0-9]{24}/(?:members|delete|accept|invite|role|leave|remove_member))?))\z~',$path,$m)) {
        limit($cfg,'api',$_SERVER['REMOTE_ADDR']??'unknown',120);
        $raw=$_SERVER['HTTP_AUTHORIZATION']??'';
        $bearer=preg_match('/\ABearer ([A-Za-z0-9_-]{43})\z/',$raw,$t)?$t[1]:null;
        $data=null;
        if ($method==='POST') {
            $body=file_get_contents('php://input',false,null,0,8193);
            if ($body===false||strlen($body)>8192) fail(413,'Request too large');
            try { $data=json_decode($body?:'{}',true,32,JSON_THROW_ON_ERROR); } catch(JsonException) { fail(400,'Invalid JSON'); }
            if (!is_array($data)||($data!==[]&&array_is_list($data))) fail(400,'Invalid JSON');
        }
        [$s,$response]=cloud($cfg,$m[1],$method,$data,$bearer); jsonResponse($response,$s);
    }
    sessionStart();
    if ($method==='GET'&&preg_match('~\A/downloads/([^/]+)\z~',$path,$m)) serveRelease($cfg,$m[1]);
    if ($method==='POST') {
        if (preg_match('~\A/auth/(start|poll|logout)\z~',$path,$m)) authAction($cfg,$m[1]);
        if (preg_match('~\A/(workspaces|teams|friends|projects)\z~',$path,$m)) cloudAction($cfg,$m[1]);
        if ($path==='/marketplace/action') marketAction($cfg);
        if (preg_match('~\A/marketplace/package/([1-9][0-9]{0,17})\z~',$path,$m)) marketDownload($cfg,(int)$m[1]);
        fail(404,'Not found');
    }
    $user=me($cfg);
    $title='CodEz';
    if ($path==='/') $body=home($cfg);
    elseif (in_array($path,['/download','/downloads','/changelog'],true)) { $title='Releases'; $body=releaseView($cfg,$path); }
    elseif ($path==='/docs') { $title='Documentation'; $body=docsView($cfg); }
    elseif ($path==='/source') { $title='Source'; $body=sourceView($cfg); }
    elseif ($path==='/ai') { $title='Prompt Engine'; $body=aiView(); }
    elseif ($path==='/login') { $title='Auxia Account'; $body=loginView($user); }
    elseif (preg_match('~\A/marketplace(?:/(skills|plugins|mcp|create|library))?\z~',$path,$m)) { $title='Marketplace'; $body=marketView($cfg,$m[1]??'',$user); }
    elseif (preg_match('~\A/marketplace/item/([1-9][0-9]{0,17})\z~',$path,$m)) { $title='Extension'; $body=itemView($cfg,(int)$m[1],$user); }
    elseif (in_array($path,['/dashboard','/workspaces','/teams','/friends','/projects','/profile','/settings','/devices'],true)) {
        $title=ucfirst(substr($path,1)); $body=$user?accountView($cfg,$path,$user):loginView(null);
    } elseif ($path==='/status') { $title='Service status'; $body=statusView($cfg); }
    elseif ($path==='/admin') { if (!$user||!admin($cfg,$user)) fail(403,'Access denied'); $title='Administration'; $body=adminView($cfg); }
    else fail(404,'Page not found');
    layout($title,$body,$user);
} catch (HttpError $ex) {
    if (str_starts_with((string)$path,'/api/')||$path==='/auth/poll') jsonResponse(['error'=>$ex->getMessage()],$ex->status);
    http_response_code($ex->status); layout('CodEz', '<section class="section"><h1>'.e($ex->getMessage()).'</h1><a href="/">Return home</a></section>',null);
} catch (Throwable $ex) {
    error_log('CodEz web: '.get_class($ex)); http_response_code(503);
    if (str_starts_with((string)$path,'/api/')||$path==='/auth/poll') jsonResponse(['error'=>'service_unavailable'],503);
    layout('Unavailable','<section class="section"><h1>Service unavailable</h1><a href="/">Return home</a></section>',null);
}
