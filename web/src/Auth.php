<?php
declare(strict_types=1);
function authAction(array $cfg,string $action): never {
    csrf(); limit($cfg,'auth',$_SERVER['REMOTE_ADDR']??'unknown',30);
    if ($action==='start') {
        [$status,$d]=cloud($cfg,'/device/start','POST',[]);
        $code=$d['user_code']??null; $secret=$d['device_code']??null;
        $uri=$d['verification_uri']??null;
        if ($status!==200 || !is_string($code) || !preg_match('/\A[A-F0-9]{20}\z/',$code) ||
            !is_string($secret) || !preg_match('/\A[A-Za-z0-9_-]{43}\z/',$secret) ||
            $uri!==$cfg['cloud'].'/activate?code='.$code ||
            !is_int($d['interval']??null) || $d['interval']<1 || $d['interval']>30 ||
            !is_int($d['expires_in']??null) || $d['expires_in']<1 || $d['expires_in']>600) fail(502,'Authorization unavailable');
        $_SESSION['device']=['secret'=>$secret,'code'=>$code,'uri'=>$uri,'interval'=>$d['interval'],'next'=>time()+$d['interval'],'expires'=>time()+$d['expires_in']];
        go('/login');
    }
    if ($action==='poll') {
        $d=$_SESSION['device']??null;
        if (!$d || $d['expires']<=time()) { unset($_SESSION['device']); jsonResponse(['state'=>'expired'],410); }
        if ($d['next']>time()) jsonResponse(['state'=>'pending','interval'=>$d['next']-time()]);
        $_SESSION['device']['next']=time()+$d['interval'];
        [$status,$result]=cloud($cfg,'/device/poll','POST',['device_code'=>$d['secret']]);
        if ($status===400 && ($result['error']??'')==='authorization_pending') jsonResponse(['state'=>'pending','interval'=>$d['interval']]);
        if ($status===429 && ($result['error']??'')==='slow_down') {
            $interval=min(30,$d['interval']+2); $_SESSION['device']['interval']=$interval; $_SESSION['device']['next']=time()+$interval;
            jsonResponse(['state'=>'pending','interval'=>$interval]);
        }
        if ($status===410) { unset($_SESSION['device']); jsonResponse(['state'=>'expired'],410); }
        $t=$result['access_token']??null;
        if ($status!==200 || !is_string($t) || !preg_match('/\A[A-Za-z0-9_-]{43}\z/',$t)) fail(502,'Authorization unavailable');
        session_regenerate_id(true); unset($_SESSION['device']); $_SESSION['token']=$t; $_SESSION['csrf']=bin2hex(random_bytes(32));
        jsonResponse(['state'=>'connected']);
    }
    if ($action==='logout') {
        if (token()) { [$status]=cloud($cfg,'/logout','POST',[],token()); if (!in_array($status,[200,401],true)) fail(502,'Could not revoke session'); }
        $_SESSION=[]; session_destroy();
        setcookie(session_name(),'', ['expires'=>1,'path'=>'/','secure'=>true,'httponly'=>true,'samesite'=>'Lax']);
        go('/');
    }
    fail(404,'Not found');
}
function cloudAction(array $cfg,string $kind): never {
    csrf(); $u=requireUser($cfg); limit($cfg,'cloud',$u['id'],30);
    $action=post('action',32); $fields=[]; $path='/'.$kind;
    if ($action==='create') {
        if ($kind==='friends') $fields['user_id']=post('user_id',24);
        else $fields['name']=post('name',80);
        if ($kind==='projects') $fields['url']=post('url',1000);
        if ($kind==='workspaces' && ($team=post('team_id',24,false))!=='') $fields['team_id']=$team;
    } else {
        $allowed=['workspaces'=>['delete'],'projects'=>['delete'],'friends'=>['accept','delete'],'teams'=>['invite','accept','delete','leave','role','remove_member']];
        if (!in_array($action,$allowed[$kind],true)) fail(400,'Invalid action');
        $id=post('id',24); if (!preg_match('/\A[a-f0-9]{24}\z/',$id)) fail(400,'Invalid ID');
        $path.='/'.$id.'/'.$action;
        if (in_array($action,['invite','role','remove_member'],true)) $fields['user_id']=post('user_id',24);
        if ($action==='role') $fields['role']=post('role',20);
    }
    [$status,$result]=cloud($cfg,$path,'POST',$fields,token());
    if ($status!==200 || ($result['ok']??false)!==true) fail($status>=400 && $status<500?$status:502,'Cloud operation rejected');
    go('/'.$kind);
}
