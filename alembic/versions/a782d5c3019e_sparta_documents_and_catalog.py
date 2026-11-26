"""Manage Sparta documents and update public discipline terminology."""

import sqlalchemy as sa
from alembic import op

revision = "a782d5c3019e"
down_revision = "e81937d52fa0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sport_organizations", sa.Column("site_documents", sa.JSON(), nullable=True))
    op.add_column("sport_organizations", sa.Column("training_agreements", sa.JSON(), nullable=True))
    op.add_column("sport_bookings", sa.Column("training_agreement", sa.JSON(), nullable=True))

    db = op.get_bind()
    org = db.scalar(sa.text("SELECT id FROM sport_organizations WHERE slug = 'sparta'"))
    if org is None:
        return
    for table, fields in (
        ("sport_organizations", ("description",)),
        ("sport_coaches", ("role", "tags", "bio", "experience")),
        ("sport_venues", ("description",)),
        ("sport_disciplines", ("name", "description")),
        ("sport_trainings", ("discipline",)),
        ("sport_bookings", ("requested_discipline",)),
        ("sport_gallery_images", ("alt_text",)),
    ):
        key = "id" if table == "sport_organizations" else "organization_id"
        assignments = ", ".join(
            f"{field} = regexp_replace(regexp_replace({field}, :brazilian, 'джиу-джитсу', 'g'), '[Бб][Жж][Жж]', 'джиу-джитсу', 'g')"
            for field in fields
        )
        db.execute(sa.text(f"UPDATE {table} SET {assignments} WHERE {key} = :org"), {
            "org": org, "brazilian": r"[Бб]разильск[а-яё]+[[:space:]]+[Дд]жиу[-‑– ][Дд]житсу",
        })
    db.execute(sa.text(
        "UPDATE sport_disciplines SET name = 'Джиу-джитсу (CJJIF)', "
        "photo_url = '/photos/disciplines/jiu-jitsu-club.webp', "
        "description = 'Джиу-джитсу по правилам CJJIF. На занятиях изучают технику в стойке и в партере.' "
        "WHERE organization_id = :org AND lower(name) IN ('джиу-джитсу', 'джиу-джитсу (cjjif)')"
    ), {"org": org})
    db.execute(sa.text(
        "UPDATE sport_disciplines SET photo_url = '/photos/disciplines/sambo-club.webp' "
        "WHERE organization_id = :org AND name IN ('Самбо', 'самбо', 'САМБО')"
    ), {"org": org})
    for name, role, rank in (
        ("Давыдов Дмитрий Михайлович", "Руководитель клуба · тренер по самообороне, грэпплингу и джиу-джитсу",
         "Black belt (чёрный пояс) 7 DAN CJJIF"),
        ("Давыдов Аким Дмитриевич", "Тренер по грэпплингу, ММА и джиу-джитсу", None),
        ("Рыбка Михаил Дмитриевич", None, "Синий пояс CJJIF · 2-й кю"),
    ):
        db.execute(sa.text(
            "UPDATE sport_coaches SET role = coalesce(:role, role), experience = coalesce(:rank, experience) "
            "WHERE organization_id = :org AND name = :name"
        ), {"org": org, "name": name, "role": role, "rank": rank})
    db.execute(sa.text(
        "UPDATE sport_venues SET description = 'Дмитрий Давыдов ведёт занятия по самообороне, грэпплингу и джиу-джитсу' "
        "WHERE organization_id = :org AND (address ~ '[Уу]чебная' OR name ~ '[Сс]иб[Гг][Мм][Уу]')"
    ), {"org": org})


def downgrade():
    op.drop_column("sport_bookings", "training_agreement")
    op.drop_column("sport_organizations", "training_agreements")
    op.drop_column("sport_organizations", "site_documents")
