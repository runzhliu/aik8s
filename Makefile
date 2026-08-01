ZENSICAL_IMAGE ?= zensical/zensical:0.0.51
ADSENSE_CLIENT ?= ca-pub-5607799704547851
DOCKER_RUN = docker run --rm --user "$$(id -u):$$(id -g)" -v "$(CURDIR):/docs"

.PHONY: dev build build-production

dev:
	$(DOCKER_RUN) -it -p 8000:8000 $(ZENSICAL_IMAGE)

build:
	$(DOCKER_RUN) $(ZENSICAL_IMAGE) build --clean --strict

build-production: build
	python3 scripts/inject_adsense.py --site-dir site --client "$(ADSENSE_CLIENT)"
