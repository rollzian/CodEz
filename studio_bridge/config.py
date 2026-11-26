import ipaddress
import os
from pathlib import Path
from urllib.parse import urlsplit
from .protocol import BridgeError, decode, NAME


def endpoint(url):
    if not isinstance(url, str) or len(url) > 2048 or any(ord(c) < 33 for c in url):
        raise BridgeError('Invalid endpoint')
    try:
        p = urlsplit(url)
        port = p.port
    except ValueError as e:
        raise BridgeError('Invalid endpoint') from e
    if not p.hostname or p.username is not None or p.password is not None or p.fragment or p.query:
        raise BridgeError('Endpoint must not include credentials, query or fragment')
    local = p.hostname == 'localhost'
    try:
        local = local or ipaddress.ip_address(p.hostname).is_loopback
    except ValueError:
        pass
    if p.scheme != 'https' and not (p.scheme == 'http' and local):
        raise BridgeError('HTTPS required outside loopback')
    return url


def load(path):
    p = Path(path).expanduser().resolve(strict=True)
    if not p.is_file() or p.stat().st_size > 256 * 1024:
        raise BridgeError('Invalid configuration file')
    if os.name == 'posix' and (p.stat().st_uid != os.geteuid() or p.stat().st_mode & 0o022):
        raise BridgeError('Configuration must be owned by the current user and not group/world writable')
    value = decode(p.read_bytes())
    if not isinstance(value, dict) or type(value.get('version')) is not int or value['version'] != 1:
        raise BridgeError('Configuration version must be 1')
    if set(value) - {'version','mode','workspace','servers','desktop','browser','resolve','vision'}:
        raise BridgeError('Unknown configuration fields')
    if value.get('mode', 'read-only') not in ('read-only', 'approved'):
        raise BridgeError('Unknown permission mode')
    workspace = Path(value.get('workspace', p.parent)).expanduser()
    if not workspace.is_absolute():
        workspace = p.parent / workspace
    workspace = workspace.resolve(strict=True)
    if not workspace.is_dir():
        raise BridgeError('Workspace is not a directory')
    value['workspace'] = str(workspace)
    servers = value.get('servers', {})
    if not isinstance(servers, dict) or len(servers) > 12:
        raise BridgeError('At most 12 configured servers')
    for name, spec in servers.items():
        if not NAME.fullmatch(name) or len(name) > 24 or '__' in name or name == 'bridge':
            raise BridgeError('Invalid server name')
        if not isinstance(spec, dict):
            raise BridgeError('Invalid server configuration')
        allowed = spec.get('allow_tools', [])
        reads = spec.get('read_tools', [])
        for xs in (allowed, reads):
            if not isinstance(xs, list) or len(xs) > 256 or any(not isinstance(x, str) or not NAME.fullmatch(x) for x in xs) or len(set(xs)) != len(xs):
                raise BridgeError('Invalid tool allowlist')
        for field, limit in (('allow_resources',4096),('allow_prompts',128)):
            items = spec.get(field, [])
            if (not isinstance(items,list) or len(items)>256 or
                    any(not isinstance(x,str) or not 0<len(x)<=limit or any(ord(c)<32 for c in x)
                        or (field=='allow_prompts' and not NAME.fullmatch(x)) for x in items)
                    or len(set(items)) != len(items)):
                raise BridgeError('Invalid '+field)
        if not set(reads).issubset(allowed):
            raise BridgeError('read_tools must be a subset of allow_tools')
        if type(spec.get('enabled', False)) is not bool:
            raise BridgeError('Invalid server enabled flag')
        if not spec.get('enabled'):
            continue
        transport = spec.get('transport')
        if transport not in ('builtin', 'stdio', 'http'):
            raise BridgeError('Unknown transport')
        if transport == 'builtin' and spec.get('adapter') not in ('browser','desktop','resolve'):
            raise BridgeError('Unknown built-in adapter')
        if transport == 'stdio':
            command = spec.get('command')
            args = spec.get('args', [])
            if not isinstance(command, str) or not command or '\x00' in command or not isinstance(args, list) or len(args) > 64 or any(not isinstance(a, str) or '\x00' in a or len(a)>4096 for a in args):
                raise BridgeError('Invalid command or args')
        if transport == 'http':
            endpoint(spec.get('url'))
            if 'token_env' in spec and (not isinstance(spec['token_env'],str) or not NAME.fullmatch(spec['token_env'])):
                raise BridgeError('Invalid token_env variable name')
            if 'oauth' in spec:
                from .oauth import validate_spec
                validate_spec(spec)
        env = spec.get('env', [])
        if not isinstance(env, list) or any(not isinstance(x, str) or not NAME.fullmatch(x) for x in env):
            raise BridgeError('env must contain variable names, not values')
        timeout = spec.get('timeout', 45)
        if type(timeout) is not int or not 1 <= timeout <= 180:
            raise BridgeError('Timeout must be 1..180 seconds')
    for key in ('desktop','browser','resolve','vision'):
        if not isinstance(value.get(key, {}), dict):
            raise BridgeError(f'{key} must be an object')
    return value, str(p)


def within(root, path, *, must_exist=True):
    root = Path(root).resolve(strict=True)
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = root / p
    try:
        p = p.resolve(strict=must_exist)
    except (OSError, RuntimeError) as e:
        raise BridgeError('Workspace path is unavailable') from e
    if not p.is_relative_to(root):
        raise BridgeError('Path outside approved workspace')
    return p
