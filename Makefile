.PHONY: install uninstall build run test test-integration

INSTALL_DIR ?= /usr/local/bin
SCRIPT_SOURCE = bin/php-compat-check
SCRIPT_NAME = php-compat-check
VERSION_INSTALL_DIR = $(INSTALL_DIR)/../share/php-compat-check
DEV_IMAGE = php-compat-check:dev

install:
	@install -D -m 644 VERSION "$(VERSION_INSTALL_DIR)/VERSION"
	@install -D -m 755 $(SCRIPT_SOURCE) "$(INSTALL_DIR)/$(SCRIPT_NAME)"
	@echo "✓ $(SCRIPT_NAME) installed to $(INSTALL_DIR)/$(SCRIPT_NAME)"

uninstall:
	@rm -f "$(INSTALL_DIR)/$(SCRIPT_NAME)" "$(VERSION_INSTALL_DIR)/VERSION"
	@echo "✓ $(SCRIPT_NAME) uninstalled from $(INSTALL_DIR)"

build:
	docker build -t $(DEV_IMAGE) -f docker/Dockerfile .

run: build
	PHP_COMPAT_CHECK_IMAGE=$(DEV_IMAGE) bash bin/php-compat-check $(ARGS)

test:
	python3 -m unittest discover -s tests -v

test-integration: build
	PHP_COMPAT_CHECK_IMAGE=$(DEV_IMAGE) python3 -m unittest discover -s tests/integration -v
