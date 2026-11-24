<?php
declare(strict_types=1);
function releases(array $cfg): array {
    $local=packageName($cfg); $path=releasePath($cfg,$local); $items=[];
    if ($path!==null) $items[]=['name'=>$local,'url'=>releaseUrl($local),'hash'=>hash_file('sha256',$path),'channel'=>'stable','tag'=>$cfg['version']];
    try {
        $r=null;
        try { $r=redis($cfg); $cached=$r->get('codez:web:github:releases'); } catch (Throwable) { $cached=false; }
        if (is_string($cached)) $remote=json_decode($cached,true,64,JSON_THROW_ON_ERROR);
        else {
            [$status,$remote]=upstream('https://api.github.com/repos/rollzian/CodEz/releases?per_page=30');
            if ($status!==200) fail(502,'Release catalog unavailable');
            if ($r) $r->setex('codez:web:github:releases',300,json_encode($remote,JSON_THROW_ON_ERROR));
        }
        foreach ($remote as $release) {
            if (!is_array($release) || ($release['draft']??true)!==false) continue;
            $tag=$release['tag_name']??''; if (!is_string($tag)) continue;
            $channel=str_contains(strtolower($tag),'nightly')?'nightly':(($release['prerelease']??false)?'beta':'stable');
            foreach ($release['assets']??[] as $asset) {
                $url=$asset['browser_download_url']??''; $name=$asset['name']??'';
                if (!is_string($url)||!str_starts_with($url,$cfg['repository'].'/releases/download/')||!is_string($name)||!preg_match('/\.(deb|rpm|zip|tar\.gz|AppImage|exe)$/i',$name)) continue;
                $digest=$asset['digest']??''; $hash=is_string($digest)&&preg_match('/\Asha256:([a-f0-9]{64})\z/',$digest,$m)?$m[1]:null;
                $items[]=['name'=>$name,'url'=>$url,'hash'=>$hash,'channel'=>$channel,'tag'=>$tag];
            }
        }
    } catch (Throwable) { error_log('CodEz release catalog unavailable'); }
    return $items;
}
function serveRelease(array $cfg,string $encoded): never {
    $name=rawurldecode($encoded); $path=releasePath($cfg,$name);
    if (!$path) fail(404,'Release not found');
    session_write_close(); header('Content-Type: application/vnd.debian.binary-package');
    header('Content-Disposition: attachment; filename="'.$name.'"'); header('Content-Length: '.filesize($path));
    readfile($path); exit;
}
