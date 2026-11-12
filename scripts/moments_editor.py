#!/usr/bin/env python3
"""Local-only Moments editor with an explicit, scoped Git publication action."""
from __future__ import annotations
import argparse, base64, datetime, hashlib, json, os, re, secrets, subprocess, tempfile, threading, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'docs/assets/data/moments.json'
IMAGES = ROOT / 'docs/assets/images/moments'
DRAFT = ROOT / '.local/moments/draft.json'
TOKEN = secrets.token_urlsafe(32)
PENDING = ROOT / '.local/moments/pending-push.json'
PUBLISH_LOCK = threading.Lock()
MAX_REQUEST = 64 * 1024 * 1024  # Nine 5 MiB images expand to roughly 60 MiB in base64.
MAX_IMAGE = 5 * 1024 * 1024
IMAGE_RE = re.compile(r'^/assets/images/moments/[a-z0-9-]+\.(?:png|jpg|webp)$')
ID_RE = re.compile(r'^m-[0-9a-f]{16}$')

def atomic(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.moments-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f: f.write(data)
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)

def load_posts():
    value = json.loads(DATA.read_text()) if DATA.exists() else {'version': 1, 'posts': []}
    if value.get('version') != 1 or not isinstance(value.get('posts'), list): raise ValueError('动态数据格式不正确')
    return value

def publish(data):
    text = data.get('text', {})
    if not all(isinstance(text.get(k), str) and 0 < len(text[k].strip()) <= 5000 for k in ('zh','en')): raise ValueError('请填写中英文内容，每种不超过 5000 字')
    tags = data.get('tags', [])
    if not isinstance(tags, list) or len(tags)>10 or any(not isinstance(t,str) or len(t)>30 or not t.strip() for t in tags): raise ValueError('标签最多 10 个，每个不超过 30 字')
    url = data.get('url','').strip()
    if url and (len(url)>2048 or urlsplit(url).scheme not in ('http','https') or not urlsplit(url).netloc): raise ValueError('链接须为完整的 http 或 https 地址')
    images = data.get('images', [])
    if not isinstance(images,list) or len(images)>9: raise ValueError('最多添加 9 张图片')
    prepared=[]
    for image in images:
        src=image.get('src',''); alt=image.get('alt',{})
        if not isinstance(alt,dict) or not all(isinstance(alt.get(k),str) and 0<len(alt[k].strip())<=200 for k in ('zh','en')): raise ValueError('请为每张图片填写中英文描述')
        if IMAGE_RE.fullmatch(src):
            if not (ROOT/'docs'/src.lstrip('/')).is_file(): raise ValueError('引用的图片不存在')
            prepared.append((src,None,alt)); continue
        match=re.fullmatch(r'data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)',src)
        if not match: raise ValueError('图片仅支持 PNG、JPEG 和 WebP')
        raw=base64.b64decode(match[2],validate=True)
        kind=match[1]
        if len(raw)>MAX_IMAGE or not raw: raise ValueError('单张图片不能超过 5 MiB')
        if not ((kind=='png' and raw.startswith(b'\x89PNG\r\n\x1a\n')) or (kind=='jpeg' and raw.startswith(b'\xff\xd8\xff')) or (kind=='webp' and raw[:4]==b'RIFF' and raw[8:12]==b'WEBP')): raise ValueError('图片格式与文件内容不一致')
        ext={'jpeg':'jpg','png':'png','webp':'webp'}[kind]
        path='/assets/images/moments/'+hashlib.sha256(raw).hexdigest()[:24]+'.'+ext
        prepared.append((path,raw,alt))
    store=load_posts(); post_id=data.get('id') or 'm-'+secrets.token_hex(8)
    if not ID_RE.fullmatch(post_id): raise ValueError('动态 ID 无效')
    existing=next((p for p in store['posts'] if p.get('id')==post_id),None)
    if data.get('id') and not existing: raise ValueError('原动态不存在，请刷新页面')
    now=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
    post={'id':post_id,'published_at':existing['published_at'] if existing else now,'text':{k:text[k].strip() for k in ('zh','en')},'tags':[t.strip() for t in tags], 'images':[{'path':p,'alt':a} for p,_,a in prepared]}
    if url: post['link']={'url':url,'label':{'zh':'查看链接','en':'View link'}}
    for path,raw,_ in prepared:
        if raw is not None: atomic(ROOT/'docs'/path.lstrip('/'),raw)
    store['posts']=[p for p in store['posts'] if p.get('id')!=post_id]+[post]
    atomic(DATA,(json.dumps(store,ensure_ascii=False,indent=2)+'\n').encode())
    return post_id

def git(*args, check=True, timeout=30):
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0')
    try:
        result = subprocess.run(['git', *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise ValueError('Git 操作超时；请检查网络或认证后重试') from None
    if check and result.returncode:
        raise ValueError('Git 操作失败；请检查仓库状态、网络和 Git 凭据后重试')
    return result

def publish_to_site(post_id):
    """Commit only this timeline data and its images; refuse unrelated unpushed commits."""
    if git('branch', '--show-current').stdout.strip() != 'main': raise ValueError('请先切换到 main 分支后再发布')
    head = git('rev-parse', 'HEAD').stdout.strip()
    remote = git('ls-remote', '--heads', 'origin', 'refs/heads/main', timeout=30).stdout.split()
    if not remote: raise ValueError('无法读取远程 main 分支')
    remote_sha = remote[0]
    pending = json.loads(PENDING.read_text()) if PENDING.exists() else {}
    if head != remote_sha:
        if pending.get('commit') != head or pending.get('base') != remote_sha:
            raise ValueError('本地与远程 main 不一致；为避免发布其他提交，请先同步仓库')
        if git('status', '--porcelain', '--', 'docs/assets/data/moments.json', 'docs/assets/images/moments/').stdout:
            raise ValueError('上次推送尚未完成，且动态文件又有改动；请先检查仓库状态')
        git('push', 'origin', 'HEAD:refs/heads/main', timeout=120)
        PENDING.unlink(missing_ok=True)
        return head
    if git('cat-file', '-e', remote_sha + ':docs/moments.md', check=False).returncode:
        raise ValueError('动态页面尚未部署，请先将页面功能提交到远程；本次内容已保存在本地')
    post = next(p for p in load_posts()['posts'] if p['id'] == post_id)
    paths = ['docs/assets/data/moments.json'] + ['docs/' + image['path'].lstrip('/') for image in post['images']]
    if git('diff', '--cached', '--quiet', '--', *paths, check=False).returncode:
        raise ValueError('动态文件已有暂存改动，请先处理暂存区后再发布')
    git('add', '--', *paths)
    if not git('diff', '--cached', '--quiet', '--', *paths, check=False).returncode:
        return head
    try:
        git('commit', '--only', '-m', 'Publish moment', '--', *paths, timeout=60)
    except ValueError:
        git('reset', '-q', 'HEAD', '--', *paths, check=False)
        raise
    commit = git('rev-parse', 'HEAD').stdout.strip()
    atomic(PENDING, (json.dumps({'base':head,'commit':commit})+'\n').encode()); PENDING.chmod(0o600)
    try:
        git('push', 'origin', 'HEAD:refs/heads/main', timeout=120)
    except ValueError:
        raise ValueError('已创建动态提交，但推送尚未成功；请检查网络或认证后再次点击发布') from None
    PENDING.unlink(missing_ok=True)
    return commit

HTML = r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>动态编辑器 · AIK8S</title><style>
:root{font-family:-apple-system,BlinkMacSystemFont,"Helvetica Neue",sans-serif;color:#202335;background:#f7f7fb}*{box-sizing:border-box}body{margin:0}main{max-width:1050px;margin:0 auto;padding:44px 24px}h1{font-size:28px;margin:8px 0}h2{font-size:17px}.eyebrow{font-size:12px;letter-spacing:.14em;color:#4054b2}.lead,.hint{color:#667085;line-height:1.6;font-size:14px}.layout{display:grid;grid-template-columns:1fr 1fr;gap:22px;margin-top:26px}.panel{background:white;border:1px solid #e5e7ef;border-radius:16px;padding:22px}label{display:block;font-size:13px;font-weight:600;margin:16px 0 6px}textarea,input{width:100%;border:1px solid #d8dbe6;border-radius:8px;padding:11px;font:inherit;color:inherit;background:#fff}textarea{min-height:130px;resize:vertical}button,.file{border:1px solid #d8dbe6;background:white;border-radius:8px;padding:10px 14px;font:inherit;cursor:pointer;color:#344054}.primary{background:#4054b2;color:white;border-color:#4054b2}.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:20px}.drop{margin-top:12px;padding:18px;border:1px dashed #a9b1ce;border-radius:10px;color:#59647f;font-size:13px}.images{display:grid;gap:12px;margin-top:12px}.imgrow{display:grid;grid-template-columns:100px 1fr;gap:12px;border:1px solid #e7e9f0;padding:10px;border-radius:9px}.imgrow img{width:100px;height:100px;object-fit:cover;border-radius:6px}.imgrow input{margin-bottom:6px}.preview-text{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.7}.preview-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:4px}.preview-grid img{width:100%;aspect-ratio:1;object-fit:cover;border-radius:6px}.msg{min-height:1.5em;font-size:13px;color:#4054b2}.post-row{display:flex;gap:8px;margin:8px 0}.post-row button{text-align:left;flex:1}.warning{font-size:12px;color:#667085}a{color:#4054b2}@media(max-width:720px){.layout{grid-template-columns:1fr}main{padding:24px 16px}}
</style><main><div class="eyebrow">AIK8S · MOMENTS</div><h1>动态编辑器</h1><p class="lead">写下短想法，粘贴或选择图片，预览后一键发布到博客。草稿保存在这台电脑上。</p><p class="warning">本页面只监听本机。点击发布将自动提交本条动态并推送，网站部署完成后公开；图片和文字请先检查。图片保留原始元数据，请检查位置等隐私信息；勿粘贴公司信息或凭据。</p><div class="layout"><section class="panel"><h2>编辑动态</h2><label for="zh">中文内容</label><textarea id="zh" placeholder="分享一个观点或最近的发现…"></textarea><label for="en">English</label><textarea id="en" placeholder="Write the complete English version…"></textarea><label for="tags">标签（逗号分隔，可选）</label><input id="tags" placeholder="Agent, Kubernetes"><label for="url">关联链接（可选）</label><input id="url" type="url" placeholder="https://example.com/article"><div class="drop" id="paste" tabindex="0">复制截图后，在这里或任一文本框粘贴；也可以 <label class="file" for="upload">选择图片</label><input id="upload" type="file" accept="image/png,image/jpeg,image/webp" multiple hidden><p class="hint">支持 PNG、JPEG、WebP，最多 9 张，单张不超过 5 MiB。请为图片填写中英文说明。</p></div><div class="images" id="images"></div><div class="actions"><button id="save">保存草稿</button><button class="primary" id="publish">发布到网站</button><button id="new">新动态</button></div><p class="msg" id="msg" role="status"></p></section><section class="panel"><h2>预览</h2><p class="hint">预览仅在本机显示；点击“发布到网站”后内容将对所有人可见。</p><strong>runzhliu</strong><p id="previewZh" class="preview-text"></p><div class="preview-grid" id="previewImages"></div><p class="hint">English</p><p id="previewEn" class="preview-text"></p><h2>动态记录</h2><div id="posts"></div><p class="hint">点击动态可修改；保留原始发布时间和链接。</p></section></div></main><script>
const token='__TOKEN__'; let images=[], editing=''; const $=id=>document.getElementById(id); let posts=[];
function message(s){$('msg').textContent=s} function preview(){ $('previewZh').textContent=$('zh').value||'中文预览';$('previewEn').textContent=$('en').value||'English preview';$('previewImages').replaceChildren(...images.map(x=>{const i=document.createElement('img');i.src=x.src;i.alt=x.alt.zh||'图片预览';return i})) }
function draw(){const holder=$('images');holder.replaceChildren();images.forEach((item,i)=>{const row=document.createElement('div');row.className='imgrow';const image=document.createElement('img');image.src=item.src;image.alt='图片预览';const form=document.createElement('div');['zh','en'].forEach(lang=>{const input=document.createElement('input');input.placeholder=lang==='zh'?'图片描述（中文，必填）':'Image description (English, required)';input.value=item.alt[lang]||'';input.oninput=()=>{item.alt[lang]=input.value;preview()};form.append(input)});const remove=document.createElement('button');remove.type='button';remove.textContent='移除图片';remove.onclick=()=>{images.splice(i,1);draw()};form.append(remove);row.append(image,form);holder.append(row)});preview()}
async function addFiles(files){for(const f of files){if(!['image/png','image/jpeg','image/webp'].includes(f.type)||f.size>5*1024*1024){message('仅支持不超过 5 MiB 的 PNG、JPEG、WebP 图片');continue}if(images.length>=9){message('最多 9 张图片');break}const src=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=reject;r.readAsDataURL(f)});images.push({src,alt:{zh:'',en:''}})}draw()}
document.addEventListener('paste',e=>{const files=Array.from(e.clipboardData?.items||[]).filter(x=>x.kind==='file'&&x.type.startsWith('image/')).map(x=>x.getAsFile()).filter(Boolean);if(files.length){e.preventDefault();addFiles(files)}});$('upload').onchange=e=>{addFiles(e.target.files);e.target.value=''};
['zh','en','tags','url'].forEach(id=>$(id).addEventListener('input',preview));function payload(){return {id:editing,text:{zh:$('zh').value,en:$('en').value},tags:$('tags').value.split(/[,，]/).map(x=>x.trim()).filter(Boolean),url:$('url').value,images}}
function fill(p){editing=p.id||'';$('zh').value=p.text?.zh||'';$('en').value=p.text?.en||'';$('tags').value=(p.tags||[]).join(', ');$('url').value=p.url||p.link?.url||'';images=(p.images||[]).map(x=>({src:x.src||x.path,alt:x.alt||{zh:'',en:''}}));draw()}
async function api(path,body){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Moments-Token':token},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(d.error||'操作失败');return d}
async function refresh(){const r=await fetch('/api/posts');posts=(await r.json()).posts;const target=$('posts');target.replaceChildren();if(!posts.length)target.textContent='暂无动态';posts.slice().reverse().forEach(p=>{const row=document.createElement('div');row.className='post-row';const button=document.createElement('button');button.textContent=(p.text.zh||'').slice(0,55);button.onclick=()=>{fill(p);message('正在编辑已有动态')};row.append(button);target.append(row)})}
$('save').onclick=async()=>{try{await api('/api/draft',payload());message('草稿已保存到本机')}catch(e){message(e.message)}};$('publish').onclick=async()=>{try{const button=$('publish');button.disabled=true;message('正在提交并推送，请稍候…');let result;try{result=await api('/api/publish',payload())}finally{button.disabled=false}editing=result.id;await refresh();fill(posts.find(p=>p.id===result.id));try{await api('/api/draft',payload())}catch(e){} message(result.published?'已推送，网站正在自动构建，稍后即可访问。':result.error)}catch(e){message(e.message)}};$('new').onclick=()=>{fill({});message('开始编辑新动态')};(async()=>{await refresh();const r=await fetch('/api/draft');const d=await r.json();if(d.text)fill(d);else draw()})();
</script></html>'''

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def valid_host(self): return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'
    def reply(self, status, data, kind='application/json; charset=utf-8'):
        raw=data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False).encode()
        self.send_response(status); self.send_header('Content-Type',kind); self.send_header('Content-Length',str(len(raw))); self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff'); self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        if not self.valid_host(): return self.reply(403,{'error':'Forbidden'})
        path=urlsplit(self.path).path
        if path=='/': return self.reply(200,HTML.replace('__TOKEN__',TOKEN).encode(),'text/html; charset=utf-8')
        if path=='/api/posts': return self.reply(200,load_posts())
        if path=='/api/draft': return self.reply(200,json.loads(DRAFT.read_text()) if DRAFT.exists() else {})
        if IMAGE_RE.fullmatch(path):
            file=ROOT/'docs'/path.lstrip('/')
            if file.is_file(): return self.reply(200,file.read_bytes(),{'png':'image/png','jpg':'image/jpeg','webp':'image/webp'}[file.suffix[1:]])
        self.reply(404,{'error':'Not found'})
    def do_POST(self):
        if not self.valid_host() or self.headers.get('Origin') != f'http://127.0.0.1:{self.server.server_port}' or not secrets.compare_digest(self.headers.get('X-Moments-Token',''), TOKEN): return self.reply(403,{'error':'Forbidden'})
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=MAX_REQUEST: raise ValueError('内容过大')
            data=json.loads(self.rfile.read(size)); path=urlsplit(self.path).path
            if path=='/api/draft': atomic(DRAFT,(json.dumps(data,ensure_ascii=False)+'\n').encode()); DRAFT.chmod(0o600); return self.reply(200,{'ok':True})
            if path=='/api/publish':
                if not PUBLISH_LOCK.acquire(blocking=False): raise ValueError('已有发布任务正在运行，请稍候')
                try:
                    post_id=publish(data)
                    try: return self.reply(200,{'id':post_id,'published':True,'commit':publish_to_site(post_id)})
                    except ValueError as e: return self.reply(200,{'id':post_id,'published':False,'error':str(e)})
                finally:
                    PUBLISH_LOCK.release()
            self.reply(404,{'error':'Not found'})
        except (ValueError,TypeError,KeyError) as e: self.reply(400,{'error':str(e)})

def main():
    parser=argparse.ArgumentParser(description='仅供本机使用的动态编辑器')
    parser.add_argument('--port',type=int,default=18765); parser.add_argument('--no-open',action='store_true'); args=parser.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    url=f'http://127.0.0.1:{server.server_port}/'; print('动态编辑器：'+url+'（Ctrl+C 退出）',flush=True)
    if not args.no_open: webbrowser.open(url)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
if __name__=='__main__': main()
