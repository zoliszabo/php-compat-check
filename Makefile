.PHONY: install uninstall

INSTALL_DIR ?= /usr/local/bin
SCRIPT_SOURCE = bin/php-compat-check
SCRIPT_NAME = php-compat-check

install:
	@install -D -m 755 $(SCRIPT_SOURCE) $(INSTALL_DIR)/$(SCRIPT_NAME)
	@echo "✓ $(SCRIPT_NAME) installed to $(INSTALL_DIR)/$(SCRIPT_NAME)"

uninstall:
	@rm -f $(INSTALL_DIR)/$(SCRIPT_NAME)
	@echo "✓ $(SCRIPT_NAME) uninstalled from $(INSTALL_DIR)"
