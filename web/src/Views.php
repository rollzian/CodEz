<?php
declare(strict_types=1);
function layout(string $title,string $body,?array $user): void {
    $account=$user?'<a href="/dashboard">'.e($user['name']).'</a>':'<a href="/login">Sign in</a>';
    echo '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark light"><title>'.e($title).' · CodEz</title><link rel="icon" href="/assets/mark.svg"><link rel="stylesheet" href="/assets/site.css"><script src="/assets/site.js" defer></script></head><body><header class="nav"><a class="brand" href="/"><img src="/assets/mark.svg" alt="" width="32" height="32">CodEz<span>.</span></a><button class="mobile" aria-expanded="false" aria-controls="navigation">Menu</button><nav id="navigation"><a href="/docs">Docs</a><a href="/marketplace">Marketplace</a><a href="/ai">AI Engine</a><a href="/source">Source</a>'.$account.'<a class="button small" href="/download">Download</a></nav><button id="theme" aria-label="Change theme" title="Change theme">◐</button></header><main>'.$body.'</main><footer><a class="brand" href="/">CodEz.</a><div><a href="/changelog">Changelog</a><a href="/status">Status</a><a href="/api/v1">API</a><a href="https://github.com/rollzian/CodEz">GitHub ↗</a></div><span>Auxia · CodEz</span></footer></body></html>';
}
function home(array $cfg): string {
    $published=releasePath($cfg,packageName($cfg))!==null;
    $version=$published?'Release '.e($cfg['version']):'Explore published releases';
    return '<section class="hero"><div class="grid-field" aria-hidden="true"></div><div class="hero-copy"><p class="eyebrow"><span class="dot"></span> CODING AGENT / TERMINAL</p><h1>Make space<br>for <em>better code.</em></h1><p class="lead">A coding agent that works with your models, your tools and your team. Built for the terminal.</p><div class="actions"><a class="button" href="/download">Download CodEz <span>↓</span></a><a class="text-link" href="/docs">Read the docs ↗</a></div><a class="release-tag" href="/downloads">'.$version.'</a></div><div class="terminal"><div class="terminal-bar"><span>● ● ●</span><span>codez / navigation</span><span>⌘</span></div><div class="terminal-inner"><p class="dim">~/project</p><p><b class="accent">$</b> codez</p><p class="terminal-title">CodEz<span>.</span></p><p class="dim">Explore the CLI</p><div class="terminal-tabs"><button data-demo="models" aria-pressed="true">/models</button><button data-demo="skills" aria-pressed="false">/skills</button><button data-demo="cloud" aria-pressed="false">/auxia</button></div><pre id="demo">Model library
OpenAI
Anthropic
OpenRouter
Custom compatible endpoint</pre><span class="cursor" aria-hidden="true"></span></div></div></section><section class="section split reveal"><div><p class="eyebrow">01 / INTELLIGENCE</p><h2>Think in context.<br>Work in code.</h2><p>Switch providers and select the model suited to the task. Plan, inspect and edit repositories from a single terminal.</p><a class="text-link" href="/ai">Explore the engine ↗</a></div><div class="pipeline"><div><span>01</span><strong>Plan</strong><p>Inspect context and choose an approach.</p></div><span class="connector">↓</span><div><span>02</span><strong>Execute</strong><p>Apply approved edits and commands.</p></div></div></section><section class="section band reveal"><p class="eyebrow">02 / ECOSYSTEM</p><h2>Extend your workflow.</h2><div class="feature-row"><a href="/marketplace/skills"><span>01</span><h3>Skills</h3><p>Reusable agent instructions.</p><b>↗</b></a><a href="/marketplace/plugins"><span>02</span><h3>Plugins</h3><p>Extension catalog.</p><b>↗</b></a><a href="/marketplace/mcp"><span>03</span><h3>MCP</h3><p>Discover protocol servers.</p><b>↗</b></a></div></section><section class="section split reveal"><div><p class="eyebrow">03 / COLLABORATION</p><h2>Work together.<br>Stay in flow.</h2><a class="button secondary" href="/dashboard">Open your workspace ↗</a></div><div class="network"><div>Auxia Account</div><i></i><div>CodEz Cloud</div><i></i><div class="network-row"><a href="/workspaces">Workspaces</a><a href="/teams">Teams</a><a href="/projects">Projects</a></div></div></section><section class="section end reveal"><h2>Start in the terminal.</h2><a class="button" href="/download">Get CodEz ↓</a><a class="text-link" href="'.e($cfg['repository']).'">View on GitHub ↗</a></section>';
}
function releaseView(array $cfg,string $path): string {
    $items=releases($cfg); $html='<section class="section page"><p class="eyebrow">RELEASE CHANNELS</p><h1>'.($path==='/changelog'?'Release history':'Download CodEz').'</h1><p id="os">Choose a published build.</p><div class="actions"><button data-channel="all" class="secondary">All</button><button data-channel="stable">Stable</button><button data-channel="beta">Beta</button><button data-channel="nightly">Nightly</button></div><div class="records">';
    foreach ($items as $i) $html.='<article data-release="'.e($i['channel']).'"><div><strong>'.e($i['name']).'</strong><p>'.e($i['tag']).' / '.e($i['channel']).'</p><code class="hash">'.e($i['hash']??'SHA256 unavailable').'</code></div><a class="button small" href="'.e($i['url']).'">Download ↓</a></article>';
    if (!$items) $html.='<p>No published packages are available from the release catalog.</p>';
    return $html.'</div><h2>Arch Linux</h2><pre id="install">git clone '.e($cfg['repository']).'.git'."\n".'cd CodEz'."\n".'makepkg -si'."\n".'codez</pre><button data-copy="install">Copy commands</button><p>Arch installation has not been verified upstream.</p><h2>Debian</h2><p>Download an available .deb package and install it with apt.</p><a href="'.e($cfg['repository']).'/releases">GitHub Releases ↗</a></section>';
}
function docsView(array $cfg): string {
    return '<section class="section page docs"><p class="eyebrow">DOCUMENTATION</p><h1>Build with CodEz.</h1><h2>Getting started</h2><p><a href="/download">Install a published build</a> and run <code>codez</code>. Choose a provider and model on first launch.</p><h2>Commands</h2><div class="records"><article><code>/setup</code> Configure provider</article><article><code>/models</code> Discover models</article><article><code>/mode</code> Code, Ask, Plan, Review</article><article><code>/skills</code> Discover local SKILL.md</article><article><code>/auxia</code> Cloud collaboration</article><article><code>/doctor</code> Local diagnostics</article></div><h2>Permissions</h2><p>File mutations and shell commands require approval. Shell commands run with your OS permissions, not in a sandbox. Ask, Plan and Review expose read-only tools.</p><h2>Skills</h2><p>Place SKILL.md under .codez/skills/name/ or your user config directory. Up to four active skills, 32 KiB each.</p><h2>Cloud</h2><p>Connect your Auxia account with /auxia. Cloud workspaces currently store collaboration metadata, not remote machines.</p><a href="'.e($cfg['repository']).'#readme">Full CLI reference ↗</a></section>';
}
function sourceView(array $cfg): string {
    return '<section class="section page"><p class="eyebrow">OPEN SOURCE</p><h1>Read the source.</h1><p>CodEz CLI is implemented in Go. The existing collaboration service is Python.</p><pre id="clone">git clone '.e($cfg['repository']).'.git'."\n".'cd CodEz'."\n".'go test ./...</pre><button data-copy="clone">Copy commands</button><div class="actions"><a class="button" href="'.e($cfg['repository']).'">GitHub ↗</a><a href="'.e($cfg['repository']).'/issues">Issues</a></div></section>';
}
function aiView(): string {
    return '<section class="section page"><p class="eyebrow">PROMPT ENGINE</p><h1>From intent to implementation.</h1><div class="pipeline"><div><span>01</span><strong>Plan</strong><p>Use Plan mode to inspect the repository and prepare a read-only approach.</p></div><span class="connector">↓</span><div><span>02</span><strong>Code</strong><p>Use Code mode to implement approved changes.</p></div></div><h2>Provider protocols</h2><div class="records"><article>OpenAI Responses</article><article>Anthropic Messages</article><article>OpenAI-compatible Chat Completions</article></div><p>Provider and model selection run in the CLI. API credentials are not requested by this website.</p><p>Automatic two-stage execution and MCP runtime are not available in the inspected CLI release.</p><a class="button" href="/docs">CLI documentation ↗</a></section>';
}
function formStart(string $action,string $name): string { return '<form method="post" action="'.e($action).'">'.csrfField().'<input type="hidden" name="action" value="'.e($name).'">'; }
function field(string $name,string $label,string $type='text',bool $required=true): string { return '<label>'.e($label).'<input type="'.e($type).'" name="'.e($name).'" '.($required?'required':'').'></label>'; }
function hidden(string $name,mixed $value): string { return '<input type="hidden" name="'.e($name).'" value="'.e($value).'">'; }
function actionButton(string $url,string $action,string $label,array $fields=[]): string {
    $html=formStart($url,$action);
    foreach($fields as $k=>$v) $html.=hidden($k,$v);
    return $html.'<button type="submit">'.e($label).'</button></form>';
}
function loginView(?array $user): string {
    if ($user) return '<section class="section page"><h1>Connected to Auxia.</h1><a class="button" href="/dashboard">Dashboard ↗</a></section>';
    $d=$_SESSION['device']??null;
    $html='<section class="section page narrow"><p class="eyebrow">AUXIA ACCOUNT</p><h1>Connect CodEz.</h1><p>Use your existing Auxia account.</p>';
    if ($d&&$d['expires']>time()) {
        $html.='<div class="auth-code">'.e($d['code']).'</div><p>Confirm the matching code in Auxia.</p><a class="button" href="'.e($d['uri']).'" target="_blank" rel="noopener">Continue with Auxia ↗</a><form id="poll" method="post" action="/auth/poll" data-interval="'.e($d['interval']).'">'.csrfField().'<p id="poll-status" role="status">Waiting for authorization</p><button>Check connection</button></form>';
    }
    return $html.actionButton('/auth/start','start',$d?'Start again':'Connect with Auxia').'</section>';
}
function accountNav(): string {
    $s='<aside class="side">';
    foreach (['dashboard','workspaces','teams','friends','projects','profile','settings','devices'] as $p) $s.='<a href="/'.$p.'">'.ucfirst($p).'</a>';
    return $s.'</aside>';
}
function accountView(array $cfg,string $path,array $u): string {
    $kind=substr($path,1); $html='<section class="section account">'.accountNav().'<div class="account-content"><p class="eyebrow">CODEZ CLOUD</p><h1>'.e(ucfirst($kind)).'</h1>';
    if (in_array($kind,['dashboard','profile','settings','devices'],true)) {
        $html.='<h2>'.e($u['name']).'</h2><p>Account ID</p><code>'.e($u['id']).'</code>';
        if ($kind==='dashboard') $html.='<div class="feature-row"><a href="/workspaces">Workspaces ↗</a><a href="/teams">Teams ↗</a><a href="/marketplace/library">Library ↗</a></div>';
        else $html.='<p>Manage the current web session.</p>'.actionButton('/auth/logout','logout','Revoke this session');
        return $html.'</div></section>';
    }
    [$status,$data]=cloud($cfg,'/'.$kind,'GET',null,token());
    if ($status!==200||!is_array($data['items']??null)) fail(502,'Cloud collection unavailable');
    $html.=formStart('/'.$kind,'create').($kind==='friends'?field('user_id','Auxia account ID'):field('name','Name'));
    if ($kind==='projects') $html.=field('url','HTTPS repository URL','url');
    if ($kind==='workspaces') $html.=field('team_id','Team ID (optional)','text',false);
    $html.='<button class="button">Create</button></form><div class="records">';
    foreach($data['items'] as $i) {
        $id=$i['id']??''; if (!is_string($id)||!preg_match('/\A[a-f0-9]{24}\z/',$id)) continue;
        $state=$i['state']??''; $role=$i['role']??'';
        $html.='<article><div><strong>'.e($i['name']).'</strong><p>'.e($i['detail']??'').' · '.e($state).' '.e($role).'</p><code>'.e($id).'</code></div><div class="record-actions">';
        if ($kind==='projects' && is_string($i['url']??null)&&str_starts_with($i['url'],'https://')) $html.='<a href="'.e($i['url']).'" rel="noopener noreferrer">Repository ↗</a>';
        if (($kind==='teams'&&$state==='invited')||($kind==='friends'&&$state==='incoming')) $html.=actionButton('/'.$kind,'accept','Accept',['id'=>$id]);
        if ($kind==='friends'||$state==='owner') $html.=actionButton('/'.$kind,'delete','Remove',['id'=>$id]);
        if ($kind==='teams'&&$state==='member') $html.=actionButton('/teams','leave','Leave',['id'=>$id]);
        if ($kind==='teams'&&in_array($role,['owner','admin'],true)) {
            $html.=formStart('/teams','invite').hidden('id',$id).field('user_id','Invite account ID').'<button>Invite</button></form>';
            $html.=formStart('/teams','remove_member').hidden('id',$id).field('user_id','Remove account ID').'<button>Remove member</button></form>';
            if ($role==='owner') $html.=formStart('/teams','role').hidden('id',$id).field('user_id','Account ID').'<label>Role<select name="role"><option>admin</option><option>maintainer</option><option>developer</option><option>reviewer</option><option>viewer</option><option>guest</option></select></label><button>Set role</button></form>';
        }
        $html.='</div></article>';
    }
    return $html.'</div></div></section>';
}
function uploadFields(): string {
    return field('version','Version').field('compatibility','Compatible CodEz versions').field('dependencies','Dependencies','text',false).field('changelog','Changelog').field('package','Package (max 2 MiB)','file');
}
function uploadForm(string $action): string { return '<form method="post" enctype="multipart/form-data" action="/marketplace/action">'.csrfField().hidden('action',$action); }
function marketView(array $cfg,string $kind,?array $u): string {
    $html='<section class="section page"><p class="eyebrow">CODEZ ECOSYSTEM</p><h1>Marketplace.</h1><div class="actions"><a href="/marketplace">All</a><a href="/marketplace/skills">Skills</a><a href="/marketplace/plugins">Plugins</a><a href="/marketplace/mcp">MCP</a><a href="/marketplace/library">Library</a><a class="button small" href="/marketplace/create">Publish +</a></div>';
    if ($kind==='create') {
        if (!$u) return $html.loginView(null).'</section>';
        return $html.'<h2>Publish an extension</h2>'.uploadForm('create').field('title','Title').field('slug','Unique slug').'<label>Type<select name="kind"><option>skills</option><option>plugins</option><option>mcp</option></select></label>'.field('description','Description').field('category','Category').field('tags','Tags','text',false).field('license','License').uploadFields().'<button class="button">Submit for review</button></form></section>';
    }
    $db=db($cfg);
    if ($kind==='library') {
        if (!$u) return $html.loginView(null).'</section>';
        $id=$u['id'];
        $sections=['Your extensions'=>['SELECT id,title FROM extensions WHERE publisher=?',[$id]],'Favorites'=>['SELECT e.id,e.title FROM favorites f JOIN extensions e ON e.id=f.extension WHERE f.author=?',[$id]],'Subscriptions'=>['SELECT e.id,e.title FROM subscriptions s JOIN extensions e ON e.id=s.extension WHERE s.author=?',[$id]],'Download history'=>['SELECT e.id,e.title,v.version FROM downloads d JOIN versions v ON v.id=d.version JOIN extensions e ON e.id=v.extension WHERE d.author=? ORDER BY d.downloaded_at DESC LIMIT 100',[$id]]];
        foreach($sections as $label=>[$sql,$args]) {
            $html.='<h2>'.e($label).'</h2><div class="records">';
            foreach(query($db,$sql,$args) as $x) $html.='<article><a href="/marketplace/item/'.e($x['id']).'">'.e($x['title']).'</a> '.e($x['version']??'').'</article>';
            $html.='</div>';
        }
        return $html.'</section>';
    }
    $term=$_GET['q']??''; $sort=$_GET['sort']??'updated';
    if (!is_string($term)||strlen($term)>200||!is_string($sort)) fail(400,'Invalid search');
    $html.='<form class="search" method="get"><input name="q" value="'.e($term).'" placeholder="Search extensions" aria-label="Search extensions"><select name="sort" aria-label="Sort">';
    foreach(['updated','created','rating','downloads','popular'] as $s) $html.='<option'.($s===$sort?' selected':'').'>'.$s.'</option>';
    $html.='</select><button>Search</button></form><div class="catalog">';
    $items=marketCatalog($db,$kind,$term,$sort);
    foreach($items as $x) $html.='<a class="extension" href="/marketplace/item/'.e($x['id']).'"><small>'.e($x['kind']).' / '.e($x['category']).'</small><h2>'.e($x['title']).'</h2><p>'.e($x['description']).'</p><span>'.e($x['name']).($x['verified']?' ✓':'').' · '.e($x['downloads']).' downloads'.($x['rating']!==null?' · ★ '.e(round((float)$x['rating'],1)):'').'</span></a>';
    if (!$items) $html.='<p>No extensions found.</p>';
    return $html.'</div></section>';
}
function itemView(array $cfg,int $id,?array $u): string {
    $db=db($cfg); $x=extension($db,$id); $owner=$u&&$x['publisher']===$u['id'];
    if (!$owner && !($u&&admin($cfg,$u))) visible($db,$id);
    $html='<section class="section page"><a href="/marketplace">← Marketplace</a><p class="eyebrow">'.e($x['kind']).' / '.e($x['category']).'</p><h1>'.e($x['title']).'</h1><p>'.nl2br(e($x['description'])).'</p><p>Publisher: '.e($x['name']).($x['verified']?' ✓':'').' · '.e($x['license']).' · '.e($x['tags']).'</p>';
    if ($u) {
        $html.='<div class="actions">';
        foreach (['favorites'=>['favorite','unfavorite'],'subscriptions'=>['subscribe','unsubscribe']] as $table=>[$on,$off]) {
            $exists=query($db,"SELECT 1 FROM $table WHERE extension=? AND author=?",[$id,$u['id']])->fetchColumn();
            $html.=actionButton('/marketplace/action',$exists?$off:$on,ucfirst($exists?$off:$on),['id'=>$id]);
        }
        $html.='</div>';
    }
    $sql='SELECT id,version,compatibility,dependencies,changelog,filename,sha256,state FROM versions WHERE extension=?'.(($owner||($u&&admin($cfg,$u)))?'':" AND state='approved'").' ORDER BY id DESC LIMIT 100';
    $html.='<h2>Versions</h2><div class="records">';
    foreach(query($db,$sql,[$id]) as $v) {
        $html.='<article><div><strong>'.e($v['version']).' · '.e($v['state']).'</strong><p>'.e($v['changelog']).'</p><p>Compatibility: '.e($v['compatibility']).' · Dependencies: '.e($v['dependencies']).'</p><code class="hash">'.e($v['sha256']).'</code></div>';
        if ($v['state']==='approved') {
            $html.=$u?actionButton('/marketplace/package/'.$v['id'],'download','Download'): '<a href="/login">Sign in to download</a>';
            if($u) $html.=formStart('/marketplace/action','report').hidden('id',$id).hidden('version_id',$v['id']).field('reason','Report reason').'<button>Report</button></form>';
        }
        $html.='</article>';
    }
    $html.='</div>';
    if ($owner) $html.='<h2>New version</h2>'.uploadForm('version').hidden('id',$id).uploadFields().'<button>Submit version</button></form>';
    $html.='<h2>Reviews</h2>';
    foreach(query($db,'SELECT r.rating,r.body,p.name FROM reviews r JOIN publishers p ON p.id=r.author WHERE r.extension=? ORDER BY r.updated_at DESC LIMIT 100',[$id]) as $r) $html.='<article><strong>'.e($r['name']).' · '.e($r['rating']).'/5</strong><p>'.e($r['body']).'</p></article>';
    if ($u&&!$owner) $html.=formStart('/marketplace/action','review').hidden('id',$id).'<label>Rating<select name="rating"><option>5</option><option>4</option><option>3</option><option>2</option><option>1</option></select></label>'.field('body','Review').'<button>Save review</button></form>';
    return $html.'</section>';
}
function adminView(array $cfg): string {
    $db=db($cfg); $html='<section class="section page"><h1>Moderation.</h1><h2>Pending versions</h2><div class="records">';
    foreach(query($db,"SELECT v.id,v.version,v.sha256,v.filename,e.title,e.publisher FROM versions v JOIN extensions e ON e.id=v.extension WHERE v.state='pending' ORDER BY v.id LIMIT 100") as $x) {
        $html.='<article><div><strong>'.e($x['title']).' '.e($x['version']).'</strong><p>'.e($x['filename']).'</p><code class="hash">'.e($x['sha256']).'</code></div>';
        $html.=actionButton('/admin/package/'.$x['id'],'inspect','Inspect package').actionButton('/marketplace/action','moderate','Approve',['version_id'=>$x['id'],'state'=>'approved']).actionButton('/marketplace/action','moderate','Reject',['version_id'=>$x['id'],'state'=>'rejected']).'</article>';
    }
    $html.='</div><h2>Reports</h2>';
    foreach(query($db,"SELECT r.id,r.version,r.reason,e.title FROM reports r JOIN versions v ON v.id=r.version JOIN extensions e ON e.id=v.extension WHERE r.state='open' ORDER BY r.id LIMIT 100") as $x) $html.='<article><strong>'.e($x['title']).'</strong><p>'.e($x['reason']).'</p>'.actionButton('/marketplace/action','moderate','Reject version',['version_id'=>$x['version'],'state'=>'rejected']).actionButton('/marketplace/action','close_report','Close report',['report_id'=>$x['id']]).'</article>';
    return $html.'<h2>Verify publisher</h2>'.formStart('/marketplace/action','verify').field('publisher','Publisher account ID').'<button>Verify</button></form></section>';
}
function statusView(array $cfg): string {
    $checks=['Web frontend'=>'Available'];
    try { db($cfg)->query('SELECT 1'); $checks['Marketplace database']='Reachable'; } catch(Throwable) { $checks['Marketplace database']='Unavailable'; }
    try { redis($cfg)->ping(); $checks['Redis']='Reachable'; } catch(Throwable) { $checks['Redis']='Unavailable'; }
    try { [$s]=cloud($cfg,'/me'); $checks['Cloud API']=$s===401?'Responding':'Unverified'; } catch(Throwable) { $checks['Cloud API']='Unavailable'; }
    $html='<section class="section page"><h1>Service status.</h1><div class="records">';
    foreach($checks as $name=>$state) $html.='<article><strong>'.e($name).'</strong><span>'.e($state).'</span></article>';
    return $html.'</div></section>';
}
