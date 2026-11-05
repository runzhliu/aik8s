/* Integration checks for the built bilingual topic cloud. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const ROOT = path.resolve(__dirname, '..');

async function makeContext(browser, options = {}, failData = false) {
  const context = await browser.newContext(options);
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== 'https://aik8s.run') return route.abort();
    if (failData && /topic-cloud-(zh|en)\.json$/.test(url.pathname)) return route.abort();
    let file = path.join(ROOT, 'site', decodeURIComponent(url.pathname));
    if (url.pathname.endsWith('/')) file = path.join(file, 'index.html');
    if (!file.startsWith(path.join(ROOT, 'site') + path.sep) || !fs.existsSync(file)) return route.abort();
    return route.fulfill({ path: file });
  });
  return context;
}

async function assertPackedCloud(page) {
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const layout = await page.locator('[data-topic-words]').evaluate(container => {
    const parent = container.getBoundingClientRect();
    const boxes = Array.from(container.querySelectorAll('button'), button => {
      const r = button.getBoundingClientRect();
      return { term: button.textContent, left: r.left, right: r.right, top: r.top, bottom: r.bottom,
        position: getComputedStyle(button).position };
    });
    const outside = boxes.filter(r => r.left < parent.left - 1 || r.right > parent.right + 1 || r.top < parent.top - 1 || r.bottom > parent.bottom + 1).map(r => r.term);
    const overlapping = [];
    boxes.forEach((a, i) => boxes.slice(i + 1).forEach(b => {
      if (Math.min(a.right, b.right) - Math.max(a.left, b.left) > 1 && Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 1) overlapping.push([a.term, b.term]);
    }));
    return { outside, overlapping, positions: boxes.map(r => r.position) };
  });
  assert.ok(layout.positions.every(position => position === 'absolute'), 'Cloud terms use packed, free-form positioning');
  assert.deepEqual(layout.outside, [], 'Words fit inside the cloud');
  assert.deepEqual(layout.overlapping, [], 'Word buttons must not overlap');
}

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', args: ['--no-sandbox'] });
  try {
    const context = await makeContext(browser, { reducedMotion: 'reduce' });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    for (const [prefix, lang] of [['', 'zh'], ['en/', 'en']]) {
      await page.goto('https://aik8s.run/' + prefix);
      await page.locator('[data-topic-words] button').first().waitFor();
      for (const selector of ['script[src*="javascripts/topic-cloud.js"]', 'link[href*="stylesheets/topic-cloud.css"]']) {
        const version = await page.locator(selector).evaluate(el => el.src || el.href);
        assert.match(version, /\?v=[a-f0-9]{12}$/);
      }
      const data = JSON.parse(fs.readFileSync(path.join(ROOT, 'site', prefix, 'assets', `topic-cloud-${lang}.json`), 'utf8'));
      const buttons = page.locator('[data-topic-words] button');
      assert.equal(await buttons.count(), data.topics.length);
      assert.equal(await buttons.first().textContent(), data.topics[0].term);
      const palette = await buttons.evaluateAll(nodes => [...new Set(nodes.map(node => getComputedStyle(node).color))]);
      assert.ok(palette.length >= 3, 'Cloud uses a varied topic palette');
      const sizes = await buttons.evaluateAll(nodes => [parseFloat(getComputedStyle(nodes[0]).fontSize), parseFloat(getComputedStyle(nodes[nodes.length - 1]).fontSize)]);
      assert.ok(sizes[0] > sizes[1], 'More frequent terms are larger');
      assert.ok((await page.locator('[data-topic-status]').textContent()).includes(String(data.article_count)));
      await buttons.first().focus();
      await page.keyboard.press('Enter');
      assert.equal(await buttons.first().getAttribute('aria-pressed'), 'true');
      const detail = await page.locator('[data-topic-detail]').textContent();
      assert.ok(detail.includes(data.topics[0].term));
      assert.ok(detail.includes(new Intl.NumberFormat(lang === 'en' ? 'en' : 'zh-CN').format(data.topics[0].count)));
      assert.equal(await buttons.first().evaluate(el => getComputedStyle(el).animationName), 'none');
      for (const width of [1280, 375, 320, 768, 1440]) {
        await page.setViewportSize({ width, height: 900 });
        await assertPackedCloud(page);
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'No horizontal page overflow at ' + width + 'px');
      }
      await buttons.last().click();
      assert.equal(await buttons.last().getAttribute('aria-pressed'), 'true');
      assert.equal(await buttons.first().getAttribute('aria-pressed'), 'false');
      assert.ok((await page.locator('[data-topic-detail]').textContent()).includes(data.topics.at(-1).term));
      await page.evaluate(() => document.body.setAttribute('data-md-color-scheme', 'slate'));
      await assertPackedCloud(page);
      const darkPalette = await buttons.evaluateAll(nodes => [...new Set(nodes.map(node => getComputedStyle(node).color))]);
      assert.ok(darkPalette.length >= 3, 'Dark mode retains a varied palette');
    }
    assert.deepEqual(errors, []);
    await context.close();
    const noJs = await makeContext(browser, { javaScriptEnabled: false });
    const fallback = await noJs.newPage();
    await fallback.goto('https://aik8s.run/');
    assert.match(await fallback.locator('[data-topic-status]').textContent(), /JavaScript/);
    await noJs.close();
    const unmeasurable = await makeContext(browser);
    await unmeasurable.addInitScript(() => {
      const original = Element.prototype.getBoundingClientRect;
      Element.prototype.getBoundingClientRect = function () {
        return this.classList.contains('topic-cloud__word') ? new DOMRect() : original.call(this);
      };
    });
    const fallbackPage = await unmeasurable.newPage();
    await fallbackPage.goto('https://aik8s.run/');
    await fallbackPage.waitForFunction(() => document.querySelectorAll('[data-topic-words] button').length > 0);
    assert.equal(await fallbackPage.locator('[data-topic-words]').evaluate(el => getComputedStyle(el).display), 'flex');
    await unmeasurable.close();
    const failed = await makeContext(browser, {}, true);
    const failurePage = await failed.newPage();
    await failurePage.goto('https://aik8s.run/en/');
    await failurePage.waitForFunction(() => document.querySelector('[data-topic-status]').textContent.includes('could not be loaded'));
    await failed.close();
    console.log('Bilingual topic cloud browser checks passed.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
