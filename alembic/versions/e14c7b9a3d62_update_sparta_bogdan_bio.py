"""Update Bogdan Dmitriev's Sparta coach profile."""

from alembic import op
import sqlalchemy as sa


revision = "e14c7b9a3d62"
down_revision = "8732df4060f1"
branch_labels = None
depends_on = None

NEW_BIO = (
    "Я Дмитриев Богдан Дмитриевич, учусь на педагога физической культуры. "
    "Кандидат в мастера спорта по грэпплингу, панкратиону, рукопашному бою и ММА. "
    "Финалист первенства мира по грэпплингу, бронзовый призёр первенства мира по ММА. "
    "Победитель и призёр первенств России по грэпплингу, панкратиону и ММА. "
    "Многократный победитель первенств Сибирского федерального округа и всероссийских "
    "турниров по грэпплингу, панкратиону, ММА и рукопашному бою. "
    "Вице-президент Федерации КЭМПО. Чёрный пояс, 1-й дан."
)
OLD_BIO = (
    "Победитель первенств России по грэпплингу и панкратиону, призёр первенства мира по ММА. "
    "Кандидат в мастера спорта по грэпплингу, панкратиону, ММА и рукопашному бою. "
    "Вице-президент Федерации КЭМПО Томской области."
)


def upgrade():
    op.execute(sa.text(
        "UPDATE sport_coaches SET bio = :bio "
        "WHERE organization_id IN (SELECT id FROM sport_organizations WHERE slug = 'sparta') "
        "AND name = :name"
    ).bindparams(bio=NEW_BIO, name="Дмитриев Богдан Дмитриевич"))


def downgrade():
    op.execute(sa.text(
        "UPDATE sport_coaches SET bio = :bio "
        "WHERE organization_id IN (SELECT id FROM sport_organizations WHERE slug = 'sparta') "
        "AND name = :name AND bio = :current_bio"
    ).bindparams(bio=OLD_BIO, name="Дмитриев Богдан Дмитриевич", current_bio=NEW_BIO))
