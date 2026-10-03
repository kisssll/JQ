"""Движение витрины: лист снизу и единственный авторский переход.

Браузера в тестах нет, поэтому здесь проверяется КОНТРАКТ, а не картинка:
движение берётся из одной обёртки, выключатель движения один на весь сервис, а
авторский момент в клиентском мире ровно один (docs/design.md).

Проверка именно такая потому, что сломать это легко и незаметно: достаточно
позвать animate() из 'motion' напрямую в одном файле — и prefers-reduced-motion
на этом экране перестанет работать, а на остальных останется.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "static" / "src" / "js"
UI_CSS = ROOT / "static" / "src" / "css" / "ui.css"
SHEET_JS = JS / "sheet.js"
MAIN_JS = JS / "main.js"


# ─────────────────────── одна точка движения ───────────────────────

#: Файлы витрины — то, что переписано этим заходом. Остальной фронт
#: (лендинги, панель) живёт по своим правилам до своего захода: например
#: master-landing.js до сих пор сам спрашивает prefers-reduced-motion и
#: показывает секции по прокрутке.
_SHOWCASE_JS = ("sheet.js", "card-transition.js", "salon-detail.js", "salons.js")


def _front_js():
    for p in JS.rglob("*.js"):
        if p.name == "motion.js":
            continue
        yield p


def _showcase_js():
    for name in _SHOWCASE_JS:
        yield JS / name


def test_only_motion_js_talks_to_the_animation_library():
    """Пресеты пружин, правило прерывания и prefers-reduced-motion решены в
    motion.js один раз. Импорт 'motion' в другом файле — это второй набор
    значений и второй (забытый) выключатель."""
    offenders = [
        p.relative_to(ROOT) for p in _front_js()
        if re.search(r"""from\s+['"]motion['"]""", p.read_text())
    ]
    assert not offenders, f"движение мимо motion.js: {offenders}"


def test_nobody_re_implements_the_reduced_motion_query():
    """Запрос prefers-reduced-motion в JS живёт только в motion.js; в CSS —
    только в global.css (общее глушение) и в ui.css (правило перехода между
    документами, которое иначе не выключить)."""
    offenders = [
        p.relative_to(ROOT) for p in _showcase_js()
        if re.search(r"matchMedia\s*\(\s*['\"]\(prefers-reduced-motion", p.read_text())
    ]
    assert not offenders, f"свой запрос вместо prefersReducedMotion(): {offenders}"


# ─────────────────────── лист снизу ───────────────────────

def test_sheet_uses_the_apple_preset_and_the_shared_wrapper():
    src = SHEET_JS.read_text()
    assert "from './motion.js'" in src
    # Лист снизу: демпфирование 0.8, отклик 0.3 — пресет SPRING.sheet.
    assert "SPRING.sheet" in src
    assert "prefersReducedMotion" in src, "закрытие листа обязано работать и без движения"


def test_sheet_can_be_closed_without_the_gesture():
    """Жест — не единственный способ: его не видно с клавиатуры и его нет у
    человека с тачпадом. Проверяем сам обработчик клика, а не присутствие слова
    в файле: ``data-sheet-close`` встречается ещё и в жесте, и поломка «убрать
    закрытие кнопкой» прошла бы мимо."""
    src = SHEET_JS.read_text()
    click = src[src.index("document.addEventListener('click'"):]
    click = click[:click.index("\ndocument.addEventListener")]
    assert "data-sheet-close" in click, "крестик и затемнение не закрывают лист"
    assert "close()" in click
    assert "'Escape'" in src
    assert "sheet-open" in src


def test_sheet_locks_the_page_under_it_and_returns_focus():
    src = SHEET_JS.read_text()
    assert "overflow" in src, "страница под листом должна не прокручиваться"
    assert "lastOpener" in src, "фокус обязан вернуться на кнопку, открывшую лист"


def test_the_gesture_lives_on_the_head_not_on_the_body():
    """Жест на теле листа отобрал бы у него прокрутку, и список свободных окон
    стало бы невозможно пролистать."""
    src = SHEET_JS.read_text()
    assert "head.addEventListener('pointerdown'" in src
    assert "body.addEventListener('pointerdown'" not in src


def test_sheet_and_card_transition_are_registered_in_the_bundle():
    src = MAIN_JS.read_text()
    assert "./sheet.js" in src
    assert "./card-transition.js" in src


# ─────────────────── один авторский момент ───────────────────

def test_the_authored_moment_is_the_card_to_page_transition():
    css = UI_CSS.read_text()
    assert "@view-transition" in css
    assert "view-transition-group(salon-mark)" in css


def test_the_transition_is_off_for_reduced_motion():
    """Правило навигации объявлено внутри no-preference — иначе переход между
    документами остаётся включённым у того, кто попросил убрать анимацию, и
    отдельного выключателя для него нет."""
    css = UI_CSS.read_text()
    block = css[css.index("@media (prefers-reduced-motion: no-preference)"):]
    assert block.index("@view-transition") < block.index("}", block.index("@view-transition"))


def test_the_showcase_has_no_scroll_reveal_animations():
    """Анимаций появления секций по прокрутке нет: они первым делом съедают
    ощущение скорости на телефоне (docs/design.md)."""
    for name in ("home.css", "salons.css", "salon-detail.css"):
        src = (ROOT / "static" / "src" / "css" / name).read_text()
        assert "IntersectionObserver" not in src
        assert "@keyframes fadeInUp" not in src
    for name in ("salon-detail.js", "salons.js", "card-transition.js"):
        src = (JS / name).read_text()
        assert "IntersectionObserver" not in src, name


# ─────────────────── телефонные грабли ───────────────────

def _unguarded_hovers(css: str) -> list[str]:
    """Правила :hover, не завёрнутые в ОТКРЫТЫЙ сейчас @media (hover: hover).

    Считаем вложенность фигурных скобок, а не «последний встреченный @media»:
    закрывшийся выше блок (hover: hover) иначе прикрывал бы собой всё, что идёт
    за ним, и проверка молча перестала бы что-либо находить.
    """
    # Комментарии убираем первыми: в них встречается и слово «:hover», и
    # «hover: hover», и без этого проверка ловит сама себя.
    css = re.sub(r"/\*.*?\*/", " ", css, flags=re.S)
    stack: list[bool] = []          # True — это @media (hover: hover)
    guarded = 0
    out: list[str] = []
    i = 0
    while i < len(css):
        ch = css[i]
        if ch == "{":
            head = css[max(0, css.rfind("}", 0, i)):i]
            head = head[head.rfind(";") + 1:]
            m = re.search(r"@media([^{]*)", head)
            if m:
                is_hover = "hover: hover" in m.group(1)
                stack.append(is_hover)
                guarded += is_hover
            else:
                if ":hover" in head and not guarded:
                    out.append(head.strip().splitlines()[-1].strip())
                stack.append(False)
        elif ch == "}" and stack:
            guarded -= stack.pop()
        i += 1
    return out


@pytest.mark.parametrize("name", ["ui.css", "home.css", "salons.css", "salon-detail.css"])
def test_hover_is_guarded_by_the_pointer_query(name):
    """Залипший hover после тапа: на телефоне :hover остаётся до следующего
    касания в другом месте. Поэтому все наведения — внутри (hover: hover)."""
    src = (ROOT / "static" / "src" / "css" / name).read_text()
    # Берём только то, что написано в этом заходе: ниже в файлах лежат чужие
    # блоки, оставленные дословно (партнёрский баннер, шаги лендингов, метки
    # админки) — у их страниц свои заходы.
    mine = src.split("НИЖЕ — ЧУЖОЕ")[0]
    unguarded = _unguarded_hovers(mine)
    assert not unguarded, f"{name}: наведение без (hover: hover): {unguarded}"


def test_pinned_controls_respect_the_safe_area():
    """Закреплённая снизу кнопка и лист без safe-area попадают под полосу жеста
    «домой», и запись оказывается в сантиметре от промаха. Оба компонента
    объявлены в ui.css — там же и запас."""
    src = UI_CSS.read_text()
    dock = src[src.index(".r-dock {"):]
    assert "safe-area-inset-bottom" in dock.split("}")[0]
    panel = src[src.index(".r-sheet__panel {"):]
    assert "safe-area-inset-bottom" in panel.split("}")[0]


def test_the_page_leaves_room_for_the_pinned_button():
    """Иначе подвал и последний отзыв оказываются под кнопкой записи."""
    src = (ROOT / "static" / "src" / "css" / "salon-detail.css").read_text()
    assert "padding-bottom: calc(var(--control-h)" in src
