(function () {
  "use strict";

  var SITE_URL = "https://aik8s.run";
  var GISCUS_REPO = "runzhliu/aik8s";
  var GISCUS_REPO_ID = "R_kgDOTp14Dw";
  var GISCUS_CATEGORY = "General";
  var GISCUS_CATEGORY_ID = "DIC_kwDOTp14D84DCohY";

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

  function shareLink(label, href) {
    var link = element("a", "aik8s-share__button", label);
    link.href = href;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    return link;
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
      var nativeButton = element("button", "aik8s-share__button aik8s-share__button--primary", "系统分享");
      nativeButton.type = "button";
      nativeButton.addEventListener("click", function () {
        navigator.share({ title: title, text: title, url: url }).catch(function (error) {
          if (error && error.name !== "AbortError") copyUrl(copyButton, url);
        });
      });
      bar.appendChild(nativeButton);
    }

    var copyButton = element("button", "aik8s-share__button", "复制链接");
    copyButton.type = "button";
    copyButton.addEventListener("click", function () { copyUrl(copyButton, url); });
    bar.appendChild(copyButton);
    bar.appendChild(shareLink("微博", "https://service.weibo.com/share/share.php?url=" + encodedUrl + "&title=" + encodedTitle));
    bar.appendChild(shareLink("X", "https://twitter.com/intent/tweet?url=" + encodedUrl + "&text=" + encodedTitle));
    bar.appendChild(shareLink("LinkedIn", "https://www.linkedin.com/sharing/share-offsite/?url=" + encodedUrl));
    bar.appendChild(shareLink("Telegram", "https://t.me/share/url?url=" + encodedUrl + "&text=" + encodedTitle));
    bar.appendChild(shareLink("WhatsApp", "https://api.whatsapp.com/send?text=" + encodedTitle + "%20" + encodedUrl));
    bar.appendChild(shareLink("RSS", SITE_URL + "/rss.xml"));

    var commentsLink = element("a", "aik8s-share__button", "评论");
    commentsLink.href = "#comments";
    bar.appendChild(commentsLink);

    var heading = article.querySelector("h1");
    if (heading && heading.nextSibling) heading.parentNode.insertBefore(bar, heading.nextSibling);
    else article.insertBefore(bar, article.firstChild);
  }

  function copyUrl(button, url) {
    function done() {
      var original = button.textContent;
      button.textContent = "已复制，可粘贴到微信";
      window.setTimeout(function () { button.textContent = original; }, 2200);
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

