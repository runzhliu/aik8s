ZENSICAL_IMAGE ?= zensical/zensical:0.0.51
ADSENSE_CLIENT ?= ca-pub-5607799704547851
CLOUDFLARE_WEB_ANALYTICS_TOKEN ?= 74fa5819a51b45448c0062e7de37cee0
DOCKER_RUN = docker run --rm --user "$$(id -u):$$(id -g)" -v "$(CURDIR):/docs"

.PHONY: dev build build-production distribution

dev:
	$(DOCKER_RUN) -it -p 8000:8000 $(ZENSICAL_IMAGE)

build:
	$(DOCKER_RUN) $(ZENSICAL_IMAGE) build --clean --strict

build-production: build
	python3 scripts/build_distribution.py --docs-dir docs --site-dir site --site-url "https://aik8s.run/"
	python3 scripts/inject_adsense.py --site-dir site --client "$(ADSENSE_CLIENT)"
	python3 scripts/inject_cloudflare_analytics.py --site-dir site --token "$(CLOUDFLARE_WEB_ANALYTICS_TOKEN)"

distribution:
	python3 scripts/build_distribution.py --docs-dir docs --site-dir site --site-url "https://aik8s.run/"
