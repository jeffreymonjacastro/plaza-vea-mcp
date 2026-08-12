"""SQLite persistence for the catalog cache and crawl history."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    distinct,
    func,
    select,
    update,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from plaza_vea_mcp.config import Settings
from plaza_vea_mcp.schemas import (
    BrandSummary,
    CatalogOffer,
    CatalogRefreshStatus,
    ProductDetails,
    ProductSummary,
)
from plaza_vea_mcp.utils import normalize_text, utc_now


class Base(DeclarativeBase):
    pass


class ProductRecord(Base):
    __tablename__ = "products"

    product_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    normalized_name: Mapped[str] = mapped_column(Text, index=True)
    brand: Mapped[str] = mapped_column(String(200), index=True)
    normalized_brand: Mapped[str] = mapped_column(String(200), index=True)
    categories_json: Mapped[str] = mapped_column(Text, default="[]")
    product_url: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OfferRecord(Base):
    __tablename__ = "offers"

    sku_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    seller_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    product_id: Mapped[str] = mapped_column(
        ForeignKey("products.product_id", ondelete="CASCADE"), index=True
    )
    sku_name: Mapped[str] = mapped_column(Text)
    seller_name: Mapped[str] = mapped_column(Text)
    price_cents: Mapped[int] = mapped_column(Integer)
    list_price_cents: Mapped[int] = mapped_column(Integer)
    is_available: Mapped[bool] = mapped_column(Boolean, index=True)
    available_quantity: Mapped[int] = mapped_column(Integer)
    image_urls_json: Mapped[str] = mapped_column(Text, default="[]")
    add_to_cart_url: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class PriceObservationRecord(Base):
    __tablename__ = "price_observations"

    observation_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sku_id: Mapped[str] = mapped_column(String(64), index=True)
    seller_id: Mapped[str] = mapped_column(String(64), index=True)
    price_cents: Mapped[int] = mapped_column(Integer)
    list_price_cents: Mapped[int] = mapped_column(Integer)
    is_available: Mapped[bool] = mapped_column(Boolean)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    run_id: Mapped[str | None] = mapped_column(String(64), index=True)


class CrawlRunRecord(Base):
    __tablename__ = "crawl_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    category_id: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    products_processed: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    pid: Mapped[int | None] = mapped_column(Integer)


def create_database_engine(settings: Settings) -> Engine:
    settings.ensure_directories()
    return create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )


class CatalogRepository:
    """Synchronous repository; SQLite operations are deliberately short-lived."""

    def __init__(self, engine: Engine):
        self.engine = engine
        self.session_factory = sessionmaker(engine, expire_on_commit=False)

    def initialize(self) -> None:
        Base.metadata.create_all(self.engine)

    def close(self) -> None:
        self.engine.dispose()

    def upsert_offers(
        self,
        offers: Iterable[CatalogOffer],
        *,
        run_id: str | None = None,
        record_observations: bool = True,
    ) -> int:
        saved = 0
        with self.session_factory.begin() as session:
            for offer in offers:
                self._upsert_offer(session, offer)
                if record_observations:
                    session.add(
                        PriceObservationRecord(
                            sku_id=offer.sku_id,
                            seller_id=offer.seller_id,
                            price_cents=offer.price_cents,
                            list_price_cents=offer.list_price_cents,
                            is_available=offer.is_available,
                            observed_at=offer.fetched_at,
                            run_id=run_id,
                        )
                    )
                saved += 1
        return saved

    @staticmethod
    def _upsert_offer(session: Session, offer: CatalogOffer) -> None:
        product_insert = sqlite_insert(ProductRecord).values(
            product_id=offer.product_id,
            name=offer.product_name,
            normalized_name=normalize_text(offer.product_name),
            brand=offer.brand,
            normalized_brand=normalize_text(offer.brand),
            categories_json=json.dumps(offer.categories, ensure_ascii=False),
            product_url=offer.product_url,
            updated_at=offer.fetched_at,
        )
        session.execute(
            product_insert.on_conflict_do_update(
                index_elements=[ProductRecord.product_id],
                set_={
                    "name": product_insert.excluded.name,
                    "normalized_name": product_insert.excluded.normalized_name,
                    "brand": product_insert.excluded.brand,
                    "normalized_brand": product_insert.excluded.normalized_brand,
                    "categories_json": product_insert.excluded.categories_json,
                    "product_url": product_insert.excluded.product_url,
                    "updated_at": product_insert.excluded.updated_at,
                },
            )
        )
        offer_insert = sqlite_insert(OfferRecord).values(
            sku_id=offer.sku_id,
            seller_id=offer.seller_id,
            product_id=offer.product_id,
            sku_name=offer.sku_name,
            seller_name=offer.seller_name,
            price_cents=offer.price_cents,
            list_price_cents=offer.list_price_cents,
            is_available=offer.is_available,
            available_quantity=offer.available_quantity,
            image_urls_json=json.dumps(offer.image_urls),
            add_to_cart_url=offer.add_to_cart_url,
            fetched_at=offer.fetched_at,
        )
        session.execute(
            offer_insert.on_conflict_do_update(
                index_elements=[OfferRecord.sku_id, OfferRecord.seller_id],
                set_={
                    "product_id": offer_insert.excluded.product_id,
                    "sku_name": offer_insert.excluded.sku_name,
                    "seller_name": offer_insert.excluded.seller_name,
                    "price_cents": offer_insert.excluded.price_cents,
                    "list_price_cents": offer_insert.excluded.list_price_cents,
                    "is_available": offer_insert.excluded.is_available,
                    "available_quantity": offer_insert.excluded.available_quantity,
                    "image_urls_json": offer_insert.excluded.image_urls_json,
                    "add_to_cart_url": offer_insert.excluded.add_to_cart_url,
                    "fetched_at": offer_insert.excluded.fetched_at,
                },
            )
        )

    def search_products(
        self,
        *,
        name: str | None,
        brand: str | None,
        sort: str,
        only_available: bool,
        limit: int,
    ) -> list[ProductSummary]:
        statement = select(ProductRecord, OfferRecord).join(
            OfferRecord, OfferRecord.product_id == ProductRecord.product_id
        )
        if name:
            statement = statement.where(
                ProductRecord.normalized_name.contains(normalize_text(name))
            )
        if brand:
            statement = statement.where(ProductRecord.normalized_brand == normalize_text(brand))
        if only_available:
            statement = statement.where(OfferRecord.is_available.is_(True))
        with self.session_factory() as session:
            rows = session.execute(statement).all()

        best_by_product: dict[str, CatalogOffer] = {}
        for product, offer in rows:
            candidate = self._to_offer(product, offer)
            current = best_by_product.get(candidate.product_id)
            if current is None or self._offer_rank(candidate) < self._offer_rank(current):
                best_by_product[candidate.product_id] = candidate
        products = [ProductSummary.from_offer(offer) for offer in best_by_product.values()]
        self._sort_products(products, sort)
        return products[:limit]

    def get_product(self, product_id: str) -> ProductDetails | None:
        statement = (
            select(ProductRecord, OfferRecord)
            .join(OfferRecord, OfferRecord.product_id == ProductRecord.product_id)
            .where(ProductRecord.product_id == product_id)
        )
        with self.session_factory() as session:
            rows = session.execute(statement).all()
        if not rows:
            return None
        offers = [self._to_offer(product, offer) for product, offer in rows]
        product = rows[0][0]
        return ProductDetails(
            product_id=product.product_id,
            product_name=product.name,
            brand=product.brand,
            categories=json.loads(product.categories_json),
            product_url=product.product_url,
            offers=offers,
            source="cache",
            stale=True,
            fetched_at=max(offer.fetched_at for offer in offers),
        )

    def get_sku_offers(self, sku_id: str) -> list[CatalogOffer]:
        statement = (
            select(ProductRecord, OfferRecord)
            .join(OfferRecord, OfferRecord.product_id == ProductRecord.product_id)
            .where(OfferRecord.sku_id == sku_id)
        )
        with self.session_factory() as session:
            return [self._to_offer(product, offer) for product, offer in session.execute(statement)]

    def list_brands(self, prefix: str | None, limit: int) -> list[BrandSummary]:
        statement = (
            select(ProductRecord.brand, func.count(distinct(ProductRecord.product_id)))
            .join(OfferRecord, OfferRecord.product_id == ProductRecord.product_id)
            .where(OfferRecord.is_available.is_(True))
            .group_by(ProductRecord.brand)
            .order_by(ProductRecord.brand)
        )
        if prefix:
            statement = statement.where(
                ProductRecord.normalized_brand.startswith(normalize_text(prefix))
            )
        with self.session_factory() as session:
            rows = session.execute(statement.limit(limit)).all()
        return [BrandSummary(brand=brand, available_product_count=count) for brand, count in rows]

    def create_run(self, run_id: str, category_id: str | None) -> CatalogRefreshStatus:
        now = utc_now()
        with self.session_factory.begin() as session:
            session.add(
                CrawlRunRecord(
                    run_id=run_id,
                    status="queued",
                    category_id=category_id,
                    started_at=now,
                    finished_at=None,
                    products_processed=0,
                    error=None,
                    pid=None,
                )
            )
        status = self.get_run(run_id)
        if status is None:
            raise RuntimeError("No se pudo crear la ejecucion del crawler")
        return status

    def mark_run_running(self, run_id: str, pid: int) -> None:
        with self.session_factory.begin() as session:
            session.execute(
                update(CrawlRunRecord)
                .where(CrawlRunRecord.run_id == run_id)
                .values(status="running", pid=pid)
            )

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        products_processed: int,
        error: str | None = None,
    ) -> None:
        with self.session_factory.begin() as session:
            session.execute(
                update(CrawlRunRecord)
                .where(CrawlRunRecord.run_id == run_id)
                .values(
                    status=status,
                    finished_at=utc_now(),
                    products_processed=products_processed,
                    error=error,
                )
            )

    def get_run(self, run_id: str) -> CatalogRefreshStatus | None:
        with self.session_factory() as session:
            record = session.get(CrawlRunRecord, run_id)
            return self._run_status(record) if record else None

    def active_run(self) -> CatalogRefreshStatus | None:
        cutoff = utc_now() - timedelta(hours=12)
        with self.session_factory.begin() as session:
            stale_records = session.scalars(
                select(CrawlRunRecord).where(
                    CrawlRunRecord.status.in_(["queued", "running"]),
                    CrawlRunRecord.started_at < cutoff,
                )
            ).all()
            for record in stale_records:
                record.status = "failed"
                record.finished_at = utc_now()
                record.error = "Ejecucion marcada como obsoleta despues de 12 horas"
            active_record = session.scalar(
                select(CrawlRunRecord)
                .where(CrawlRunRecord.status.in_(["queued", "running"]))
                .order_by(CrawlRunRecord.started_at.desc())
            )
            return self._run_status(active_record) if active_record else None

    @staticmethod
    def _offer_rank(offer: CatalogOffer) -> tuple[bool, int]:
        return (not offer.is_available, offer.price_cents)

    @staticmethod
    def _sort_products(products: list[ProductSummary], sort: str) -> None:
        if sort == "price_desc":
            products.sort(key=lambda product: product.price_cents, reverse=True)
        elif sort == "name_asc":
            products.sort(key=lambda product: normalize_text(product.product_name))
        else:
            products.sort(key=lambda product: product.price_cents)

    @staticmethod
    def _to_offer(product: ProductRecord, offer: OfferRecord) -> CatalogOffer:
        return CatalogOffer(
            product_id=product.product_id,
            product_name=product.name,
            brand=product.brand,
            categories=json.loads(product.categories_json),
            product_url=product.product_url,
            sku_id=offer.sku_id,
            sku_name=offer.sku_name,
            seller_id=offer.seller_id,
            seller_name=offer.seller_name,
            price_cents=offer.price_cents,
            list_price_cents=offer.list_price_cents,
            is_available=offer.is_available,
            available_quantity=offer.available_quantity,
            image_urls=json.loads(offer.image_urls_json),
            add_to_cart_url=offer.add_to_cart_url,
            fetched_at=offer.fetched_at,
        )

    @staticmethod
    def _run_status(record: CrawlRunRecord) -> CatalogRefreshStatus:
        started_at = (
            record.started_at.replace(tzinfo=UTC)
            if record.started_at.tzinfo is None
            else record.started_at
        )
        finished_at = record.finished_at
        if finished_at is not None and finished_at.tzinfo is None:
            finished_at = finished_at.replace(tzinfo=UTC)
        return CatalogRefreshStatus(
            run_id=record.run_id,
            status=cast(
                Literal["queued", "running", "completed", "failed"],
                record.status,
            ),
            category_id=record.category_id,
            started_at=started_at,
            finished_at=finished_at,
            products_processed=record.products_processed,
            error=record.error,
            pid=record.pid,
        )
