import sqlalchemy
from sqlalchemy import BigInteger, CheckConstraint, Integer, text
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

    __table_args__ = (
        CheckConstraint("cnt >= 0", name="ck_affection_histogram_cnt_non_negative"),
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

    sum_before = (
        await session.execute(
            sqlalchemy.select(
                sqlalchemy.func.coalesce(sqlalchemy.func.sum(AffectionHistogram.cnt), 0)
            ).where(AffectionHistogram.bucket < bucket)
        )
    ).scalar() or 0

    bucket_cnt = (
        await session.execute(
            sqlalchemy.select(
                sqlalchemy.func.coalesce(AffectionHistogram.cnt, 0)
            ).where(AffectionHistogram.bucket == bucket)
        )
    ).scalar() or 0

    total = (
        await session.execute(
            sqlalchemy.select(sqlalchemy.func.count()).select_from(UserData)
        )
    ).scalar() or 0

    if total <= 0:
        return 0.0

    return min(1.0, max(0.0, (sum_before + bucket_cnt * 0.5) / total))


@with_session
async def _get_affection_percentile_fallback(
    affection: int,
    session: AsyncSession | None = None,
) -> float:
    assert session is not None

    if runtime_config.db_is_sqlite:
        stmt = text("""
            SELECT
                CAST(SUM(CASE WHEN json_extract(config, '$.affection') <= :affection THEN 1 ELSE 0 END) AS REAL)
                / NULLIF(COUNT(*), 0)
            FROM user_data
        """)
    elif runtime_config.db_is_mysql:
        stmt = text("""
            SELECT COUNT(*) / NULLIF((SELECT COUNT(*) FROM user_data), 0)
            FROM user_data
            WHERE JSON_EXTRACT(config, '$.affection') <= :affection
        """)
    else:
        stmt = text("""
            SELECT
                COUNT(*) FILTER (WHERE (config->>'affection')::int <= :affection)::float
                / NULLIF(COUNT(*), 0)::float
            FROM user_data
        """)

    result = await session.execute(stmt, {"affection": affection})
    return float(result.scalar() or 0.0)


@with_session
async def get_affection_percentile(
    affection: int,
    use_histogram: bool = True,
    session: AsyncSession | None = None,
) -> float:
    return (
        await _get_affection_percentile_fast(affection, session=session)
        if use_histogram
        else await _get_affection_percentile_fallback(affection, session=session)
    )


@with_tx
async def rebuild_histogram(session: AsyncSession | None = None) -> int:
    assert session is not None
    logger.info("Rebuilding affection histogram...")

    if runtime_config.db_is_postgres:
        await session.execute(
            text("ALTER TABLE user_data DISABLE TRIGGER trg_update_affection_histogram")
        )

    await session.execute(sqlalchemy.delete(AffectionHistogram))

    result = await session.execute(sqlalchemy.select(UserData.config))

    bucket_counts: dict[int, int] = {}

    for (config,) in result:
        cfg = UserConfig.from_dict(config)
        b = affection_bucket(cfg.affection)
        bucket_counts[b] = bucket_counts.get(b, 0) + 1

    for bucket, cnt in bucket_counts.items():
        session.add(AffectionHistogram(bucket=bucket, cnt=cnt))

    if runtime_config.db_is_postgres:
        await session.execute(
            text("ALTER TABLE user_data ENABLE TRIGGER trg_update_affection_histogram")
        )

    logger.info("Histogram rebuilt")
    return len(bucket_counts)


async def install_postgres_trigger() -> None:
    if not runtime_config.db_is_postgres:
        return

    async with engine.begin() as conn:
        await conn.execute(
            text("""
        CREATE OR REPLACE FUNCTION affection_bucket(x INT)
        RETURNS INT IMMUTABLE AS $$
        BEGIN
            IF x < -200 THEN RETURN x / 50;
            ELSIF x < 200 THEN RETURN x / 2;
            ELSIF x < 500 THEN RETURN 100 + (x - 200) / 5;
            ELSIF x < 1000 THEN RETURN 160 + (x - 500) / 10;
            ELSIF x < 2000 THEN RETURN 210 + (x - 1000) / 20;
            ELSE RETURN 260 + (x - 2000) / 50;
            END IF;
        END;
        $$ LANGUAGE plpgsql;
        """)
        )

        await conn.execute(
            text("""
CREATE OR REPLACE FUNCTION update_affection_histogram()
RETURNS trigger AS $$
DECLARE
    old_aff INT;
    new_aff INT;
    old_bucket INT;
    new_bucket INT;
BEGIN
    IF TG_OP = 'INSERT' THEN
        new_aff := COALESCE((NEW.config->>'affection')::int, 0);
        new_bucket := affection_bucket(new_aff);

        INSERT INTO affection_histogram(bucket, cnt)
        VALUES (new_bucket, 1)
        ON CONFLICT (bucket)
        DO UPDATE SET cnt = affection_histogram.cnt + 1;

        RETURN NEW;
    END IF;

    IF TG_OP = 'DELETE' THEN
        old_aff := COALESCE((OLD.config->>'affection')::int, 0);
        old_bucket := affection_bucket(old_aff);

        UPDATE affection_histogram
        SET cnt = GREATEST(cnt - 1, 0)
        WHERE bucket = old_bucket;

        RETURN OLD;
    END IF;

    -- UPDATE
    old_aff := (OLD.config->>'affection')::int;
    new_aff := (NEW.config->>'affection')::int;

    -- affection 没变，直接跳过（关键）
    IF old_aff IS NOT DISTINCT FROM new_aff THEN
        RETURN NEW;
    END IF;

    old_bucket := affection_bucket(COALESCE(old_aff, 0));
    new_bucket := affection_bucket(COALESCE(new_aff, 0));

    UPDATE affection_histogram
    SET cnt = GREATEST(cnt - 1, 0)
    WHERE bucket = old_bucket;

    INSERT INTO affection_histogram(bucket, cnt)
    VALUES (new_bucket, 1)
    ON CONFLICT (bucket)
    DO UPDATE SET cnt = affection_histogram.cnt + 1;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
        """)
        )

        await conn.execute(
            text("DROP TRIGGER IF EXISTS trg_update_affection_histogram ON user_data;")
        )

        await conn.execute(
            text("""
CREATE TRIGGER trg_update_affection_histogram
AFTER INSERT OR DELETE OR UPDATE
ON user_data
FOR EACH ROW
EXECUTE FUNCTION update_affection_histogram();
            """)
        )

        logger.info("PostgreSQL affection histogram trigger installed")


@with_tx
async def update_user_affection(
    user_id: int,
    new_affection: int,
    session: AsyncSession | None = None,
):
    assert session is not None

    user = await session.get(UserData, user_id)
    if user is None:
        raise ValueError("User not found")

    old_affection = user.user_config.affection
    if old_affection == new_affection:
        return

    old_bucket = affection_bucket(old_affection)
    new_bucket = affection_bucket(new_affection)

    cfg = user.config.copy()
    cfg["affection"] = new_affection
    user.config = cfg
    flag_modified(user, "config")

    if runtime_config.db_is_postgres:
        return

    # 非 PG：手动维护
    if old_bucket != new_bucket:
        await session.execute(
            sqlalchemy.update(AffectionHistogram)
            .where(AffectionHistogram.bucket == old_bucket)
            .values(cnt=sqlalchemy.func.greatest(AffectionHistogram.cnt - 1, 0))
        )

        if runtime_config.db_is_mysql:
            stmt = text("""
                INSERT INTO affection_histogram(bucket, cnt)
                VALUES (:bucket, 1)
                ON DUPLICATE KEY UPDATE cnt = cnt + 1
            """)
        else:
            stmt = text("""
                INSERT INTO affection_histogram(bucket, cnt)
                VALUES (:bucket, 1)
                ON CONFLICT (bucket)
                DO UPDATE SET cnt = cnt + 1
            """)

        await session.execute(stmt, {"bucket": new_bucket})


async def init_affection_histogram() -> None:
    from .db import AsyncSessionFactory

    async with AsyncSessionFactory() as session:
        count = (
            await session.execute(
                sqlalchemy.select(sqlalchemy.func.count()).select_from(
                    AffectionHistogram
                )
            )
        ).scalar()

        if not count:
            await rebuild_histogram(session=session)
            await session.commit()

    if runtime_config.db_is_postgres:
        await install_postgres_trigger()


@with_session
async def get_affection_stats(session: AsyncSession | None = None) -> dict:
    assert session is not None

    total_users = (
        await session.execute(
            sqlalchemy.select(sqlalchemy.func.count()).select_from(UserData)
        )
    ).scalar() or 0

    row = (
        await session.execute(
            sqlalchemy.select(
                sqlalchemy.func.count(AffectionHistogram.bucket),
                sqlalchemy.func.min(AffectionHistogram.bucket),
                sqlalchemy.func.max(AffectionHistogram.bucket),
            )
        )
    ).one()

    return {
        "total_users": total_users,
        "bucket_count": row[0],
        "min_bucket": row[1],
        "max_bucket": row[2],
    }


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


__all__ = [
    "AffectionHistogram",
    "affection_bucket",
    "get_affection_percentile",
    "rebuild_histogram",
    "get_affection_stats",
    "init_affection_histogram",
    "install_postgres_trigger",
    "uninstall_postgres_trigger",
    "update_user_affection",
    "add_user_affection",
]
