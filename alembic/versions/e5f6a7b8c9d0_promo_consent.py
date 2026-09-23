"""Одно согласие на рекламные сообщения вместо узкой темы «вечерние окна»

Акции, конкурсы и подборка вечерних окон — одна рекламная тема и одно
согласие: спрашивать человека под каждую затею отдельно значит получить отказ
от всего сразу. Записей по прежней теме нет ни одной (проверено на проде
16.09.2026), поэтому переносить нечего — старое значение enum остаётся
неиспользованным.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c0
"""
from alembic import op

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Новое значение enum нельзя использовать в той же транзакции, где оно
    # добавлено, — выносим в autocommit-блок.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE consentdocument ADD VALUE IF NOT EXISTS 'ADS_PROMOS'")

    # Остатки прежней темы в настройках: ключ evening_deals и отметка
    # «спрашивали». Согласия по ним нет, поэтому просто убираем.
    op.execute("""
        UPDATE users
           SET tg_notify_prefs = (tg_notify_prefs::jsonb
                                  - 'evening_deals' - 'evening_deals_asked_at')::json
         WHERE tg_notify_prefs::jsonb ?| array['evening_deals', 'evening_deals_asked_at']
    """)


def downgrade() -> None:
    # Значение enum Postgres удалить не умеет; настройки назад не возвращаем —
    # согласий по ним не было.
    pass
