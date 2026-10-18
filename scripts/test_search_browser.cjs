/* Optional browser integration test against existing site/, without rebuilding.
 * NODE_PATH=.local/browser-check/node_modules node scripts/test_search_browser.cjs
 * CHROMIUM_PATH defaults to /usr/bin/chromium. No server/browser install needed.
 * Tests built assets by default. SEARCH_POLISH_SOURCE=1 injects source for isolated development.
 * Native comparison context removes only this enhancement; never writes site/.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const ROOT = path.resolve(__dirname, '..');
const SOURCE_OVERRIDE = process.env.SEARCH_POLISH_SOURCE === '1';
const SOURCE = path.join(ROOT, SOURCE_OVERRIDE ? 'docs/javascripts/search-polish.js' : 'site/javascripts/search-polish.js');

async function contextFor(browser, javascriptEnabled = true, enhanced = true) {
  const context = await browser.newContext({ javaScriptEnabled: javascriptEnabled, reducedMotion: 'reduce' });
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== 'https://aik8s.run') return route.abort();
    if (url.pathname === '/__test/search-polish.js') return route.fulfill({ path: SOURCE, contentType: 'text/javascript' });
    const site = path.join(ROOT, 'site');
    let file = path.resolve(site, '.' + decodeURIComponent(url.pathname));
    if (url.pathname.endsWith('/')) file = path.join(file, 'index.html');
    if (!file.startsWith(site + path.sep) || !fs.existsSync(file)) return route.abort();
    if (file.endsWith('.html')) {
      let body = fs.readFileSync(file, 'utf8');
      if (!enhanced || SOURCE_OVERRIDE) body = body.replace(/<script\b[^>]*\bsrc=["'][^"']*\/search-polish\.js(?:\?[^"']*)?["'][^>]*>\s*<\/script>/g, '');
      if (enhanced && SOURCE_OVERRIDE) body = body.replace('</body>', '<script src="/__test/search-polish.js"></script></body>');
      return route.fulfill({ contentType: 'text/html', body });
    }
    return route.fulfill({ path: file });
  });
  return context;
}
const links = page => page.locator('ol.b > li > a[href]');
async function query(page, value) {
  const input = page.locator('input[role=combobox]');
  await input.fill(value);
  await page.waitForFunction(() => {
    const host = Array.from(document.body.children).find(el => el.shadowRoot?.querySelector('input[role=combobox]'));
    return !!host?.shadowRoot.querySelector('ol.b > li > a');
  });
  // A result set is asynchronous and the preceding query can still be rendered.
  await page.waitForTimeout(450);
  assert.equal(await input.inputValue(), value, 'Never translate the query');
}
async function snapshot(page) {
  return links(page).evaluateAll(nodes => nodes.map(node => ({ href: node.href,
    title: node.querySelector('h2').innerHTML, summary: node.querySelector('.u').innerHTML })));
}

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', args: ['--no-sandbox'] });
  try {
    const errors = [];
    for (const prefix of ['', 'en/']) {
      const en = !!prefix;
      const context = await contextFor(browser);
      const nativeContext = await contextFor(browser, true, false);
      const page = await context.newPage();
      const nativePage = await nativeContext.newPage();
      page.on('pageerror', error => errors.push(error.message));
      nativePage.on('pageerror', error => errors.push(error.message));
      const base = 'https://aik8s.run/' + prefix;
      await page.goto(base);
      await nativePage.goto(base);
      if (en) await page.keyboard.press('/');
      else await page.locator('.md-search__button').click();
      await nativePage.locator('.md-search__button').click();
      const input = page.locator('input[role=combobox]');
      await input.waitFor({ state: 'visible' });
      assert.equal(await input.getAttribute('placeholder'), en ? 'Search' : '搜索');
      assert.equal(await input.getAttribute('aria-label'), en ? 'Search articles' : '搜索文章');
      const filter = page.locator('button:has(svg.lucide-list-filter)');
      assert.equal(await filter.getAttribute('aria-label'), en ? 'Filters' : '筛选');
      const waitForFilter = expected => page.waitForFunction(value => Array.from(document.body.children).some(el =>
        el.shadowRoot?.querySelector('button:has(svg.lucide-list-filter)')?.getAttribute('aria-expanded') === value), expected);
      // The theme starts expanded when the index contains authored tags. Do not
      // assume a collapsed default: normalize first, then verify both transitions.
      if (await filter.getAttribute('aria-expanded') === 'true') {
        await filter.click();
        await waitForFilter('false');
      }
      await filter.click();
      await waitForFilter('true');
      await page.locator('.X h3.I').waitFor({ state: 'visible' });
      assert.equal(await page.locator('.X h3.I').textContent(), en ? 'Filters' : '筛选');
      assert.equal(await page.locator('.X h4.R').textContent(), en ? 'Tags' : '标签');
      assert.equal(await filter.getAttribute('aria-expanded'), 'true');
      await filter.click();
      await waitForFilter('false');
      assert.equal(await filter.getAttribute('aria-expanded'), 'false');
      for (const term of ['KubeVirt', '调度']) {
        await query(page, term);
        await query(nativePage, term);
        const before = await snapshot(nativePage);
        assert.ok(before.length > 0, `${prefix}${term} has actual indexed results`);
        assert.deepEqual(await snapshot(page), before, 'All native links, titles, summaries and order remain unchanged');
        const summary = await page.locator('[data-search-polish-status]').textContent();
        const unique = new Set(before.map(item => item.href.split('#')[0])).size;
        assert.match(summary, en ? new RegExp(`Displayed: ${before.length} matches in ${unique} articles`) :
          new RegExp(`已显示 ${before.length} 处匹配，涉及 ${unique} 篇文章`));
        assert.match(await page.locator('h3.B').textContent(), en ? /\d+ results$/ : /\d+ 处匹配$/);
        if (before.length > unique) assert.ok(await page.locator('[data-search-polish-group]').count() > 1);
        console.log(`${en ? 'English' : 'Chinese'} ${term}: ${before.length} displayed matches / ${unique} articles; native content identical`);
      }
      await query(page, 'KubeVirt');
      await input.evaluate(el => {
        const root = el.getRootNode();
        window.__searchOriginalNodes = Array.from(root.querySelectorAll('ol.b > li > a'));
        const scroller = root.querySelector('.z');
        scroller.scrollTop = scroller.scrollHeight;
      });
      await page.waitForFunction(() => Array.from(document.body.children).some(el =>
        el.shadowRoot?.querySelectorAll('ol.b > li > a').length > 10));
      const loaded = await links(page).count();
      await page.waitForFunction(count => Array.from(document.body.children).some(el =>
        el.shadowRoot?.querySelector('[data-search-polish-status]')?.textContent.includes(String(count))), loaded);
      assert.equal(await input.evaluate(el => window.__searchOriginalNodes.every((node, index) =>
        node === el.getRootNode().querySelectorAll('ol.b > li > a')[index])), true, 'Infinite loading retains all original nodes');
      await query(page, '调度');
      await query(page, 'KubeVirt');
      const original = await links(page).evaluateAll(nodes => nodes.map(node => node.href));
      // Re-running the exact script must not duplicate observers, styles or listeners.
      await page.addScriptTag({ path: SOURCE });
      await page.addScriptTag({ path: SOURCE });
      assert.equal(await page.locator('style[data-search-polish]').count(), 1);
      assert.equal(await page.locator('[data-search-polish-status]').count(), 1);
      await input.press('ArrowDown');
      assert.equal(await page.locator('ol.b a.h').getAttribute('href'), original[1]);
      await input.press('ArrowUp');
      assert.equal(await page.locator('ol.b a.h').getAttribute('href'), original[0]);
      // Pick a real section anchor, then use native Enter to follow it.
      let selected = 0;
      const section = original.findIndex(href => new URL(href).hash);
      assert.ok(section >= 0);
      while (selected < section) { await input.press('ArrowDown'); selected++; }
      assert.equal(await page.locator('ol.b a.h').getAttribute('href'), original[section]);
      await Promise.all([page.waitForURL(original[section]), input.press('Enter')]);
      assert.equal(page.url(), original[section]);
      await page.locator('.md-search__button').click();
      await input.waitFor({ state: 'visible' });
      await input.press('Escape');
      // The native portal closes via opacity/pointer-events, not display:none.
      await page.waitForFunction(() => Array.from(document.body.children).some(el =>
        el.shadowRoot?.querySelector('input[role=combobox]') && el.shadowRoot.querySelector('.n.l')));
      await page.locator('.md-search__button').click();
      await page.waitForFunction(() => Array.from(document.body.children).some(el =>
        el.shadowRoot?.querySelector('input[role=combobox]') && el.shadowRoot.querySelector('.n:not(.l)')));
      assert.equal(await input.getAttribute('placeholder'), en ? 'Search' : '搜索');
      await input.fill('no-such-zxy49827');
      await page.waitForFunction(expected => {
        const host = Array.from(document.body.children).find(el => el.shadowRoot?.querySelector('input[role=combobox]'));
        return host?.shadowRoot.querySelector('[data-search-polish-status]')?.textContent === expected;
      }, en ? 'No matching results' : '暂无匹配结果');
      assert.equal(await links(page).count(), 0);
      await input.fill('');
      await page.waitForTimeout(1100);
      assert.equal(await page.locator('[data-search-polish-status]').isVisible(), false);
      // A language change followed by document$ initialization updates fixed UI only.
      await page.evaluate(() => { document.documentElement.lang = document.documentElement.lang === 'en' ? 'zh' : 'en'; });
      await input.fill('KubeVirt');
      await page.waitForTimeout(500);
      assert.equal(await input.getAttribute('placeholder'), en ? '搜索' : 'Search');
      assert.equal(await input.inputValue(), 'KubeVirt');
      await context.close();
      await nativeContext.close();
    }
    const staticContext = await contextFor(browser, false);
    const staticPage = await staticContext.newPage();
    staticPage.on('pageerror', error => errors.push(error.message));
    for (const prefix of ['', 'en/']) {
      await staticPage.goto('https://aik8s.run/' + prefix);
      assert.equal(await staticPage.locator('.md-search__button').count(), 1);
      assert.equal(await staticPage.locator('[data-search-polish-status]').count(), 0);
      assert.ok(await staticPage.locator('main').isVisible(), 'No-JS article remains readable');
    }
    await staticContext.close();
    assert.deepEqual(errors, []);
    console.log('PASS: localized UI, empty states, filters/tags, slash shortcut, infinite loading, native keyboard/Enter/Esc, reopen, idempotence, dynamic language, no-JS; no page errors');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
