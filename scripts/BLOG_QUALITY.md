# Blog quality checks / 博客质量检查

## Authored article metadata / 人工维护的文章信息

The builder never treats a Git update as a test certification. 阅读时间为估算，不包含动手实验；Git 更新日期、人工内容审阅日期是两个不同口径。

Optional, single-line Markdown front matter:

```yaml
last_reviewed: 2026-10-17
applicable_versions: "填写实际适用的 Kubernetes、框架等版本"
tested_environment: "填写实际核验过的硬件与运行环境"
```

- Do not add or refresh these values unless the content was actually reviewed. 未填写的版本、环境不显示，不从正文或 Git 推断。
- English documents can supply localized `applicable_versions` / `tested_environment`; the source document's `last_reviewed` remains the shared review date.
- Reading estimates weight CJK prose, English words, code lines, and illustrations separately. They are approximate reading aids, not promised completion times.
- “Report an issue / 反馈问题” only opens a prefilled GitHub issue; it does not submit anything or collect browser/environment details automatically.

## Search / 搜索

Search UI localization is scoped to the pinned theme's search shadow root. Native article titles, summaries, result nodes, links, ordering and keyboard navigation are preserved. The theme loads only part of the result corpus initially, so article counts explicitly describe **displayed** matches/articles. Same-article badges identify related section hits; results are not forcibly collapsed or moved, which would break the theme's virtualized selection behavior.

## Images / 图片

Local PNG/JPEG/GIF/WebP/SVG dimensions are read without decoding the image. The build reserves the aspect ratio, respects explicit sizing/loading, and only automatically lazy-loads later article images. A possible first/LCP image and header logos are not automatically lazy-loaded. No image bytes are re-encoded or changed.

## Local checks / 本地检查

After installing the pinned requirements and building both languages:

```bash
python3 -m unittest discover -s scripts -p 'test_*.py'
python3 scripts/build_bilingual.py
python3 scripts/check_site_links.py --site-dir site --site-url https://aik8s.run/
python3 scripts/check_site_budget.py --site-dir site
```

With a separately installed Playwright package and an existing Chromium/Chrome executable:

```bash
export NODE_PATH="$PWD/.local/browser-check/node_modules"
export CHROMIUM_PATH="/path/to/existing/chromium"
node scripts/test_timeline_browser.cjs
node scripts/test_engagement_browser.cjs
node scripts/test_blog_polish_browser.cjs
node scripts/test_search_browser.cjs
```

The browser tests serve built files through request interception, not a replacement server. Search tests compare enhanced and unenhanced native results. `SEARCH_POLISH_SOURCE=1` enables isolated source development; production CI uses the built asset.

## CI and budgets / 自动检查与预算

- Production publication is blocked by internal broken links, missing local images/assets, invalid HTML anchors, browser regressions, or exceeded authored-asset budgets.
- The budget JSON measures **raw local file bytes**, not compressed transfers, Lighthouse scores, Core Web Vitals, or ad payloads. Do not raise limits merely to silence a regression.
- The separate weekly external-link workflow never publishes a site. It produces a report for review; HTTP 403/429 and network failures are warnings, not proof that a URL is broken.
- External checking is opt-in locally: `python3 scripts/check_site_links.py --site-dir site --external --external-limit 100`. Private/local network targets, external iframes and generated feedback actions are not probed. External response bodies are not read.
- Internal checking is offline and does not parse CSS imports, JavaScript-generated routes or SVG-internal fragments. A small explicit dynamic-anchor allowlist exists; do not broadly ignore missing fragments.
- Ads, analytics configuration and consent behavior are unchanged by these optimizations.
