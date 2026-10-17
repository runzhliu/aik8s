/* Zensical 0.0.51 search enhancement. Keep native result order, links and keys.
 * Only the known search dialog is observed; no fetch/attachShadow interception.
 * Counts of articles refer to rendered matches, not the full lazy-loaded corpus.
 */
(function () {
  'use strict';
  if (window.__aik8sSearchPolish) return;
  window.__aik8sSearchPolish = true;
  const roots = new WeakMap();
  const buttons = new WeakSet();
  let discovery = 0;
  const english = () => /^en(?:-|$)/i.test(document.documentElement.lang);
  const text = (node, value) => { if (node && node.textContent !== value) node.textContent = value; };
  const attr = (node, name, value) => { if (node && node.getAttribute(name) !== value) node.setAttribute(name, value); };

  function enhance(root) {
    if (roots.has(root)) { roots.get(root)(); return; }
    const input = root.querySelector('input[role="combobox"]');
    const list = root.querySelector('ol.b');
    const toolbar = input && input.closest('.k');
    if (!input || !list || !toolbar || !root.querySelector('.X h3.I')) return;
    const style = document.createElement('style');
    style.dataset.searchPolish = '';
    style.textContent = '[data-search-polish-status]{margin:0;padding:8px 18px;color:rgb(var(--color-foreground)/.7);font:12px/1.5 var(--font-family);flex-shrink:0}' +
      '.C[data-search-polish-group]::after{content:attr(data-search-polish-group);display:block;color:var(--color-highlight);font-size:11px;line-height:1.5;position:relative}';
    root.appendChild(style);
    const status = document.createElement('p');
    status.dataset.searchPolishStatus = '';
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    toolbar.after(status);
    let queued = false;
    let emptyTimer;
    let lastQuery = input.value;
    let settled = false;
    const observer = new MutationObserver(schedule);
    function observe() {
      observer.observe(root, { subtree: true, childList: true, characterData: true,
        attributes: true, attributeFilter: ['class', 'href', 'placeholder', 'aria-label'] });
    }
    function waitForEmpty() {
      clearTimeout(emptyTimer);
      settled = false;
      emptyTimer = setTimeout(() => { settled = true; schedule(); }, 900);
    }
    function schedule() {
      if (queued) return;
      queued = true;
      queueMicrotask(() => { queued = false; update(); });
    }
    function update() {
      observer.disconnect();
      try {
        const en = english();
        const query = input.value;
        if (query !== lastQuery) { lastQuery = query; waitForEmpty(); }
        attr(input, 'placeholder', en ? 'Search' : '搜索');
        attr(input, 'aria-label', en ? 'Search articles' : '搜索文章');
        for (const button of toolbar.querySelectorAll('button')) {
          const filter = !!button.querySelector('svg.lucide-list-filter');
          attr(button, 'aria-label', filter ? (en ? 'Filters' : '筛选') : (en ? 'Search' : '搜索'));
          if (filter) attr(button, 'aria-expanded', String(!root.querySelector('.e')?.classList.contains('l')));
        }
        text(root.querySelector('.X h3.I'), en ? 'Filters' : '筛选');
        text(root.querySelector('.X h4.R'), en ? 'Tags' : '标签');
        const heading = root.querySelector('h3.B');
        const number = heading && heading.querySelector('span');
        // Preserve the theme-owned span and its numeric text for subsequent updates.
        if (number) for (const node of heading.childNodes) {
          if (node.nodeType === Node.TEXT_NODE && /^(results|处匹配)$/.test(node.data.trim())) {
            const value = en ? 'results' : '处匹配';
            if (node.data !== value) node.data = value;
          }
        }
        const links = Array.from(list.querySelectorAll(':scope > li > a[href]'));
        const groups = new Map();
        for (const link of links) {
          const url = new URL(link.href, location.href);
          url.hash = '';
          const key = url.href;
          if (!groups.has(key)) groups.set(key, { index: groups.size + 1, links: [] });
          groups.get(key).links.push(link);
        }
        for (const group of groups.values()) for (const link of group.links) {
          const content = link.querySelector('.C');
          if (!content) continue;
          if (group.links.length > 1) attr(content, 'data-search-polish-group', en ?
            `Article ${group.index} · ${group.links.length} displayed matches in this article` :
            `文章 ${group.index} · 同篇已显示 ${group.links.length} 处匹配`);
          else content.removeAttribute('data-search-polish-group');
        }
        let message = '';
        if (links.length) message = en ?
          `Displayed: ${links.length} matches in ${groups.size} articles · All section links retained` :
          `已显示 ${links.length} 处匹配，涉及 ${groups.size} 篇文章 · 保留全部章节链接`;
        else if (query.trim() && settled) message = en ? 'No matching results' : '暂无匹配结果';
        text(status, message);
        status.hidden = !message;
      } finally { observe(); }
    }
    // Listen without canceling or implementing any native keyboard/pointer behavior.
    input.addEventListener('input', () => { waitForEmpty(); schedule(); });
    roots.set(root, schedule);
    update();
  }

  function discover() {
    // The current theme mounts this portal as a direct body child, not .md-search.
    let found = false;
    for (const host of document.body.children) if (host.shadowRoot && host.shadowRoot.querySelector('input[role="combobox"]')) {
      enhance(host.shadowRoot);
      found = true;
    }
    return found;
  }
  function onOpen() {
    if (discovery) return;
    const until = performance.now() + 4000;
    function probe() {
      const found = discover();
      if (!found && performance.now() < until) discovery = requestAnimationFrame(probe);
      else discovery = 0;
    }
    discovery = requestAnimationFrame(probe);
  }
  function initialize() {
    for (const button of document.querySelectorAll('.md-search__button')) {
      if (buttons.has(button)) continue;
      buttons.add(button);
      button.addEventListener('click', onOpen);
      attr(button, 'aria-label', english() ? 'Search' : '搜索');
    }
    discover();
  }
  // The inspected theme also opens its lazy portal with '/'. Observe that gesture
  // without canceling it; typing a slash inside an editable field is not an open.
  document.addEventListener('keydown', event => {
    if (event.key === '/' && !event.target.closest?.('input,textarea,select,[contenteditable]')) onOpen();
  });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize, { once: true });
  else initialize();
  if (typeof document$ !== 'undefined' && document$.subscribe) document$.subscribe(initialize);
}());
