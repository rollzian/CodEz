<?php
declare(strict_types=1);
require dirname(__DIR__).'/src/Core.php';
require dirname(__DIR__).'/src/Marketplace.php';
$cfg=require dirname(__DIR__).'/config.php';
$db=db($cfg);
function check(bool $value,string $message):void { if (!$value) throw new RuntimeException($message); }
$db->beginTransaction();
try {
    $u=['id'=>str_repeat('a',24),'name'=>'Fixture publisher'];
    publisher($db,$u);
    $id=(int)query($db,"INSERT INTO extensions(publisher,slug,kind,title,description,category,tags,license) VALUES(?,?,?,?,?,?,?,?) RETURNING id",[$u['id'],'fixture-search','skills','Compiler review','Review compiler patches','Engineering','compiler','MIT'])->fetchColumn();
    $payload="# Skill\nReview compiler patches.";
    $vid=query($db,"INSERT INTO versions(extension,version,compatibility,dependencies,changelog,filename,package,sha256) VALUES(?,?,?,?,?,?,decode(?,'hex'),?) RETURNING id",[$id,'1.0.0','0.7.7','','Initial','SKILL.md',bin2hex($payload),hash('sha256',$payload)])->fetchColumn();
    check(marketCatalog($db,'skills','compiler','updated')===[],'Pending version leaked');
    query($db,"UPDATE versions SET state='approved' WHERE id=?",[$vid]);
    $items=marketCatalog($db,'skills','compiler','updated');
    check(count($items)===1 && (int)$items[0]['id']===$id,'Approved search result missing');
    check(marketCatalog($db,'mcp','compiler','updated')===[],'Type filter failed');
    check(marketCatalog($db,'skills','nonexistent','updated')===[],'Search filter failed');
    visible($db,$id);
    $v=query($db,"SELECT encode(package,'hex') payload,sha256 FROM versions WHERE id=?",[$vid])->fetch();
    check(hex2bin($v['payload'])===$payload && $v['sha256']===hash('sha256',$payload),'Package corrupted');
    query($db,"UPDATE versions SET state='rejected' WHERE id=?",[$vid]);
    check(marketCatalog($db,'skills','compiler','updated')===[],'Rejected version leaked');
} finally { $db->rollBack(); }
echo "Marketplace database contract passed\n";
