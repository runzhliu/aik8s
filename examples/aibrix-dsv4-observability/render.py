#!/usr/bin/env python3
"""Render site-specific manifests locally; never commit generated secrets."""
import argparse,json,re,secrets
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--output',default='rendered');args=p.parse_args()
root=Path(__file__).resolve().parent;config=json.loads(Path(args.config).read_text());out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
password_file=out/'grafana-admin-password.txt'
config.setdefault('GRAFANA_ADMIN_PASSWORD',password_file.read_text() if password_file.exists() else secrets.token_urlsafe(24))
pattern=re.compile(r'<([A-Z][A-Z0-9_]*)>')
def replace(value):
    if isinstance(value,dict):return {k:replace(v) for k,v in value.items()}
    if isinstance(value,list):return [replace(v) for v in value]
    if isinstance(value,str):
        # ConfigMap configuration values themselves contain serialized JSON.
        try:
            nested=json.loads(value)
            if isinstance(nested,(dict,list)):return json.dumps(replace(nested),ensure_ascii=False)
        except (ValueError,TypeError):pass
        def sub(match):
            name=match.group(1)
            if name not in config or not config[name]:raise ValueError('Missing site parameter: '+name)
            return str(config[name])
        return pattern.sub(sub,value)
    return value
for name in ['model','monitoring','client']:
    manifest=replace(json.loads((root/(name+'.template.json')).read_text()))
    target=out/(name+'.json');target.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n');target.chmod(0o600)
target=out/'grafana-admin-password.txt';target.write_text(config['GRAFANA_ADMIN_PASSWORD']);target.chmod(0o600)
print('Rendered model and monitoring manifests; local output is private. Review before applying.')
