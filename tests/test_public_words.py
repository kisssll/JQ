"""Словарь публичных подписей: соло и команда через ОДИН реестр.

Восемь из девяти салонов на проде — один человек, и витрина, которая говорит
«записаться в салон», разговаривает не с тем, кто за ней стоит (решение 0011,
п. 13). Здесь проверяется и сам словарь, и то, что страницы берут подписи из
него, а не из тернарников по месту.
"""
import re
from pathlib import Path

import pytest

from app.models.models import SalonPanelMode
from app.services import public_words as pw

ROOT = Path(__file__).resolve().parent.parent


# ─────────────────────────── падеж ───────────────────────────

@pytest.mark.parametrize("name,expected", [
    ("Анна", "Анне"),
    ("Ольга", "Ольге"),
    ("Жанна", "Жанне"),
    ("Мария", "Марии"),
    ("Юлия", "Юлии"),
    ("Настя", "Насте"),
    ("Дарья", "Дарье"),
    ("Илья", "Илье"),
    ("Игорь", "Игорю"),
    ("Алексей", "Алексею"),
    ("Иван", "Ивану"),
    ("Матвей", "Матвею"),
    # Беглая гласная: общее правило дало бы «Павелу» и «Левy».
    ("Павел", "Павлу"),
    ("Лев", "Льву"),
    ("Пётр", "Петру"),
    # Женское на «-ь» склоняется в «-и», и по виду слова его не отличить от
    # мужского «Игорь» — поэтому оно в исключениях.
    ("Любовь", "Любови"),
    # Несклоняемые остаются как есть — это и есть верный дательный.
    ("Нино", "Нино"),
])
def test_dative_declines_russian_given_names(name, expected):
    assert pw.dative(name) == expected


@pytest.mark.parametrize("value", ["Hair Studio", "ООО", "SPA", "", "A", "12"])
def test_dative_refuses_what_is_not_a_russian_name(value):
    """При любом сомнении — пустая строка: «Записаться к Hair Studio» хуже,
    чем «Записаться» без имени."""
    assert pw.dative(value) == ""


def test_first_name_takes_only_the_first_word():
    assert pw.first_name("Анна Ивановна Смирнова") == "Анна"
    assert pw.first_name("   ") == ""


# ─────────────────────────── соло или команда ───────────────────────────

def test_solo_needs_exactly_one_master():
    """Двое мастеров — уже не «записаться к Анне»: так мы спрятали бы Бориса."""
    assert pw.solo_from_facts(SalonPanelMode.SOLO, 2) is False
    assert pw.solo_from_facts(SalonPanelMode.SOLO, 0) is False
    assert pw.solo_from_facts(SalonPanelMode.SOLO, 1) is True


def test_team_mode_with_one_master_is_solo_only_if_he_is_the_owner():
    """Объявленный режим — ответ владельца; структурная проверка нужна тем, кто
    панель не открывал (прежняя развилка в guest_booking именно такой и была)."""
    assert pw.solo_from_facts(SalonPanelMode.TEAM, 1, False) is False
    assert pw.solo_from_facts(SalonPanelMode.TEAM, 1, True) is True


def test_solo_accepts_the_mode_as_a_string_from_sql():
    """Каталог собирает страницу одним SQL-запросом и объектов салона не держит."""
    assert pw.solo_from_facts("SOLO", 1) is True
    assert pw.solo_from_facts("team", 1, False) is False


# ─────────────────────────── сам словарь ───────────────────────────

#: Места, которых в одном из режимов нет вовсе. Пустая строка здесь — это
#: ответ «такого раздела не бывает», а не забытый перевод: у соло-мастера нет
#: раздела «Мастера», показывать одного человека списком людей значит называть
#: его организацией.
_ONE_SIDED = {"team_title": "solo"}


def test_every_place_has_both_variants():
    for key in pw.KEYS:
        solo = pw.word(key, solo=True, name="Анне")
        team = pw.word(key, solo=False, name="Салон")
        missing = _ONE_SIDED.get(key)
        if missing != "solo":
            assert solo, f"нет соло-варианта: {key}"
        if missing != "team":
            assert team, f"нет командного варианта: {key}"
        if missing == "solo":
            assert not solo, f"{key} объявлен односторонним, но соло-вариант есть"


def test_unknown_key_is_silent():
    assert pw.word("нет-такого", solo=True) == ""


def test_name_template_falls_back_to_the_wordless_variant():
    """Имя могло не определиться (падеж не дался) — подпись обязана остаться
    осмысленной, а не оборваться на «Записаться к »."""
    assert pw.word("book_cta", solo=True, name="") == "Записаться"
    assert "{name}" not in pw.word("book_cta", solo=True, name="")


# ──────────────────── один реестр, а не копии по файлам ────────────────────

_SHOWCASE = [
    "app/web/pages/salon_detail.py",
    "app/web/pages/master_detail.py",
    "app/web/pages/salons.py",
    "app/web/pages/guest_booking.py",
]


@pytest.mark.parametrize("path", _SHOWCASE)
def test_showcase_pages_do_not_keep_their_own_solo_branch(path):
    """Прецедент, из-за которого словарь и появился: ``confirmer = "мастер" if
    solo else "салон"`` жил прямо в разметке страницы записи. Второй такой
    развилки быть не должно — иначе через месяц они разойдутся."""
    src = (ROOT / path).read_text()
    assert not re.search(r'"мастер"\s+if\s+\w+\s+else\s+"салон"', src), path
    assert not re.search(r'if\s+solo\s+else\s+f?"Запись', src), path


def test_guest_booking_takes_its_words_from_the_registry():
    src = (ROOT / "app/web/pages/guest_booking.py").read_text()
    assert "words_for(" in src
    assert 'w("confirmer")' in src
