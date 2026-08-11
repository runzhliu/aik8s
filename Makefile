ZENSICAL_IMAGE ?= zensical/zensical:0.0.51
ADSENSE_CLIENT ?= ca-pub-5607799704547851
CLOUDFLARE_WEB_ANALYTICS_TOKEN ?= 74fa5819a51b45448c0062e7de37cee0
WECHAT_EDITOR_PORT ?= 8899
WECHAT_ARTICLE ?= articles/wechat/deepseek-v4-flash-h20.md
WECHAT_COVER ?= articles/wechat/assets/deepseek-v4-flash-h20-cover.png
WECHAT_PREVIEW ?= .wechat-output/$(basename $(notdir $(WECHAT_ARTICLE))).html
WECHAT_SOURCE_URL ?=
WECHAT_PYTHON = .venv/wechat/bin/python
WECHAT_INSTALLED = .venv/wechat/.installed
DOCKER_RUN = docker run --rm --user "$$(id -u):$$(id -g)" -v "$(CURDIR):/docs"

.PHONY: dev build build-production distribution wechat-editor wechat-cover wechat-preview wechat-draft

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

wechat-editor:
	npx --yes @doocs/md-cli@2.1.3 port=$(WECHAT_EDITOR_PORT)

$(WECHAT_INSTALLED): requirements-wechat.txt
	python3 -m venv .venv/wechat
	$(WECHAT_PYTHON) -m pip install --upgrade pip
	$(WECHAT_PYTHON) -m pip install -r requirements-wechat.txt
	touch $(WECHAT_INSTALLED)

wechat-preview: $(WECHAT_INSTALLED)
	$(WECHAT_PYTHON) scripts/publish_wechat.py render $(WECHAT_ARTICLE) \
		--output $(WECHAT_PREVIEW)

wechat-cover: $(WECHAT_INSTALLED)
	$(WECHAT_PYTHON) scripts/generate_wechat_cover.py --output $(WECHAT_COVER)

wechat-draft: $(WECHAT_INSTALLED)
	$(WECHAT_PYTHON) scripts/publish_wechat.py draft $(WECHAT_ARTICLE) \
		--env-file .deploy-secrets/wechat.env \
		$(if $(WECHAT_COVER),--cover $(WECHAT_COVER),) \
		$(if $(WECHAT_SOURCE_URL),--source-url "$(WECHAT_SOURCE_URL)",)
