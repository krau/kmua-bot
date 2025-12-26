import sqlalchemy
from sqlalchemy import BigInteger, Integer, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm.attributes import flag_modified

from kmua.config import runtime_config
from kmua.logger import logger

from .db import engine, with_session, with_tx
from .models import Base, UserConfig, UserData


def affection_bucket(x: int) -> int:
    if x < -200:
        return x // 50
    if x < 200:
        return x // 2
    if x < 500:
        return 100 + (x - 200) // 5
    if x < 1000:
        return 160 + (x - 500) // 10
    if x < 2000:
        return 210 + (x - 1000) // 20
    return 260 + (x - 2000) // 50


class AffectionHistogram(Base):
    __tablename__ = "affection_histogram"

    bucket: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=False,
        index=True,
    )
    cnt: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
    )

    def __repr__(self) -> str:
        return f"<AffectionHistogram(bucket={self.bucket}, cnt={self.cnt})>"


@with_session
async def _get_affection_percentile_fast(
    affection: int,
    session: AsyncSession | None = None,
) -> float:
    assert session is not None

    bucket = affection_bucket(affection)

    stmt_before = sqlalchemy.select(
        sqlalchemy.func.coalesce(sqlalchemy.func.sum(AffectionHistogram.cnt), 0)
    ).where(AffectionHistogram.bucket < bucket)
    result_before = await session.execute(stmt_before)
    sum_before = int(result_before.scalar() or 0)

    stmt_bucket = sqlalchemy.select(AffectionHistogram.cnt).where(
        AffectionHistogram.bucket == bucket
    )
    result_bucket = await session.execute(stmt_bucket)
    bucket_cnt = int(result_bucket.scalar() or 0)

    stmt_total = sqlalchemy.select(
        sqlalchemy.func.coalesce(sqlalchemy.func.sum(AffectionHistogram.cnt), 0)
    )
    result_total = await session.execute(stmt_total)
    total = int(result_total.scalar() or 0)

    if total == 0:
        return 0.0

    percentile = (sum_before + bucket_cnt * 0.5) / total

    return min(1.0, max(0.0, percentile))


@with_session
async def _get_affection_percentile_fallback(
    affection: int,
    session: AsyncSession | None = None,
) -> float:
    assert session is not None

    if runtime_config.db_is_sqlite:
        # 全表扫描
        stmt = text("""
            SELECT
                CAST(SUM(CASE WHEN json_extract(config, '$.affection') <= :affection THEN 1 ELSE 0 END) AS REAL)
                / CAST(COUNT(*) AS REAL)
            FROM user_data
        """)
        result = await session.execute(stmt, {"affection": affection})
        percentile = result.scalar()
        return float(percentile) if percentile is not None else 0.0
    elif runtime_config.db_is_mysql:
        stmt = text("""
            SELECT COUNT(*) / (SELECT COUNT(*) FROM user_data)
            FROM user_data
            WHERE JSON_EXTRACT(config, '$.affection') <= :affection
        """)
        result = await session.execute(stmt, {"affection": affection})
        percentile = result.scalar()
        return float(percentile) if percentile is not None else 0.0
    else:
        stmt = text("""
            SELECT
                COUNT(*) FILTER (WHERE (config->>'affection')::int <= :affection)::float
                / NULLIF(COUNT(*), 0)::float
            FROM user_data
        """)
        result = await session.execute(stmt, {"affection": affection})
        percentile = result.scalar()
        return float(percentile) if percentile is not None else 0.0


@with_session
async def get_affection_percentile(
    affection: int,
    use_histogram: bool = True,
    session: AsyncSession | None = None,
) -> float:
    if use_histogram:
        return await _get_affection_percentile_fast(affection, session=session)
    else:
        return await _get_affection_percentile_fallback(affection, session=session)


@with_tx
async def rebuild_histogram(session: AsyncSession | None = None) -> int:
    assert session is not None

    logger.info("Rebuilding affection histogram...")

    await session.execute(sqlalchemy.delete(AffectionHistogram))

    stmt = sqlalchemy.select(UserData.config)
    result = await session.execute(stmt)
    bucket_counts: dict[int, int] = {}
    for (config,) in result:
        user_config = UserConfig.from_dict(config)
        bucket = affection_bucket(user_config.affection)
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1

    for bucket, cnt in bucket_counts.items():
        session.add(AffectionHistogram(bucket=bucket, cnt=cnt))

    logger.info(f"Affection histogram rebuilt with {len(bucket_counts)} buckets")
    return len(bucket_counts)


@with_session
async def get_histogram_stats(
    session: AsyncSession | None = None,
) -> dict:
    assert session is not None

    stmt = sqlalchemy.select(
        sqlalchemy.func.coalesce(sqlalchemy.func.sum(AffectionHistogram.cnt), 0).label(
            "total_users"
        ),
        sqlalchemy.func.count(AffectionHistogram.bucket).label("bucket_count"),
        sqlalchemy.func.min(AffectionHistogram.bucket).label("min_bucket"),
        sqlalchemy.func.max(AffectionHistogram.bucket).label("max_bucket"),
    )
    result = await session.execute(stmt)
    row = result.one()

    return {
        "total_users": row.total_users,
        "bucket_count": row.bucket_count,
        "min_bucket": row.min_bucket,
        "max_bucket": row.max_bucket,
    }


async def install_postgres_trigger() -> None:
    """
    为 PostgreSQL 安装自动维护直方图的触发器

    触发器会在 user_data 的 config 字段更新时自动更新直方图
    """
    if not runtime_config.db_is_postgres:
        logger.warning("install_postgres_trigger called on non-PostgreSQL database")
        return

    bucket_function = """
    CREATE OR REPLACE FUNCTION affection_bucket(x INT)
    RETURNS INT AS $$
    BEGIN
        IF x < -200 THEN
            RETURN x / 50;
        ELSIF x < 200 THEN
            RETURN x / 2;
        ELSIF x < 500 THEN
            RETURN 100 + (x - 200) / 5;
        ELSIF x < 1000 THEN
            RETURN 160 + (x - 500) / 10;
        ELSIF x < 2000 THEN
            RETURN 210 + (x - 1000) / 20;
        ELSE
            RETURN 260 + (x - 2000) / 50;
        END IF;
    END;
    $$ LANGUAGE plpgsql IMMUTABLE;
    """

    trigger_function = """
    CREATE OR REPLACE FUNCTION update_affection_histogram()
    RETURNS trigger AS $$
    DECLARE
        old_affection INT;
        new_affection INT;
        old_bucket INT;
        new_bucket INT;
    BEGIN
        IF TG_OP = 'INSERT' THEN
            new_affection := COALESCE((NEW.config->>'affection')::int, 41);
            new_bucket := affection_bucket(new_affection);

            INSERT INTO affection_histogram (bucket, cnt)
            VALUES (new_bucket, 1)
            ON CONFLICT (bucket)
            DO UPDATE SET cnt = affection_histogram.cnt + 1;

        ELSIF TG_OP = 'UPDATE' THEN
            old_affection := COALESCE((OLD.config->>'affection')::int, 41);
            new_affection := COALESCE((NEW.config->>'affection')::int, 41);
            old_bucket := affection_bucket(old_affection);
            new_bucket := affection_bucket(new_affection);

            IF old_bucket != new_bucket THEN
                UPDATE affection_histogram
                SET cnt = cnt - 1
                WHERE bucket = old_bucket;

                INSERT INTO affection_histogram (bucket, cnt)
                VALUES (new_bucket, 1)
                ON CONFLICT (bucket)
                DO UPDATE SET cnt = affection_histogram.cnt + 1;
            END IF;

        ELSIF TG_OP = 'DELETE' THEN
            old_affection := COALESCE((OLD.config->>'affection')::int, 41);
            old_bucket := affection_bucket(old_affection);

            UPDATE affection_histogram
            SET cnt = cnt - 1
            WHERE bucket = old_bucket;
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

    trigger_drop = """
    DROP TRIGGER IF EXISTS trg_update_affection_histogram ON user_data;
    """

    trigger_create = """
    CREATE TRIGGER trg_update_affection_histogram
    AFTER INSERT OR UPDATE OF config OR DELETE ON user_data
    FOR EACH ROW
    EXECUTE FUNCTION update_affection_histogram();
    """

    async with engine.begin() as conn:
        await conn.execute(text(bucket_function))
        await conn.execute(text(trigger_function))
        await conn.execute(text(trigger_drop))
        await conn.execute(text(trigger_create))
        logger.info("PostgreSQL affection histogram trigger installed successfully")


async def uninstall_postgres_trigger() -> None:
    """
    卸载 PostgreSQL 触发器
    """
    if not runtime_config.db_is_postgres:
        return

    async with engine.begin() as conn:
        await conn.execute(
            text("DROP TRIGGER IF EXISTS trg_update_affection_histogram ON user_data;")
        )
        await conn.execute(text("DROP FUNCTION IF EXISTS update_affection_histogram;"))
        await conn.execute(text("DROP FUNCTION IF EXISTS affection_bucket;"))
        logger.info("PostgreSQL affection histogram trigger uninstalled")


@with_tx
async def update_user_affection(
    user_id: int,
    new_affection: int,
    session: AsyncSession | None = None,
):
    assert session is not None

    user_data = await session.get(UserData, user_id)
    if user_data is None:
        raise ValueError(f"User with id {user_id} not found")

    old_config = user_data.user_config
    old_affection = old_config.affection
    old_config.affection = new_affection

    user_data.user_config = old_config
    flag_modified(user_data, "config")

    if not runtime_config.db_is_postgres:
        old_bucket = affection_bucket(old_affection)
        new_bucket = affection_bucket(new_affection)

        if old_bucket != new_bucket:
            stmt_dec = (
                sqlalchemy.update(AffectionHistogram)
                .where(AffectionHistogram.bucket == old_bucket)
                .values(cnt=AffectionHistogram.cnt - 1)
            )
            await session.execute(stmt_dec)

            if runtime_config.db_is_mysql:
                stmt_inc = text("""
                    INSERT INTO affection_histogram (bucket, cnt)
                    VALUES (:bucket, 1)
                    ON DUPLICATE KEY UPDATE cnt = cnt + 1
                """)
            else:
                stmt_inc = text("""
                    INSERT INTO affection_histogram (bucket, cnt)
                    VALUES (:bucket, 1)
                    ON CONFLICT (bucket)
                    DO UPDATE SET cnt = cnt + 1
                """)
            await session.execute(stmt_inc, {"bucket": new_bucket})


@with_tx
async def add_user_affection(
    user_id: int,
    delta: int,
    session: AsyncSession | None = None,
):
    assert session is not None

    user_data = await session.get(UserData, user_id)
    if user_data is None:
        raise ValueError(f"User with id {user_id} not found")

    old_config = user_data.user_config
    new_affection = old_config.affection + delta

    await update_user_affection(
        user_id=user_id,
        new_affection=new_affection,
        session=session,
    )


async def init_affection_histogram() -> None:
    from .db import AsyncSessionFactory

    async with AsyncSessionFactory() as session:
        # 检查直方图是否有数据
        stmt = sqlalchemy.select(sqlalchemy.func.count()).select_from(
            AffectionHistogram
        )
        result = await session.execute(stmt)
        count = result.scalar() or 0

        if count == 0:
            logger.info("Affection histogram is empty, rebuilding from user_data...")
            await rebuild_histogram(session=session)
            await session.commit()

    if runtime_config.db_is_postgres:
        await install_postgres_trigger()


__all__ = [
    "AffectionHistogram",
    "affection_bucket",
    "get_affection_percentile",
    "rebuild_histogram",
    "get_histogram_stats",
    "init_affection_histogram",
    "install_postgres_trigger",
    "uninstall_postgres_trigger",
    "update_user_affection",
    "add_user_affection",
]
