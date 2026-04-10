FROM php:8.5-alpine

RUN apk add --no-cache \
    git \
    unzip \
    bash \
    libzip-dev

RUN docker-php-ext-install zip

COPY --from=composer:2 /usr/bin/composer /usr/bin/composer

RUN composer global config allow-plugins.dealerdirect/phpcodesniffer-composer-installer true \
 && composer global require \
    --no-interaction \
    --no-progress \
    --prefer-dist \
    squizlabs/php_codesniffer \
    phpcompatibility/php-compatibility

ENV PATH="/root/.composer/vendor/bin:/root/.config/composer/vendor/bin:${PATH}"

WORKDIR /work

COPY bin/php-compat-check /usr/local/bin/php-compat-check
RUN chmod +x /usr/local/bin/php-compat-check
