"""Apply the club's updated public catalog and group timetable."""

import json
from datetime import time

import sqlalchemy as sa
from alembic import op

revision = "a16c7f8e4b30"
down_revision = "f23a9e5c40d1"
branch_labels = None
depends_on = None


def upgrade():
    db = op.get_bind()
    org = db.execute(sa.text(
        "SELECT id FROM sport_organizations WHERE slug = 'sparta'"
    )).scalar_one_or_none()
    if org is None:
        return

    db.execute(sa.text("UPDATE sport_organizations SET description = :description WHERE id = :org"), {
        "org": org,
        "description": "Томский клуб единоборств для детей от 5 лет, подростков и взрослых. "
                       "Грэпплинг, боевое дзю-дзютцу, БЖЖ, ММА и самооборона.",
    })

    irk = "Иркутский тракт, 68"
    frunze = "пр. Фрунзе, 115/3"
    uchebnaya = "ул. Учебная, 40 · корпус СибГМУ"
    venues = {}
    for address, photo, description in (
        (irk, "irk", "Здесь занимаются младшая группа и взрослые. По субботам проходит открытый ковёр."),
        (frunze, "fr", "Аким Давыдов ведёт занятия по грэпплингу, ММА и БЖЖ."),
        (uchebnaya, "ssmu", "Дмитрий Давыдов ведёт занятия по самообороне, грэпплингу и БЖЖ."),
    ):
        venues[address] = db.execute(sa.text(
            "UPDATE sport_venues SET description = :description, photo_url = :photo "
            "WHERE organization_id = :org AND address = :address RETURNING id"
        ), {"org": org, "address": address, "description": description,
            "photo": f"/photos/gyms/{photo}-club-1.jpg"}).scalars().first()

    dmitry = "Давыдов Дмитрий Михайлович"
    akim = "Давыдов Аким Дмитриевич"
    bogdan = "Дмитриев Богдан Дмитриевич"
    mikhail = "Рыбка Михаил Дмитриевич"
    coaches = {}
    for order, (name, role, tags, experience, photo, bio) in enumerate((
        (dmitry, "Руководитель клуба и старший тренер", "Иркутский тракт · СибГМУ", "7 дан · тренирует с 2002 года", "dmitry",
         "Возглавляет клуб и областные федерации боевого дзю-дзютцу и грэпплинга. "
         "Исполнительный директор областной федерации спортивной борьбы. Среди его воспитанников "
         "чемпионы и призёры российских и международных соревнований."),
        (akim, "Тренер", "Фрунзе · грэпплинг, ММА и БЖЖ", "Синий пояс, 2 кю · CJJIF", "akim",
         "Преподаёт самооборону и боевое дзю-дзютцу на кафедре физического воспитания и спорта ТУСУРа."),
        (bogdan, "Тренер", "Иркутский тракт · ММА и грэпплинг", "Чёрный пояс, 1 дан по джиу-джитсу", "bogdan",
         "Победитель первенств России по грэпплингу и панкратиону, призёр первенства мира по ММА. "
         "КМС по грэпплингу, панкратиону, ММА и рукопашному бою. "
         "Вице-президент Федерации КЭМПО Томской области."),
        (mikhail, "Тренер младшей группы", "Иркутский тракт · дети от 5 лет", "Синий пояс, 2 кю · тренирует с 2023 года", "mikhail",
         "Призёр чемпионата мира и всероссийских соревнований по грэпплингу, победитель и призёр СФО. "
         "Призёр и победитель городских и областных соревнований по ММА и городских соревнований "
         "по боевому дзю-дзютцу. КМС по грэпплингу и борьбе на поясах «Кореш»."),
    )):
        values = {"org": org, "name": name, "role": role, "tags": tags, "experience": experience,
                  "bio": bio, "photo": f"/photos/coaches/{photo}-club.jpg", "order": order}
        coach_id = db.execute(sa.text(
            "UPDATE sport_coaches SET role = :role, tags = :tags, experience = :experience, "
            "bio = :bio, photo_url = :photo WHERE organization_id = :org AND name = :name RETURNING id"
        ), values).scalars().first()
        if coach_id is None:
            coach_id = db.execute(sa.text(
                "INSERT INTO sport_coaches (organization_id, name, role, tags, experience, bio, photo_url, sort_order) "
                "VALUES (:org, :name, :role, :tags, :experience, :bio, :photo, :order) RETURNING id"
            ), values).scalar_one()
        coaches[name] = coach_id

    for code, days, start, end, coach, address, discipline in (
        ("mr-irk", [1, 3, 5], time(18, 45), time(20), mikhail, irk, "Младшая группа"),
        ("dm-irk", [1, 3, 5], time(20), time(21, 30), dmitry, irk, "Самооборона и грэпплинг"),
        ("bd-irk", [2, 4, 6], time(20), time(21), bogdan, irk, "ММА и грэпплинг"),
        ("dm-sat", [6], time(18), time(20), dmitry, irk, "Открытый ковёр"),
        ("ak-fr", [1, 3, 5], time(19, 45), time(21, 15), akim, frunze, "Грэпплинг, ММА и БЖЖ"),
        ("dm-ssmu", [2, 4], time(19), time(20, 30), dmitry, uchebnaya, "Самооборона, грэпплинг и БЖЖ"),
    ):
        db.execute(sa.text(
            "INSERT INTO sport_trainings "
            "(organization_id, code, weekdays, start_time, end_time, coach, gym, discipline, coach_id, venue_id) "
            "VALUES (:org, :code, CAST(:days AS json), :start, :end, :coach, :gym, :discipline, :coach_id, :venue_id) "
            "ON CONFLICT (organization_id, code) DO UPDATE SET "
            "weekdays = EXCLUDED.weekdays, start_time = EXCLUDED.start_time, end_time = EXCLUDED.end_time, "
            "coach = EXCLUDED.coach, gym = EXCLUDED.gym, discipline = EXCLUDED.discipline, "
            "coach_id = EXCLUDED.coach_id, venue_id = EXCLUDED.venue_id, discipline_id = NULL"
        ), {"org": org, "code": code, "days": json.dumps(days), "start": start, "end": end,
            "coach": coach, "gym": address, "discipline": discipline, "coach_id": coaches[coach],
            "venue_id": venues[address]})

    for order, (code, name, price, unit, details) in enumerate((
        ("trial", "Пробная тренировка", 0, "первое занятие", ["Познакомьтесь с тренером и группой"]),
        ("base", "12 тренировок", 5000, "12 занятий", ["Групповые занятия по расписанию"]),
        ("unlimited", "Безлимит", 8000, "абонемент", ["Групповые занятия без ограничения числа посещений"]),
        ("family", "Семейный абонемент", 8000, "на двоих", ["Для родителя и ребёнка или двоих детей из одной семьи"]),
        ("individual", "Индивидуальная тренировка", 1500, "1 занятие", ["Время согласует администратор клуба"]),
        ("certificate", "Подарочный сертификат", 1500, "3 занятия", ["Три тренировки в подарок"]),
    )):
        db.execute(sa.text(
            "INSERT INTO sport_membership_plans (organization_id, code, name, price, unit, items, sort_order) "
            "VALUES (:org, :code, :name, :price, :unit, CAST(:items AS json), :order) "
            "ON CONFLICT (organization_id, code) DO UPDATE SET name = EXCLUDED.name, "
            "price = EXCLUDED.price, unit = EXCLUDED.unit, items = EXCLUDED.items, sort_order = EXCLUDED.sort_order"
        ), {"org": org, "code": code, "name": name, "price": price, "unit": unit,
            "items": json.dumps(details, ensure_ascii=False), "order": order})


def downgrade():
    # Catalog entries can acquire booking and payment history after publication.
    # Preserve the data and its references when rolling back application code.
    pass
