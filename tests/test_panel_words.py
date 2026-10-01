"""Словарь подписей панели: соло-вариант и командный (решение 0009, п. 6).

Проверяется без базы и без HTTP — ``word()`` работает на значениях. Смысл
проверок: словарь должен оставаться ОДНИМ реестром. Пустой вариант, забытая
пара или второй набор текстов рядом с panel_guide — это не стилистика, а то,
из-за чего подписи снова расползутся по файлам.
"""
import pathlib
import re

from app.models.models import SalonPanelMode
from app.services import panel_guide, panel_words


def test_every_place_has_both_variants():
    """Пара на каждое место. Пустая строка допустима только там, где вариант
    существует лишь в одном режиме, — и тогда это осознанное «промолчать», а не
    подстановка чужого текста."""
    for key in panel_words.KEYS:
        solo = panel_words.word(key, solo=True)
        team = panel_words.word(key, solo=False)
        assert isinstance(solo, str) and isinstance(team, str), key
        assert solo or team, f"{key}: пусты оба варианта"


def test_only_the_group_titles_are_solo_only():
    """Групп настроек в командном режиме нет вовсе (решение 0009, п. 2) — это
    единственные места, где командный вариант пуст намеренно. Любое новое
    пустое место тест заставит объяснить."""
    team_empty = {k for k in panel_words.KEYS if not panel_words.word(k, solo=False)}
    assert team_empty == {
        "group_public", "group_work", "card_basic_hint",
        "mode_switch_hint_solo_tail", "master_elsewhere_tail",
    }


def test_unknown_key_is_empty_not_an_exception():
    """Подпись, которой нет, не должна валить панель — и не должна подставлять
    чужую."""
    assert panel_words.word("no_such_place", solo=True) == ""
    assert panel_words.word("no_such_place", solo=False) == ""


def test_solo_variants_do_not_call_the_person_a_salon():
    """Ровно то, ради чего словарь и заведён."""
    allowed = {
        # Второй режим так и называется, и подсказка про него — про режимы.
        "mode_switch_hint_solo_tail",
        "master_elsewhere_tail",
    }
    for key in panel_words.KEYS - allowed:
        assert "алон" not in panel_words.word(key, solo=True).lower(), key


def test_team_variants_are_unchanged_wording():
    """Командный режим по смыслу не менялся: подписи в нём те же, что были до
    переноса. Сверяем несколько самых заметных — если кто-то поправит их
    «заодно», тест спросит, зачем."""
    w = panel_guide.words_for(SalonPanelMode.TEAM)
    assert w("card_basic_title") == "Основная информация"
    assert w("card_hours_title") == "Часы работы"
    assert w("hide_btn_off") == "Скрыть салон"
    assert w("delete_btn") == "Удалить салон"
    assert w("publish_btn") == "Опубликовать салон"
    assert w("header_title") == "Панель салона"


def test_words_for_picks_the_variant_by_mode():
    solo = panel_guide.words_for(SalonPanelMode.SOLO)
    team = panel_guide.words_for(SalonPanelMode.TEAM)
    assert solo("card_basic_title") == "О вас"
    assert team("card_basic_title") == "Основная информация"
    # Неизвестный режим (None из getattr на объекте без поля) — как команда:
    # так панель чужого салона не начнёт говорить с человеком «ты».
    assert panel_guide.words_for(None)("header_title") == "Панель салона"


def test_the_dictionary_enters_the_panel_through_one_door():
    """Решение 0009, дополнение 02.10: словарь не должен стать ВТОРЫМ реестром
    текстов панели рядом с panel_guide. Поэтому panel_guide его импортирует и
    отдаёт наружу — проверяем, что это так и осталось."""
    assert panel_guide.word is panel_words.word
    assert panel_guide.words_for is panel_words.words_for


def test_no_panel_file_keeps_its_own_copy_of_a_forked_caption():
    """Страховка от возврата к тернарникам по файлам: подписи, у которых есть
    соло-вариант, не должны лежать строкой в разметке панели."""
    root = pathlib.Path(__file__).resolve().parents[1]
    watched = [
        "app/web/pages/business/dashboard.py",
        "app/web/pages/business/tabs/my_salon.py",
        "app/web/pages/business/tabs/employees.py",
        "app/web/pages/business/tabs/overview.py",
        "app/web/components/evening_deal.py",
    ]
    # Берём заметные подписи, которые раньше были зашиты в этих файлах.
    forked = [
        "Основная информация", "Часы работы салона", "Фото салона",
        "Скрыть салон", "Удалить салон", "Панель салона",
    ]
    for rel in watched:
        text = (root / rel).read_text()
        # Комментарии и докстринги не считаем — они объясняют, а не выводятся.
        code = "\n".join(
            line for line in text.splitlines() if not line.lstrip().startswith("#")
        )
        code = re.sub(r'"""', "", code)
        for caption in forked:
            assert f'>{caption}<' not in code, f"{rel}: «{caption}» зашита в разметке"
