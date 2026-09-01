#!/usr/bin/env python3
"""Render Markdown and create, update, or inspect a WeChat Official Account draft."""

from __future__ import annotations

import argparse
import html
import json
import mimetypes
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import markdown
import requests
from bs4 import BeautifulSoup, NavigableString, Tag


API_BASE = "https://api.weixin.qq.com/cgi-bin"
DEFAULT_OUTPUT = Path(".wechat-output")
WECHAT_AUTHOR = "runzhliu"

STYLES = {
    "section": (
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC',"
        "'Hiragino Sans GB','Microsoft YaHei',sans-serif;font-size:16px;"
        "line-height:1.75;color:#1f2937;letter-spacing:0;word-break:break-word;"
        "text-align:left!important;"
    ),
    "h2": (
        "margin:2.2em 0 1em;padding:0.15em 0 0.15em 0.75em;border-left:4px solid #2563eb;"
        "font-size:22px;line-height:1.45;color:#111827;font-weight:700;"
        "text-align:left!important;"
    ),
    "h3": (
        "margin:1.8em 0 0.8em;font-size:18px;line-height:1.5;color:#1d4ed8;"
        "font-weight:700;text-align:left!important;"
    ),
    "p": "margin:0.9em 0;line-height:1.75;text-align:left!important;",
    "ul": "margin:0.8em 0;padding-left:1.4em;text-align:left!important;",
    "ol": "margin:0.8em 0;padding-left:1.4em;text-align:left!important;",
    "li": "margin:0.35em 0;line-height:1.7;text-align:left!important;",
    "strong": "color:#111827;font-weight:700;",
    "blockquote": (
        "margin:1.2em 0;padding:0.8em 1em;border-left:4px solid #93c5fd;"
        "background:#eff6ff;color:#374151;text-align:left!important;"
    ),
    "pre": (
        "margin:1.2em 0;padding:1em;overflow-x:auto;border-radius:8px;background:#0f172a;"
        "color:#e2e8f0;font-size:12.5px;line-height:1.6;white-space:pre;word-break:normal;"
        "overflow-wrap:normal;-webkit-overflow-scrolling:touch;text-align:left!important;"
    ),
    "code": (
        "padding:0.15em 0.35em;border-radius:4px;background:#f1f5f9;color:#be123c;"
        "font-family:SFMono-Regular,Consolas,'Liberation Mono',monospace;font-size:0.9em;"
    ),
    "table": (
        "width:100%;margin:1.2em 0;border-collapse:collapse;table-layout:auto;"
        "font-size:13px;line-height:1.55;"
    ),
    "th": (
        "padding:0.55em;border:1px solid #cbd5e1;background:#eff6ff;color:#1e3a8a;"
        "font-weight:700;text-align:left!important;"
    ),
    "td": "padding:0.55em;border:1px solid #cbd5e1;vertical-align:top;text-align:left!important;",
    "a": "color:#2563eb;text-decoration:none;word-break:break-all;",
    "img": "display:block;max-width:100%;height:auto;margin:1.2em auto;border-radius:6px;",
    "hr": "margin:2em 0;border:0;border-top:1px solid #e5e7eb;",
}


class WeChatAPIError(RuntimeError):
    pass


def redact_sensitive(value: object) -> str:
    message = str(value)
    return re.sub(
        r"(?i)(access_token|secret)=([^&\s'\"\)]+)",
        lambda match: f"{match.group(1)}=<redacted>",
        message,
    )


def load_env_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"missing env file: {path}")
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ValueError(f"invalid env line {line_number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ValueError(f"invalid env key on line {line_number}: {key}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def extract_title(markdown_text: str, source: Path) -> tuple[str, str]:
    match = re.search(r"^#\s+(.+?)\s*$", markdown_text, re.MULTILINE)
    if match is None:
        return source.stem.replace("-", " "), markdown_text
    title = match.group(1).strip()
    body = markdown_text[: match.start()] + markdown_text[match.end() :]
    return title, body.lstrip()


def inline_styles(fragment: str) -> BeautifulSoup:
    parsed = BeautifulSoup(fragment, "html.parser")
    section = parsed.new_tag("section")
    section["style"] = STYLES["section"]
    for child in list(parsed.contents):
        section.append(child.extract())

    for tag_name, style in STYLES.items():
        if tag_name == "section":
            continue
        for tag in section.find_all(tag_name):
            existing = tag.get("style", "")
            tag["style"] = style + existing

    # Match the metadata emitted by the WeChat rich-text editor. Plain
    # <a href> tags can be removed when a draft is saved through the API.
    for anchor in section.find_all("a", href=True):
        anchor["target"] = "_blank"
        anchor["linktype"] = "text"
        anchor["textvalue"] = anchor.get_text(" ", strip=True)
        anchor["tab"] = "outerlink"
        anchor["data-linktype"] = "2"

    for code in section.find_all("code"):
        if code.parent and code.parent.name == "pre":
            raw_code = code.get_text().rstrip("\n")
            code.clear()
            lines = raw_code.split("\n")
            for index, line in enumerate(lines):
                # WeChat collapses raw newlines in <pre> after a draft is
                # saved. Use structural line breaks and non-breaking spaces
                # so ASCII diagrams and YAML indentation survive sanitizing.
                code.append(NavigableString(line.replace("\t", "    ").replace(" ", "\u00a0")))
                if index < len(lines) - 1:
                    code.append(parsed.new_tag("br"))
            code["style"] = (
                "font-family:SFMono-Regular,Consolas,'Liberation Mono',monospace;"
                "font-size:12.5px;color:inherit;background:transparent;padding:0;"
                "white-space:normal;display:block;"
            )

    # WeChat's draft sanitizer can turn formatting-only newline nodes inside
    # ul/ol into empty list items. Compact each list before serializing it.
    for list_tag in section.find_all(["ul", "ol"]):
        for child in list(list_tag.children):
            if isinstance(child, NavigableString) and not child.strip():
                child.extract()
    return BeautifulSoup(str(section), "html.parser")


def render_markdown(source: Path) -> tuple[str, str, str]:
    markdown_text = source.read_text(encoding="utf-8")
    title, body = extract_title(markdown_text, source)
    fragment = markdown.markdown(
        body,
        extensions=["extra", "sane_lists", "codehilite"],
        extension_configs={"codehilite": {"noclasses": True, "guess_lang": False}},
        output_format="html5",
    )
    soup = inline_styles(fragment)
    first_paragraph = soup.find("p")
    digest = first_paragraph.get_text(" ", strip=True) if first_paragraph else title
    digest = re.sub(r"\s+", " ", digest)[:120]
    return title, str(soup.section), digest


def full_preview(title: str, content: str) -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{title}</title>
</head>
<body style="margin:0;background:#f3f4f6;">
  <main style="max-width:677px;margin:0 auto;padding:28px 22px;background:#fff;">
    <h1 style="font-size:28px;line-height:1.4;color:#111827;margin:0 0 1.2em;">{title}</h1>
    {content}
  </main>
</body>
</html>
""".format(title=html.escape(title), content=content)


def check_response(response: requests.Response, action: str) -> dict[str, Any]:
    response.raise_for_status()
    try:
        # Some WeChat endpoints omit a UTF-8 charset and requests otherwise
        # decodes Chinese response fields as ISO-8859-1.
        payload = json.loads(response.content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise WeChatAPIError(f"{action} returned invalid UTF-8 JSON") from error
    if payload.get("errcode", 0) != 0:
        raise WeChatAPIError(
            f"{action} failed: errcode={payload.get('errcode')} errmsg={payload.get('errmsg')}"
        )
    return payload


def get_access_token(app_id: str, app_secret: str) -> str:
    response = requests.get(
        f"{API_BASE}/token",
        params={"grant_type": "client_credential", "appid": app_id, "secret": app_secret},
        timeout=30,
    )
    payload = check_response(response, "get access token")
    token = payload.get("access_token")
    if not token:
        raise WeChatAPIError("get access token returned no access_token")
    return str(token)


def upload_file(
    token: str,
    endpoint: str,
    path: Path,
    action: str,
    *,
    params: dict[str, str] | None = None,
) -> dict[str, Any]:
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    request_params = {"access_token": token}
    if params:
        request_params.update(params)
    with path.open("rb") as stream:
        response = requests.post(
            endpoint,
            params=request_params,
            files={"media": (path.name, stream, mime_type)},
            timeout=180,
        )
    return check_response(response, action)


def upload_article_image(token: str, path: Path) -> str:
    payload = upload_file(
        token,
        f"{API_BASE}/media/uploadimg",
        path,
        "upload article image",
    )
    url = payload.get("url")
    if not url:
        raise WeChatAPIError(f"upload article image returned no url for {path}")
    return str(url)


def upload_cover(token: str, path: Path) -> str:
    payload = upload_file(
        token,
        f"{API_BASE}/material/add_material",
        path,
        "upload cover",
        params={"type": "image"},
    )
    media_id = payload.get("media_id")
    if not media_id:
        raise WeChatAPIError("upload cover returned no media_id")
    return str(media_id)


def materialize_image(src: str, article_dir: Path, temp_dir: Path) -> Path:
    parsed = urlparse(src)
    if parsed.scheme in {"http", "https"}:
        response = requests.get(src, timeout=60)
        response.raise_for_status()
        suffix = Path(parsed.path).suffix or ".img"
        target = temp_dir / f"remote-{abs(hash(src))}{suffix}"
        target.write_bytes(response.content)
        return target
    path = Path(src)
    if not path.is_absolute():
        path = article_dir / path
    if not path.is_file():
        raise FileNotFoundError(f"article image not found: {path}")
    return path


def upload_content_images(token: str, content: str, article_dir: Path) -> str:
    soup = BeautifulSoup(content, "html.parser")
    with tempfile.TemporaryDirectory(prefix="aik8s-wechat-") as temp_name:
        temp_dir = Path(temp_name)
        for image in soup.find_all("img"):
            src = image.get("src")
            if not src:
                continue
            local_path = materialize_image(src, article_dir, temp_dir)
            image["src"] = upload_article_image(token, local_path)
    return str(soup.section or soup)


def create_draft(
    token: str,
    *,
    title: str,
    author: str,
    digest: str,
    content: str,
    source_url: str,
    thumb_media_id: str,
) -> str:
    # WeChat's draft endpoint may persist JSON Unicode escape sequences as
    # literal text. Send an explicit UTF-8 body so Chinese remains Chinese.
    payload = {
        "articles": [
            {
                "title": title,
                "author": author,
                "digest": digest,
                "content": content,
                "content_source_url": source_url,
                "thumb_media_id": thumb_media_id,
                "need_open_comment": 0,
                "only_fans_can_comment": 0,
            }
        ]
    }
    response = requests.post(
        f"{API_BASE}/draft/add",
        params={"access_token": token},
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=60,
    )
    payload = check_response(response, "create draft")
    media_id = payload.get("media_id")
    if not media_id:
        raise WeChatAPIError("create draft returned no media_id")
    return str(media_id)


def update_draft(
    token: str,
    *,
    media_id: str,
    title: str,
    author: str,
    digest: str,
    content: str,
    source_url: str,
    thumb_media_id: str,
) -> None:
    payload = {
        "media_id": media_id,
        "index": 0,
        "articles": {
            "title": title,
            "author": author,
            "digest": digest,
            "content": content,
            "content_source_url": source_url,
            "thumb_media_id": thumb_media_id,
            "need_open_comment": 0,
            "only_fans_can_comment": 0,
        },
    }
    response = requests.post(
        f"{API_BASE}/draft/update",
        params={"access_token": token},
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=60,
    )
    check_response(response, "update draft")


def get_draft(token: str, media_id: str) -> dict[str, Any]:
    response = requests.post(
        f"{API_BASE}/draft/get",
        params={"access_token": token},
        data=json.dumps({"media_id": media_id}).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=60,
    )
    return check_response(response, "get draft")


def list_drafts(token: str, *, offset: int = 0, count: int = 20) -> dict[str, Any]:
    response = requests.post(
        f"{API_BASE}/draft/batchget",
        params={"access_token": token},
        data=json.dumps(
            {"offset": offset, "count": count, "no_content": 1}
        ).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=60,
    )
    return check_response(response, "list drafts")


def command_render(args: argparse.Namespace) -> None:
    title, content, _ = render_markdown(args.article)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(full_preview(title, content), encoding="utf-8")
    print(f"rendered: {args.output}")


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"missing required setting: {name}")
    return value


def command_draft(args: argparse.Namespace) -> None:
    load_env_file(args.env_file)
    app_id = required_env("WECHAT_APP_ID")
    app_secret = required_env("WECHAT_APP_SECRET")
    author = WECHAT_AUTHOR
    source_url = (
        args.source_url.strip()
        if args.source_url is not None
        else os.environ.get("WECHAT_SOURCE_URL", "").strip()
    )

    title, content, digest = render_markdown(args.article)
    token = get_access_token(app_id, app_secret)
    content = upload_content_images(token, content, args.article.parent)

    if args.cover is not None:
        thumb_media_id = upload_cover(token, args.cover)
    else:
        thumb_media_id = os.environ.get("WECHAT_THUMB_MEDIA_ID", "").strip()
        if not thumb_media_id:
            raise ValueError("set WECHAT_THUMB_MEDIA_ID or pass --cover")

    media_id = create_draft(
        token,
        title=title,
        author=author,
        digest=digest,
        content=content,
        source_url=source_url,
        thumb_media_id=thumb_media_id,
    )
    print(f"draft created: media_id={media_id}")


def command_update(args: argparse.Namespace) -> None:
    load_env_file(args.env_file)
    app_id = required_env("WECHAT_APP_ID")
    app_secret = required_env("WECHAT_APP_SECRET")
    author = WECHAT_AUTHOR
    source_url = (
        args.source_url.strip()
        if args.source_url is not None
        else os.environ.get("WECHAT_SOURCE_URL", "").strip()
    )

    title, content, digest = render_markdown(args.article)
    token = get_access_token(app_id, app_secret)
    content = upload_content_images(token, content, args.article.parent)

    if args.cover is not None:
        thumb_media_id = upload_cover(token, args.cover)
    else:
        thumb_media_id = os.environ.get("WECHAT_THUMB_MEDIA_ID", "").strip()
        if not thumb_media_id:
            existing = get_draft(token, args.media_id)
            articles = existing.get("news_item", [])
            if not articles:
                raise WeChatAPIError("get draft returned no articles")
            thumb_media_id = str(articles[0].get("thumb_media_id", "")).strip()
            if not thumb_media_id:
                raise ValueError("existing draft has no cover; pass --cover")

    update_draft(
        token,
        media_id=args.media_id,
        title=title,
        author=author,
        digest=digest,
        content=content,
        source_url=source_url,
        thumb_media_id=thumb_media_id,
    )
    print(f"draft updated: media_id={args.media_id}")


def command_inspect(args: argparse.Namespace) -> None:
    """Read back a draft without printing credentials or the full article body."""
    load_env_file(args.env_file)
    token = get_access_token(
        required_env("WECHAT_APP_ID"),
        required_env("WECHAT_APP_SECRET"),
    )
    payload = get_draft(token, args.media_id)
    articles = payload.get("news_item", [])
    if not articles:
        raise WeChatAPIError("get draft returned no articles")

    article = articles[0]
    content = str(article.get("content", ""))
    soup = BeautifulSoup(content, "html.parser")
    print(f"title: {article.get('title', '')}")
    print(f"author: {article.get('author', '')}")
    print(f"source_url: {article.get('content_source_url', '')}")
    image_sources = [
        str(image.get("data-src") or image.get("src") or "").strip()
        for image in soup.find_all("img")
    ]
    remote_images = []
    for source in image_sources:
        parsed_source = urlparse(source)
        if parsed_source.scheme in {"http", "https"} or bool(parsed_source.netloc):
            remote_images.append(source)
    print(
        f"content_images: {len(image_sources)} "
        f"(remote={len(remote_images)}, local={len(image_sources) - len(remote_images)})"
    )
    print(f"cover: {'present' if article.get('thumb_media_id') else 'missing'}")
    paragraphs = [
        paragraph.get_text(" ", strip=True)
        for paragraph in soup.find_all("p")
        if paragraph.get_text(" ", strip=True)
    ]
    for index, paragraph in enumerate(paragraphs[:2], start=1):
        print(f"intro_{index}: {paragraph}")
    visible_text = soup.get_text(" ", strip=True)
    visible_urls = list(
        dict.fromkeys(re.findall(r"https?://[^\s，。；、）)]+", visible_text))
    )
    print(f"visible_urls: {len(visible_urls)}")
    for url in visible_urls:
        print(f"- {url}")
    anchors = soup.find_all("a")
    print(f"anchors: {len(anchors)}")
    for anchor in anchors:
        label = anchor.get_text(" ", strip=True)
        print(f"- {label} -> {anchor.get('href', '')}")


def command_list(args: argparse.Namespace) -> None:
    """List recent drafts without printing credentials or article bodies."""
    load_env_file(args.env_file)
    token = get_access_token(
        required_env("WECHAT_APP_ID"),
        required_env("WECHAT_APP_SECRET"),
    )
    payload = list_drafts(token, count=args.count)
    for item in payload.get("item", []):
        articles = item.get("content", {}).get("news_item", [])
        if not articles:
            continue
        article = articles[0]
        print(
            f"{item.get('media_id', '')}\t"
            f"{article.get('title', '')}\t"
            f"{article.get('author', '')}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    render = subparsers.add_parser("render", help="render a local HTML preview")
    render.add_argument("article", type=Path)
    render.add_argument("--output", type=Path, default=DEFAULT_OUTPUT / "preview.html")
    render.set_defaults(func=command_render)

    draft = subparsers.add_parser("draft", help="create a WeChat Official Account draft")
    draft.add_argument("article", type=Path)
    draft.add_argument("--env-file", type=Path, default=Path(".deploy-secrets/wechat.env"))
    draft.add_argument("--cover", type=Path)
    draft.add_argument("--source-url")
    draft.set_defaults(func=command_draft)

    update = subparsers.add_parser("update", help="update a WeChat Official Account draft")
    update.add_argument("article", type=Path)
    update.add_argument("--media-id", required=True)
    update.add_argument("--env-file", type=Path, default=Path(".deploy-secrets/wechat.env"))
    update.add_argument("--cover", type=Path)
    update.add_argument("--source-url")
    update.set_defaults(func=command_update)

    inspect = subparsers.add_parser(
        "inspect", help="read back a draft title, source URL, and links"
    )
    inspect.add_argument("--media-id", required=True)
    inspect.add_argument("--env-file", type=Path, default=Path(".deploy-secrets/wechat.env"))
    inspect.set_defaults(func=command_inspect)

    list_parser = subparsers.add_parser("list", help="list recent drafts")
    list_parser.add_argument("--count", type=int, default=20, choices=range(1, 21))
    list_parser.add_argument(
        "--env-file", type=Path, default=Path(".deploy-secrets/wechat.env")
    )
    list_parser.set_defaults(func=command_list)

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        args.func(args)
    except (FileNotFoundError, ValueError, WeChatAPIError, requests.RequestException) as error:
        print(f"error: {redact_sensitive(error)}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
