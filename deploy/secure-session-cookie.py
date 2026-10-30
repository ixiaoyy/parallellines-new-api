"""Add Secure to only this application's session cookie in a marked HTTPS vhost.

Invoke with explicit config/container/marker/backup paths. No credentials are read.
Writes the existing inode so Docker's single-file bind sees the update.
"""
import argparse
import datetime
import hashlib
import json
import pathlib
import re
import subprocess

p = argparse.ArgumentParser()
p.add_argument('--config', required=True)
p.add_argument('--container', required=True)
p.add_argument('--marker', required=True)
p.add_argument('--backup-directory', required=True)
p.add_argument('--rebind-replaced-config', action='store_true')
args = p.parse_args()
conf = pathlib.Path(args.config)
backup_dir = pathlib.Path(args.backup_directory)
if not conf.is_file() or conf.is_symlink():
    raise RuntimeError('Config must be an existing regular file')
disk_original = conf.read_bytes()
original = disk_original
stale_bind = False
metadata = json.loads(subprocess.check_output(['docker','inspect',args.container],text=True))[0]
matches = [m for m in metadata['Mounts'] if m['Destination']=='/etc/nginx/conf.d/default.conf']
if len(matches)!=1 or matches[0]['Source']!=str(conf):
    raise RuntimeError('Unexpected Nginx configuration mount')
live = subprocess.check_output(['docker','exec',args.container,'cat','/etc/nginx/conf.d/default.conf'])
if live != disk_original:
    if not args.rebind_replaced_config:
        raise RuntimeError('Bind-mounted inode differs; explicit reconciliation required')
    # Only the already-deployed Chat/API blocks may be absent from the replaced file.
    stripped = re.sub(r'(?ms)^# BEGIN (official-(?:chat|api)-\d{8})\n.*?^# END \1\n?', '', live.decode('utf-8'))
    if stripped.rstrip() != disk_original.decode('utf-8').rstrip():
        raise RuntimeError('Other configuration changed; reconciliation requires review')
    original = live
    stale_bind = True
text = original.decode('utf-8')
start = '# BEGIN ' + args.marker + '\n'
end = '# END ' + args.marker + '\n'
if text.count(start) != 1 or text.count(end) != 1:
    raise RuntimeError('Vhost markers must be unique')
before, rest = text.split(start, 1)
section, after = rest.split(end, 1)
if section.count('listen 443 ssl;') != 1 or 'server_name api.pingxingxian.space;' not in section:
    raise RuntimeError('Expected the dedicated API HTTPS vhost')
http, https = section.split('listen 443 ssl;', 1)
directive = '        proxy_cookie_flags session secure;\n'
anchor = '        proxy_http_version 1.1;\n'
if https.count(anchor) != 1 or 'proxy_cookie_flags' in http:
    raise RuntimeError('Unexpected proxy configuration')
if 'proxy_cookie_flags' in https and directive not in https:
    raise RuntimeError('Conflicting cookie policy; review first')
already = directive in https
if not already:
    https = https.replace(anchor, anchor + directive, 1)
replacement = (before + start + http + 'listen 443 ssl;' + https + end + after).encode('utf-8')
backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
timestamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
backup = backup_dir / ('nginx-before-cookie-' + timestamp + '.conf')
if not already or stale_bind:
    backup.write_bytes(original)
    backup.chmod(0o600)
    if stale_bind:
        disk_backup = backup_dir / ('nginx-disk-before-rebind-' + timestamp + '.conf')
        disk_backup.write_bytes(disk_original)
        disk_backup.chmod(0o600)
def run(*tail):
    result = subprocess.run(['docker','exec',args.container,'nginx',*tail], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('nginx validation/reload failed; config restored; see server Docker logs')
if stale_bind:
    # Validate the future config against existing mounts before the brief proxy restart.
    candidate = '/tmp/pl-cookie-default-' + timestamp + '.conf'
    wrapper = '/tmp/pl-cookie-nginx-' + timestamp + '.conf'
    main = subprocess.check_output(['docker','exec',args.container,'cat','/etc/nginx/nginx.conf'],text=True)
    include = 'include /etc/nginx/conf.d/*.conf;'
    if main.count(include)!=1:
        raise RuntimeError('Unexpected Nginx main include; no production file changed')
    main = main.replace(include, 'include ' + candidate + ';')
    for target, contents in [(candidate,replacement),(wrapper,main.encode('utf-8'))]:
        result = subprocess.run(['docker','exec','-i',args.container,'sh','-c','cat > '+target],input=contents,capture_output=True)
        if result.returncode:
            raise RuntimeError('Could not stage temporary proxy validation file')
    run('-t','-c',wrapper)
try:
    if not already or stale_bind:
        conf.write_bytes(replacement)
    if stale_bind:
        result = subprocess.run(['docker','restart','--time','10',args.container],capture_output=True,text=True)
        if result.returncode:
            raise RuntimeError('Proxy restart outcome needs inspection before another restart')
    run('-t')
    if not already and not stale_bind:
        run('-s','reload')
except Exception:
    if not already or stale_bind:
        conf.write_bytes(original)
        # Do not blindly repeat a restart after an uncertain transport/process result.
        if not stale_bind:
            run('-t')
            run('-s','reload')
    raise
receipt = {'time_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'success':True,'already_configured':already,'scope':'API HTTPS session cookie Secure',
 'source_sha256':hashlib.sha256(original).hexdigest(),
 'result_sha256':hashlib.sha256(replacement).hexdigest(),
 'backup':str(backup) if not already or stale_bind else None,
 'rebound_replaced_config':stale_bind,'restored_existing_app_vhosts':stale_bind,
 'other_vhosts_changed':False}
(backup_dir/'cookie-secure-receipt.json').write_text(json.dumps(receipt,indent=2))
print(json.dumps(receipt))
