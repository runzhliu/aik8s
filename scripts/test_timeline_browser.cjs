/* Optional integration test after scripts/build_bilingual.py.
 * Install Playwright separately and expose it via NODE_PATH, then run:
 * NODE_PATH=.local/browser-check/node_modules node scripts/test_timeline_browser.cjs
 * Uses system Chromium and serves built files by request interception, not a server.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const ROOT = path.resolve(__dirname, '..');

async function contextFor(browser, javascriptEnabled = true) {
  const context = await browser.newContext({ javaScriptEnabled: javascriptEnabled, reducedMotion: 'reduce' });
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== 'https://aik8s.run') return route.abort();
    let file = path.join(ROOT, 'site', decodeURIComponent(url.pathname));
    if (url.pathname.endsWith('/')) file = path.join(file, 'index.html');
    if (!file.startsWith(path.join(ROOT, 'site') + path.sep) || !fs.existsSync(file)) return route.abort();
    return route.fulfill({ path: file });
  });
  return context;
}

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', args: ['--no-sandbox'] });
  try {
    const context = await contextFor(browser);
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    for (const prefix of ['', 'en/']) {
      const base = 'https://aik8s.run/' + prefix;
      await page.setViewportSize({ width: 1440, height: 1000 });
      await page.goto(base + 'timeline.html?utm_source=test#article-timeline');
      const controls = page.locator('[data-timeline-controls]');
      await controls.waitFor({ state: 'visible' });
      const style = await controls.evaluate(form => {
        const select = form.querySelector('select');
        const input = form.querySelector('input');
        const button = form.querySelector('button');
        return {
          layout: getComputedStyle(form).display,
          appearance: getComputedStyle(select).appearance,
          heights: [select, input, button].map(el => el.getBoundingClientRect().height),
          inputWidth: input.getBoundingClientRect().width,
          selectWidth: select.getBoundingClientRect().width,
          heading: !!form.querySelector('.aik8s-timeline-controls__title svg'),
          version: document.querySelector('link[href*="stylesheets/timeline.css"]').href
        };
      });
      assert.equal(style.layout, 'grid');
      assert.equal(style.appearance, 'none', 'Select uses themed styling, not browser defaults');
      assert.ok(style.heights.every(height => Math.abs(height - style.heights[0]) < 1));
      assert.ok(style.inputWidth > style.selectWidth * 1.8, 'Search spans two columns');
      assert.ok(style.heading);
      assert.match(style.version, /\?v=[a-f0-9]{12}$/);
      const rows = await page.locator('[data-timeline-item]').evaluateAll(nodes => nodes.map(node => ({
        published: node.dataset.published, updated: node.dataset.updated,
        tags: node.dataset.tags.split(/\s+/).filter(Boolean), type: node.dataset.contentType
      })));
      assert.ok(rows.length > 50, 'All articles, not the RSS cap');
      await controls.locator('[name=sort]').selectOption('updated');
      let times = await page.locator('[data-timeline-date]').evaluateAll(nodes => nodes.map(node => Date.parse(node.dateTime)));
      assert.deepEqual(times, rows.map(row => Date.parse(row.updated)).sort((a,b) => b-a));
      const target = rows.find(row => row.tags.length && row.type === 'benchmark') || rows.find(row => row.tags.length);
      const tag = target.tags[0];
      await controls.locator('[name=tag]').selectOption(tag);
      assert.equal(await page.locator('[data-timeline-item]').count(), rows.filter(row => row.tags.includes(tag)).length);
      await controls.locator('[name=type]').selectOption(target.type);
      const matched = rows.filter(row => row.tags.includes(tag) && row.type === target.type).length;
      assert.equal(await page.locator('[data-timeline-item]').count(), matched);
      assert.ok(matched > 0);
      assert.equal(new URL(page.url()).searchParams.get('utm_source'), 'test');
      assert.equal(new URL(page.url()).hash, '#article-timeline');
      await page.reload();
      await controls.waitFor({ state: 'visible' });
      assert.equal(await controls.locator('[name=sort]').inputValue(), 'updated');
      assert.equal(await page.locator('[data-timeline-item]').count(), matched);
      const languageLink = page.locator('.md-select__link').filter({ hasText: prefix ? '简体中文' : 'English' });
      const languageUrl = new URL(await languageLink.getAttribute('href'), page.url());
      assert.equal(languageUrl.searchParams.get('tag'), tag);
      assert.equal(languageUrl.searchParams.get('type'), target.type);
      await controls.locator('[name=q]').fill('no-such-article-49827 <img src=x onerror=alert(1)>');
      assert.equal(await page.locator('[data-timeline-item]').count(), 0);
      assert.ok(await page.locator('[data-timeline-empty]').isVisible());
      await controls.locator('[name=q]').press('Enter');
      await page.goBack();
      assert.equal(await page.locator('[data-timeline-item]').count(), matched);
      await page.goForward();
      assert.equal(await page.locator('[data-timeline-item]').count(), 0);
      await controls.locator('[type=reset]').click();
      assert.equal(await page.locator('[data-timeline-item]').count(), rows.length);
      assert.equal(new URL(page.url()).searchParams.get('tag'), null);
      assert.equal(new URL(page.url()).searchParams.get('utm_source'), 'test');
      await controls.locator('[name=q]').fill('vllm');
      assert.ok(await page.locator('[data-timeline-item]').count() > 0);
      await controls.locator('[name=q]').fill('vllm impossibleword49827');
      assert.equal(await page.locator('[data-timeline-item]').count(), 0, 'Search words combine with AND');
      await controls.locator('[type=reset]').click();
      await page.setViewportSize({ width: 390, height: 844 });
      assert.ok(await controls.isVisible());
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      assert.ok(await controls.locator('input').evaluate(el => parseFloat(getComputedStyle(el).fontSize) >= 16));
      for (const height of await controls.locator('select,input,button').evaluateAll(nodes => nodes.map(el => el.getBoundingClientRect().height))) assert.ok(height >= 44);
      const lightBackground = await controls.evaluate(el => getComputedStyle(el).backgroundColor);
      await page.locator('.md-header [data-md-component=palette] label:visible').first().click();
      assert.ok(await controls.isVisible());
      assert.notEqual(await controls.evaluate(el => getComputedStyle(el).backgroundColor), lightBackground, 'Controls follow theme changes');
      await controls.locator('input').focus();
      assert.notEqual(await controls.locator('input').evaluate(el => getComputedStyle(el).boxShadow), 'none');
      await page.goto(base + 'timeline.html?tag=invalid&type=invalid&sort=invalid');
      await controls.waitFor({ state: 'visible' });
      assert.equal(await controls.locator('[name=tag]').inputValue(), '');
      assert.equal(await controls.locator('[name=sort]').inputValue(), 'published');
      assert.equal(await page.locator('[data-timeline-item]').count(), rows.length);
      await page.goto(base + 'ai-k8s/inference/engines/');
      const recommendations = page.locator('.aik8s-related li a');
      assert.ok(await recommendations.count() >= 1 && await recommendations.count() <= 4);
      for (const href of await recommendations.evaluateAll(nodes => nodes.map(node => node.href))) {
        assert.ok(href.startsWith(base));
        assert.notEqual(href, page.url());
        assert.ok(fs.existsSync(path.join(ROOT, 'site', new URL(href).pathname, 'index.html')));
      }
      await page.locator('.aik8s-article-tags a').first().click();
      await controls.waitFor({ state: 'visible' });
      assert.ok(new URL(page.url()).searchParams.has('tag'));
      assert.ok(await page.locator('[data-timeline-item]').count() > 0);
      console.log((prefix ? 'English' : 'Chinese') + ': filters, dates, history, search, URL, mobile, related articles OK');
    }
    assert.deepEqual(errors, []);
    await context.close();
    const staticContext = await contextFor(browser, false);
    const staticPage = await staticContext.newPage();
    for (const prefix of ['', 'en/']) {
      await staticPage.goto('https://aik8s.run/' + prefix + 'timeline.html');
      assert.ok(await staticPage.locator('[data-timeline-item]').count() > 50);
      assert.equal(await staticPage.locator('[data-timeline-controls]').isVisible(), false);
      await staticPage.goto('https://aik8s.run/' + prefix + 'ai-k8s/inference/engines/');
      assert.ok(await staticPage.locator('.aik8s-related li a').count() > 0);
    }
    await staticContext.close();
    console.log('No JavaScript: full timelines and related links remain readable');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
