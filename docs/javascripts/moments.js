/* Moments are owner-authored GitHub issues. Never insert issue content as HTML. */
(() => {
  const english = location.pathname.startsWith('/en/');
  const word = (zh,en) => english ? en : zh;
  const root = english ? '/en/moments/' : '/moments/';
  const api = 'https://api.github.com/repos/runzhliu/aik8s/issues';
  const repo = 'https://github.com/runzhliu/aik8s';
  const cachePrefix = 'aik8s-moments-issues-v1:';
  let snapshotPromise;
  function node(tag,cls,text) { const e=document.createElement(tag); if(cls)e.className=cls; if(text!==undefined)e.textContent=text; return e; }
  function safeUrl(value) { try {const u=new URL(value,location.origin); return ['http:','https:'].includes(u.protocol)?u.href:null;} catch (_) {return null;} }
  async function getJson(url) {
    try {
      const res=await fetch(url,{headers:{Accept:'application/vnd.github+json'},signal:AbortSignal.timeout(7000)});
      if(!res.ok)throw Error('GitHub '+res.status);
      const data=await res.json();
      try {sessionStorage.setItem(cachePrefix+url,JSON.stringify({at:Date.now(),data}));} catch (_) {}
      return data;
    } catch (err) {
      try {
        snapshotPromise ||= (async () => {
          const urls=['https://raw.githubusercontent.com/runzhliu/aik8s/moments-data/moments-issues.json?v='+Math.floor(Date.now()/300000),'/assets/data/moments-issues.json'];
          for(const candidate of urls)try {const r=await fetch(candidate,{signal:AbortSignal.timeout(7000)});if(r.ok)return await r.json();} catch (_) {}
          throw Error('snapshot unavailable');
        })();
        const snapshot=await snapshotPromise, parsed=new URL(url);
        if(!Array.isArray(snapshot.issues)||!snapshot.comments)throw Error();
        const match=parsed.pathname.match(/\/issues\/(\d+)\/comments$/);
        if(match)return snapshot.comments[match[1]] || [];
        if(parsed.pathname.endsWith('/issues')) {const page=Number(parsed.searchParams.get('page')||1), per=Number(parsed.searchParams.get('per_page')||30);return snapshot.issues.slice((page-1)*per,page*per);}
      } catch (_) {snapshotPromise=null;}
      try {const cached=JSON.parse(sessionStorage.getItem(cachePrefix+url)); if(cached && Date.now()-cached.at<86400000)return cached.data;} catch (_) {}
      throw err;
    }
  }
  function parseBody(body) {
    const match=String(body||'').match(/<!--\s*moment:zh\s*-->([\s\S]*?)<!--\s*moment:en\s*-->([\s\S]*?)(?:<!--\s*moment:images\s*-->([\s\S]*?))?<!--\s*moment:end\s*-->/i);
    if(!match || !match[1].trim() || !match[2].trim())return null;
    const legacy=String(body).match(/<!--\s*moment-id:(m-[a-z0-9-]+)\s*-->/i);
    const date=String(body).match(/<!--\s*moment-published:([^\s]+)\s*-->/i);
    return {text:((english?match[2]:match[1])+'\n'+(match[3]||'')).trim(), legacy:legacy?.[1], date:date?.[1]};
  }
  function appendContent(body,content) {
    const images=[];
    const text=content.replace(/!\[([^\]]*)\]\((https?:\/\/[^\s)]+)(?:\s+"[^"]*")?\)/g,(_,alt,url)=>{if(images.length<9 && safeUrl(url))images.push({alt,url});return '';}).trim();
    if(text)body.append(node('p','moment__text',text));
    if(images.length){const grid=node('div','moment__images');images.forEach(({alt,url})=>{const a=node('a','moment__image');a.href=safeUrl(url);a.target='_blank';a.rel='noopener noreferrer';const img=node('img');img.src=a.href;img.loading='lazy';img.alt=alt||word('动态图片','Moment image');a.append(img);grid.append(a);});body.append(grid);}
  }
  function comments(body, issue) {
    const details=node('details','moment__comments');
    details.append(node('summary','moment__comment-toggle',word(`评论 ${issue.comments || 0}`,`Comments ${issue.comments || 0}`)));
    details.addEventListener('toggle',async()=>{
      if(!details.open || details.dataset.loaded)return;
      details.dataset.loaded='1'; details.querySelector('.moment__comments-list')?.remove(); const area=node('div','moment__comments-list'); area.append(node('p','moment__comments-note',word('正在加载评论…','Loading comments…'))); details.append(area);
      try {
        const list=await getJson(`${api}/${issue.number}/comments?per_page=100`); if(!Array.isArray(list))throw Error();
        area.replaceChildren();
        if(!list.length) area.append(node('p','moment__comments-note',word('还没有评论。','No comments yet.')));
        list.forEach(comment=>{const item=node('div','moment__comment');const author=node('a','moment__comment-author',String(comment.user?.login||'GitHub')); const login=String(comment.user?.login||''); author.href=/^[a-z0-9-]+$/i.test(login)?'https://github.com/'+login:repo;author.target='_blank';author.rel='noopener noreferrer';item.append(author,node('p','moment__comment-text',String(comment.body||'')));area.append(item);});
        if((issue.comments||0)>list.length)area.append(node('p','moment__comments-note',word('更多评论请前往 GitHub 查看。','View more comments on GitHub.')));
      } catch (_) {area.replaceChildren(node('p','moment__comments-note',word('评论暂时无法加载，请到 GitHub 查看。','Comments could not be loaded. View them on GitHub.')));delete details.dataset.loaded;}
      const a=node('a','moment__github-link',word('在 GitHub 登录并评论 ↗','Sign in and comment on GitHub ↗'));a.href=`${repo}/issues/${issue.number}`;a.target='_blank';a.rel='noopener noreferrer';area.append(a);
    });
    body.append(details);
  }
  function card(issue,withActions) {
    const parsed=parseBody(issue.body); if(!parsed)return null;
    const item=node('article','moment');item.id='issue-'+issue.number;
    if(parsed.legacy){const anchor=node('span','moment__legacy-anchor');anchor.id=parsed.legacy;item.append(anchor);}
    const avatar=node('div','moment__avatar','R');avatar.setAttribute('aria-hidden','true');
    const body=node('div','moment__body'),head=node('div','moment__head');
    const author=node('strong','moment__author','runzhliu'), link=node('a','moment__time');link.href=root+'#issue-'+issue.number;
    const date=parsed.date && !Number.isNaN(Date.parse(parsed.date))?parsed.date:issue.created_at;
    const time=node('time','',new Intl.DateTimeFormat(english?'en':'zh-CN',{dateStyle:'medium',timeZone:'Asia/Shanghai'}).format(new Date(date)));time.dateTime=date;link.append(time);head.append(author,link);body.append(head);appendContent(body,parsed.text);
    if(withActions){const reactions=issue.reactions||{};const count=(Number(reactions.heart)||0)+(Number(reactions['+1'])||0);const a=node('a','moment__github-like',word('♡ GitHub 点赞','♡ Like on GitHub')+(count?' '+count:''));a.href=`${repo}/issues/${issue.number}`;a.target='_blank';a.rel='noopener noreferrer';body.append(a);comments(body,issue);}
    item.append(avatar,body);return item;
  }
  async function mount(el) {
    if(el.dataset.momentsReady)return;el.dataset.momentsReady='1';
    const home=el.dataset.mode==='home'; let page=1; el.replaceChildren();
    async function load() {
      const url=api+'?'+new URLSearchParams({state:'open',labels:'moments',creator:'runzhliu',sort:'created',direction:'desc',per_page:'30',page:String(page)});
      const issues=await getJson(url);if(!Array.isArray(issues))throw Error();
      const visible=issues.filter(i=>!i.pull_request && i.user?.login?.toLowerCase()==='runzhliu' && i.labels?.some(l=>l.name==='moments')).map(i=>card(i,!home)).filter(Boolean);
      if(!el.isConnected)return;
      (home?visible.slice(0,3):visible).forEach(c=>el.append(c));
      if(page===1 && !visible.length)el.append(node('p','moments__empty',word('还没有发布动态，敬请期待。','No moments yet. Stay tuned.')));
      if(home){const a=node('a','moments__more',word('查看全部动态 →','All moments →'));a.href=root;el.append(a);}
      else if(issues.length===30){const more=node('button','moments__load-more',word('加载更多','Load more'));more.type='button';more.addEventListener('click',async()=>{more.disabled=true;more.remove();page++;try{await load();}catch(_){el.append(node('p','moments__empty',word('加载失败，请稍后刷新。','Could not load more. Please refresh.')));}});el.append(more);}
      if(location.hash && !home){const target=document.getElementById(decodeURIComponent(location.hash.slice(1)));if(target)target.scrollIntoView();}
    }
    try{await load();}catch(_){if(el.isConnected)el.replaceChildren(node('p','moments__empty',word('动态暂时无法加载，可能是 GitHub 网络或请求限制，请稍后刷新。','Could not load moments. GitHub may be unavailable or rate limited. Please try again.')));}
  }
  function init(){document.querySelectorAll('[data-moments]').forEach(mount);}
  if(typeof document$!=='undefined')document$.subscribe(init);else if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
