/* Build first. NODE_PATH=.local/browser-check/node_modules node scripts/test_blog_polish_browser.cjs */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const ROOT = path.resolve(__dirname, '..');

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', args: ['--no-sandbox'] });
  try {
    const context = await browser.newContext({ reducedMotion: 'reduce' });
    const badSitemaps = [];
    const missing = [];
    await context.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.origin !== 'https://aik8s.run') return route.abort();
      if (url.pathname.endsWith('/sitemap.xml') && !['/sitemap.xml', '/en/sitemap.xml'].includes(url.pathname)) badSitemaps.push(url.href);
      let file = path.join(ROOT, 'site', decodeURIComponent(url.pathname));
      if (url.pathname.endsWith('/')) file = path.join(file, 'index.html');
      if (!file.startsWith(path.join(ROOT, 'site') + path.sep) || !fs.existsSync(file)) {
        missing.push(url.pathname);
        return route.abort();
      }
      return route.fulfill({ path: file });
    });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    for (const prefix of ['', 'en/']) {
      const base = 'https://aik8s.run/' + prefix;
      await page.setViewportSize({ width: 1440, height: 1000 });
      await page.goto(base, { waitUntil: 'networkidle' });
      assert.equal(await page.title(), prefix ? 'AI/LLM on Kubernetes Infrastructure' : 'AI/LLM on Kubernetes 基础设施', 'Homepage title must not duplicate the site name');
      const primary = page.locator('.md-nav--primary');
      assert.equal(await primary.locator(':scope > ul.md-nav__list > li').count(), 2, 'Home plus one integrated technical navigation root');
      const caseRoutes = ['cases/', 'cases/ai-cluster-component-checklist/', 'k3s-upgrade/', 'k3s-upgrade/report/'];
      const navigationPaths = await primary.locator('a[href]').evaluateAll(nodes => nodes.map(node => new URL(node.href).pathname));
      for (const route of caseRoutes) assert.ok(navigationPaths.includes('/' + prefix + route), 'Original case route remains in the unified sidebar: ' + route);
      const latest = page.locator('.aik8s-home-latest');
      assert.ok(await latest.isVisible());
      assert.equal(await latest.locator('li').count(), 3);
      assert.equal(await latest.locator('nav a').count(), 2);
      assert.ok(await latest.locator('a[href$="timeline.html"]').isVisible());
      assert.ok(await latest.locator('a[href$="?sort=updated"]').isVisible());
      assert.ok(await page.locator('.aik8s-view-toggle__label').isVisible());
      assert.equal(await page.locator('a[href="#comments"]').count(), 0);
      assert.equal(await page.locator('meta[property="og:type"]').getAttribute('content'), 'website');
      const dated = await latest.locator('time').evaluateAll(nodes => nodes.map(node => Date.parse(node.dateTime)));
      assert.deepEqual(dated, [...dated].sort((a, b) => b - a));
      for (const width of [390, 760]) {
        await page.setViewportSize({ width, height: 844 });
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
        assert.equal(await page.locator('.aik8s-view-toggle__label').isVisible(), false);
        assert.ok(await page.locator('[data-aik8s-timeline]').isVisible());
      }
      for (const route of caseRoutes) {
        await page.goto(base + route, { waitUntil: 'networkidle' });
        assert.equal(await page.locator('article h1').count(), 1);
        assert.equal(await page.locator('link[rel=canonical]').getAttribute('href'), base + route);
        assert.ok((await page.locator('.md-path').innerText()).includes('AI/LLM on Kubernetes'), 'Cases inherit the unified technical breadcrumb');
      }
      await page.goto(base + 'ai-k8s/practices/kubevirt-rbd-notebook/', { waitUntil: 'networkidle' });
      const firstRelated = await page.locator('.aik8s-related li a').first().getAttribute('href');
      assert.equal(firstRelated, base + 'ai-k8s/practices/kubevirt-local-desktop-lab/');
      assert.equal(await page.locator('meta[property="og:type"]').getAttribute('content'), 'article');
      const info = page.locator('.aik8s-article-info');
      assert.ok(await info.isVisible());
      assert.match(await info.innerText(), prefix ? /About \d+ min read/ : /预计阅读约 \d+ 分钟/);
      assert.equal(await info.locator('time').getAttribute('datetime'), '2026-08-04', 'Review date comes from authored metadata, not Git');
      assert.doesNotMatch(await info.innerText(), /Applicable versions|适用版本|Test environment|实测环境/, 'Do not infer unprovided versions or test environments');
      const feedback = new URL(await info.locator('[data-aik8s-feedback]').getAttribute('href'));
      assert.equal(feedback.origin, 'https://github.com');
      assert.equal(feedback.pathname, '/runzhliu/aik8s/issues/new');
      assert.ok(feedback.searchParams.get('body').includes(page.url()));
      assert.ok(await info.locator('a[href*="/blob/main/"]').count());
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      const paired = prefix ? '/ai-k8s/practices/kubevirt-rbd-notebook/' : '/en/ai-k8s/practices/kubevirt-rbd-notebook/';
      const otherLanguage = page.locator('.md-select__link').filter({ hasText: prefix ? '简体中文' : 'English' });
      assert.equal(new URL(await otherLanguage.getAttribute('href'), page.url()).pathname, paired);
      const alternate = prefix ? 'zh-Hans' : 'en';
      assert.equal(new URL(await page.locator('link[hreflang="' + alternate + '"]').getAttribute('href')).pathname, paired);
      for (const selector of ['link[href*="stylesheets/engagement.css"]', 'script[src*="javascripts/engagement.js"]', 'script[src*="assets/javascripts/bundle."]']) {
        const element = page.locator(selector);
        const url = await element.getAttribute(selector.startsWith('link') ? 'href' : 'src');
        assert.match(url, /\?v=[a-f0-9]{12}$/);
      }
      await page.goto(base + 'ai-k8s/practices/minimax-m3-h20-benchmark/', { waitUntil: 'networkidle' });
      const images = page.locator('article img');
      assert.ok(await images.count() > 1);
      assert.notEqual(await images.first().getAttribute('loading'), 'lazy', 'Never lazy-load a possible first/LCP image automatically');
      const imageAttributes = await images.evaluateAll(nodes => nodes.map(node => ({ width: node.getAttribute('width'), height: node.getAttribute('height'), loading: node.loading, decoding: node.decoding })));
      assert.ok(imageAttributes.every(image => Number(image.width) > 0 && Number(image.height) > 0), 'Reserve intrinsic image aspect ratios');
      assert.ok(imageAttributes.slice(1).every(image => image.loading === 'lazy' && image.decoding === 'async'));
      assert.notEqual(await page.locator('header img').first().getAttribute('loading'), 'lazy');
      await page.goto(base + '404.html', { waitUntil: 'networkidle' });
      assert.match(await page.locator('meta[name=robots]').getAttribute('content'), /noindex/);
      assert.equal(await page.locator('#__skip').count(), 1);
      assert.equal(await page.locator('.aik8s-share,.aik8s-comments,.aik8s-article-info').count(), 0);
      await page.goto(base + 'timeline.html', { waitUntil: 'networkidle' });
      assert.equal(await page.locator('.aik8s-share, .aik8s-comments').count(), 0);
      assert.equal(await page.locator('meta[property="og:type"]').getAttribute('content'), 'website');
      assert.equal(await page.locator('footer [data-aik8s-friend-link]').getAttribute('href'), 'https://runzhliu.cn');
      console.log((prefix ? 'English' : 'Chinese') + ': homepage entry, latest articles, recommendations, metadata, mobile, theme assets OK');
    }
    assert.deepEqual(badSitemaps, [], 'Theme must not request per-article/language sitemap.xml paths');
    assert.deepEqual(missing, [], 'No same-origin missing resources');
    assert.deepEqual(errors, []);
    await context.close();
    console.log('Language navigation preserves page SEO alternates without nested sitemap requests');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
