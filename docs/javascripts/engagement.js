(function () {
  "use strict";

  var SITE_URL = "https://aik8s.run";
  var GISCUS_REPO = "runzhliu/aik8s";
  var GISCUS_REPO_ID = "R_kgDOTp14Dw";
  var GISCUS_CATEGORY = "General";
  var GISCUS_CATEGORY_ID = "DIC_kwDOTp14D84DCohY";
  var ICONS = {
    share: '<circle cx="18" cy="5" r="3"></circle><circle cx="6" cy="12" r="3"></circle><circle cx="18" cy="19" r="3"></circle><path d="m8.59 13.51 6.83 3.98M15.41 6.51 8.59 10.49"></path>',
    copy: '<rect width="13" height="13" x="9" y="9" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>',
    rss: '<path d="M4 11a9 9 0 0 1 9 9M4 4a16 16 0 0 1 16 16"></path><circle cx="5" cy="19" r="1"></circle>',
    comment: '<path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z"></path>',
    weibo: '<path data-brand d="M10.098 20.323c-3.977.391-7.414-1.406-7.672-4.02-.259-2.609 2.759-5.047 6.74-5.441 3.979-.394 7.413 1.404 7.671 4.018.259 2.6-2.759 5.049-6.737 5.439l-.002.004zM9.05 17.219c-.384.616-1.208.884-1.829.602-.612-.279-.793-.991-.406-1.593.379-.595 1.176-.861 1.793-.601.622.263.82.972.442 1.592zm1.27-1.627c-.141.237-.449.353-.689.253-.236-.09-.313-.361-.177-.586.138-.227.436-.346.672-.24.239.09.315.36.18.601l.014-.028zm.176-2.719c-1.893-.493-4.033.45-4.857 2.118-.836 1.704-.026 3.591 1.886 4.21 1.983.64 4.318-.341 5.132-2.179.8-1.793-.201-3.642-2.161-4.149zm7.563-1.224c-.346-.105-.57-.18-.405-.615.375-.977.42-1.804 0-2.404-.781-1.112-2.915-1.053-5.364-.03 0 0-.766.331-.571-.271.376-1.217.315-2.224-.27-2.809-1.338-1.337-4.869.045-7.888 3.08C1.309 10.87 0 13.273 0 15.348c0 3.981 5.099 6.395 10.086 6.395 6.536 0 10.888-3.801 10.888-6.82 0-1.822-1.547-2.854-2.915-3.284v.01zm1.908-5.092c-.766-.856-1.908-1.187-2.96-.962-.436.09-.706.511-.616.932.09.42.511.691.932.602.511-.105 1.067.044 1.442.465.376.421.466.977.316 1.473-.136.406.089.856.51.992.405.119.857-.105.992-.512.33-1.021.12-2.178-.646-3.035l.03.045zm2.418-2.195c-1.576-1.757-3.905-2.419-6.054-1.968-.496.104-.812.587-.706 1.081.104.496.586.813 1.082.707 1.532-.331 3.185.15 4.296 1.383 1.112 1.246 1.429 2.943.947 4.416-.165.48.106 1.007.586 1.157.479.165.991-.104 1.157-.586.675-2.088.241-4.478-1.338-6.235l.03.045z"></path>',
    x: '<path data-brand d="M14.234 10.162 22.977 0h-2.072l-7.591 8.824L7.251 0H.258l9.168 13.343L.258 24H2.33l8.016-9.318L16.749 24h6.993zm-2.837 3.299-.929-1.329L3.076 1.56h3.182l5.965 8.532.929 1.329 7.754 11.09h-3.182z"></path>',
    linkedin: '<path data-brand d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.447-2.136 2.941v5.665H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433c-1.144 0-2.063-.926-2.063-2.065 0-1.138.92-2.063 2.063-2.063 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-2.064 2.065zm1.782 13.019H3.555V9H7.12v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"></path>',
    telegram: '<path data-brand d="M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0a12 12 0 0 0-.056 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z"></path>',
    whatsapp: '<path data-brand d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 0 1-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 0 1-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 0 1 2.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0 0 12.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 0 0 5.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 0 0-3.48-8.413Z"></path>'
  };

  function element(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  }

  function articleTitle(article) {
    var heading = article.querySelector("h1");
    return heading ? heading.textContent.trim() : document.title;
  }

  function icon(name) {
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.classList.add("aik8s-share__icon");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    svg.innerHTML = ICONS[name];
    return svg;
  }

  function decorateControl(control, label, iconName) {
    control.appendChild(icon(iconName));
    control.appendChild(element("span", "aik8s-share__text", label));
    control.setAttribute("aria-label", label);
    control.title = label;
    return control;
  }

  function shareLink(label, href, iconName, platform) {
    var link = element("a", "aik8s-share__button aik8s-share__button--" + platform);
    link.href = href;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    return decorateControl(link, label, iconName);
  }

  function initializeShare(article) {
    if (article.querySelector(".aik8s-share")) return;

    var title = articleTitle(article);
    var url = window.location.href.split("#")[0];
    var encodedUrl = encodeURIComponent(url);
    var encodedTitle = encodeURIComponent(title + " | AI/LLM on Kubernetes");
    var bar = element("nav", "aik8s-share");
    bar.setAttribute("aria-label", "文章分享与订阅");
    bar.appendChild(element("span", "aik8s-share__label", "分享"));

    if (navigator.share) {
      var nativeButton = element("button", "aik8s-share__button aik8s-share__button--primary");
      nativeButton.type = "button";
      decorateControl(nativeButton, "系统分享", "share");
      nativeButton.addEventListener("click", function () {
        navigator.share({ title: title, text: title, url: url }).catch(function (error) {
          if (error && error.name !== "AbortError") copyUrl(copyButton, url);
        });
      });
      bar.appendChild(nativeButton);
    }

    var copyButton = element("button", "aik8s-share__button");
    copyButton.type = "button";
    decorateControl(copyButton, "复制链接", "copy");
    copyButton.addEventListener("click", function () { copyUrl(copyButton, url); });
    bar.appendChild(copyButton);
    bar.appendChild(shareLink("微博", "https://service.weibo.com/share/share.php?url=" + encodedUrl + "&title=" + encodedTitle, "weibo", "weibo"));
    bar.appendChild(shareLink("X", "https://twitter.com/intent/tweet?url=" + encodedUrl + "&text=" + encodedTitle, "x", "x"));
    bar.appendChild(shareLink("LinkedIn", "https://www.linkedin.com/sharing/share-offsite/?url=" + encodedUrl, "linkedin", "linkedin"));
    bar.appendChild(shareLink("Telegram", "https://t.me/share/url?url=" + encodedUrl + "&text=" + encodedTitle, "telegram", "telegram"));
    bar.appendChild(shareLink("WhatsApp", "https://api.whatsapp.com/send?text=" + encodedTitle + "%20" + encodedUrl, "whatsapp", "whatsapp"));
    bar.appendChild(shareLink("RSS", SITE_URL + "/rss.xml", "rss", "rss"));

    var commentsLink = element("a", "aik8s-share__button");
    commentsLink.href = "#comments";
    decorateControl(commentsLink, "评论", "comment");
    bar.appendChild(commentsLink);

    var heading = article.querySelector("h1");
    if (heading && heading.nextSibling) heading.parentNode.insertBefore(bar, heading.nextSibling);
    else article.insertBefore(bar, article.firstChild);
  }

  function copyUrl(button, url) {
    function done() {
      var textNode = button.querySelector(".aik8s-share__text");
      var original = textNode.textContent;
      textNode.textContent = "已复制，可粘贴到微信";
      window.setTimeout(function () { textNode.textContent = original; }, 2200);
    }

    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(url).then(done).catch(function () { fallbackCopy(url, done); });
    } else {
      fallbackCopy(url, done);
    }
  }

  function fallbackCopy(url, done) {
    var input = document.createElement("textarea");
    input.value = url;
    input.setAttribute("readonly", "");
    input.style.position = "fixed";
    input.style.opacity = "0";
    document.body.appendChild(input);
    input.select();
    document.execCommand("copy");
    document.body.removeChild(input);
    done();
  }

  function commentsEnabledForPath(pathname) {
    var excluded = ["/", "/ai-k8s/", "/cases/", "/k3s-upgrade/"];
    return excluded.indexOf(pathname) === -1;
  }

  function initializeComments(article) {
    if (!commentsEnabledForPath(window.location.pathname)) return;
    if (article.querySelector(".aik8s-comments")) return;

    var section = element("section", "aik8s-comments");
    section.id = "comments";
    section.appendChild(element("h2", "", "参与讨论"));
    var note = element("p", "aik8s-comments__note");
    note.appendChild(document.createTextNode("评论由 Giscus 和 GitHub Discussions 提供，需要使用 GitHub 登录；也可以直接前往 "));
    var discussionLink = element("a", "", "仓库 Discussions");
    discussionLink.href = "https://github.com/runzhliu/aik8s/discussions";
    discussionLink.target = "_blank";
    discussionLink.rel = "noopener noreferrer";
    note.appendChild(discussionLink);
    note.appendChild(document.createTextNode(" 参与讨论。"));
    section.appendChild(note);

    var mount = element("div", "giscus");
    section.appendChild(mount);
    article.appendChild(section);

    var script = document.createElement("script");
    script.src = "https://giscus.app/client.js";
    script.async = true;
    script.crossOrigin = "anonymous";
    script.setAttribute("data-repo", GISCUS_REPO);
    script.setAttribute("data-repo-id", GISCUS_REPO_ID);
    script.setAttribute("data-category", GISCUS_CATEGORY);
    script.setAttribute("data-category-id", GISCUS_CATEGORY_ID);
    script.setAttribute("data-mapping", "pathname");
    script.setAttribute("data-strict", "1");
    script.setAttribute("data-reactions-enabled", "1");
    script.setAttribute("data-emit-metadata", "0");
    script.setAttribute("data-input-position", "bottom");
    script.setAttribute("data-theme", giscusTheme());
    script.setAttribute("data-lang", "zh-CN");
    script.setAttribute("data-loading", "lazy");
    mount.appendChild(script);
  }

  function giscusTheme() {
    return document.body.getAttribute("data-md-color-scheme") === "slate" ? "dark" : "light";
  }

  function updateGiscusTheme() {
    var frame = document.querySelector("iframe.giscus-frame");
    if (!frame || !frame.contentWindow) return;
    frame.contentWindow.postMessage({ giscus: { setConfig: { theme: giscusTheme() } } }, "https://giscus.app");
  }

  function calculateModelMemory(root) {
    var params = Number(root.querySelector('[name="params"]').value);
    var bytes = Number(root.querySelector('[name="bytes"]').value);
    var gpus = Number(root.querySelector('[name="gpus"]').value);
    var memory = Number(root.querySelector('[name="memory"]').value);
    var reserve = Number(root.querySelector('[name="reserve"]').value) / 100;
    var kv = Number(root.querySelector('[name="kv"]').value);
    var weights = params * 1000000000 * bytes / Math.pow(1024, 3);
    var available = gpus * memory * (1 - reserve);
    var kvBudget = available - weights;
    var concurrency = kvBudget > 0 && kv > 0 ? Math.floor(kvBudget / kv) : 0;
    root.querySelector("output").textContent =
      "权重约 " + weights.toFixed(1) + " GiB；预留后总显存约 " + available.toFixed(1) +
      " GiB；KV Cache 预算约 " + kvBudget.toFixed(1) + " GiB；理论并发约 " + concurrency + "。";
  }

  function calculateTokenCost(root) {
    var hourly = Number(root.querySelector('[name="hourly"]').value);
    var gpus = Number(root.querySelector('[name="gpus"]').value);
    var tokens = Number(root.querySelector('[name="tokens"]').value);
    var utilization = Number(root.querySelector('[name="utilization"]').value) / 100;
    var effectiveTokens = tokens * utilization;
    var cost = effectiveTokens > 0 ? hourly * gpus / (effectiveTokens * 3600) * 1000000 : 0;
    root.querySelector("output").textContent =
      "有效输出约 " + effectiveTokens.toFixed(1) + " Token/s；仅 GPU 成本约 " + cost.toFixed(2) + " / 百万输出 Token。";
  }

  function initializeCalculators(article) {
    article.querySelectorAll(".aik8s-calculator").forEach(function (root) {
      if (root.getAttribute("data-initialized") === "true") return;
      var type = root.getAttribute("data-calculator");
      var calculate = type === "model-memory" ? calculateModelMemory : calculateTokenCost;
      root.querySelectorAll("input").forEach(function (input) {
        input.addEventListener("input", function () { calculate(root); });
      });
      root.setAttribute("data-initialized", "true");
      calculate(root);
    });
  }

  function initialize() {
    var article = document.querySelector("article.md-content__inner");
    if (!article) return;
    initializeShare(article);
    initializeCalculators(article);
    initializeComments(article);
  }

  if (typeof document$ !== "undefined" && document$.subscribe) {
    document$.subscribe(initialize);
  } else if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize);
  } else {
    initialize();
  }

  var themeObserver = new MutationObserver(updateGiscusTheme);
  themeObserver.observe(document.body, { attributes: true, attributeFilter: ["data-md-color-scheme"] });
})();
