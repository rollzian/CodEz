<?php
declare(strict_types=1);
function marketCatalog(PDO $db,string $kind,string $term,string $sort): array {
    $order=match($sort){'rating'=>'rating DESC NULLS LAST','downloads','popular'=>'downloads DESC','created'=>'e.created_at DESC',default=>'updated DESC'};
    $sql="SELECT e.id,e.slug,e.kind,e.title,e.description,e.category,e.tags,e.license,p.name,p.verified,
        (SELECT avg(r.rating) FROM reviews r WHERE r.extension=e.id) rating,
        (SELECT count(*) FROM downloads d JOIN versions v ON v.id=d.version WHERE v.extension=e.id) downloads,
        (SELECT max(v.created_at) FROM versions v WHERE v.extension=e.id AND v.state='approved') updated
        FROM extensions e JOIN publishers p ON p.id=e.publisher
        WHERE EXISTS(SELECT 1 FROM versions v WHERE v.extension=e.id AND v.state='approved')";
    $args=[];
    if ($kind!=='') { $sql.=' AND e.kind=?'; $args[]=$kind; }
    if ($term!=='') { $sql.=" AND e.search @@ websearch_to_tsquery('simple',?)"; $args[]=$term; }
    return query($db,$sql.' ORDER BY '.$order.',e.id DESC LIMIT 100',$args)->fetchAll();
}
function publisher(PDO $db,array $u): void {
    query($db,'INSERT INTO publishers(id,name) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name',[$u['id'],$u['name']]);
}
function extension(PDO $db,int $id): array {
    $x=query($db,'SELECT e.*,p.name,p.verified FROM extensions e JOIN publishers p ON p.id=e.publisher WHERE e.id=?',[$id])->fetch();
    if (!$x) fail(404,'Extension not found');
    return $x;
}
function visible(PDO $db,int $id): void {
    if (!query($db,"SELECT 1 FROM versions WHERE extension=? AND state='approved'",[$id])->fetchColumn()) fail(404,'Extension not found');
}
function marketId(string $key): int {
    $id=filter_var(post($key,18),FILTER_VALIDATE_INT,['options'=>['min_range'=>1]]);
    if (!$id) fail(400,'Invalid ID');
    return $id;
}
function addVersion(PDO $db,int $id,string $kind): void {
    $v=post('version',80); $compat=post('compatibility',200); $deps=post('dependencies',2000,false); $changes=post('changelog',4000);
    if (!preg_match('/\A[0-9][a-zA-Z0-9.+-]{0,79}\z/',$v)) fail(400,'Invalid version');
    $f=$_FILES['package']??null;
    if (!is_array($f)||$f['error']!==UPLOAD_ERR_OK||!is_uploaded_file($f['tmp_name'])||$f['size']<1||$f['size']>2097152) fail(400,'Upload a package of at most 2 MiB');
    $name=$f['name'];
    if (!is_string($name)||!preg_match('/\A[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}\z/',$name)) fail(400,'Invalid package filename');
    $data=file_get_contents($f['tmp_name'],false,null,0,2097153);
    if ($data===false||strlen($data)<1||strlen($data)>2097152) fail(400,'Invalid package');
    if ($kind==='skills' && ($name!=='SKILL.md'||!preg_match('//u',$data)||strlen($data)>32768)) fail(400,'Skills require UTF-8 SKILL.md, at most 32 KiB');
    query($db,"INSERT INTO versions(extension,version,compatibility,dependencies,changelog,filename,package,sha256) VALUES(?,?,?,?,?,?,decode(?,'hex'),?)",
        [$id,$v,$compat,$deps,$changes,$name,bin2hex($data),hash('sha256',$data)]);
}
function marketAction(array $cfg): never {
    csrf(); $u=requireUser($cfg); limit($cfg,'market',$u['id'],20); $db=db($cfg); $action=post('action',32);
    $db->beginTransaction();
    try {
        publisher($db,$u);
        if ($action==='create') {
            $slug=post('slug',63); $kind=post('kind',10);
            if (!preg_match('/\A[a-z0-9][a-z0-9-]{1,62}\z/',$slug)||!in_array($kind,['skills','plugins','mcp'],true)) fail(400,'Invalid extension');
            $id=(int)query($db,'INSERT INTO extensions(publisher,slug,kind,title,description,category,tags,license) VALUES(?,?,?,?,?,?,?,?) RETURNING id',
                [$u['id'],$slug,$kind,post('title',100),post('description',4000),post('category',80),post('tags',300,false),post('license',80)])->fetchColumn();
            addVersion($db,$id,$kind);
        } elseif (in_array($action,['moderate','verify','close_report'],true)) {
            if (!admin($cfg,$u)) fail(403,'Access denied');
            if ($action==='moderate') {
                $state=post('state',10); if (!in_array($state,['approved','rejected'],true)) fail(400,'Invalid state');
                query($db,'UPDATE versions SET state=? WHERE id=? AND state IN (\'pending\',\'approved\')',[$state,marketId('version_id')]);
            } elseif ($action==='verify') {
                query($db,'UPDATE publishers SET verified=true WHERE id=?',[post('publisher',24)]);
            } else query($db,"UPDATE reports SET state='closed' WHERE id=?",[marketId('report_id')]);
            $db->commit(); go('/admin');
        } else {
            $id=marketId('id'); $x=extension($db,$id);
            if ($action==='version') {
                if ($x['publisher']!==$u['id']) fail(403,'Access denied');
                addVersion($db,$id,$x['kind']);
            } else {
                visible($db,$id);
                if (in_array($action,['favorite','subscribe','unfavorite','unsubscribe'],true)) {
                    $table=in_array($action,['favorite','unfavorite'],true)?'favorites':'subscriptions';
                    if (str_starts_with($action,'un')) query($db,"DELETE FROM $table WHERE extension=? AND author=?",[$id,$u['id']]);
                    else query($db,"INSERT INTO $table(extension,author) VALUES(?,?) ON CONFLICT DO NOTHING",[$id,$u['id']]);
                } elseif ($action==='review') {
                    $rating=filter_var(post('rating',1),FILTER_VALIDATE_INT,['options'=>['min_range'=>1,'max_range'=>5]]);
                    if (!$rating||$x['publisher']===$u['id']) fail(400,'Invalid review');
                    query($db,'INSERT INTO reviews(extension,author,rating,body) VALUES(?,?,?,?) ON CONFLICT(extension,author) DO UPDATE SET rating=excluded.rating,body=excluded.body,updated_at=now()',[$id,$u['id'],$rating,post('body',2000)]);
                } elseif ($action==='report') {
                    $vid=marketId('version_id');
                    if (!query($db,"SELECT 1 FROM versions WHERE id=? AND extension=? AND state='approved'",[$vid,$id])->fetchColumn()) fail(404,'Version not found');
                    query($db,'INSERT INTO reports(version,author,reason) VALUES(?,?,?) ON CONFLICT DO NOTHING',[$vid,$u['id'],post('reason',1000)]);
                } else fail(400,'Invalid action');
            }
        }
        $db->commit(); go('/marketplace/item/'.$id);
    } catch (Throwable $ex) {
        if ($db->inTransaction()) $db->rollBack();
        if ($ex instanceof PDOException && $ex->getCode()==='23505') fail(409,'Slug or version already exists');
        throw $ex;
    }
}
function marketDownload(array $cfg,int $id): never {
    csrf(); $u=requireUser($cfg); limit($cfg,'download',$u['id'],30); $db=db($cfg);
    $v=query($db,"SELECT filename,encode(package,'base64') data,sha256 FROM versions WHERE id=? AND state='approved'",[$id])->fetch();
    if (!$v) fail(404,'Version not found');
    $data=base64_decode($v['data'],true);
    if ($data===false||!hash_equals($v['sha256'],hash('sha256',$data))) fail(503,'Package integrity check failed');
    publisher($db,$u);
    query($db,'INSERT INTO downloads(version,author) VALUES(?,?) ON CONFLICT DO NOTHING',[$id,$u['id']]);
    header('Content-Type: application/octet-stream'); header('Content-Disposition: attachment; filename="'.$v['filename'].'"');
    header('Content-Length: '.strlen($data)); session_write_close(); echo $data; exit;
}
