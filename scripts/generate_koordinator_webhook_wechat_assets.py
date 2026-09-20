#!/usr/bin/env python3
"""Generate WeChat covers and the certificate ownership diagram."""

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "articles/wechat/assets/koordinator-webhook-cert-race"
TMP = ROOT / ".local/koordinator-webhook-cert-race/wechat"
CHROME = Path(
    "/Users/oscar01.liu/Library/Caches/ms-playwright/"
    "chromium_headless_shell-1228/chrome-headless-shell-mac-arm64/"
    "chrome-headless-shell"
)


def page(width: int, height: int, body: str, extra_css: str = "") -> str:
    return f"""<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">
<meta name=\"viewport\" content=\"width={width},initial-scale=1\"><style>
*{{box-sizing:border-box}}html,body{{margin:0;width:{width}px;height:{height}px;overflow:hidden}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Hiragino Sans GB','Microsoft YaHei',sans-serif;background:#fffaf8;color:#28222a}}
{extra_css}</style></head><body>{body}</body></html>"""


def render(name: str, width: int, height: int, html: str) -> None:
    TMP.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    source = TMP / f"{name}.html"
    target = OUT / f"{name}.png"
    source.write_text(html, encoding="utf-8")
    subprocess.run(
        [
            str(CHROME),
            "--headless",
            "--disable-gpu",
            "--hide-scrollbars",
            f"--window-size={width},{height}",
            f"--screenshot={target}",
            source.as_uri(),
        ],
        check=True,
    )


def cover_wide() -> str:
    body = """
<main class="cover"><div class="stripe"></div>
  <section class="copy"><div class="kicker">AI-K8S 生产实战</div>
    <h1>Koordinator Webhook</h1><h2>八个副本，八套 CA</h2>
    <div class="metric">60.1 次/秒 409 <b>→ 0</b></div>
    <p>证书竞态 · 写放大 · 共享 Secret</p>
  </section>
  <section class="visual"><div class="pods">
    <i>CA-1</i><i>CA-2</i><i>CA-3</i><i>CA-4</i><i>CA-5</i><i>CA-6</i><i>CA-7</i><i>CA-8</i>
  </div><div class="arrow">↓</div><div class="secret">Shared Secret<br><b>ONE CA</b></div></section>
</main>"""
    css = """
.cover{position:relative;width:900px;height:383px;padding:35px 46px;background:#fffaf8}.stripe{position:absolute;left:0;top:0;bottom:0;width:13px;background:linear-gradient(#326ce5,#6558d9,#33b9d5)}
.copy{width:550px}.kicker{font-size:18px;color:#326ce5;margin-bottom:25px}h1{margin:0;font-size:43px;line-height:1.05;color:#2454bc;font-weight:500}h2{margin:21px 0 15px;font-size:31px;font-weight:450;letter-spacing:.03em}.metric{font-size:25px;color:#d04435}.metric b{color:#16835a}p{margin:22px 0 0;font-size:17px;color:#8b7780}
.visual{position:absolute;right:47px;top:75px;width:250px;text-align:center}.pods{display:grid;grid-template-columns:repeat(4,1fr);gap:9px}.pods i{height:48px;border:1px solid #9eb8f2;border-radius:8px;background:#fff;color:#326ce5;font-style:normal;font-size:12px;display:flex;align-items:center;justify-content:center}.arrow{font-size:24px;color:#7b66d9;height:34px}.secret{border:1.5px solid #7b66d9;border-radius:10px;background:#f4f1ff;padding:10px;color:#5746b8;font-size:15px;line-height:1.25}.secret b{font-size:17px}
"""
    return page(900, 383, body, css)


def cover_square() -> str:
    body = """
<main class="cover"><div class="stripe"></div><div class="kicker">AI-K8S 生产实战</div>
  <h1>Koordinator<br>Webhook</h1><h2>八个副本，八套 CA</h2>
  <div class="flow"><div class="pods"><i>CA-1</i><i>CA-2</i><i>CA-3</i><i>CA-4</i><i>CA-5</i><i>CA-6</i><i>CA-7</i><i>CA-8</i></div><div class="arrow">↓</div><div class="secret">Shared Secret · ONE CA</div></div>
  <div class="metric">60.1 次/秒 409 <b>→ 0</b></div><p>证书竞态 · 写放大 · 生产修复</p>
</main>"""
    css = """
.cover{position:relative;width:900px;height:900px;padding:62px;background:#fffaf8}.stripe{position:absolute;left:0;top:0;bottom:0;width:15px;background:linear-gradient(#326ce5,#6558d9,#33b9d5)}
.kicker{font-size:25px;color:#326ce5;margin-bottom:70px}h1{margin:0;color:#2454bc;font-size:72px;line-height:1.05;font-weight:500;letter-spacing:-.02em}h2{margin:35px 0 45px;font-size:42px;font-weight:450}.flow{width:775px}.pods{display:grid;grid-template-columns:repeat(4,1fr);gap:15px}.pods i{height:72px;border:1.5px solid #9eb8f2;border-radius:11px;background:#fff;color:#326ce5;font-style:normal;font-size:19px;display:flex;align-items:center;justify-content:center}.arrow{text-align:center;font-size:36px;color:#7b66d9;height:51px}.secret{height:72px;border:2px solid #7b66d9;border-radius:12px;background:#f4f1ff;color:#5746b8;font-size:25px;display:flex;align-items:center;justify-content:center}.metric{margin-top:48px;font-size:34px;color:#d04435}.metric b{color:#16835a}p{font-size:23px;color:#8b7780;margin-top:20px}
"""
    return page(900, 900, body, css)


def architecture() -> str:
    before_pods = "".join(f"<i>Pod {n}<small>CA-{n}</small></i>" for n in range(1, 9))
    after_pods = "".join(f"<i>Pod {n}<small>同一 CA</small></i>" for n in range(1, 9))
    body = f"""
<main><header><h1>八个副本为什么会制造一场证书竞态</h1><p>问题不在副本数本身，而在证书与 caBundle 的所有权</p></header>
  <div class="columns">
    <section class="case bad"><h2>修复前：8 个本地证书所有者</h2><div class="pods">{before_pods}</div>
      <div class="arrows">多套 CA 反复覆盖　↓</div><div class="object">WebhookConfiguration<small>caBundle 持续抖动</small></div>
      <div class="result">PUT 82.4/s　·　409 60.1/s</div>
    </section>
    <section class="case good"><h2>修复后：1 个共享证书源</h2><div class="secret">Shared Secret<small>唯一 CA 与服务端证书</small></div>
      <div class="arrows">所有副本读取　↓</div><div class="pods">{after_pods}</div>
      <div class="object">WebhookConfiguration<small>caBundle 稳定</small></div><div class="result">PUT 0　·　409 0</div>
    </section>
  </div><footer>Webhook Server 可以多副本；证书与全局配置必须有唯一、可验证的 Owner。</footer>
</main>"""
    css = """
main{width:1200px;height:675px;padding:28px 34px;background:linear-gradient(145deg,#fffaf8,#f2f6fc)}header h1{margin:0;font-size:31px;color:#172033}header p{margin:8px 0 18px;color:#667085;font-size:15px}.columns{display:grid;grid-template-columns:1fr 1fr;gap:18px}.case{height:498px;border:1px solid #d7dfeb;border-radius:15px;background:#fff;padding:19px 20px;box-shadow:0 8px 24px rgba(40,55,85,.06)}.case h2{margin:0 0 15px;font-size:20px}.bad h2{color:#b42318}.good h2{color:#067647}.pods{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.pods i{height:59px;border:1px solid #ccd5e2;border-radius:9px;background:#f8fafc;font-style:normal;display:flex;flex-direction:column;align-items:center;justify-content:center;font-size:14px;color:#344054}.pods small,.object small,.secret small{display:block;margin-top:3px;font-size:11px;color:#667085}.bad .pods i{border-color:#f0b4ae;background:#fff7f6}.good .pods i{border-color:#a6dac2;background:#f4fbf7}.arrows{text-align:center;color:#667085;font-size:13px;margin:10px 0}.object,.secret{height:63px;border-radius:10px;display:flex;flex-direction:column;align-items:center;justify-content:center;font-size:17px;font-weight:650}.bad .object{border:1.5px solid #e9776e;background:#fff2f1;color:#b42318}.good .object,.secret{border:1.5px solid #55b88a;background:#edfbf4;color:#067647}.good .secret{margin-bottom:0}.good .pods i{height:48px}.good .object{margin-top:10px}.result{margin-top:12px;text-align:center;font-size:19px;font-weight:700}.bad .result{color:#b42318}.good .result{color:#067647}footer{height:50px;margin-top:12px;border:1px solid #bfd1fb;border-radius:11px;background:#eef4ff;color:#2454bc;display:flex;align-items:center;justify-content:center;font-size:17px;font-weight:600}
"""
    return page(1200, 675, body, css)


if __name__ == "__main__":
    render("cover", 900, 383, cover_wide())
    render("cover-square", 900, 900, cover_square())
    render("certificate-ownership", 1200, 675, architecture())
