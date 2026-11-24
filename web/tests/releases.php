<?php
declare(strict_types=1);
require dirname(__DIR__).'/src/Core.php';
$cfg=require dirname(__DIR__).'/config.php';
function check(bool $condition,string $message): void { if (!$condition) throw new RuntimeException($message); }
$name='codez#1a-v1.deb';
check(packageName($cfg)===$name,'Filename contract');
check(releaseUrl($name)==='/downloads/codez%231a-v1.deb','Hash URL encoding');
$dir=sys_get_temp_dir().'/codez-release-'.bin2hex(random_bytes(8)); mkdir($dir,0700);
$cfg['release_dir']=$dir;
try {
    check(releasePath($cfg,$name)===null,'Missing build must not be served');
    file_put_contents($dir.'/'.$name,'test fixture');
    check(releasePath($cfg,$name)===$dir.'/'.$name,'Existing build available');
    check(releasePath($cfg,'../'.$name)===null,'Traversal must fail');
    unlink($dir.'/'.$name);
    symlink(__FILE__,$dir.'/'.$name);
    check(releasePath($cfg,$name)===null,'Symlink outside release root must fail');
} finally { if (is_link($dir.'/'.$name)||is_file($dir.'/'.$name)) unlink($dir.'/'.$name); rmdir($dir); }
echo "Release contract passed\n";
