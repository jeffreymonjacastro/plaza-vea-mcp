"""Polite crawler settings for Plaza Vea's public catalog API."""

BOT_NAME = "plaza_vea_mcp"

SPIDER_MODULES = ["plaza_vea_mcp.crawler.spiders"]
NEWSPIDER_MODULE = "plaza_vea_mcp.crawler.spiders"

ROBOTSTXT_OBEY = True
ROBOTSTXT_USER_AGENT = "plaza-vea-mcp"
USER_AGENT = "plaza-vea-mcp/0.1 (+https://github.com/jeffreymonjacastro/plaza-vea-mcp)"

CONCURRENT_REQUESTS = 4
CONCURRENT_REQUESTS_PER_DOMAIN = 2
DOWNLOAD_DELAY = 0.5
DOWNLOAD_TIMEOUT = 30

AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1.0
AUTOTHROTTLE_MAX_DELAY = 20.0
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0

RETRY_ENABLED = True
RETRY_TIMES = 3
RETRY_HTTP_CODES = [429, 500, 502, 503, 504, 522, 524]

HTTPCACHE_ENABLED = True
HTTPCACHE_EXPIRATION_SECS = 300
HTTPCACHE_DIR = "data/httpcache"
HTTPCACHE_IGNORE_HTTP_CODES = [429, 500, 502, 503, 504, 522, 524]

ITEM_PIPELINES = {"plaza_vea_mcp.crawler.pipelines.CatalogPipeline": 300}

LOG_LEVEL = "INFO"
TELNETCONSOLE_ENABLED = False
