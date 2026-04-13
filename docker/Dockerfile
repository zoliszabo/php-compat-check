FROM php:8.5-alpine

RUN apk add --no-cache \
    git \
    unzip \
    bash \
    curl \
    jq \
    libzip-dev

RUN docker-php-ext-install zip

COPY --from=composer:2 /usr/bin/composer /usr/bin/composer

RUN composer global config allow-plugins.dealerdirect/phpcodesniffer-composer-installer true \
 && composer global require \
    --no-interaction \
    --no-progress \
    --prefer-dist \
    squizlabs/php_codesniffer \
    dealerdirect/phpcodesniffer-composer-installer \
    composer/semver \
    phpcompatibility/php-compatibility:"^10.0.0@dev" \
    phpcompatibility/phpcompatibility-symfony:"*@dev" \
    phpcompatibility/phpcompatibility-paragonie:"*@dev" \
    phpcompatibility/phpcompatibility-passwordcompat:"*@dev"

ENV PATH="/root/.composer/vendor/bin:/root/.config/composer/vendor/bin:${PATH}"

WORKDIR /work

COPY bin/php-compat-check /usr/local/bin/php-compat-check
RUN chmod +x /usr/local/bin/php-compat-check
