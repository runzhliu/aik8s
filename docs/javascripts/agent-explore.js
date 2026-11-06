/* A transparent, client-side guide to curated reading paths and the site index. */
(function () {
  'use strict';
  if (window.__aik8sExploreLoaded) return;
  window.__aik8sExploreLoaded = true;
  const initialized = new WeakSet();
  const paths = {
    pending: [
      ['ai-k8s/rag-agent/kagent-kubernetes-practice/', '用 kagent 只读诊断 Pending Pod', 'Diagnose a Pending Pod with kagent'],
      ['ai-k8s/practices/gpu-pending/', 'GPU Pod Pending 排查', 'Troubleshoot Pending GPU Pods'],
      ['ai-k8s/gpu-scheduling/', 'GPU 与异构资源调度', 'GPU and heterogeneous resource scheduling']
    ],
    gpu: [
      ['ai-k8s/llm-inference/', 'LLM 推理平台总览', 'LLM inference platform overview'],
      ['ai-k8s/inference/engines/', '推理引擎选型', 'Choosing an inference engine'],
      ['ai-k8s/inference/optimization/', 'LLM 推理性能优化', 'LLM inference performance optimization']
    ],
    sandbox: [
      ['ai-k8s/rag-agent/agent-sandbox-selection/', 'Agent 沙箱选型与架构', 'Agent sandbox selection and architecture'],
      ['ai-k8s/rag-agent/cubesandbox-kubernetes/', 'CubeSandbox 部署条件与评估', 'CubeSandbox deployment and evaluation'],
      ['ai-k8s/rag-agent/agent-long-running-durable-execution/', 'Agent 长任务中断续跑', 'Durable execution for long-running agents']
    ]
  };
  const strings = {
    zh: { prompts: { pending: 'Pod Pending 应该怎么排查？', gpu: '如何建设 GPU 模型推理服务？', sandbox: '怎么选择 Agent 沙箱？' },
      titles: { pending: '从调度事件开始排查', gpu: '从引擎到性能优化', sandbox: '从执行环境到任务恢复' },
      curated: '已匹配预设阅读路径', results: '站内关键词匹配', empty: '没有找到匹配内容。试试更短的关键词，或从下方技术地图开始。',
      error: '暂时无法读取搜索索引，请使用下方技术地图。', query: '请先输入一个问题，或选择快捷任务。', random: '随机发现', count: '篇相关内容' },
    en: { prompts: { pending: 'How do I troubleshoot a Pending Pod?', gpu: 'How do I build a GPU inference service?', sandbox: 'How do I choose an agent sandbox?' },
      titles: { pending: 'Start with scheduling events', gpu: 'From engines to performance tuning', sandbox: 'From execution environments to recovery' },
      curated: 'Curated reading path', results: 'Keyword matches from this site', empty: 'No matches found. Try shorter keywords or browse the technical map below.',
      error: 'The search index is unavailable. Please use the technical map below.', query: 'Enter a question or choose a suggested task.', random: 'A random discovery', count: 'related articles' }
  };
  const presets = [
    ['pending', /pending|unschedul|调度失败|无法调度|不能调度|调度不|节点选择器/i],
    ['sandbox', /sandbox|沙箱|microvm|micro.?vm/i],
    ['gpu', /gpu.*推理|推理.*gpu|gpu.*inference|inference.*gpu|模型.*部署|部署.*模型/i]
  ];
  function init() {
    const root = document.querySelector('[data-agent-explore]');
    if (!root || initialized.has(root)) return;
    initialized.add(root);
    const english = /^en(?:-|$)/i.test(document.documentElement.lang);
    const t = strings[english ? 'en' : 'zh'];
    const base = new URL(english ? '/en/' : '/', window.location.origin);
    const form = root.querySelector('[data-explore-form]');
    const input = root.querySelector('[data-explore-query]');
    const result = root.querySelector('[data-explore-result]');
    const trace = root.querySelector('[data-explore-trace]');
    const panel = root.querySelector('[data-explore-trace-panel]');
    let request = 0;
    let previous = '';
    let indexPromise;
    function setResult(title, detail, links) {
      result.replaceChildren();
      const heading = document.createElement('strong'); heading.textContent = title; result.appendChild(heading);
      if (detail) { const p = document.createElement('p'); p.textContent = detail; result.appendChild(p); }
      if (links && links.length) {
        const list = document.createElement('ol');
        links.forEach(function (item) {
          const li = document.createElement('li'); const a = document.createElement('a');
          const destination = new URL(item[0], base);
          if (destination.origin !== base.origin || !destination.pathname.startsWith(base.pathname)) return;
          a.href = destination.href; a.textContent = item[1]; li.appendChild(a); list.appendChild(li);
        });
        result.appendChild(list);
      }
      result.hidden = false;
    }
    function showPreset(key) {
      request++;
      input.value = t.prompts[key];
      setResult(t.titles[key], t.curated, paths[key].map(function (p) { return [p[0], p[english ? 2 : 1]]; }));
    }
    function tokens(text) {
      const lower = text.toLowerCase();
      const words = lower.match(/[a-z0-9][a-z0-9.+_-]{1,}|[\u3400-\u9fff]+/g) || [];
      const stop = new Set(['如何', '怎么', '为什么', '什么', '可以', '应该', '哪些', '如何做', '请问', 'how', 'what', 'with', 'the', 'and', 'for', 'can', 'does', 'help', 'about']);
      const terms = [];
      words.forEach(function (word) {
        if (/[\u3400-\u9fff]/.test(word)) {
          if (word.length <= 4 && !stop.has(word)) terms.push(word);
          else for (let i = 0; i < word.length - 1; i++) { const part = word.slice(i, i + 2); if (!stop.has(part)) terms.push(part); }
        } else if (!stop.has(word)) terms.push(word);
      });
      return Array.from(new Set(terms)).slice(0, 18);
    }
    async function search(value) {
      const own = ++request;
      const terms = tokens(value);
      if (!terms.length) { setResult(t.results, t.query); return; }
      setResult(t.results, english ? 'Searching the local site index…' : '正在查找站内内容…');
      try {
        if (!indexPromise) indexPromise = fetch(new URL('search.json', base)).then(function (res) {
          if (!res.ok) throw new Error('index unavailable'); return res.json();
        }).catch(function (err) { indexPromise = null; throw err; });
        const data = await indexPromise;
        if (own !== request) return;
        const hits = (Array.isArray(data.items) ? data.items : []).filter(function (item) {
          return item.level === 1 && item.location && !item.location.includes('#') && typeof item.title === 'string';
        }).map(function (item) {
          const title = item.title.toLowerCase();
          const text = String(item.text || '').replace(/<[^>]*>/g, ' ').toLowerCase();
          const score = terms.reduce(function (n, term) { return n + (title.includes(term) ? 6 : 0) + (text.includes(term) ? 1 : 0); }, 0);
          return { item: item, score: score };
        }).filter(function (hit) { return hit.score > 0; }).sort(function (a, b) { return b.score - a.score; }).slice(0, 5);
        setResult(t.results, hits.length ? hits.length + ' ' + t.count : t.empty, hits.map(function (hit) { return [hit.item.location, hit.item.title]; }));
      } catch (_) { if (own === request) setResult(t.results, t.error); }
    }
    form.addEventListener('submit', function (event) {
      event.preventDefault();
      const value = input.value.trim();
      if (!value) { request++; setResult(t.results, t.query); input.focus(); return; }
      const match = presets.find(function (entry) { return entry[1].test(value); });
      if (match) { request++; setResult(t.titles[match[0]], t.curated, paths[match[0]].map(function (p) { return [p[0], p[english ? 2 : 1]]; })); }
      else search(value);
    });
    root.querySelectorAll('[data-explore-preset]').forEach(function (button) {
      button.addEventListener('click', function () { showPreset(button.dataset.explorePreset); });
    });
    root.querySelector('[data-explore-random]').addEventListener('click', function () {
      request++;
      const all = Object.values(paths).flat();
      const available = all.filter(function (item) { return item[0] !== previous; });
      const item = available[Math.floor(Math.random() * available.length)];
      previous = item[0]; setResult(t.random, '', [[item[0], item[english ? 2 : 1]]]);
    });
    trace.addEventListener('click', function () {
      const open = trace.getAttribute('aria-expanded') !== 'true';
      trace.setAttribute('aria-expanded', String(open)); panel.hidden = !open;
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
  if (window.document$ && typeof window.document$.subscribe === 'function') window.document$.subscribe(init);
})();
