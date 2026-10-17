/* Run after the bilingual distribution build (no server or external network):
 * NODE_PATH=.local/browser-check/node_modules node scripts/test_engagement_browser.cjs
 * Playwright is optional; use system Chromium, overridable via CHROMIUM_PATH.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const ROOT = path.resolve(__dirname, '..');
const SITE = path.join(ROOT, 'site');
const engagement = fs.readFileSync(path.join(SITE, 'javascripts/engagement.js'), 'utf8');

async function reinitialize(page) {
  // Re-execute the actual built entry, including its normal initialize path.
  await page.addScriptTag({ content: engagement });
  await page.addScriptTag({ content: engagement });
}

async function assertModal(page, trigger) {
  await trigger.focus();
  await trigger.press('Enter');
  const dialog = page.locator('dialog.aik8s-lightbox[open]');
  await dialog.waitFor({ state: 'visible' });
  assert.ok(await dialog.evaluate(el => el.matches(':modal')), 'Native modal top layer');
  assert.equal(await page.evaluate(() => getComputedStyle(document.body).overflow), 'hidden');
  assert.ok(await dialog.evaluate(el => el.contains(document.activeElement)));
  for (const key of ['Tab', 'Shift+Tab']) {
    for (let i = 0; i < 8; i++) {
      await page.keyboard.press(key);
      assert.ok(await dialog.evaluate(el => el.contains(document.activeElement)), `${key} stays inside modal`);
    }
  }
  // Programmatic focus is also blocked by native background inertness.
  await page.locator('#engagement-background').evaluate(el => el.focus());
  assert.ok(await dialog.evaluate(el => el.contains(document.activeElement)));
  await page.keyboard.press('Escape');
  await dialog.waitFor({ state: 'hidden' });
  assert.ok(await trigger.evaluate(el => el === document.activeElement), 'Esc restores trigger focus');
  assert.equal(await page.locator('body.aik8s-lightbox-open').count(), 0);
  await trigger.press('Enter');
  await dialog.waitFor({ state: 'visible' });
  // The full-viewport dialog is its own overlay; click well outside the figure.
  await page.mouse.click(4, 4);
  await dialog.waitFor({ state: 'hidden' });
  assert.ok(await trigger.evaluate(el => el === document.activeElement), 'Backdrop restores trigger focus');
}

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', args: ['--no-sandbox'] });
  try {
    const context = await browser.newContext({ reducedMotion: 'reduce', viewport: { width: 1280, height: 900 }, serviceWorkers: 'block' });
    await context.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.origin !== 'https://aik8s.run') return route.abort();
      let file = path.resolve(SITE, '.' + decodeURIComponent(url.pathname));
      if (url.pathname.endsWith('/')) file = path.join(file, 'index.html');
      if (!file.startsWith(SITE + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) return route.abort();
      return route.fulfill({ path: file });
    });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    for (const prefix of ['', 'en/']) {
      const base = 'https://aik8s.run/' + prefix;
      for (const route of ['', 'ai-k8s/', 'cases/', 'k3s-upgrade/']) {
        await page.goto(base + route);
        await reinitialize(page);
        assert.equal(await page.locator('.aik8s-comments').count(), 0, `${prefix + route}: no index comments`);
        assert.equal(await page.locator('.aik8s-share a[href="#comments"]').count(), 0, 'No dead comment anchor');
        assert.equal(await page.locator('.aik8s-share').count(), 1, 'Index sharing remains available');
      }
      await page.goto(base + 'timeline.html?utm_source=engagement-test#article-timeline');
      for (let i = 0; i < 2; i++) {
        // Simulate stale instant-navigation DOM, not just a clean initial load.
        await page.locator('article.md-content__inner').evaluate(article => {
          article.insertAdjacentHTML('beforeend', '<nav class="aik8s-share"><a href="#comments">Stale comments</a></nav><section class="aik8s-comments" id="comments"></section>');
        });
        await reinitialize(page);
        assert.equal(await page.locator('.aik8s-share, .aik8s-comments, .aik8s-share a[href="#comments"]').count(), 0, 'Timeline never mounts engagement');
        await page.reload();
      }
      await page.goto(base + 'ai-k8s/inference/engines/');
      await reinitialize(page);
      assert.equal(await page.locator('.aik8s-share').count(), 1);
      assert.equal(await page.locator('.aik8s-comments#comments').count(), 1);
      assert.equal(await page.locator('.aik8s-share a[href="#comments"]').count(), 1);
      // Deterministic visuals avoid remote images/CDN Mermaid dependencies. They
      // exercise the real built article, MutationObserver, modal and restoration.
      await page.evaluate(() => {
        const article = document.querySelector('article.md-content__inner');
        article.insertAdjacentHTML('beforeend', '<div id="engagement-fixtures"><button id="engagement-background">Background</button><button id="engagement-disabled" disabled>Disabled</button><div id="engagement-inert" inert><button>Inert</button></div><button id="engagement-hidden" hidden>Hidden</button><img id="engagement-image" alt="Offline preview fixture" width="240" height="120"><div id="engagement-mermaid-parent"><div class="mermaid" id="engagement-mermaid"><svg xmlns="http://www.w3.org/2000/svg" width="320" height="100" viewBox="0 0 320 100"><rect width="320" height="100" fill="lightblue"/><text x="20" y="50">Offline Mermaid-shaped fixture</text></svg></div></div></div>');
        document.querySelector('#engagement-image').src = 'data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="240" height="120"><rect width="240" height="120" fill="steelblue"/></svg>');
      });
      const image = page.locator('#engagement-image');
      await page.waitForFunction(() => document.querySelector('#engagement-image').dataset.aik8sLightbox === 'true');
      await assertModal(page, image);
      await image.press('Enter');
      const preview = page.locator('dialog[open] .aik8s-lightbox__image');
      await page.waitForFunction(() => { const img = document.querySelector('dialog[open] .aik8s-lightbox__image'); return img && img.complete && img.naturalWidth > 0; });
      assert.equal(await preview.getAttribute('alt'), 'Offline preview fixture');
      assert.equal(await page.locator('dialog[open] .aik8s-lightbox__diagram-host').isVisible(), false);
      await page.locator('dialog[open] .aik8s-lightbox__close').click();
      assert.ok(await image.evaluate(el => el === document.activeElement));
      const diagram = page.locator('#engagement-mermaid');
      await assertModal(page, diagram);
      assert.equal(await diagram.locator('..').getAttribute('id'), 'engagement-mermaid-parent', 'Diagram returns to original parent');
      assert.equal(await page.locator('.aik8s-lightbox__placeholder').count(), 0);
      await diagram.press('Enter');
      assert.equal(await page.locator('dialog[open] .aik8s-lightbox__image').isVisible(), false, 'Hidden image stays hidden for diagrams');
      assert.equal(await page.locator('dialog[open] #engagement-mermaid svg').count(), 1, 'Original SVG moved, not cloned');
      await page.keyboard.press('Escape');
      assert.ok(await page.locator('#engagement-disabled').isDisabled());
      assert.ok(await page.locator('#engagement-inert').evaluate(el => el.inert));
      assert.ok(await page.locator('#engagement-hidden').evaluate(el => el.hidden));
      // Development builds lack distribution dates/structured data: keep comments.
      await page.evaluate(() => {
        document.querySelectorAll('.aik8s-article-dates, script[type="application/ld+json"], .aik8s-share, .aik8s-comments').forEach(el => el.remove());
      });
      await reinitialize(page);
      assert.equal(await page.locator('.aik8s-comments').count(), 1, 'No-dates dev article retains comments');
      // Other generated directory indexes advertise CollectionPage explicitly.
      await page.evaluate(() => {
        document.querySelectorAll('.aik8s-share, .aik8s-comments').forEach(el => el.remove());
        const script = document.createElement('script');
        script.type = 'application/ld+json';
        script.textContent = JSON.stringify({ '@graph': [{ '@type': 'CollectionPage' }] });
        document.head.append(script);
      });
      await reinitialize(page);
      assert.equal(await page.locator('.aik8s-comments, .aik8s-share a[href="#comments"]').count(), 0, 'Metadata index has no comment link');
      console.log(`${prefix ? 'English' : 'Chinese'}: index/timeline/article policy, repeat initialization, image/Mermaid modal focus/Esc/backdrop/restoration OK`);
    }
    assert.deepEqual(errors, []);
    await context.close();
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
