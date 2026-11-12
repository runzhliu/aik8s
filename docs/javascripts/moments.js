/* Public read-only timeline. Content is inserted as text, never HTML. */
(() => {
  const english = location.pathname.startsWith('/en/');
  const word = (zh, en) => english ? en : zh;
  const root = english ? '/en/moments/' : '/moments/';
  function node(tag, cls, text) {
    const el = document.createElement(tag); if (cls) el.className = cls;
    if (text !== undefined) el.textContent = text;
    return el;
  }
  function safeLink(value) {
    try { const u = new URL(value, location.origin); return ['http:', 'https:'].includes(u.protocol) ? u.href : null; } catch (_) { return null; }
  }
  function card(post) {
    const item = node('article', 'moment'); item.id = post.id;
    const avatar = node('div', 'moment__avatar', 'R'); avatar.setAttribute('aria-hidden', 'true');
    const body = node('div', 'moment__body'); const head = node('div', 'moment__head');
    const author = node('strong', 'moment__author', 'runzhliu');
    const link = node('a', 'moment__time'); link.href = root + '#' + encodeURIComponent(post.id);
    const time = node('time', '', new Intl.DateTimeFormat(english ? 'en' : 'zh-CN', {dateStyle: 'medium', timeZone: 'Asia/Shanghai'}).format(new Date(post.published_at))); time.dateTime = post.published_at; link.append(time); head.append(author, link);
    const content = node('p', 'moment__text', post.text[english ? 'en' : 'zh']); body.append(head, content);
    if (Array.isArray(post.images) && post.images.length) {
      const grid = node('div', 'moment__images');
      post.images.forEach((img) => { if (!/^\/assets\/images\/moments\/[a-z0-9-]+\.(png|jpg|webp)$/.test(img.path)) return; const a = node('a', 'moment__image'); a.href=img.path; a.target='_blank'; a.rel='noopener noreferrer'; const pic=node('img'); pic.src=img.path; pic.loading='lazy'; pic.alt=img.alt?.[english?'en':'zh'] || word('动态图片','Moment image'); a.append(pic); grid.append(a); }); body.append(grid);
    }
    if (post.link && safeLink(post.link.url)) { const a=node('a','moment__link',post.link.label?.[english?'en':'zh'] || word('查看链接','View link')); a.href=safeLink(post.link.url); a.rel='noopener noreferrer'; body.append(a); }
    if (post.tags?.length) { const tags=node('div','moment__tags'); post.tags.forEach((tag)=>tags.append(node('span','moment__tag','#'+tag))); body.append(tags); }
    item.append(avatar, body); return item;
  }
  async function mount(el) {
    if (el.dataset.momentsReady) return; el.dataset.momentsReady = '1';
    try {
      const response = await fetch('/assets/data/moments.json'); if (!response.ok) throw Error();
      const data = await response.json(); const posts = Array.isArray(data.posts) ? data.posts.slice().sort((a,b)=>Date.parse(b.published_at)-Date.parse(a.published_at)) : [];
      if (!el.isConnected) return;
      el.replaceChildren(); if (!posts.length) { el.append(node('p','moments__empty', word('还没有发布动态，敬请期待。','No moments yet. Stay tuned.'))); return; }
      (el.dataset.mode === 'home' ? posts.slice(0,3) : posts).forEach(p=>el.append(card(p)));
      if (el.dataset.mode === 'home') { const a=node('a','moments__more',word('查看全部动态 →','All moments →')); a.href=root; el.append(a); }
      if (location.hash && el.dataset.mode !== 'home') { const id=decodeURIComponent(location.hash.slice(1)); const target=document.getElementById(id); if (target) target.scrollIntoView(); }
    } catch (_) { el.replaceChildren(node('p','moments__empty', word('动态暂时无法加载，请稍后刷新。','Could not load moments. Please try again.'))); }
  }
  function init() { document.querySelectorAll('[data-moments]').forEach(mount); }
  if (typeof document$ !== 'undefined') document$.subscribe(init); else if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
