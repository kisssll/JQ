"""Состав шагов тура и решение «показывать ли его» (решение 0008, п. 4–6).

Проверяется без базы и без HTTP: build() и decide() работают на значениях. Это
то место, где тур может тихо соврать — повести человека в раздел, которого у
него нет, или запуститься во второй раз, — поэтому проверок здесь больше, чем
на саму полосу.
"""
import pytest

from app.models.models import SalonPanelMode
from app.services import panel_guide, panel_sections, panel_tour


class _Salon:
    """Салон как значение: build() не трогает базу."""

    def __init__(self, mode=SalonPanelMode.SOLO, sections=None):
        self.panel_mode = mode
        self.panel_sections = sections


def _visible(salon):
    """Что видно в меню, когда прав хватает на всё."""
    return panel_sections.ordered_keys(salon)


def _steps(salon, visible=None):
    return panel_tour.build(salon, visible_keys=visible or _visible(salon))


def _tabs(steps):
    return [s.tab for s in steps if s.tab]


# ───────────────────── состав шагов в соло и в команде ─────────────────────

def test_solo_tour_has_prologue_three_acts_and_a_finale():
    steps = _steps(_Salon(SalonPanelMode.SOLO))
    acts = []
    for s in steps:
        if s.act not in acts:
            acts.append(s.act)
    assert acts == [
        panel_tour.ACT_PROLOGUE, panel_tour.ACT_VISIBLE,
        panel_tour.ACT_CHOSEN, panel_tour.ACT_WATCH, panel_tour.ACT_FINALE,
    ]
    assert steps[0].act == panel_tour.ACT_PROLOGUE
    assert steps[-1].act == panel_tour.ACT_FINALE


def test_solo_tour_does_not_mention_team_only_sections():
    """В соло «Аналитики», «Зарплат», «Себестоимости» и «Склада» нет в панели —
    водить по ним нельзя, даже рассказом."""
    steps = _steps(_Salon(SalonPanelMode.SOLO))
    for absent in ("analytics", "payroll", "cost", "warehouse"):
        assert absent not in _tabs(steps)


def test_team_tour_is_longer_than_solo_and_includes_analytics():
    solo = _steps(_Salon(SalonPanelMode.SOLO))
    team = _steps(_Salon(SalonPanelMode.TEAM))
    assert "analytics" in _tabs(team)
    assert len(team) > len(solo)


def test_the_core_path_to_the_feed_is_in_order():
    """Акт «чтобы вас было видно» — это порядок действий, а не набор ссылок.

    В команде: салон → мастера → услуги → расписание → тариф. В соло вкладки
    «Редактировать салон» нет, её содержимое в «Моей карточке мастера», и
    раздел занимает ДВА шага — по одному на группу настроек (решение 0009,
    дополнение 02.10). Порядок от этого не меняется: сначала о себе, потом
    услуги, график и тариф."""
    team = [s for s in _steps(_Salon(SalonPanelMode.TEAM))
            if s.act == panel_tour.ACT_VISIBLE]
    assert [s.tab for s in team] == ["edit", "employees", "services", "schedule", "billing"]

    solo = [s for s in _steps(_Salon(SalonPanelMode.SOLO))
            if s.act == panel_tour.ACT_VISIBLE]
    assert [s.tab for s in solo] == [
        "employees", "employees", "services", "schedule", "billing",
    ]
    assert [s.anchor for s in solo[:2]] == [
        panel_tour.ANCHOR_CARD_PUBLIC, panel_tour.ANCHOR_CARD_WORK,
    ]


def test_every_step_has_a_text():
    for mode in (SalonPanelMode.SOLO, SalonPanelMode.TEAM):
        for step in _steps(_Salon(mode)):
            assert step.text.strip(), step.key


def test_solo_master_card_step_speaks_about_himself():
    """В соло «Сотрудники» — это «Моя карточка мастера», и реплика другая."""
    solo = [s for s in _steps(_Salon(SalonPanelMode.SOLO)) if s.tab == "employees"]
    team = {s.tab: s for s in _steps(_Salon(SalonPanelMode.TEAM))}
    assert solo[0].text != team["employees"].text
    assert solo[0].text == panel_guide.tour_line("employees", solo=True)
    assert solo[1].text == panel_guide.tour_line("employees-work", solo=True)


def test_the_solo_tour_still_tells_what_the_vanished_section_told():
    """Самая тихая дыра переноса (решение 0009, дополнение 02.10): шаг про
    «Редактировать салон» в соло исчезает сам, потому что build() фильтрует по
    видимым разделам. Вместе с ним ушло бы всё, что он рассказывал.

    Проверка на СОДЕРЖАНИЕ, а не на наличие шага: тест «тур не ведёт в
    выключенный раздел» здесь зелёный и при пустом туре."""
    said = " ".join(s.text for s in _steps(_Salon(SalonPanelMode.SOLO))).lower()
    for must in ("имя", "фото", "адрес", "город", "телефон", "час", "ссылк", "qr"):
        assert must in said, f"соло-тур больше не рассказывает про «{must}»"


def test_the_solo_tour_shows_where_the_door_to_team_mode_is():
    """Переключатель режима — единственный выход из соло, и тур обязан про него
    сказать: раздел, в котором он живёт, теперь выглядит как «моя карточка»."""
    said = " ".join(s.text for s in _steps(_Salon(SalonPanelMode.SOLO))).lower()
    assert "режим работы" in said and "команда" in said


def test_the_solo_finale_does_not_name_the_vanished_section():
    """Финал «что есть ещё» не имеет права звать в раздел, которого нет."""
    finale = [s for s in _steps(_Salon(SalonPanelMode.SOLO))
              if s.act == panel_tour.ACT_FINALE][0]
    assert "Редактировать салон" not in finale.text
    label = panel_sections.label("edit", SalonPanelMode.TEAM)
    assert label not in finale.text


# ─────────────────── тур не ведёт туда, чего у человека нет ───────────────────

def test_tour_never_leads_into_a_section_turned_off_by_the_owner():
    """Владелец убрал «Модели» и «Отзывы» из панели — шагов про них нет."""
    kept = [k for k in panel_sections.ALL_KEYS if k not in ("models", "reviews")]
    salon = _Salon(SalonPanelMode.TEAM, sections=kept)
    steps = _steps(salon)
    assert "models" not in _tabs(steps)
    assert "reviews" not in _tabs(steps)
    # и акт «чтобы выбирали вас» не исчез целиком — в нём остались «Акции»
    assert "promos" in _tabs(steps)


def test_tour_never_leads_into_a_section_closed_by_permissions():
    """У участника может не быть права на раздел: в меню его нет, значит и в
    туре быть не должно — visible_keys уже учитывает права."""
    salon = _Salon(SalonPanelMode.TEAM)
    visible = [k for k in _visible(salon) if k not in ("billing", "analytics", "models")]
    steps = _steps(salon, visible)
    for absent in ("billing", "analytics", "models"):
        assert absent not in _tabs(steps)


def test_every_step_tab_is_visible():
    """Общая страховка: ни один шаг не ведёт за пределы меню."""
    salon = _Salon(SalonPanelMode.TEAM, sections=["overview", "services", "schedule",
                                                  "records", "billing", "edit"])
    visible = _visible(salon)
    for step in _steps(salon, visible):
        assert step.tab is None or step.tab in visible, step.key


def test_an_act_that_lost_all_its_sections_disappears_whole():
    """Если владелец убрал всё из акта «чтобы выбирали вас», пустого акта с
    нулём шагов в туре не остаётся."""
    kept = [k for k in panel_sections.ALL_KEYS
            if k not in ("models", "reviews", "promos")]
    steps = _steps(_Salon(SalonPanelMode.TEAM, sections=kept))
    assert panel_tour.ACT_CHOSEN not in {s.act for s in steps}


def test_step_keys_are_unique_and_short_enough_for_the_column():
    """Ключ шага лежит в users.panel_tour_step (varchar 40)."""
    for mode in (SalonPanelMode.SOLO, SalonPanelMode.TEAM):
        keys = [s.key for s in _steps(_Salon(mode))]
        assert len(keys) == len(set(keys))
        assert all(len(k) <= 40 for k in keys)


def test_finale_lists_the_sections_the_tour_skipped():
    """Финал «что есть ещё» перечисляет разделы, по которым не водили, — и
    только те, что у салона есть."""
    team = _steps(_Salon(SalonPanelMode.TEAM))
    finale = [s for s in team if s.act == panel_tour.ACT_FINALE][0]
    assert "Склад" in finale.text and "Зарплаты" in finale.text
    solo_finale = [s for s in _steps(_Salon(SalonPanelMode.SOLO))
                   if s.act == panel_tour.ACT_FINALE][0]
    assert "Склад" not in solo_finale.text


# ─────────────────────── переходы между шагами ───────────────────────

def test_next_and_prev_walk_the_whole_tour():
    steps = _steps(_Salon(SalonPanelMode.SOLO))
    key = steps[0].key
    walked = [key]
    while True:
        nxt = panel_tour.next_key(steps, key)
        if nxt is None:
            break
        key = nxt
        walked.append(key)
    assert walked == [s.key for s in steps]
    assert panel_tour.prev_key(steps, steps[0].key) is None
    assert panel_tour.prev_key(steps, steps[1].key) == steps[0].key


def test_skipping_an_act_lands_on_the_first_step_of_the_next_one():
    steps = _steps(_Salon(SalonPanelMode.SOLO))
    first_visible = [s for s in steps if s.act == panel_tour.ACT_VISIBLE][0]
    target = panel_tour.skip_act_key(steps, first_visible.key)
    assert target is not None
    landed = [s for s in steps if s.key == target][0]
    assert landed.act == panel_tour.ACT_CHOSEN
    # пропуск последнего акта — конец тура, а не выход в никуда
    last = steps[-1]
    assert panel_tour.skip_act_key(steps, last.key) is None


def test_an_unknown_or_vanished_step_key_falls_back_to_the_first_step():
    """Владелец убрал раздел, на шаге которого стоял тур: шага больше нет, и
    поднять тур надо на существующем, а не упасть."""
    steps = _steps(_Salon(SalonPanelMode.SOLO))
    assert panel_tour.resolve_step(steps, "no-such-step").key == steps[0].key
    assert panel_tour.resolve_step(steps, None).key == steps[0].key
    assert panel_tour.resolve_step(steps, steps[3].key).key == steps[3].key


# ─────────────────────── кому и когда показывать ───────────────────────

_DEFAULT = object()


def _decide(**kw):
    steps = kw.pop("steps", _DEFAULT)
    if steps is _DEFAULT:
        steps = _steps(_Salon(SalonPanelMode.SOLO))
    params = dict(
        steps=steps, requested=None, stored_step=None, started=False, done=False,
        can_manage=True, already_working=False,
    )
    params.update(kw)
    return panel_tour.decide(**params)


def test_autostart_fires_once_for_the_owner():
    first = _decide()
    assert first.step is not None and first.start_now
    # второй заход: запуск уже был — полоса сама не всплывает
    again = _decide(started=True, stored_step=first.step.key)
    assert again.step is None
    assert again.invite_step is not None, "но вернуться на том же шаге предлагаем"


def test_no_tour_for_someone_who_cannot_change_the_salon():
    """Наёмный мастер и участник без manage_salon: почти все действия в туре
    ему недоступны, звать его некуда."""
    d = _decide(can_manage=False)
    assert d.step is None and d.invite_step is None and not d.start_now


def test_a_working_salon_is_invited_instead_of_being_dragged():
    """Решение 0008, п. 5: у кого всё работает и есть записи — тур сам не
    запускается, но приглашение есть."""
    d = _decide(already_working=True)
    assert d.step is None and not d.start_now
    assert d.invite_step is not None


def test_a_working_salon_still_gets_the_tour_when_it_asks():
    d = _decide(already_working=True, requested=panel_tour.REQUEST_ON)
    assert d.step is not None and d.start_now


def test_finished_tour_does_not_come_back_by_itself():
    steps = _steps(_Salon(SalonPanelMode.SOLO))
    d = _decide(steps=steps, started=True, done=True, stored_step=steps[-1].key)
    assert d.step is None and d.invite_step is None


def test_asking_for_a_step_shows_that_step_and_saves_it():
    steps = _steps(_Salon(SalonPanelMode.SOLO))
    d = _decide(steps=steps, started=True, stored_step=steps[0].key,
                requested=steps[4].key)
    assert d.step.key == steps[4].key
    assert d.save_step == steps[4].key


def test_resuming_picks_up_the_stored_step_not_the_first_one():
    """Это и есть «вернуться на том же»: шаг приходит из базы, а не из URL."""
    steps = _steps(_Salon(SalonPanelMode.SOLO))
    d = _decide(steps=steps, started=True, stored_step=steps[6].key,
                requested=panel_tour.REQUEST_ON)
    assert d.step.key == steps[6].key


def test_exit_keeps_the_step_and_hides_the_bar():
    steps = _steps(_Salon(SalonPanelMode.SOLO))
    d = _decide(steps=steps, started=True, stored_step=steps[3].key,
                requested=panel_tour.REQUEST_OFF)
    assert d.step is None, "полоса ушла"
    assert d.save_step is None, "шаг в базе не затёрт"
    assert d.invite_step is not None and d.invite_step.key == steps[3].key


def test_finishing_marks_done_and_closes_the_bar():
    steps = _steps(_Salon(SalonPanelMode.SOLO))
    d = _decide(steps=steps, started=True, stored_step=steps[-1].key,
                requested=panel_tour.REQUEST_DONE)
    assert d.step is None and d.finish_now
    assert d.invite_step is None


def test_restart_goes_back_to_the_first_step_and_clears_done():
    steps = _steps(_Salon(SalonPanelMode.SOLO))
    d = _decide(steps=steps, started=True, done=True, stored_step=steps[-1].key,
                requested=panel_tour.REQUEST_RESTART)
    assert d.step.key == steps[0].key
    assert d.save_step == steps[0].key
    assert d.clear_done


def test_restart_works_even_for_someone_who_never_started():
    d = _decide(requested=panel_tour.REQUEST_RESTART)
    assert d.step is not None and d.start_now


def test_the_bar_never_appears_without_steps():
    """Страховка: пустой состав шагов не должен поднимать полосу «Шаг 1 из 0».
    Сам build() пустым не бывает (пролог и финал есть всегда), но decide()
    обязан выдержать и это — он решает про показ, а не про состав."""
    d = _decide(steps=[])
    assert d.step is None and d.invite_step is None and not d.start_now


# ─────────────────────── реестр текстов ───────────────────────

def test_every_section_of_the_panel_has_a_tour_line():
    for key in panel_sections.ALL_KEYS:
        assert panel_guide.tour_line(key).strip(), key


def test_manual_sections_use_the_panel_labels():
    """Остальное про справочник — в tests/test_panel_manual.py; здесь остаётся
    связка с реестром, потому что подпись раздела у тура и у справочника одна
    и та же."""
    solo = {s.key: s.label for s in panel_guide.manual_sections(SalonPanelMode.SOLO)}
    assert solo["employees"] == "Моя карточка мастера"
    team = {s.key: s.label for s in panel_guide.manual_sections(SalonPanelMode.TEAM)}
    assert team["employees"] == "Сотрудники"


def test_sources_point_at_files_that_exist():
    """Ссылка «откуда взято» обязана переживать переносы кода."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[1]
    for claim, source in panel_guide.SOURCES.items():
        paths = re.findall(r"app/[\w/]+\.py", source)
        assert paths, claim
        for rel in paths:
            assert (root / rel).exists(), f"{claim}: нет {rel}"


def test_every_tour_line_build_can_ask_for_exists():
    """build() спрашивает реплики не только по ключам разделов: в соло у «Моей
    карточки мастера» их две. Пустая реплика дала бы полосу без текста."""
    for solo in (False, True):
        for key in panel_tour.line_keys(solo=solo):
            assert panel_guide.tour_line(key, solo=solo).strip(), (key, solo)


def test_tour_lines_fit_into_the_bar():
    """Реплика живёт в полосе внизу экрана, и на 375px она не может быть любой
    длины: на восьмой строке полоса занимает почти половину телефона, а текст
    начинает обрезаться. 300 знаков — семь строк на узком экране, проверено
    руками. Это не придирка к стилю, а рамка вёрстки: тексты правит владелец,
    и тест должен поймать реплику, которая в полосу не влезет."""
    for key in panel_guide.TOUR_KEYS:
        for solo in (False, True):
            line = panel_guide.tour_line(key, solo=solo)
            assert len(line) <= 300, f"{key} (solo={solo}): {len(line)} знаков"


#: Слова, которыми обещание объёма клиентов, выручки или срока обычно и
#: пишется. Список грубый намеренно: он не разбирает смысл, а ловит оборот.
FORBIDDEN_PROMISES = (
    "больше клиентов", "лучше, чем", "лучше чем", "гарантиру",
    "тысячи", "в разы", "вырастет", "окупится", "обязательно придут",
)


def test_no_forbidden_promises_in_the_tour_texts():
    """Обещания объёма клиентов, выручки и сроков запрещены (ч. 7 ст. 5 закона
    «О рекламе» и CLAUDE.local.md)."""
    for key in panel_guide.TOUR_KEYS:
        text = panel_guide.tour_line(key).lower() + panel_guide.tour_line(key, solo=True).lower()
        for word in FORBIDDEN_PROMISES:
            assert word not in text, f"{key}: «{word}»"


def test_no_forbidden_promises_in_the_manual_texts():
    """Та же защита на прозу справочника (заход 5). Раньше она покрывала только
    реплики тура, а описания длиннее реплик — обещание проще спрятать как раз
    в них. Сюда же попадают шаги «с чего начать»: это такой же текст панели."""
    for key in panel_guide.MANUAL_KEYS:
        for solo in (False, True):
            why, body = panel_guide.manual_text(key, solo=solo)
            text = (why + body).lower()
            for word in FORBIDDEN_PROMISES:
                assert word not in text, f"{key} (solo={solo}): «{word}»"

    # Тексты живого блока «Путь к первому клиенту» (решение 0010, п. 8) — под
    # той же защитой: они говорят про каталог и поиск, то есть ровно про то, где
    # обещание объёма клиентов и появляется.
    for solo in (False, True):
        items = list(panel_guide.check_items(solo=solo))
        items.append(panel_guide.check_review_item(solo=solo))
        texts = [t for _k, t, a, _r in items for t in (t, a)]
        texts += [t for _k, title, lead in panel_guide.check_groups()
                  for t in (title, lead)]
        texts += [p for _k, p in panel_guide.check_next(solo=solo)]
        texts.append(panel_guide.check_promo_text(solo=solo))
        for text in texts:
            for word in FORBIDDEN_PROMISES:
                assert word not in text.lower(), f"«{text[:40]}»: «{word}»"
