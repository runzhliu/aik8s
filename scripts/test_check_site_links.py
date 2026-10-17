"""Isolated fixtures and mocked HTTP; never contacts the public network."""
from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from urllib import error, request

import check_site_links as links


class SiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "site"
        self.root.mkdir()

    def put(self, name, content=""):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def check(self, site_url="https://aik8s.run/", dynamic=()):
        return links.SiteChecker(self.root, site_url, dynamic).check()

    def test_relative_root_absolute_unicode_download_and_queries(self):
        self.put("index.html", '''<a href="en/">English</a>
            <a href="/中文/?a=1&amp;b=2#%E6%A0%87%E9%A2%98">中文</a>
            <a href="https://aik8s.run/en/index.html#old">Legacy</a>
            <a href="/files/report%20one.pdf?download=1#page=2">Download</a>
            <a href="/%E4%B8%AD%E6%96%87/index.html#%E6%A0%87%E9%A2%98">Encoded</a>''')
        self.put("en/index.html", '<a name="old"></a><a href="../中文/#标题">cross directory</a>')
        self.put("中文/index.html", '<h2 id="标题">标题</h2><a href="../en/">English</a>')
        self.put("files/report one.pdf", "fixture")
        report = self.check()
        self.assertEqual(report.errors, {})
        self.assertEqual(report.pages, 3)
        self.assertEqual(report.internal, 7)

    def test_absolute_origin_without_path_resolves_to_root_from_nested_page(self):
        self.put("index.html", '<h2 id="home"></h2>')
        self.put("nested/index.html", '<a href="https://aik8s.run#home"></a><a href="//aik8s.run?x=1#home"></a>')
        self.assertEqual(self.check().errors, {})

    def test_all_resource_fields_srcsets_and_svg_fragments(self):
        self.put("index.html", '''<link rel="stylesheet" href="/a.css?v=1">
          <link rel="shortcut icon" href="icon.ico"><script src="a.js"></script>
          <img src="a.png" srcset="a.png 1x, b.png 2x">
          <picture><source src="a.png" srcset="a.png 100w,b.png 200w"></picture>
          <iframe src="/frame/"></iframe><iframe src="https://other.test/not-counted"></iframe>
          <img src="a.svg#not-an-html-anchor"><video src="a.mp4" poster="a.png"></video>
          <audio src="a.mp3"></audio><track src="a.vtt"><object data="file.pdf"></object>
          <embed src="file.pdf"><input type="image" src="a.png">
          <link rel="canonical" href="/not-a-resource">''')
        self.put("frame/index.html", "frame")
        for asset in ["a.css", "icon.ico", "a.js", "a.png", "b.png", "a.svg", "a.mp4", "a.mp3", "a.vtt", "file.pdf"]:
            self.put(asset, "fixture")
        report = self.check()
        self.assertEqual(report.errors, {})
        self.assertEqual(report.external, {})
        self.assertGreater(report.internal, 15)

    def test_external_prefilled_feedback_is_not_probed(self):
        self.put('index.html', '<a href="https://github.com/runzhliu/aik8s/issues/new?body=public-title" data-aik8s-feedback>Feedback</a><a href="https://example.org/docs">Docs</a>')
        report = self.check()
        self.assertEqual(set(report.external), {'https://example.org/docs'})
        self.assertEqual(report.errors, {})

    def test_empty_and_non_http_schemes_and_data_srcset(self):
        self.put("index.html", '''<a href=""></a><a href="#"></a>
          <a href="mailto:a@example.org"></a><a href="tel:123"></a>
          <a href="javascript:void(0)"></a><img src="data:image/png;base64,AAAA">
          <img srcset="data:image/png;base64,AAAA 1x, /ok.png 2x">''')
        self.put("ok.png")
        report = self.check()
        self.assertEqual(report.errors, {})
        self.assertEqual(report.ignored, 7)
        self.assertEqual(report.internal, 1)

    def test_data_srcset_candidate_with_no_descriptor(self):
        self.assertEqual(links.srcset_urls("data:image/png;base64,AAAA, /ok.png 2x"), ["data:image/png;base64,AAAA", "/ok.png"])

    def test_fragments_are_exact_and_dynamic_allowlist_is_narrow(self):
        self.put("index.html", '''<h2 id="a&amp;b"></h2><a name="legacy"></a>
          <a href="#a%26b"></a><a href="#legacy"></a><a href="#comments"></a>
          <a href="#custom-widget"></a><a href="#Comments"></a><a href="#missing"></a>''')
        report = self.check(dynamic=["custom-widget"])
        self.assertEqual(len(report.errors), 2)
        self.assertTrue(any("#missing" in message for message in report.errors))
        self.assertTrue(any("#Comments" in message for message in report.errors))

    def test_missing_files_anchors_dedup_and_source_locations(self):
        self.put("index.html", '<a href="gone.html">first</a>\n<a href="gone.html?q=1">second</a>\n<img src="missing.png">\n<a href="ok/#absent">anchor</a>')
        self.put("ok/index.html", '<h2 id="present"></h2>')
        report = self.check()
        self.assertEqual(len(report.errors), 3)
        missing = next(refs for text, refs in report.errors.items() if "gone.html" in text)
        self.assertEqual([ref.line for ref in missing], [1, 2])
        self.assertEqual(report.unique_internal, 3)
        output = io.StringIO()
        with redirect_stdout(output):
            links.print_report(report, self.root)
        self.assertIn("index.html:2:1", output.getvalue())
        self.assertIn("[resource]", output.getvalue())

    def test_404_page_is_not_itself_an_error(self):
        self.put("404.html", '<a href="/">Home</a>')
        self.put("index.html", "home")
        self.assertEqual(self.check().errors, {})

    def test_directory_index_and_explicit_index(self):
        self.put("index.html", '<a href="/guide/">one</a><a href="guide/index.html">two</a><a href="guide">three</a>')
        self.put("guide/index.html", '<a href="./index.html">self</a>')
        report = self.check()
        self.assertEqual(report.errors, {})
        self.assertEqual(report.unique_internal, 1)

    def test_site_url_prefix_rejects_other_same_origin_paths(self):
        self.put("index.html", '<a href="/blog/en/">ok</a><a href="/outside/">no</a>')
        self.put("en/index.html", '<a href="../">ok</a><a href="https://aik8s.run/blog/">ok</a>')
        report = self.check("https://aik8s.run/blog/")
        self.assertEqual(len(report.errors), 1)
        self.assertTrue(any("outside site URL root" in x for x in report.errors))

    def test_traversals_invalid_paths_and_symlink_are_rejected_without_read(self):
        outside = Path(self.temp.name) / "secret.html"
        outside.write_text('<a href="https://must-not-collect.test/">private</a>', encoding="utf-8")
        (self.root / "leak.html").symlink_to(outside)
        self.put("index.html", '''<a href="../secret.html">no</a>
          <a href="%2e%2e/secret.html">no</a><a href="/%2e%2e/secret.html">no</a>
          <a href="/dir/../../secret.html">no</a><a href="/leak.html">no</a>
          <a href="bad%00.html">no</a><a href="bad%ZZ.html">no</a>
          <a href="bad%5cname.html">no</a><a href="http://[bad">no</a>''')
        with patch.object(Path, "read_text", autospec=True, side_effect=Path.read_text) as read:
            report = self.check()
        self.assertGreaterEqual(len(report.errors), 9)
        self.assertEqual(report.external, {})
        self.assertNotIn(outside.resolve(), [call.args[0] for call in read.call_args_list])

    def test_offline_does_not_touch_network_and_counts_unique_external(self):
        self.put("index.html", '''<a href="https://other.test/a#one"></a>
          <a href="https://other.test/a#two"></a><img src="//cdn.test/a.png">
          <iframe src="https://frame.test/"></iframe>''')
        with patch.object(request, "build_opener", side_effect=AssertionError("network forbidden")), patch.object(request, "urlopen", side_effect=AssertionError("network forbidden")):
            report = self.check()
            output = io.StringIO()
            with redirect_stdout(output):
                status = links.main(["--site-dir", str(self.root)])
        self.assertEqual(status, 0)
        self.assertEqual(len(report.external), 2)
        self.assertEqual(len(report.external["https://other.test/a"]), 2)
        self.assertIn("external URLs: 2", output.getvalue())

    def test_external_warning_reports_source_locations(self):
        self.put("index.html", '<a href="https://host.test/a">link</a>')
        report = self.check()
        report.warnings = ["https://host.test/a: HTTP 403; needs review"]
        output = io.StringIO()
        with redirect_stdout(output):
            links.print_report(report, self.root)
        self.assertIn("index.html:1:1 [navigation]", output.getvalue())

    def test_cli_failure_and_no_site_mutation(self):
        path = self.put("index.html", '<a href="missing/">broken</a>')
        before = path.read_bytes()
        with redirect_stdout(io.StringIO()):
            self.assertEqual(links.main(["--site-dir", str(self.root)]), 1)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["index.html"])

    def test_external_warnings_never_fail_ci_and_limit_zero_means_all(self):
        self.put("index.html", '<a href="https://one.test/"></a><a href="https://two.test/"></a>')
        for limit, expected in [("1", 1), ("0", 2)]:
            with self.subTest(limit=limit), patch.object(links.ExternalChecker, "check", return_value=["HTTP 429; needs review"]) as check:
                output = io.StringIO()
                with redirect_stdout(output):
                    status = links.main(["--site-dir", str(self.root), "--external", "--external-limit", limit])
                self.assertEqual(status, 0)
                self.assertEqual(len(check.call_args.args[0]), expected)
                self.assertIn("WARNING:", output.getvalue())


class ExternalTests(unittest.TestCase):
    def response(self, status=200):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = status
        return response

    def test_head_success_no_response_body_read_and_bounded_timeout(self):
        opener = MagicMock()
        response = self.response()
        opener.open.return_value = response
        checker = links.ExternalChecker(timeout=2, opener=opener)
        self.assertIsNone(checker.check_one("https://host.test/a"))
        req = opener.open.call_args.args[0]
        self.assertEqual(req.get_method(), "HEAD")
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 2)
        response.read.assert_not_called()

    def test_head_405_and_501_fall_back_to_get_without_body_read(self):
        for status in (405, 501):
            with self.subTest(status=status):
                opener = MagicMock()
                response = self.response()
                opener.open.side_effect = [error.HTTPError("https://host.test/", status, "unsupported", {}, None), response]
                checker = links.ExternalChecker(interval=0, opener=opener)
                self.assertIsNone(checker.check_one("https://host.test/"))
                self.assertEqual([call.args[0].get_method() for call in opener.open.call_args_list], ["HEAD", "GET"])
                response.read.assert_not_called()

    def test_http_access_limits_not_reported_as_definite_broken_links(self):
        for status in (403, 429, 404, 500):
            with self.subTest(status=status):
                opener = MagicMock()
                opener.open.side_effect = error.HTTPError("https://host.test/", status, "error", {}, None)
                warning = links.ExternalChecker(opener=opener).check_one("https://host.test/")
                self.assertIn(str(status), warning)
                self.assertIn("needs review", warning)
                if status in (403, 429):
                    self.assertIn("not proof of a broken link", warning)

    def test_network_timeouts_warn(self):
        opener = MagicMock()
        opener.open.side_effect = TimeoutError("timeout")
        checker = links.ExternalChecker(opener=opener)
        self.assertIn("request failed", checker.check_one("https://host.test/"))

    def test_per_host_rate_limit_and_independent_hosts(self):
        checker = links.ExternalChecker(interval=0.5)
        with patch.object(links.time, "monotonic", return_value=100), patch.object(links.time, "sleep") as sleep:
            checker.pace("https://one.test/a")
            checker.pace("https://one.test/b")
            checker.pace("https://two.test/c")
            checker.pace("https://one.test/c")
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [0.5, 1.0])

    def test_redirect_non_http_is_rejected(self):
        redirect = links.HTTPOnlyRedirect()
        with self.assertRaises(error.URLError):
            redirect.redirect_request(request.Request("https://host.test/"), None, 302, "", {}, "file:///etc/passwd")

    def test_external_probes_reject_local_private_and_credential_urls(self):
        for url in ('http://localhost/test', 'http://service.namespace.svc/test', 'https://user:pass@example.org/'):
            with self.subTest(url=url), patch.object(links.socket, 'getaddrinfo') as lookup:
                with self.assertRaises(ValueError):
                    links.require_public_url(url)
                lookup.assert_not_called()
        for address in ('127.0.0.1', '10.0.0.1', '169.254.169.254', '::1'):
            with self.subTest(address=address), patch.object(links.socket, 'getaddrinfo', return_value=[(0, 0, 0, '', (address, 80))]):
                with self.assertRaises(ValueError):
                    links.require_public_url('http://example.org/test')
        with patch.object(links.socket, 'getaddrinfo', return_value=[(0, 0, 0, '', ('93.184.216.34', 443))]):
            links.require_public_url('https://example.org/test')

    def test_cli_bounds(self):
        for flag, value in [("--external-limit", "-1"), ("--external-workers", "17"), ("--external-timeout", "31"), ("--external-host-interval", "0")]:
            with self.subTest(flag=flag), redirect_stdout(io.StringIO()), patch("sys.stderr", new_callable=io.StringIO):
                with self.assertRaises(SystemExit):
                    links.main([flag, value])


if __name__ == "__main__":
    unittest.main()
