/* Progressive enhancement: the generated timeline remains complete without JS. */
(function () {
  "use strict";

  if (window.__aik8sTimelineLoaded) return;
  window.__aik8sTimelineLoaded = true;

  var instances = new WeakMap();
  var languageLinks = new Map();
  var keys = ["sort", "tag", "type", "q"];

  function isEnglish() {
    return /^en(?:-|$)/i.test(document.documentElement.lang);
  }

  function knownValue(select, value, fallback) {
    return Array.prototype.some.call(select.options, function (option) {
      return option.value === value && !option.disabled;
    }) ? value : fallback;
  }

  function initialize() {
    var timeline = document.querySelector(".aik8s-timeline");
    // Instant navigation may retain the language menu: undo our previous decoration.
    languageLinks.forEach(function (href, link) {
      if (link.isConnected && href !== null) link.setAttribute("href", href);
      if (!link.isConnected || !timeline) languageLinks.delete(link);
    });
    if (!timeline) return;
    if (instances.has(timeline)) {
      instances.get(timeline).restore();
      return;
    }

    var scope = timeline.closest(".md-content__inner, article") || timeline.parentElement;
    var controls = scope.querySelector("form[data-timeline-controls]");
    var count = scope.querySelector("[data-timeline-count]");
    var empty = scope.querySelector("[data-timeline-empty]");
    if (!controls || !count || !empty) return;
    var sort = controls.querySelector('select[name="sort"]');
    var tag = controls.querySelector('select[name="tag"]');
    var type = controls.querySelector('select[name="type"]');
    var query = controls.querySelector('input[name="q"]');
    if (!sort || !tag || !type || !query) return;

    var english = isEnglish();
    var locale = english ? "en-US" : "zh-CN";
    var dateFormatter = new Intl.DateTimeFormat(locale, {
      timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit"
    });
    var monthFormatter = new Intl.DateTimeFormat(locale, {
      timeZone: "Asia/Shanghai", year: "numeric", month: "long"
    });
    var groupFormatter = new Intl.DateTimeFormat("en-US", {
      timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit"
    });

    // Retain every original node, including currently filtered-out articles.
    var items = Array.prototype.map.call(timeline.querySelectorAll("[data-timeline-item]"), function (node, index) {
      var published = Date.parse(node.dataset.published);
      var updated = Date.parse(node.dataset.updated);
      return {
        node: node,
        index: index,
        published: published,
        updated: Number.isFinite(updated) ? updated : published,
        tags: (node.dataset.tags || "").split(/\s+/).filter(Boolean),
        type: node.dataset.contentType || "",
        search: (node.dataset.search || "").toLocaleLowerCase(locale),
        date: node.querySelector("time[data-timeline-date]")
      };
    });
    // Malformed generated data must not destroy the readable static fallback.
    if (items.some(function (item) { return !Number.isFinite(item.published) || !item.date; })) return;

    function readState(params) {
      return {
        sort: params.get("sort") === "updated" ? "updated" : "published",
        tag: knownValue(tag, params.get("tag") || "", ""),
        type: knownValue(type, params.get("type") || "", ""),
        q: params.get("q") || ""
      };
    }

    function controlState() {
      return readState(new URLSearchParams({ sort: sort.value, tag: tag.value, type: type.value, q: query.value }));
    }

    function syncLanguageLinks() {
      // Only touch language links while a timeline is mounted; other pages are untouched.
      document.querySelectorAll(".md-select__link").forEach(function (link) {
        if (!languageLinks.has(link)) languageLinks.set(link, link.getAttribute("href"));
        var original = languageLinks.get(link);
        if (!original) return;
        var url;
        try { url = new URL(original, document.baseURI); } catch (_) { return; }
        if (url.origin !== window.location.origin) return;
        var current = new URLSearchParams(window.location.search);
        // Merge the source query (including unrelated fields) without dropping a target hash.
        Array.from(new Set(Array.from(current.keys()))).forEach(function (key) {
          url.searchParams.delete(key);
          current.getAll(key).forEach(function (value) { url.searchParams.append(key, value); });
        });
        // Remove stale timeline state from a generated language link as well.
        keys.forEach(function (key) { if (!current.has(key)) url.searchParams.delete(key); });
        link.href = url.href;
      });
    }

    function render(state) {
      sort.value = state.sort;
      tag.value = state.tag;
      type.value = state.type;
      query.value = state.q;
      var words = state.q.trim().toLocaleLowerCase(locale).split(/\s+/).filter(Boolean);
      var visible = items.filter(function (item) {
        return (!state.tag || item.tags.indexOf(state.tag) !== -1) &&
          (!state.type || item.type === state.type) &&
          words.every(function (word) { return item.search.indexOf(word) !== -1; });
      }).sort(function (a, b) {
        return b[state.sort] - a[state.sort] || a.index - b.index;
      });
      var fragment = document.createDocumentFragment();
      var previousMonth = null;
      var list;
      visible.forEach(function (item) {
        var date = new Date(item[state.sort]);
        var parts = groupFormatter.formatToParts(date);
        var monthKey = parts.find(function (part) { return part.type === "year"; }).value + "-" +
          parts.find(function (part) { return part.type === "month"; }).value;
        if (monthKey !== previousMonth) {
          var section = document.createElement("section");
          var heading = document.createElement("h2");
          heading.textContent = monthFormatter.format(date);
          heading.id = "month-" + monthKey;
          section.setAttribute("aria-labelledby", heading.id);
          list = document.createElement("ol");
          section.appendChild(heading);
          section.appendChild(list);
          fragment.appendChild(section);
          previousMonth = monthKey;
        }
        item.date.textContent = dateFormatter.format(date);
        item.date.dateTime = date.toISOString();
        list.appendChild(item.node);
      });
      timeline.replaceChildren(fragment);
      count.textContent = english ? visible.length + (visible.length === 1 ? " article" : " articles") : visible.length + " 篇";
      empty.textContent = english ? "No matching articles." : "没有匹配的文章。";
      empty.hidden = visible.length !== 0;
    }

    var searchStart = null;

    function update(mode) {
      var state = controlState();
      var url = new URL(window.location.href);
      keys.forEach(function (key) {
        if (state[key] && !(key === "sort" && state[key] === "published")) url.searchParams.set(key, state[key]);
        else url.searchParams.delete(key);
      });
      // Typing edits one draft entry. On commit, retain the pre-search filter for Back.
      if (mode === "push" && searchStart !== null) {
        window.history.replaceState(window.history.state, "", searchStart);
        searchStart = null;
      }
      if (url.href !== window.location.href) {
        window.history[mode === "push" ? "pushState" : "replaceState"](window.history.state, "", url.href);
      }
      render(state);
      syncLanguageLinks();
    }

    var instance = {
      restore: function () {
        searchStart = null;
        render(readState(new URLSearchParams(window.location.search)));
        syncLanguageLinks();
      }
    };
    instance.restore();
    controls.addEventListener("submit", function (event) { event.preventDefault(); update("push"); });
    controls.addEventListener("input", function (event) {
      if (event.target === query) {
        if (searchStart === null) searchStart = window.location.href;
        update("replace");
      }
    });
    controls.addEventListener("change", function (event) {
      if (event.target === sort || event.target === tag || event.target === type || event.target === query) update("push");
    });
    controls.addEventListener("reset", function (event) {
      event.preventDefault();
      sort.value = "published";
      tag.value = "";
      type.value = "";
      query.value = "";
      update("push");
    });
    instances.set(timeline, instance);
    controls.hidden = false;
  }

  window.addEventListener("popstate", initialize);
  if (typeof document$ !== "undefined" && typeof document$.subscribe === "function") {
    document$.subscribe(initialize);
  } else if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();
