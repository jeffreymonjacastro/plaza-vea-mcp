"""Standalone crawler entrypoint used by the MCP refresh manager."""

from __future__ import annotations

import argparse

from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings

from plaza_vea_mcp.config import Settings
from plaza_vea_mcp.crawler.spiders.catalog import PlazaVeaCatalogSpider
from plaza_vea_mcp.db import CatalogRepository, create_database_engine


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--category-id")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = Settings.from_env()
    repository = CatalogRepository(create_database_engine(settings))
    repository.initialize()
    crawler_process = CrawlerProcess(get_project_settings())
    crawler = crawler_process.create_crawler(PlazaVeaCatalogSpider)
    crawler_process.crawl(crawler, run_id=args.run_id, category_id=args.category_id)
    try:
        crawler_process.start()
        if crawler.stats is None:
            raise RuntimeError("Scrapy no inicializo el colector de estadisticas")
        stats = crawler.stats.get_stats()
        processed = int(stats.get("item_scraped_count", 0))
        finish_reason = str(stats.get("finish_reason", "unknown"))
        error_count = int(stats.get("log_count/ERROR", 0))
        if finish_reason != "finished" or error_count:
            message = f"Scrapy termino con finish_reason={finish_reason} y {error_count} error(es)"
            repository.finish_run(
                args.run_id,
                status="failed",
                products_processed=processed,
                error=message,
            )
            return 1
        repository.finish_run(
            args.run_id,
            status="completed",
            products_processed=processed,
        )
        return 0
    except Exception as exc:
        processed = (
            0 if crawler.stats is None else int(crawler.stats.get_value("item_scraped_count", 0))
        )
        repository.finish_run(
            args.run_id,
            status="failed",
            products_processed=processed,
            error=str(exc),
        )
        raise
    finally:
        repository.close()


if __name__ == "__main__":
    raise SystemExit(main())
