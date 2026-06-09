from __future__ import annotations

import json
import html
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from wb_autoposter.content import GeneratedContent, TemplateContentGenerator, create_content_generator, sanitize_social_text
from wb_autoposter.models import PlannedPost, PostStatus, Product, SocialPostMetrics


class Base(DeclarativeBase):
    pass


class ProductRecord(Base):
    __tablename__ = "products"
    __table_args__ = (Index("ix_products_first_seen_at", "first_seen_at"),)

    nm_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    brand: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    photos_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    price: Mapped[float | None] = mapped_column(nullable=True)
    stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SeenProductRecord(Base):
    __tablename__ = "seen_products"
    __table_args__ = (Index("ix_seen_products_source_first_seen_at", "source", "first_seen_at"),)

    nm_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_baseline: Mapped[bool] = mapped_column(nullable=False, default=False)


class PostRecord(Base):
    __tablename__ = "posts"
    __table_args__ = (UniqueConstraint("product_nm_id", "platform", name="uq_post_product_platform"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_nm_id: Mapped[int] = mapped_column(ForeignKey("products.nm_id"), nullable=False)
    platform: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PostMetricRecord(Base):
    __tablename__ = "post_metrics"
    __table_args__ = (
        Index("ix_post_metrics_post_captured", "post_id", "captured_at"),
        Index("ix_post_metrics_platform_captured", "platform", "captured_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), nullable=False)
    product_nm_id: Mapped[int] = mapped_column(Integer, nullable=False)
    platform: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="zernio")
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    impressions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reach: Mapped[int | None] = mapped_column(Integer, nullable=True)
    clicks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    likes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comments: Mapped[int | None] = mapped_column(Integer, nullable=True)
    saves: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shares: Mapped[int | None] = mapped_column(Integer, nullable=True)
    views: Mapped[int | None] = mapped_column(Integer, nullable=True)
    engagement: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")


class SyncStateRecord(Base):
    __tablename__ = "sync_state"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Store:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{db_path}", future=True)
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False, future=True)

    def init_db(self) -> None:
        Base.metadata.create_all(self.engine)

    def upsert_products(self, products: list[Product]) -> dict[str, int]:
        now = datetime.now(UTC)
        created = 0
        updated = 0

        with self.session_factory.begin() as session:
            for product in products:
                record = session.get(ProductRecord, product.nm_id)
                if record is None:
                    session.add(_product_to_record(product, first_seen_at=now))
                    created += 1
                else:
                    _update_product_record(record, product)
                    updated += 1

            self.set_state(session, "last_sync_at", now.isoformat())
            self.set_state(session, "last_sync_product_count", str(len(products)))

        return {"total": len(products), "created": created, "updated": updated}

    def upsert_seen_nm_ids(
        self,
        nm_ids: list[int],
        *,
        source: str,
        mark_baseline: bool = False,
    ) -> dict[str, int]:
        now = datetime.now(UTC)
        unique_nm_ids = sorted(set(nm_ids))
        created = 0
        updated = 0
        baseline_marked = 0

        with self.session_factory.begin() as session:
            for nm_id in unique_nm_ids:
                record = session.get(SeenProductRecord, nm_id)
                if record is None:
                    session.add(
                        SeenProductRecord(
                            nm_id=nm_id,
                            source=source,
                            first_seen_at=now,
                            last_seen_at=now,
                            is_baseline=mark_baseline,
                        )
                    )
                    created += 1
                    if mark_baseline:
                        baseline_marked += 1
                    continue

                record.last_seen_at = now
                record.source = source
                updated += 1
                if mark_baseline and not record.is_baseline:
                    record.is_baseline = True
                    baseline_marked += 1

            self.set_state(session, f"{source}_last_seen_sync_at", now.isoformat())
            self.set_state(session, f"{source}_last_seen_count", str(len(unique_nm_ids)))
            if mark_baseline:
                self.set_state(session, "baseline_at", now.isoformat())
                self.set_state(session, f"{source}_baseline_at", now.isoformat())
                self.set_state(session, f"{source}_baseline_nm_id_count", str(len(unique_nm_ids)))

        return {
            "total": len(unique_nm_ids),
            "created": created,
            "updated": updated,
            "baseline_marked": baseline_marked,
        }

    def list_new_seen_nm_ids(self, *, source: str, limit: int | None = None) -> list[int]:
        stmt = (
            select(SeenProductRecord.nm_id)
            .where(SeenProductRecord.source == source, SeenProductRecord.is_baseline.is_(False))
            .order_by(SeenProductRecord.first_seen_at, SeenProductRecord.nm_id)
        )
        if limit is not None:
            stmt = stmt.limit(limit)

        with self.session_factory() as session:
            return list(session.scalars(stmt).all())

    def list_seen_nm_ids_pending_details(self, *, source: str, limit: int | None = None) -> list[int]:
        product_nm_ids = select(ProductRecord.nm_id)
        stmt = (
            select(SeenProductRecord.nm_id)
            .where(
                SeenProductRecord.source == source,
                SeenProductRecord.is_baseline.is_(False),
                SeenProductRecord.nm_id.not_in(product_nm_ids),
            )
            .order_by(SeenProductRecord.first_seen_at, SeenProductRecord.nm_id)
        )
        if limit is not None:
            stmt = stmt.limit(limit)

        with self.session_factory() as session:
            return list(session.scalars(stmt).all())

    def set_source_top_window(self, *, source: str, nm_ids: list[int], window_size: int) -> list[int]:
        top_window = list(dict.fromkeys(nm_ids))[:window_size]
        with self.session_factory.begin() as session:
            self.set_state(session, f"{source}_top_window_nm_ids", json.dumps(top_window))
            self.set_state(session, f"{source}_top_window_size", str(window_size))
        return top_window

    def get_source_top_window(self, *, source: str) -> list[int]:
        raw_value = self._state_value(f"{source}_top_window_nm_ids") or self._state_value(
            f"{source}_checkpoint_nm_ids"
        )
        if not raw_value:
            return []
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, list):
            return []
        return [item for item in parsed if isinstance(item, int)]

    def count_seen_products(self, *, source: str | None = None) -> int:
        stmt = select(func.count()).select_from(SeenProductRecord)
        if source is not None:
            stmt = stmt.where(SeenProductRecord.source == source)
        with self.session_factory() as session:
            return int(session.scalar(stmt) or 0)

    def mark_baseline(self) -> dict[str, int | str]:
        now = datetime.now(UTC)
        with self.session_factory.begin() as session:
            product_count = session.scalar(select(func.count()).select_from(ProductRecord)) or 0
            self.set_state(session, "baseline_at", now.isoformat())
            self.set_state(session, "baseline_product_count", str(product_count))

        return {"products": product_count, "baseline_at": now.isoformat()}

    def baseline_at(self) -> datetime | None:
        with self.session_factory() as session:
            record = session.get(SyncStateRecord, "baseline_at")
            if record is None:
                return None
            return _parse_datetime(record.value)

    def plan_posts(
        self,
        platform: str,
        board_id: str | None = None,
        vk_owner_id: str | None = None,
        vk_from_group: bool = True,
        vk_upload_photo: bool = True,
        tracking_params: dict[str, str] | None = None,
        only_after_baseline: bool = False,
    ) -> dict[str, int]:
        planned = 0
        skipped_existing = 0
        skipped_ineligible = 0
        skipped_baseline = 0
        content_generator = create_content_generator()

        with self.session_factory.begin() as session:
            baseline_at = None
            if only_after_baseline:
                baseline_record = session.get(SyncStateRecord, "baseline_at")
                if baseline_record is None:
                    raise ValueError("Baseline is missing. Run baseline-sync before planning real new arrivals.")
                baseline_at = _parse_datetime(baseline_record.value)

            products = session.scalars(select(ProductRecord).order_by(ProductRecord.first_seen_at)).all()
            for product_record in products:
                if baseline_at is not None and _as_utc(product_record.first_seen_at) <= baseline_at:
                    skipped_baseline += 1
                    continue

                existing = session.scalar(
                    select(PostRecord).where(
                        PostRecord.product_nm_id == product_record.nm_id,
                        PostRecord.platform == platform,
                    )
                )
                product = _record_to_product(product_record)
                if existing is not None:
                    if existing.status == PostStatus.PLANNED.value:
                        self._refresh_planned_post(
                            existing,
                            session,
                            platform,
                            product,
                            board_id,
                            vk_owner_id,
                            vk_from_group,
                            vk_upload_photo,
                            content_generator,
                            tracking_params,
                        )
                    skipped_existing += 1
                    continue

                if not is_publishable(product):
                    skipped_ineligible += 1
                    continue

                content = _content_from_existing_post(session, product.nm_id) or content_generator.generate(product)

                record = (
                    PostRecord(
                        product_nm_id=product.nm_id,
                        platform=platform,
                        status=PostStatus.PLANNED.value,
                        payload_json=json.dumps(
                            build_social_payload(
                                platform,
                                product,
                                content,
                                board_id=board_id,
                                vk_owner_id=vk_owner_id,
                                vk_from_group=vk_from_group,
                                vk_upload_photo=vk_upload_photo,
                                tracking_params=tracking_params,
                            ),
                            ensure_ascii=False,
                        ),
                        created_at=datetime.now(UTC),
                    )
                )
                if self._add_post_record_idempotently(session, record):
                    planned += 1
                else:
                    skipped_existing += 1

        result = {
            "planned": planned,
            "skipped_existing": skipped_existing,
            "skipped_ineligible": skipped_ineligible,
        }
        if only_after_baseline:
            result["skipped_baseline"] = skipped_baseline
        return result

    def retry_failed_posts(
        self,
        platform: str,
        board_id: str | None = None,
        vk_owner_id: str | None = None,
        vk_from_group: bool = True,
        vk_upload_photo: bool = True,
        tracking_params: dict[str, str] | None = None,
    ) -> dict[str, int]:
        retried = 0
        skipped_ineligible = 0
        skipped_missing_product = 0
        content_generator = create_content_generator()

        with self.session_factory.begin() as session:
            records = session.scalars(
                select(PostRecord)
                .where(PostRecord.platform == platform, PostRecord.status == PostStatus.FAILED.value)
                .order_by(PostRecord.created_at, PostRecord.id)
            ).all()

            for record in records:
                product_record = session.get(ProductRecord, record.product_nm_id)
                if product_record is None:
                    skipped_missing_product += 1
                    continue

                product = _record_to_product(product_record)
                if not is_publishable(product):
                    skipped_ineligible += 1
                    continue

                content = _content_from_existing_post(session, product.nm_id) or content_generator.generate(product)
                record.status = PostStatus.PLANNED.value
                record.payload_json = json.dumps(
                    build_social_payload(
                        platform,
                        product,
                        content,
                        board_id=board_id,
                        vk_owner_id=vk_owner_id,
                        vk_from_group=vk_from_group,
                        vk_upload_photo=vk_upload_photo,
                        tracking_params=tracking_params,
                    ),
                    ensure_ascii=False,
                )
                record.external_id = None
                record.error = None
                record.published_at = None
                retried += 1

        return {
            "retried": retried,
            "skipped_ineligible": skipped_ineligible,
            "skipped_missing_product": skipped_missing_product,
        }

    def recover_publishing_posts(
        self,
        platform: str,
        *,
        action: str = "fail",
        board_id: str | None = None,
        vk_owner_id: str | None = None,
        vk_from_group: bool = True,
        vk_upload_photo: bool = True,
        tracking_params: dict[str, str] | None = None,
    ) -> dict[str, int]:
        if action not in {"fail", "retry"}:
            raise ValueError("action must be 'fail' or 'retry'.")

        recovered = 0
        skipped_ineligible = 0
        skipped_missing_product = 0
        content_generator = create_content_generator()

        with self.session_factory.begin() as session:
            records = session.scalars(
                select(PostRecord)
                .where(PostRecord.platform == platform, PostRecord.status == PostStatus.PUBLISHING.value)
                .order_by(PostRecord.created_at, PostRecord.id)
            ).all()

            for record in records:
                if action == "fail":
                    record.status = PostStatus.FAILED.value
                    record.error = "Recovered from stuck publishing state. Verify Pinterest before retrying."
                    record.external_id = None
                    record.published_at = None
                    recovered += 1
                    continue

                product_record = session.get(ProductRecord, record.product_nm_id)
                if product_record is None:
                    skipped_missing_product += 1
                    continue

                product = _record_to_product(product_record)
                if not is_publishable(product):
                    skipped_ineligible += 1
                    continue

                content = _content_from_existing_post(session, product.nm_id) or content_generator.generate(product)
                record.status = PostStatus.PLANNED.value
                record.payload_json = json.dumps(
                    build_social_payload(
                        platform,
                        product,
                        content,
                        board_id=board_id or _board_id_from_payload(record.payload_json),
                        vk_owner_id=vk_owner_id or _vk_owner_id_from_payload(record.payload_json),
                        vk_from_group=vk_from_group,
                        vk_upload_photo=vk_upload_photo,
                        tracking_params=tracking_params,
                    ),
                    ensure_ascii=False,
                )
                record.external_id = None
                record.error = None
                record.published_at = None
                recovered += 1

        return {
            "recovered": recovered,
            "skipped_ineligible": skipped_ineligible,
            "skipped_missing_product": skipped_missing_product,
        }

    def list_posts(self, platform: str | None = None, status: PostStatus | None = None) -> list[PlannedPost]:
        stmt = select(PostRecord).order_by(PostRecord.created_at, PostRecord.id)
        if platform is not None:
            stmt = stmt.where(PostRecord.platform == platform)
        if status is not None:
            stmt = stmt.where(PostRecord.status == status.value)

        with self.session_factory() as session:
            records = session.scalars(stmt).all()
            return [_record_to_post(record) for record in records]

    def save_post_metrics(self, metrics: SocialPostMetrics) -> SocialPostMetrics:
        with self.session_factory.begin() as session:
            post = session.get(PostRecord, metrics.post_id)
            if post is None:
                raise ValueError(f"Post not found: {metrics.post_id}")
            record = PostMetricRecord(
                post_id=metrics.post_id,
                product_nm_id=metrics.product_nm_id,
                platform=metrics.platform,
                external_id=metrics.external_id,
                source=metrics.source,
                captured_at=metrics.captured_at,
                impressions=metrics.impressions,
                reach=metrics.reach,
                clicks=metrics.clicks,
                likes=metrics.likes,
                comments=metrics.comments,
                saves=metrics.saves,
                shares=metrics.shares,
                views=metrics.views,
                engagement=metrics.engagement,
                raw_json=json.dumps(metrics.raw, ensure_ascii=False),
            )
            session.add(record)
            session.flush()
            return _record_to_metrics(record)

    def latest_post_metrics(self, platform: str | None = None, limit: int | None = None) -> list[SocialPostMetrics]:
        stmt = select(PostMetricRecord).order_by(PostMetricRecord.captured_at.desc(), PostMetricRecord.id.desc())
        if platform is not None:
            stmt = stmt.where(PostMetricRecord.platform == platform)

        with self.session_factory() as session:
            records = session.scalars(stmt).all()

        latest_by_post: dict[int, SocialPostMetrics] = {}
        for record in records:
            if record.post_id in latest_by_post:
                continue
            latest_by_post[record.post_id] = _record_to_metrics(record)
            if limit is not None and len(latest_by_post) >= limit:
                break
        return list(latest_by_post.values())

    def metrics_summary(self, platform: str | None = None) -> dict[str, int]:
        latest = self.latest_post_metrics(platform=platform)
        totals = {
            "posts_with_metrics": len(latest),
            "impressions": 0,
            "reach": 0,
            "clicks": 0,
            "likes": 0,
            "comments": 0,
            "saves": 0,
            "shares": 0,
            "views": 0,
            "engagement": 0,
        }
        for metrics in latest:
            for key in totals:
                if key == "posts_with_metrics":
                    continue
                totals[key] += getattr(metrics, key) or 0
        return totals

    def update_post_result(self, post_id: int, status: PostStatus, external_id: str | None, error: str | None) -> None:
        with self.session_factory.begin() as session:
            record = session.get(PostRecord, post_id)
            if record is None:
                raise ValueError(f"Post not found: {post_id}")
            record.status = status.value
            record.external_id = external_id
            record.error = error
            if status in {PostStatus.DRY_RUN_PUBLISHED, PostStatus.PUBLISHED}:
                record.published_at = datetime.now(UTC)

    def mark_post_publishing(self, post_id: int) -> None:
        with self.session_factory.begin() as session:
            record = session.get(PostRecord, post_id)
            if record is None:
                raise ValueError(f"Post not found: {post_id}")
            if record.status != PostStatus.PLANNED.value:
                raise ValueError(f"Post {post_id} is not planned; current status is {record.status}")
            record.status = PostStatus.PUBLISHING.value
            record.error = None

    def summary(self) -> dict[str, Any]:
        with self.session_factory() as session:
            products = session.scalars(select(ProductRecord)).all()
            posts = session.scalars(select(PostRecord)).all()
            last_sync = session.get(SyncStateRecord, "last_sync_at")

        by_status: dict[str, int] = {}
        for post in posts:
            by_status[post.status] = by_status.get(post.status, 0) + 1

        return {
            "products_total": len(products),
            "products_publishable": sum(1 for product in products if is_publishable(_record_to_product(product))),
            "posts_total": len(posts),
            "posts_by_status": by_status,
            "last_sync_at": last_sync.value if last_sync else None,
            "baseline_at": self._state_value("baseline_at"),
        }

    def _state_value(self, key: str) -> str | None:
        with self.session_factory() as session:
            record = session.get(SyncStateRecord, key)
            return record.value if record else None

    @staticmethod
    def set_state(session: Session, key: str, value: str) -> None:
        record = session.get(SyncStateRecord, key)
        now = datetime.now(UTC)
        if record is None:
            session.add(SyncStateRecord(key=key, value=value, updated_at=now))
        else:
            record.value = value
            record.updated_at = now

    @staticmethod
    def _add_post_record_idempotently(session: Session, record: PostRecord) -> bool:
        try:
            with session.begin_nested():
                session.add(record)
                session.flush()
        except IntegrityError:
            return False
        return True

    @staticmethod
    def _refresh_planned_post(
        record: PostRecord,
        session: Session,
        platform: str,
        product: Product,
        board_id: str | None,
        vk_owner_id: str | None,
        vk_from_group: bool,
        vk_upload_photo: bool,
        content_generator: TemplateContentGenerator,
        tracking_params: dict[str, str] | None = None,
    ) -> None:
        if not is_publishable(product):
            record.status = PostStatus.FAILED.value
            record.error = "Product is no longer publishable."
            return

        content = content_generator.generate(product)
        record.payload_json = json.dumps(
            build_social_payload(
                platform,
                product,
                content,
                board_id=board_id,
                vk_owner_id=vk_owner_id,
                vk_from_group=vk_from_group,
                vk_upload_photo=vk_upload_photo,
                tracking_params=tracking_params,
            ),
            ensure_ascii=False,
        )
        record.error = None


def _content_from_existing_post(session: Session, nm_id: int) -> GeneratedContent | None:
    records = session.scalars(
        select(PostRecord)
        .where(PostRecord.product_nm_id == nm_id)
        .order_by(PostRecord.created_at, PostRecord.id)
    ).all()
    for record in records:
        try:
            payload = json.loads(record.payload_json)
        except json.JSONDecodeError:
            continue
        generated = payload.get("generated_content")
        if not isinstance(generated, dict):
            continue
        title = generated.get("title")
        description = generated.get("description")
        cta = generated.get("cta")
        hashtags = generated.get("hashtags")
        if not isinstance(title, str) or not isinstance(description, str) or not isinstance(cta, str):
            continue
        if not isinstance(hashtags, list) or not all(isinstance(tag, str) for tag in hashtags):
            continue
        platform_texts = generated.get("platform_texts")
        if platform_texts is not None:
            if not isinstance(platform_texts, dict):
                platform_texts = None
            else:
                platform_texts = {str(key): str(value) for key, value in platform_texts.items() if isinstance(value, str)}
        seo = generated.get("seo")
        if seo is not None and not isinstance(seo, dict):
            seo = None
        return GeneratedContent(
            title=title,
            description=description,
            cta=cta,
            hashtags=hashtags,
            platform_texts=platform_texts,
            seo=seo,
        )
    return None


def is_publishable(product: Product) -> bool:
    return (
        bool(product.title.strip())
        and bool(product.brand.strip())
        and bool(product.photos)
        and _is_http_url(product.photos[0])
        and product.price is not None
        and product.price > 0
        and product.stock > 0
        and _is_http_url(product.url)
    )


def build_pinterest_payload(
    product: Product,
    board_id: str,
    content: GeneratedContent | None = None,
    tracking_params: dict[str, str] | None = None,
) -> dict[str, Any]:
    if not is_publishable(product):
        raise ValueError(f"Product {product.nm_id} is not publishable.")

    generated_content = content or TemplateContentGenerator().generate(product)
    pinterest_title = _seo_field(generated_content, "pinterest_title", generated_content.title)

    return {
        "product_nm_id": product.nm_id,
        "generated_content": generated_content.to_dict(),
        "pinterest": {
            "title": pinterest_title,
            "description": _platform_text(generated_content, "pinterest", generated_content.description),
            "board_id": board_id,
            "link": build_tracked_link(product.url.strip(), product.nm_id, tracking_params),
            "media_source": {
                "source_type": "image_url",
                "url": product.photos[0].strip(),
            },
        },
    }


def build_vk_payload(
    product: Product,
    owner_id: str,
    content: GeneratedContent | None = None,
    *,
    from_group: bool = True,
    upload_photo: bool = True,
    tracking_params: dict[str, str] | None = None,
) -> dict[str, Any]:
    if not is_publishable(product):
        raise ValueError(f"Product {product.nm_id} is not publishable.")
    if not owner_id.strip():
        raise ValueError("VK owner_id is required.")

    generated_content = content or TemplateContentGenerator().generate(product)
    link = build_tracked_link(product.url.strip(), product.nm_id, tracking_params)
    message = _build_vk_message(product, generated_content, link)

    return {
        "product_nm_id": product.nm_id,
        "generated_content": generated_content.to_dict(),
        "vk": {
            "owner_id": owner_id.strip(),
            "from_group": 1 if from_group else 0,
            "message": message,
            "attachments": [link] if upload_photo else [],
            "link": link,
            "image_url": product.photos[0].strip(),
            "upload_photo": upload_photo,
        },
    }


def build_instagram_payload(
    product: Product,
    content: GeneratedContent | None = None,
    *,
    tracking_params: dict[str, str] | None = None,
) -> dict[str, Any]:
    if not is_publishable(product):
        raise ValueError(f"Product {product.nm_id} is not publishable.")

    generated_content = content or TemplateContentGenerator().generate(product)
    link = build_tracked_link(product.url.strip(), product.nm_id, tracking_params)
    caption = _build_instagram_caption(product, generated_content)

    return {
        "product_nm_id": product.nm_id,
        "generated_content": generated_content.to_dict(),
        "instagram": {
            "image_url": product.photos[0].strip(),
            "caption": caption,
            "link": link,
        },
    }


def build_social_payload(
    platform: str,
    product: Product,
    content: GeneratedContent | None = None,
    *,
    board_id: str | None = None,
    vk_owner_id: str | None = None,
    vk_from_group: bool = True,
    vk_upload_photo: bool = True,
    tracking_params: dict[str, str] | None = None,
) -> dict[str, Any]:
    if platform == "pinterest":
        if board_id is None:
            raise ValueError("Pinterest board_id is required.")
        return build_pinterest_payload(product, board_id, content, tracking_params=tracking_params)
    if platform == "vk":
        if vk_owner_id is None:
            raise ValueError("VK owner_id is required.")
        return build_vk_payload(
            product,
            vk_owner_id,
            content,
            from_group=vk_from_group,
            upload_photo=vk_upload_photo,
            tracking_params=tracking_params,
        )
    if platform == "instagram":
        return build_instagram_payload(product, content, tracking_params=tracking_params)
    raise ValueError(f"Unsupported platform: {platform}")


def _build_vk_message(_product: Product, content: GeneratedContent, link: str) -> str:
    parts = [_platform_text(content, "vk", content.description), f"Ссылка на Вайлдберриз: {link}"]
    return "\n\n".join(part for part in parts if part.strip())


def _build_instagram_caption(product: Product, content: GeneratedContent) -> str:
    instagram_text = _platform_text(content, "instagram", "")
    article_line = f"Артикул WB: {product.nm_id}"
    if instagram_text:
        tags = " ".join(content.hashtags)
        return "\n\n".join(part for part in [instagram_text, article_line, tags] if part.strip())

    title = content.title.rstrip(".")
    fact = _short_caption_fact(product.description)
    price = _format_caption_price(product.price)
    tags = " ".join(content.hashtags)

    price_line = f"Цена: {price}" if price else ""
    article_line = f"Артикул WB: {product.nm_id}"

    variant = product.nm_id % 3
    if variant == 0:
        lines = [title, fact, price_line, article_line]
    elif variant == 1:
        lines = [title, price_line, fact, article_line]
    else:
        lines = ["Новинка на Wildberries", title, fact, price_line, article_line]

    body = "\n".join(line for line in lines if line.strip())
    return "\n\n".join(part for part in [body, tags] if part.strip())


def _platform_text(content: GeneratedContent, platform: str, fallback: str) -> str:
    if content.platform_texts:
        value = content.platform_texts.get(platform)
        if isinstance(value, str) and value.strip():
            return sanitize_social_text(value)
    return sanitize_social_text(fallback)


def _seo_field(content: GeneratedContent, key: str, fallback: str) -> str:
    if isinstance(content.seo, dict):
        value = content.seo.get(key)
        if isinstance(value, str) and value.strip():
            return sanitize_social_text(value)
    return sanitize_social_text(fallback)


def _format_caption_price(price: float | None) -> str:
    if price is None:
        return ""
    return f"{price:,.0f}".replace(",", " ") + " руб."


def _short_caption_fact(description: str) -> str:
    cleaned = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", description))).strip()
    if not cleaned:
        return ""
    sentence = re.split(r"(?<=[.!?])\s+", cleaned, maxsplit=1)[0].strip()
    if len(sentence) < 12 or "http" in sentence.lower() or sentence.count("#") > 1:
        return ""
    if len(sentence) > 120:
        sentence = sentence[:119].rsplit(" ", 1)[0].rstrip(".,;:") + "..."
    return sentence.rstrip(".") + "."


def build_tracked_link(url: str, nm_id: int, tracking_params: dict[str, str] | None = None) -> str:
    if not tracking_params:
        return url

    parsed = urlparse(url.strip())
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update({key: value for key, value in tracking_params.items() if value})
    query.setdefault("utm_content", str(nm_id))
    return urlunparse(parsed._replace(query=urlencode(query)))


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _board_id_from_payload(payload_json: str) -> str:
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        return "unknown-board"
    return str((payload.get("pinterest") or {}).get("board_id") or "unknown-board")


def _vk_owner_id_from_payload(payload_json: str) -> str:
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        return ""
    return str((payload.get("vk") or {}).get("owner_id") or "")


def _product_to_record(product: Product, first_seen_at: datetime) -> ProductRecord:
    return ProductRecord(
        nm_id=product.nm_id,
        brand=product.brand,
        title=product.title,
        description=product.description,
        photos_json=json.dumps(product.photos, ensure_ascii=False),
        price=product.price,
        stock=product.stock,
        created_at=product.created_at,
        updated_at=product.updated_at,
        url=product.url,
        first_seen_at=first_seen_at,
    )


def _update_product_record(record: ProductRecord, product: Product) -> None:
    record.brand = product.brand
    record.title = product.title
    record.description = product.description
    record.photos_json = json.dumps(product.photos, ensure_ascii=False)
    record.price = product.price
    record.stock = product.stock
    record.created_at = product.created_at
    record.updated_at = product.updated_at
    record.url = product.url


def _record_to_product(record: ProductRecord) -> Product:
    return Product(
        nm_id=record.nm_id,
        brand=record.brand,
        title=record.title,
        description=record.description,
        photos=json.loads(record.photos_json),
        price=record.price,
        stock=record.stock,
        created_at=record.created_at,
        updated_at=record.updated_at,
        url=record.url,
    )


def _record_to_post(record: PostRecord) -> PlannedPost:
    return PlannedPost(
        id=record.id,
        product_nm_id=record.product_nm_id,
        platform=record.platform,
        status=PostStatus(record.status),
        payload=json.loads(record.payload_json),
        external_id=record.external_id,
        error=record.error,
        created_at=record.created_at,
        published_at=record.published_at,
    )


def _record_to_metrics(record: PostMetricRecord) -> SocialPostMetrics:
    try:
        raw = json.loads(record.raw_json)
    except json.JSONDecodeError:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    return SocialPostMetrics(
        id=record.id,
        post_id=record.post_id,
        product_nm_id=record.product_nm_id,
        platform=record.platform,
        external_id=record.external_id,
        source=record.source,
        captured_at=record.captured_at,
        impressions=record.impressions,
        reach=record.reach,
        clicks=record.clicks,
        likes=record.likes,
        comments=record.comments,
        saves=record.saves,
        shares=record.shares,
        views=record.views,
        engagement=record.engagement,
        raw=raw,
    )


def _parse_datetime(value: str) -> datetime:
    return _as_utc(datetime.fromisoformat(value))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
