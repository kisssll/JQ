"""Вкладка «Инструкция» — справочник по панели (решение 0009, п. 7, заход 5).

Что здесь проверяется и почему именно это:

  1. **Справочник не врёт про состав панели.** Секция на каждый раздел,
     который у человека есть, и ни одной лишней. Прежний текст приходил к
     неточностям именно так: раздел переезжал, а описание оставалось.
  2. **Ни одной ссылки в раздел, которого у человека нет.** Такая ссылка не
     ошибка 404, а молчаливый возврат в «Обзор» — человек нажимает «где это»
     и оказывается там, откуда пришёл. Поймать это можно только проверкой
     ссылок, потому что страница при этом открывается нормально.
  3. **Якорь у каждой секции.** Ими делятся — в поддержке, в письме, из бота.
     Переименовали якорь молча — отвалились все разосланные ссылки.
  4. **Порядок совпадает с туром.** Человек, прошедший знакомство, ищет
     раздел там, где его запомнил. Совпадение держится тестом, а не памятью
     того, кто правит текст.
  5. **Запрещённых обещаний нет в прозе справочника.** Раньше эта защита
     покрывала только реплики тура; описания длиннее реплик, и обещание
     объёма клиентов или срока проще спрятать как раз в них.

Первая половина файла — без базы и без HTTP: manual_groups() работает на
значениях. Вторая половина открывает вкладку по-настоящему: разметку и ссылки
на значениях не проверить.
"""
import re

import pytest

from app.core.security import get_password_hash
from app.models.models import (
    Master, OWNER_DEFAULT_PERMISSIONS, Salon, SalonMember, SalonModerationStatus,
    SalonPanelMode, SalonRole, User, UserRole,
)
from app.services import panel_guide, panel_sections, panel_tour
from app.web.pages.business.tabs.instructions import render_instructions_tab


_MODES = (SalonPanelMode.SOLO, SalonPanelMode.TEAM)


def _checklist_texts(mode):
    """Все тексты живого блока «Путь к первому клиенту» одним списком.

    Нужен защитам ниже: пункты, их подписи действий, заголовки и фразы групп,
    строки группы 3 и врезка справочника. Без такого списка новый пункт попал
    бы в панель, не пройдя ни одной проверки.
    """
    solo = mode is SalonPanelMode.SOLO
    out = [panel_guide.CHECKLIST_TITLE, panel_guide.CHECK_VISIBLE_CLEAR,
           panel_guide.CHECK_PROMO_ACTION, panel_guide.check_promo_text(solo=solo),
           # Шапка свёртки (заход 6.5) — такой же текст панели, и под теми же
           # защитами: подпись кнопки и подпись линии прогресса.
           panel_guide.CHECK_IMPROVE, panel_guide.check_progress(3, 12)]
    items = list(panel_guide.check_items(solo=solo))
    items.append(panel_guide.check_review_item(solo=solo))
    for _key, text, action, _role in items:
        out += [text, action]
    for _key, title, lead in panel_guide.check_groups():
        out += [title, lead]
    for _key, phrase in panel_guide.check_next(solo=solo):
        out.append(phrase)
    return out


def _keys(mode, visible=None):
    return [s.key for s in panel_guide.manual_sections(mode, visible)]


# ═══════════════ 1. Состав секций ═══════════════

@pytest.mark.parametrize("mode", _MODES)
def test_the_manual_describes_every_section_of_the_mode(mode):
    """Ни лишних, ни пропущенных. «Инструкция» — единственное исключение:
    описывать открытую страницу самой этой странице незачем (тот же выбор
    сделан в финале тура, panel_tour._FINALE_SECTIONS)."""
    expected = {
        k for k in panel_sections.ALL_KEYS
        if k in panel_sections.available_keys(mode) and k != "instructions"
    }
    assert set(_keys(mode)) == expected


@pytest.mark.parametrize("mode", _MODES)
def test_every_section_key_appears_once(mode):
    keys = _keys(mode)
    assert len(keys) == len(set(keys))


def test_solo_manual_does_not_describe_the_vanished_section():
    """В соло «Редактировать салон» не существует (решение 0009, п. 2), и
    описывать его человеку, у которого этой вкладки нет, значит отправлять его
    искать несуществующий раздел."""
    assert "edit" not in _keys(SalonPanelMode.SOLO)
    assert "edit" in _keys(SalonPanelMode.TEAM)


def test_the_manual_follows_what_the_person_actually_sees():
    """Раздел, выключенный владельцем или закрытый правами, в справочник не
    попадает: ссылка «где это» вернула бы человека в «Обзор»."""
    visible = ["overview", "services", "schedule", "records", "billing"]
    assert _keys(SalonPanelMode.TEAM, visible) == [
        "services", "schedule", "billing", "overview", "records",
    ]


def test_an_empty_group_is_not_rendered_as_a_promise():
    """Заголовок «Пригодится позже» без единой секции — обещание, которого на
    странице нет."""
    visible = ["overview", "records"]
    groups = panel_guide.manual_groups(SalonPanelMode.TEAM, visible)
    assert [g.key for g in groups] == [panel_guide.GROUP_WATCH]


def test_visible_keys_cannot_resurrect_a_section_the_mode_has_not_got():
    """Ключ мог остаться в сохранённом JSON или прийти из старой закладки."""
    assert "edit" not in _keys(SalonPanelMode.SOLO, ["overview", "edit", "employees"])


# ═══════════════ 2. Названия и ссылки ═══════════════

@pytest.mark.parametrize("mode", _MODES)
def test_section_labels_come_from_the_panel_not_from_a_string(mode):
    for section in panel_guide.manual_sections(mode):
        assert section.label == panel_sections.label(section.key, mode)


def test_solo_calls_the_settings_section_the_way_the_panel_does():
    labels = {s.key: s.label for s in panel_guide.manual_sections(SalonPanelMode.SOLO)}
    assert labels["employees"] == "Моя карточка мастера"
    team = {s.key: s.label for s in panel_guide.manual_sections(SalonPanelMode.TEAM)}
    assert team["employees"] == "Сотрудники"


@pytest.mark.parametrize("mode", _MODES)
def test_every_target_leads_into_a_section_that_exists_in_this_mode(mode):
    available = panel_sections.available_keys(mode)
    for section in panel_guide.manual_sections(mode):
        assert section.targets, section.key
        for target in section.targets:
            assert target.tab in available, (section.key, target.tab)
            assert target.caption.strip(), (section.key, target.tab)


def test_the_solo_settings_section_links_to_both_of_its_groups():
    """В соло «Моя карточка мастера» вобрала настройки салона и состоит из двух
    групп. Описание говорит про обе, и вести в начало длинного раздела, когда
    речь про нижнюю половину, бессмысленно."""
    section = next(
        s for s in panel_guide.manual_sections(SalonPanelMode.SOLO)
        if s.key == "employees"
    )
    assert [t.anchor for t in section.targets] == [
        panel_sections.ANCHOR_CARD_PUBLIC, panel_sections.ANCHOR_CARD_WORK,
    ]
    assert [t.caption for t in section.targets] == [
        panel_guide.word("group_public", solo=True),
        panel_guide.word("group_work", solo=True),
    ]


@pytest.mark.parametrize("mode", _MODES)
def test_every_section_has_its_own_anchor(mode):
    slugs = [s.slug for s in panel_guide.manual_sections(mode)]
    assert len(slugs) == len(set(slugs))
    assert all(re.fullmatch(r"manual-[a-z]+", s) for s in slugs), slugs


# ═══════════════ 3. Согласие с туром ═══════════════

def test_the_manual_follows_the_tour():
    """Порядок справочника — это порядок тура, и совпадение не должно держаться
    на памяти того, кто правит текст. Группы 1–3 — акты тура, группа 4 — те
    разделы, про которые тур говорит одним списком в финале."""
    groups = {g.key: g for g in panel_guide.manual_groups(SalonPanelMode.TEAM)}
    for group_key, act in (
        (panel_guide.GROUP_VISIBLE, panel_tour.ACT_VISIBLE),
        (panel_guide.GROUP_CHOSEN, panel_tour.ACT_CHOSEN),
        (panel_guide.GROUP_WATCH, panel_tour.ACT_WATCH),
    ):
        assert [s.key for s in groups[group_key].sections] == \
            list(panel_tour._ACT_SECTIONS[act]), group_key
        assert groups[group_key].title == panel_tour.ACT_TITLES[act].capitalize()
    # У этой группы порядок внутри не путь, а просто перечисление — тур
    # называет те же разделы одной фразой финала, и сравнивать их по порядку
    # значило бы придираться к порядку слов в предложении.
    assert set(s.key for s in groups[panel_guide.GROUP_LATER].sections) == \
        set(panel_tour._FINALE_SECTIONS)


def test_the_manual_does_not_repeat_the_tour_word_for_word():
    """У тура задача провести, у справочника — ответить. Один и тот же текст в
    двух подачах означает, что одну из них не писали."""
    for mode, solo in ((SalonPanelMode.TEAM, False), (SalonPanelMode.SOLO, True)):
        for section in panel_guide.manual_sections(mode):
            line = panel_guide.tour_line(section.key, solo=solo)
            assert section.why.strip() != line.strip(), section.key
            assert line.strip() not in section.body, section.key


def test_the_manual_sends_the_path_to_the_overview_instead_of_printing_it():
    """Шагов «С чего начать» текстом здесь больше нет (решение 0010, п. 6).

    Прежний гайд перечислял путь словами и не знал, что половина уже сделана, —
    а живой блок в «Обзоре» знает. Два источника правды об одном и том же
    расходятся при первой правке, поэтому в справочнике осталась врезка.

    Якорь прежний: на #manual-start уже могли дать ссылку в поддержке.
    """
    for mode in _MODES:
        html = render_instructions_tab(salon_id=5, mode=mode)
        assert 'id="manual-start"' in html, mode
        assert panel_guide.CHECKLIST_TITLE in html, mode
        assert panel_guide.CHECK_PROMO_ACTION in html, mode
        assert "tab=overview" in html, mode
        # Прежний гайд ушёл целиком, а не остался рядом с врезкой.
        assert "С чего начать" not in html, mode
        assert "instructions-guide-steps" not in html, mode
        assert not hasattr(panel_guide, "start_steps"), \
            "реестр шагов остался — значит есть кому разойтись с блоком"


# ═══════════════ 4. Что текст себе не позволяет ═══════════════

def test_every_section_has_both_a_why_and_a_what():
    """Описание без «зачем» — это снова справка к программе."""
    for solo in (False, True):
        for key in panel_sections.ALL_KEYS:
            if key == "instructions":
                continue
            why, body = panel_guide.manual_text(key, solo=solo)
            assert why.strip(), (key, solo)
            assert body.strip(), (key, solo)
            assert not why.rstrip().endswith(":"), (key, solo)


def test_the_manual_is_not_written_as_a_program_help():
    """Прежняя структура «За что отвечает / Как пользоваться» — ровно то, что
    решение 0009 требует убрать: она не отвечает на вопрос «зачем мне это»."""
    for key in panel_guide.MANUAL_KEYS:
        for solo in (False, True):
            why, body = panel_guide.manual_text(key, solo=solo)
            text = (why + body).lower()
            for banned in ("за что отвечает", "как пользоваться"):
                assert banned not in text, f"{key} (solo={solo}): «{banned}»"


def test_the_manual_does_not_sell_the_panel_to_its_owner():
    """«Просто», «легко» и восклицания — язык рекламы своей же панели. Человек
    пришёл работать."""
    for key in panel_guide.MANUAL_KEYS:
        for solo in (False, True):
            why, body = panel_guide.manual_text(key, solo=solo)
            text = (why + body).lower()
            assert "!" not in text, key
            for banned in ("просто ", "легко", "удобно и"):
                assert banned not in text, f"{key} (solo={solo}): «{banned}»"


def test_no_section_promises_a_deadline_for_the_moderation():
    """Срока модерации в коде нет — решение принимает человек (SOURCES). Срок,
    которого продукт не гарантирует, запрещён ч. 7 ст. 5 закона «О рекламе»."""
    everything = " ".join(
        panel_guide.manual_text(k, solo=s)[0] + panel_guide.manual_text(k, solo=s)[1]
        for k in panel_guide.MANUAL_KEYS for s in (False, True)
    ) + " ".join(_checklist_texts(SalonPanelMode.SOLO)
                 + _checklist_texts(SalonPanelMode.TEAM))
    for banned in ("рабочих дня", "рабочих дней", "за сутки", "в течение дня"):
        assert banned not in everything.lower(), banned


def test_solo_texts_do_not_call_the_person_a_salon():
    """Проза справочника теперь под той же защитой, что и остальная панель
    (решение 0009, п. 10 снят). Разметочный тест ниже ловит страницу целиком,
    этот — сам реестр, чтобы причина падения была видна сразу."""
    # Только разделы, которые в соло существуют: у «Редактировать салон»
    # соло-варианта нет и быть не должно — этого раздела в соло нет вовсе.
    for key in panel_sections.available_keys(SalonPanelMode.SOLO):
        if key == "instructions":
            continue
        why, body = panel_guide.manual_text(key, solo=True)
        assert "алон" not in (why + body).lower(), key
    # Тексты живого блока — такой же текст панели (решение 0010, п. 8): защита
    # обязана покрывать и его, иначе новый пункт соврал бы первым.
    for text in _checklist_texts(SalonPanelMode.SOLO):
        assert "алон" not in text.lower(), text[:60]
    for _slug, title, lead, _keys in panel_guide._GROUPS:
        assert "алон" not in (title + lead).lower(), title


def test_sources_cover_the_claims_added_by_the_manual():
    """Каждое новое утверждение про возможности зарегистрировано. Тест грубый —
    он держит сам факт регистрации, а существование файлов проверяет
    test_panel_tour_steps.py::test_sources_point_at_files_that_exist."""
    for claim in (
        "«Пришёл» — не раньше чем за час до начала записи",
        "«Не пришёл» — только с начала записи",
        "отзыв возможен только после завершённой через Руми записи",
        "править отзыв может только его автор",
        "клиент появляется в списке после первой завершённой записи",
        "повышение тарифа — со следующего счёта, понижение раз в три месяца",
        "себестоимость — по фактическим списаниям со склада, а не по нормам",
        "анкеты моделей открываются после первой публикации поиска",
        "модерацию решает человек, автоматических проверок карточки нет",
    ):
        assert claim in panel_guide.SOURCES, claim


# ═══════════════ 5. Настоящая страница ═══════════════

async def _make_salon(db_session, phone, mode=SalonPanelMode.SOLO):
    async with db_session() as db:
        owner = User(
            phone=phone, full_name="Ольга Мастерова",
            hashed_password=get_password_hash("Testpass1"), role=UserRole.BUSINESS,
            is_active=True,
        )
        db.add(owner)
        await db.commit()
        await db.refresh(owner)

        salon = Salon(
            name="Ольга Мастерова", address="Томск, ул. Ленина, 1",
            phone="+73822000111", latitude=56.4, longitude=84.9, timezone="Asia/Tomsk",
            moderation_status=SalonModerationStatus.APPROVED, is_active=True,
            creator_id=owner.id, panel_mode=mode, guest_booking_enabled=True,
        )
        db.add(salon)
        await db.commit()
        await db.refresh(salon)
        db.add(SalonMember(
            salon_id=salon.id, user_id=owner.id, role=SalonRole.OWNER, is_creator=True,
            permissions=dict(OWNER_DEFAULT_PERMISSIONS), is_active=True,
        ))
        db.add(Master(
            user_id=owner.id, salon_id=salon.id, specialization="Маникюр",
            experience_years=3, rating=0.0, is_active=True,
        ))
        await db.commit()
        return owner.id, salon.id


async def _manual(client, salon_id: int) -> str:
    r = await client.get(
        f"/business/dashboard?salon_id={salon_id}&tab=instructions&tour=off"
    )
    assert r.status_code == 200
    return r.text.split('id="tab-instructions"', 1)[1].rsplit("</main>", 1)[0]


async def _login(client, phone):
    r = await client.post(
        "/api/v1/auth/login-web", data={"phone": phone, "password": "Testpass1"},
    )
    assert r.status_code == 302, r.text


async def test_the_page_has_an_anchor_for_every_section(client, db_session):
    _, salon_id = await _make_salon(db_session, "+79995581001")
    await _login(client, "+79995581001")
    html = await _manual(client, salon_id)

    # Ровно те разделы, которые у этого салона в меню: справочник описывает
    # панель человека, а не весь список возможных разделов режима.
    visible = panel_sections.ordered_keys(
        type("S", (), {"panel_mode": SalonPanelMode.SOLO, "panel_sections": None})()
    )
    sections = panel_guide.manual_sections(SalonPanelMode.SOLO, visible)
    assert sections
    for section in sections:
        assert f'id="{section.slug}"' in html, section.key
        assert f'href="#{section.slug}"' in html, f"{section.key}: нет в оглавлении"
    for group in panel_guide.manual_groups(SalonPanelMode.SOLO, visible):
        assert f'id="{group.slug}"' in html, group.key
    # И ни одного описания раздела, которого в этом меню нет.
    assert 'id="manual-warehouse"' not in html


async def test_every_link_on_the_page_leads_into_a_visible_section(client, db_session):
    """Самая тихая поломка справочника: ссылка открывается, но приводит в
    «Обзор», потому что раздела у человека нет."""
    _, salon_id = await _make_salon(db_session, "+79995581002")
    await _login(client, "+79995581002")
    html = await _manual(client, salon_id)

    tabs = set(re.findall(r"\?salon_id=\d+&tab=([a-z]+)", html))
    # overview приходит из ссылки «пройти знакомство заново»
    solo_visible = set(panel_sections.ordered_keys(
        type("S", (), {"panel_mode": SalonPanelMode.SOLO, "panel_sections": None})()
    ))
    assert tabs, "на странице нет ни одной ссылки в раздел"
    assert tabs <= solo_visible, tabs - solo_visible
    assert "edit" not in tabs


async def test_the_page_names_sections_the_way_the_panel_does(client, db_session):
    _, salon_id = await _make_salon(db_session, "+79995581003")
    await _login(client, "+79995581003")
    html = await _manual(client, salon_id)

    assert "Моя карточка мастера" in html
    assert panel_sections.LABELS["employees"] not in html, "соло-панель так не говорит"
    assert panel_sections.LABELS["edit"] not in html


async def test_the_page_is_not_an_accordion_any_more(client, db_session):
    """Пятнадцать закрытых ящиков — это не страница, которую читают сверху
    вниз (решение 0009, п. 7)."""
    _, salon_id = await _make_salon(db_session, "+79995581004")
    await _login(client, "+79995581004")
    html = await _manual(client, salon_id)

    assert "accordion-item" not in html
    assert "instructions-toc" in html


async def test_links_keep_the_tour_alive_while_it_runs(client, db_session):
    """Панель во время знакомства живая (решение 0008, п. 8): человек вправе
    уйти из справочника в раздел посреди шага, и полоса не должна исчезнуть."""
    _, salon_id = await _make_salon(db_session, "+79995581005")
    await _login(client, "+79995581005")

    r = await client.get(
        f"/business/dashboard?salon_id={salon_id}&tab=instructions&tour=on"
    )
    assert r.status_code == 200
    body = r.text.split('id="tab-instructions"', 1)[1].rsplit("</main>", 1)[0]
    hrefs = re.findall(r'href="(/business/dashboard\?salon_id=\d+&tab=[^"]+)"', body)
    assert hrefs
    assert all("tour=" in h for h in hrefs), [h for h in hrefs if "tour=" not in h]


async def test_the_team_page_keeps_the_salon_settings_section(client, db_session):
    _, salon_id = await _make_salon(db_session, "+79995581006", SalonPanelMode.TEAM)
    await _login(client, "+79995581006")
    html = await _manual(client, salon_id)

    assert 'id="manual-edit"' in html
    assert panel_sections.LABELS["edit"] in html
    assert "Моя карточка мастера" not in html


async def test_a_section_turned_off_by_the_owner_is_not_described(client, db_session):
    """Владелец убрал «Модели» из панели — справочник про них молчит, иначе он
    описывал бы вкладку, которой в меню нет."""
    _, salon_id = await _make_salon(db_session, "+79995581007", SalonPanelMode.TEAM)
    await _login(client, "+79995581007")

    kept = [k for k in panel_sections.ALL_KEYS if k != "models"]
    r = await client.post(
        "/api/v1/business/my-salon/panel-sections",
        json={"salon_id": salon_id, "sections": kept},
    )
    assert r.status_code == 200, r.text

    html = await _manual(client, salon_id)
    assert 'id="manual-models"' not in html
    assert "&tab=models" not in html
