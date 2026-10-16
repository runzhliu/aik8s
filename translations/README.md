# Bilingual publishing / 中英文发布

Chinese pages live in `docs/`; their complete English counterparts live in `translations/en/` at the same relative paths. Chinese URLs remain unchanged. English pages are published below `/en/`. Every new public article and every content update must include both languages by default.

修改中文文章的正文、标题、表格、图注或链接时，必须同步修改对应英文文章。英文稿的修改也须检查中文稿是否需要同步。

中文和英文必须保持事实、数字、版本、测量条件、失败分母和结论一致。不可只翻译摘要，也不可把提案翻译为已经验证的结果。命令、API 字段、URL、模型标识和原始测试 prompt 保持原样。Mermaid 的人类可读标签需翻译；真实截图保留原始证据，并提供英文图注及正文解释。

1. Add or update both Markdown files at the same relative path.
2. Update Chinese navigation in `zensical.toml` and its label mapping in `translations/navigation.en.json`.
3. Review the English text against the source, including tables, limitations, figure explanations, and links.
4. Record the paired files' SHA-256 hashes with `python3 scripts/record_translation.py path/to/page.md`. This records a completed review; it does not translate text or validate factual accuracy for you.
5. Run `python3 scripts/bilingual.py`, `python3 -m unittest discover -s scripts -p 'test_b*.py' -v`, and `make build`.
6. Open the built site, switch languages on the article, and check images, table of contents, search, and article dates before committing.

The production build fails for missing, stale, or structurally invalid translations. It builds two separate Zensical projects so theme text and search are localized too. English publication dates use the Chinese source's Git history; translating a historical article does not make it a newly published article. Chinese heading IDs remain available as aliases on English pages so existing links with Chinese fragments keep working.

Editable SVG labels and the HTML evidence page use `asset-strings.en.json`. SVG typography is measured using actual browser fonts; fitted English SVGs live under `en-assets/`, with source, label, and output hashes in `visual-layouts.en.json`. Source drawings, chart geometry, and original screenshots remain intact. `scripts/prepare_translation_visuals.py` creates a private typography workbench under the generated `site/` directory; review and export its fitted variants before updating the layout manifest.

The user explicitly prefers Chinese text in real screenshots to stay unchanged. Keep screenshots as original evidence, with bilingual captions and surrounding explanation; do not translate their pixels or add OCR transcripts for them.

Chinese plaintext diagrams, formulas, and captured examples get an English reading from `text-blocks.en.json`. The build retains the original block verbatim in an expandable panel. An English reading is a reader aid; original benchmark prompts and captured output remain available without being silently replaced. Executable code and API fixtures keep their original content in both language sources.

Quoted Chinese experiment prompts have paired hashes in `prompt-originals.json`. Their English readings appear with expandable, verbatim originals, so readers can reproduce the actual input. After editing a listed prompt, review both language versions and update both hashes; the production build rejects stale records.

`scripts/translate_docs.py` is an optional resumable text translator for public documents. Credentials must come from an ignored private file or environment variables, never committed files. Its structural checks preserve code, URLs, headings, and table rows; an automated pass is not a substitute for reviewing the translation. It never executes instructions from source text. Caches and raw API attempts remain under ignored `.local/`.

`python3 scripts/build_bilingual.py --docker --preview` can create a **private, incomplete preview** while translating. Production and CI never pass `--preview` and never publish fallback Chinese pages under English URLs.

Company notes, unpublished test plans, credentials, and unrelated drafts must stay outside this workflow. WeChat articles retain their established Chinese layout; future articles also maintain a separate English manuscript rather than interleaving two languages in one post.

The repository landing page also has a complete pair: `README.md` and `README.en.md`, with reciprocal language links. Keep both synchronized and record a reviewed update with `python3 scripts/record_translation.py --readme`; CI checks this pair alongside the website.
