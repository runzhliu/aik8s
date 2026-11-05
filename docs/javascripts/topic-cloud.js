/* Enhance only pages containing the home-page cloud, including instant navigation. */
(function () {
  "use strict";
  if (window.__aik8sTopicCloudLoaded) return;
  window.__aik8sTopicCloudLoaded = true;
  var initialized = new WeakSet();

  // Use actual button boxes, rather than estimated glyph sizes, so mixed scripts,
  // wrapped long terms and locally installed fonts all participate in collision checks.
  function arrange(words, topics) {
    var buttons = Array.prototype.slice.call(words.querySelectorAll(".topic-cloud__word"));
    var margin = 5; // Keep room for the focus outline without opening up the cloud.
    var width = words.clientWidth;
    function fallback() {
      words.classList.remove("topic-cloud__words--packed");
      words.style.height = "";
      buttons.forEach(function (button) { button.style.left = ""; button.style.top = ""; });
    }
    if (!width || width <= margin * 2 || !buttons.length) { fallback(); return; }
    try {
      words.classList.add("topic-cloud__words--packed");
      var boxes = buttons.map(function (button, index) {
        var rect = button.getBoundingClientRect();
        if (!rect.width || !rect.height || rect.width > width - margin * 2 + 0.5) throw new Error("Cannot measure topic");
        return { button: button, index: index, width: rect.width, height: rect.height, count: topics[index].count };
      }).sort(function (a, b) { return b.count - a.count || a.index - b.index; });
      var placed = [];
      var minY = Infinity;
      var maxY = -Infinity;
      boxes.forEach(function (box, index) {
        var found = false;
        // Alternating the spiral direction avoids a row-like, mechanically aligned cloud.
        var direction = index % 2 ? -1 : 1;
        var phase = index * 2.399963229728653;
        for (var step = 0; step < 6500; step++) {
          var angle = step * 0.35;
          var radius = 2.7 * angle;
          var x = (width - box.width) / 2 + Math.cos(phase + direction * angle) * radius;
          var y = Math.sin(phase + direction * angle) * radius * 0.52 - box.height / 2;
          if (x < margin || x + box.width > width - margin) continue;
          var collides = placed.some(function (other) {
            return x < other.x + other.width + margin && x + box.width + margin > other.x &&
              y < other.y + other.height + margin && y + box.height + margin > other.y;
          });
          if (collides) continue;
          box.x = x;
          box.y = y;
          placed.push(box);
          minY = Math.min(minY, y);
          maxY = Math.max(maxY, y + box.height);
          found = true;
          break;
        }
        // A nearly full-width word may never fit a sampled spiral point. Place it
        // immediately below the cloud instead of dropping the whole layout.
        if (!found) {
          box.x = (width - box.width) / 2;
          box.y = maxY + margin;
          if (!isFinite(box.y)) throw new Error("Cannot place topic");
          placed.push(box);
          maxY = box.y + box.height;
        }
      });
      placed.forEach(function (box) {
        box.button.style.left = box.x.toFixed(2) + "px";
        box.button.style.top = (box.y - minY + margin).toFixed(2) + "px";
      });
      words.style.height = Math.ceil(maxY - minY + margin * 2) + "px";
    } catch (error) {
      // The normal flow remains usable if measurement or placement is unavailable.
      fallback();
    }
  }

  function watchLayout(words, topics) {
    var lastWidth = -1;
    var frame = null;
    function update(force) {
      if (!words.isConnected) return;
      var width = words.clientWidth;
      if (!force && width === lastWidth) return;
      lastWidth = width;
      arrange(words, topics);
    }
    function schedule() {
      if (!words.isConnected) { window.removeEventListener("resize", schedule); return; }
      if (frame !== null) return;
      var request = window.requestAnimationFrame || function (callback) { return window.setTimeout(callback, 16); };
      frame = request(function () { frame = null; update(false); });
    }
    update(true);
    if (typeof ResizeObserver !== "undefined") {
      try {
        var observer = new ResizeObserver(function () {
          if (!words.isConnected) { observer.disconnect(); return; }
          schedule();
        });
        observer.observe(words);
      } catch (error) {
        window.addEventListener("resize", schedule);
      }
    } else {
      window.addEventListener("resize", schedule);
    }
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(function () { update(true); });
    }
  }

  function initialize() {
    var cloud = document.querySelector("[data-topic-cloud]");
    if (!cloud || initialized.has(cloud)) return;
    var words = cloud.querySelector("[data-topic-words]");
    var status = cloud.querySelector("[data-topic-status]");
    var detail = cloud.querySelector("[data-topic-detail]");
    if (!words || !status || !detail) return;
    initialized.add(cloud);
    var english = /^en(?:-|$)/i.test(document.documentElement.lang);
    var formatter = new Intl.NumberFormat(english ? "en" : "zh-CN");
    status.textContent = english ? "Loading topics…" : "正在加载主题词…";

    fetch(new URL("assets/topic-cloud-" + (english ? "en" : "zh") + ".json", document.baseURI).href, { cache: "no-cache" })
      .then(function (response) {
        if (!response.ok) throw new Error("Topic data unavailable");
        return response.json();
      })
      .then(function (data) {
        if (!data || !Number.isSafeInteger(data.article_count) || data.article_count < 0 ||
            !Array.isArray(data.topics) || !data.topics.length ||
            data.topics.some(function (item) {
              return !item || typeof item.term !== "string" || !item.term.trim() ||
                !Number.isSafeInteger(item.count) || item.count < 0 ||
                !Number.isSafeInteger(item.article_count) || item.article_count < 0;
            })) throw new Error("Invalid topic data");
        var counts = data.topics.map(function (item) { return item.count; });
        var min = Math.min.apply(null, counts);
        var max = Math.max.apply(null, counts);
        var fragment = document.createDocumentFragment();
        data.topics.forEach(function (item, index) {
          var button = document.createElement("button");
          // The preview's logarithmic scale gives the middle ranks a voice while
          // preserving frequency order, including for zero and equal counts.
          var weight = max === min ? 0.5 : (Math.log1p(item.count) - Math.log1p(min)) / (Math.log1p(max) - Math.log1p(min));
          button.type = "button";
          button.className = "topic-cloud__word";
          button.style.setProperty("--topic-size", (0.70 + weight * 1.30).toFixed(3) + "rem");
          button.style.setProperty("--topic-weight", weight > 0.65 ? "700" : weight > 0.3 ? "600" : "500");
          button.style.setProperty("--topic-delay", Math.min(index * 9, 250) + "ms");
          button.textContent = item.term;
          button.setAttribute("aria-pressed", "false");
          button.addEventListener("click", function () {
            words.querySelectorAll('[aria-pressed="true"]').forEach(function (selected) {
              selected.setAttribute("aria-pressed", "false");
            });
            button.setAttribute("aria-pressed", "true");
            detail.textContent = english
              ? item.term + ": " + formatter.format(item.count) + " mentions in " + formatter.format(item.article_count) + " articles."
              : item.term + "：出现 " + formatter.format(item.count) + " 次，涉及 " + formatter.format(item.article_count) + " 篇文章。";
          });
          fragment.appendChild(button);
        });
        words.replaceChildren(fragment);
        watchLayout(words, data.topics);
        status.textContent = english
          ? formatter.format(data.topics.length) + " topics across " + formatter.format(data.article_count) + " articles."
          : formatter.format(data.article_count) + " 篇文章 · " + formatter.format(data.topics.length) + " 个主题词";
      })
      .catch(function () {
        status.textContent = english
          ? "The topic cloud could not be loaded. Please try refreshing; the technical map below remains available."
          : "词云加载失败，请刷新重试；仍可通过下方技术地图浏览文档。";
      });
  }

  if (typeof document$ !== "undefined" && typeof document$.subscribe === "function") {
    document$.subscribe(initialize);
  } else if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();
