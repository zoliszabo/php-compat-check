.PHONY: install uninstall build run test test-integration release

INSTALL_DIR ?= /usr/local/bin
SCRIPT_SOURCE = bin/php-compat-check
SCRIPT_NAME = php-compat-check
VERSION_INSTALL_DIR = $(INSTALL_DIR)/../share/php-compat-check
DEV_IMAGE = php-compat-check:dev
RELEASE_REMOTE ?= origin

install:
	@install -D -m 644 VERSION "$(VERSION_INSTALL_DIR)/VERSION"
	@install -D -m 644 HELP "$(VERSION_INSTALL_DIR)/HELP"
	@install -D -m 755 $(SCRIPT_SOURCE) "$(INSTALL_DIR)/$(SCRIPT_NAME)"
	@case "$$(cat VERSION)" in *-dev) \
		for source_file in VERSION HELP docker/Dockerfile docker/report.php docker/bin/php-compat-check; do \
			install -D -m 644 "$$source_file" "$(VERSION_INSTALL_DIR)/source/$$source_file" || exit; \
		done ;; \
	esac
	@echo "✓ $(SCRIPT_NAME) installed to $(INSTALL_DIR)/$(SCRIPT_NAME)"

uninstall:
	@rm -f "$(INSTALL_DIR)/$(SCRIPT_NAME)" "$(VERSION_INSTALL_DIR)/VERSION" "$(VERSION_INSTALL_DIR)/HELP"
	@for source_file in VERSION HELP docker/Dockerfile docker/report.php docker/bin/php-compat-check; do \
		rm -f "$(VERSION_INSTALL_DIR)/source/$$source_file"; \
	done
	@echo "✓ $(SCRIPT_NAME) uninstalled from $(INSTALL_DIR)"

build:
	docker build -t $(DEV_IMAGE) -f docker/Dockerfile .

run: build
	PHP_COMPAT_CHECK_IMAGE=$(DEV_IMAGE) bash bin/php-compat-check $(ARGS)

test:
	python3 -m unittest discover -s tests -v

test-integration: build
	PHP_COMPAT_CHECK_IMAGE=$(DEV_IMAGE) python3 -m unittest discover -s tests/integration -v

release: export RELEASE_VERSION := $(RELEASE_VERSION)
release: export NEXT_VERSION := $(NEXT_VERSION)
release: export RELEASE_REMOTE := $(RELEASE_REMOTE)
release:
	@bash scripts/release.sh
