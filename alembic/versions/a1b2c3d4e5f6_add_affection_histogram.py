"""add affection histogram

Revision ID: a1b2c3d4e5f6
Revises: d327932d860e
Create Date: 2025-12-25 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import text

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "d327932d860e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def affection_bucket(x: int) -> int:
    """
    将好感度值映射到桶编号（与 kmua/database/affection.py 保持一致）
    """
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


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    dialect = bind.dialect.name

    table_name = "affection_histogram"

    # 检查表是否已存在
    if not insp.has_table(table_name):
        op.create_table(
            table_name,
            sa.Column("bucket", sa.Integer(), primary_key=True, autoincrement=False),
            sa.Column("cnt", sa.BigInteger(), nullable=False, default=0),
        )

        # 创建索引
        op.create_index(
            "ix_affection_histogram_bucket",
            table_name,
            ["bucket"],
            unique=False,
        )

    # 由于使用非线性分桶函数，需要在应用层逐行处理
    # 所有数据库使用相同的 Python 逻辑
    if dialect == "postgresql":
        result = bind.execute(
            text(
                "SELECT config->>'affection' as affection FROM user_data WHERE config->>'affection' IS NOT NULL"
            )
        )
    elif dialect == "mysql":
        result = bind.execute(
            text(
                "SELECT JSON_EXTRACT(config, '$.affection') as affection FROM user_data WHERE JSON_EXTRACT(config, '$.affection') IS NOT NULL"
            )
        )
    else:  # sqlite
        result = bind.execute(
            text(
                "SELECT json_extract(config, '$.affection') as affection FROM user_data WHERE json_extract(config, '$.affection') IS NOT NULL"
            )
        )

    bucket_counts: dict[int, int] = {}
    for row in result:
        affection = int(row[0]) if row[0] is not None else 41
        bucket = affection_bucket(affection)
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1

    # 批量插入直方图数据
    if bucket_counts:
        for bucket, cnt in bucket_counts.items():
            if dialect == "postgresql":
                bind.execute(
                    text("""
                        INSERT INTO affection_histogram (bucket, cnt)
                        VALUES (:bucket, :cnt)
                        ON CONFLICT (bucket) DO UPDATE SET cnt = EXCLUDED.cnt
                    """),
                    {"bucket": bucket, "cnt": cnt},
                )
            elif dialect == "mysql":
                bind.execute(
                    text("""
                        INSERT INTO affection_histogram (bucket, cnt)
                        VALUES (:bucket, :cnt)
                        ON DUPLICATE KEY UPDATE cnt = VALUES(cnt)
                    """),
                    {"bucket": bucket, "cnt": cnt},
                )
            else:  # sqlite
                bind.execute(
                    text("""
                        INSERT OR REPLACE INTO affection_histogram (bucket, cnt)
                        VALUES (:bucket, :cnt)
                    """),
                    {"bucket": bucket, "cnt": cnt},
                )

    # PostgreSQL: 安装 SQL 分桶函数和触发器
    if dialect == "postgresql":
        # 创建 SQL 版本的 affection_bucket 函数
        op.execute(
            text("""
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
        """)
        )

        # 创建触发器函数
        op.execute(
            text("""
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
        """)
        )

        op.execute(
            text("""
            DROP TRIGGER IF EXISTS trg_update_affection_histogram ON user_data;
        """)
        )

        op.execute(
            text("""
            CREATE TRIGGER trg_update_affection_histogram
            AFTER INSERT OR UPDATE OF config OR DELETE ON user_data
            FOR EACH ROW
            EXECUTE FUNCTION update_affection_histogram();
        """)
        )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    dialect = bind.dialect.name

    # PostgreSQL: 删除触发器和函数
    if dialect == "postgresql":
        op.execute(
            text("DROP TRIGGER IF EXISTS trg_update_affection_histogram ON user_data;")
        )
        op.execute(text("DROP FUNCTION IF EXISTS update_affection_histogram;"))
        op.execute(text("DROP FUNCTION IF EXISTS affection_bucket;"))

    # 删除索引和表
    op.drop_index("ix_affection_histogram_bucket", table_name="affection_histogram")
    op.drop_table("affection_histogram")
