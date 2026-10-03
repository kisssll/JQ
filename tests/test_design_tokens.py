"""Подложка: токены, контраст, шрифты и движение.

Эти проверки читают настоящие файлы CSS/JS, а не копию значений в тесте:
смысл в том, чтобы правка токена, которая роняет контраст или оставляет
страницу со ссылкой на несуществующую переменную, падала на CI, а не
обнаруживалась глазами через месяц.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOKENS = ROOT / "static" / "src" / "css" / "design-tokens.css"
GLOBAL_CSS = ROOT / "static" / "src" / "css" / "global.css"
FONTS_CSS = ROOT / "static" / "src" / "css" / "fonts.css"
MOTION_JS = ROOT / "static" / "src" / "js" / "motion.js"

# Каталоги, которые к отдаваемому фронту отношения не имеют.
_SKIP = ("node_modules", "/.git/", "static/dist", "/.venv/", "__pycache__",
         "docs/reference", "/alembic/", "/tests/")


def _source_files():
    for p in ROOT.rglob("*"):
        s = str(p)
        if any(x in s for x in _SKIP) or not p.is_file():
            continue
        if p.suffix in (".py", ".css", ".js"):
            yield p


def _declared(block: str) -> dict[str, str]:
    return {m.group(1): m.group(2).strip()
            for m in re.finditer(r"^\s*(--[a-z0-9-]+)\s*:\s*([^;]+);", block, re.M)}


def _theme_blocks() -> tuple[dict[str, str], dict[str, str]]:
    """Светлая палитра и тёмная (тёмная наследует светлую и переопределяет часть)."""
    text = TOKENS.read_text()
    light_src = text.split(':root[data-theme="dark"]')[0]
    dark_src = text.split(':root[data-theme="dark"]')[1]
    light = _declared(light_src)
    dark = dict(light)
    dark.update(_declared(dark_src))
    return light, dark


# ---------------------------------------------------------------- контраст

def _srgb(c: float) -> float:
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(hexcolor: str) -> float:
    h = hexcolor.lstrip("#")
    if len(h) == 8:      # #rrggbbaa — альфу для контраста не учитываем
        h = h[:6]
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _srgb(r) + 0.7152 * _srgb(g) + 0.0722 * _srgb(b)


def contrast(fg: str, bg: str) -> float:
    a, b = _luminance(fg), _luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


# Пары «текст на фоне», которые реально встречаются в интерфейсе.
# Минимум 4,5:1 — обычный текст и плейсхолдеры; 3:1 — крупный (от 24px).
# Таблица значений — в отчёте по заходу и в docs/design.md.
PAIRS_NORMAL = [
    ("--color-heading", "--color-background"),
    ("--color-heading", "--color-surface"),
    ("--color-heading", "--color-surface-alt"),
    ("--color-heading", "--color-surface-2"),
    ("--color-heading", "--color-secondary"),
    ("--color-body", "--color-surface"),
    ("--color-body", "--color-surface-alt"),
    ("--color-muted", "--color-surface"),
    ("--color-muted", "--color-surface-alt"),
    ("--color-muted", "--color-surface-2"),
    # Подпись на залитой акцентом кнопке: именно здесь в тёмной теме был
    # белый на розовом с 2,64:1.
    ("--color-btn-text", "--color-accent"),
    ("--color-btn-text", "--color-accent-hover"),
    ("--color-accent", "--color-surface"),
    # Акцентный ТЕКСТ на подкрашенной подложке берётся из accent-hover:
    # сам accent на ней проваливается ниже 4,5.
    ("--color-accent-hover", "--color-surface-alt"),
    ("--color-accent-hover", "--color-accent-light"),
    ("--color-accent-hover", "--color-secondary"),
    ("--color-danger", "--color-surface"),
    ("--color-danger", "--color-danger-light"),
    ("--color-success", "--color-surface"),
    ("--color-success", "--color-success-light"),
    ("--color-warning", "--color-surface"),
    ("--color-warning", "--color-warning-light"),
]


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_contrast_of_every_text_pair(theme):
    light, dark = _theme_blocks()
    palette = light if theme == "light" else dark
    bad = []
    for fg, bg in PAIRS_NORMAL:
        ratio = contrast(palette[fg], palette[bg])
        if ratio < 4.5:
            bad.append(f"{fg} на {bg} = {ratio:.2f}:1 "
                       f"({palette[fg]} / {palette[bg]})")
    assert not bad, f"{theme}: ниже 4,5:1 — " + "; ".join(bad)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_accent_on_tinted_surface_needs_accent_hover(theme):
    """Правило, по которому в ui.css подписи на розовой подложке берут
    accent-hover: сам accent там не проходит. Если однажды accent станет
    темнее и правило станет лишним — этот тест об этом скажет."""
    light, dark = _theme_blocks()
    palette = light if theme == "light" else dark
    assert contrast(palette["--color-accent-hover"],
                    palette["--color-accent-light"]) >= 4.5


# ------------------------------------------------------------------ токены

# Префиксы наших токенов. Локальные переменные страниц (--ml-cta-bg,
# --readiness-rule, --i) под них не попадают и проверке не подлежат.
OUR_PREFIXES = (
    "--color-", "--page-gradient-", "--font-", "--text-", "--space-",
    "--radius-", "--shadow-", "--control-", "--ease-", "--duration-",
    "--leading-", "--tracking-", "--measure",
)


def test_no_page_uses_a_token_that_does_not_exist():
    """Главная ловушка ревизии токенов: удалили (или переименовали) значение,
    а var(--...) остался. CSS молча берёт запасной цвет или вовсе делает
    свойство невалидным — так в тёмной теме получался белый текст на белом.

    Ищем по всему репозиторию, включая f-строки в .py и шаблоны в .js.
    """
    light, _ = _theme_blocks()
    missing = {}
    for p in _source_files():
        text = p.read_text(errors="replace")
        # локальные объявления внутри самого файла — законный источник
        local = set(re.findall(r"(--[a-z0-9-]+)\s*:", text))
        for m in re.finditer(r"var\(\s*(--[a-z0-9-]+)", text):
            name = m.group(1)
            if not name.startswith(OUR_PREFIXES):
                continue
            if name in light or name in local:
                continue
            missing.setdefault(name, set()).add(p.relative_to(ROOT).as_posix())
    assert not missing, "ссылки на несуществующие токены: " + "; ".join(
        f"{k} ({', '.join(sorted(v))})" for k, v in sorted(missing.items()))


def test_dark_theme_overrides_every_colour_that_needs_it():
    """Токен, который в тёмной теме не переопределён, остаётся значением,
    посчитанным под белый лист. Так до этого захода жила семантика состояний:
    тёмно-зелёный «успех» на тёмном фоне.
    """
    light, dark = _theme_blocks()
    text = TOKENS.read_text()
    dark_src = text.split(':root[data-theme="dark"]')[1]
    overridden = set(_declared(dark_src))
    must = [k for k in light
            if k.startswith(("--color-", "--page-gradient-", "--shadow-"))]
    # Буквальные цвета, которые по смыслу не переворачиваются: «белый поверх
    # тёмного», «тёмный как таковой». --color-dark в тёмной теме красит
    # подпись на светло-розовой кнопке (overview.css) — перевернув его, мы
    # вернули бы белое по розовому с 2,6:1.
    allowed_same = {"--color-on-dark", "--color-on-dark-muted", "--color-dark"}
    not_overridden = sorted(set(must) - overridden - allowed_same)
    assert not not_overridden, (
        "цветовые токены без тёмного значения: " + ", ".join(not_overridden))


def test_scales_follow_the_grid():
    """Шкалы из docs/design.md, а не «на глаз»: отступы кратны 4, кегли —
    перечисленные ступени, радиусы — 8/12/16/пилюля."""
    light, _ = _theme_blocks()
    spaces = {k: v for k, v in light.items() if k.startswith("--space-")}
    assert spaces, "шкала отступов не объявлена"
    for name, value in spaces.items():
        px = int(value.rstrip("px"))
        assert px % 4 == 0, f"{name} = {value} не ложится на сетку 4px"
        assert name == f"--space-{px}", f"{name} не совпадает со своим значением"

    sizes = sorted(int(v.rstrip("px")) for k, v in light.items()
                   if k.startswith("--text-"))
    assert sizes == [12, 13, 14, 16, 18, 22, 28, 36, 48, 64]

    assert light["--radius-pill"] == "999px"
    for r in ("--radius-8", "--radius-12", "--radius-16"):
        assert light[r] == r.rsplit("-", 1)[1] + "px"


def test_input_scale_step_is_16px_exactly():
    """Поле мельче 16px заставляет iOS зумить страницу при фокусе. Ступень
    задана в пикселях намеренно: у html font-size 17px, и 1rem дал бы 17px —
    смысл ступени потерялся бы вместе с её именем."""
    light, _ = _theme_blocks()
    assert light["--text-16"] == "16px"


def test_shadows_have_offset_and_blur():
    """Тень без сдвига — цветной ореол, то есть декорация, а не глубина."""
    light, dark = _theme_blocks()
    for palette, theme in ((light, "light"), (dark, "dark")):
        for name in ("--shadow-1", "--shadow-2", "--shadow-3"):
            for layer in palette[name].split("),"):
                # «0 1px 2px rgba(...)» — сдвиг по X пишется без единицы,
                # поэтому ищем числа, а не только значения в px.
                head = layer.split("rgba")[0]
                nums = re.findall(r"(-?[\d.]+)(?:px)?", head)
                nums = [float(n) for n in nums if n not in ("", ".")]
                assert len(nums) >= 3, f"{theme}/{name}: не разобрать «{layer}»"
                offset_y, blur = nums[1], nums[2]
                assert offset_y > 0, f"{theme}/{name}: тень без сдвига вниз"
                assert blur > 0, f"{theme}/{name}: тень без размытия"


def test_cream_page_gradient_is_gone():
    """docs/design.md: «кремовые градиентные подложки уходят». Токены не
    удалены (на них ссылаются девять файлов), но сведены к базовому фону."""
    light, dark = _theme_blocks()
    assert light["--page-gradient-1"] == light["--color-background"]
    assert dark["--page-gradient-1"] == dark["--color-background"]
    for name in ("--page-gradient-2", "--page-gradient-3",
                 "--page-gradient-2-strong", "--page-gradient-3-strong"):
        for palette in (light, dark):
            assert palette[name].endswith("00"), f"{name} ещё красит страницу"


# ------------------------------------------------------------------- шрифт

def test_playfair_is_gone_and_prata_is_the_display_face():
    light, _ = _theme_blocks()
    # Именно ПЕРВОЕ семейство: запасное называется "Prata Fallback", и
    # проверка на вхождение подстроки прошла бы и с Playfair впереди.
    first = light["--font-heading"].split(",")[0].strip().strip('"')
    assert first == "Prata", light["--font-heading"]
    assert "Playfair" not in light["--font-heading"]
    # Ни одного объявления с Playfair не осталось — ни в токенах, ни в
    # f-строках страниц, ни в JS.
    for p in _source_files():
        text = p.read_text(errors="replace")
        for m in re.finditer(r"font-family[^;{}]*", text):
            assert "Playfair" not in m.group(0), f"{p}: {m.group(0)}"
        assert "Playfair+Display" not in text, p


def test_fonts_are_served_by_us_and_not_by_a_foreign_cdn():
    """Шрифт с fonts.gstatic.com отдаёт IP посетителя за границу, а в нашей
    Политике написано, что трансграничной передачи нет."""
    css = FONTS_CSS.read_text()
    # Ищем именно подключение, а не упоминание: в комментарии рядом с
    # @font-face записано, почему мы этот CDN не используем.
    for m in re.finditer(r"url\(([^)]+)\)", css):
        assert "gstatic" not in m.group(1) and "googleapis" not in m.group(1)
    assert "@import" not in css
    assert css.count("@font-face") >= 7
    for sub in ("prata-cyrillic", "inter-cyrillic"):
        assert sub in css
        assert (ROOT / "static" / "fonts" / "rumi" / f"{sub}.woff2").exists()
    # Без swap первый экран на медленной сети остаётся вообще без текста.
    assert css.count("font-display: swap") >= 7


def test_the_serif_is_only_used_large():
    """У Prata единственный вес и крупный рисунок: на 18–24px она читается
    как украшение интерфейса. Порог — 1.5rem при html{font-size:17px}."""
    root_px = 17.0
    small = []
    for p in (ROOT / "static" / "src" / "css").rglob("*.css"):
        if p.name == "design-tokens.css":
            continue
        text = p.read_text()
        for m in re.finditer(r"([^{}/;]+)\{([^{}]*)\}", text):
            body = m.group(2)
            if "var(--font-heading)" not in body:
                continue
            fs = re.search(r"font-size\s*:\s*([\d.]+)(rem|px)", body)
            if not fs:
                continue
            px = float(fs.group(1)) * (root_px if fs.group(2) == "rem" else 1)
            if px < 1.5 * root_px:
                small.append(f"{p.name}: {' '.join(m.group(1).split())} = {px:.0f}px")
    assert not small, "антиква в мелком кегле: " + "; ".join(small)


def test_the_serif_never_asks_for_a_weight_it_does_not_have():
    """font-weight: 700 на Prata это обещание, которого шрифт не выполнит:
    подделку жира мы запретили, и 700 всё равно нарисуется как 400, а
    незагруженная запасная Georgia честно станет жирной."""
    wrong = []
    for p in (ROOT / "static" / "src" / "css").rglob("*.css"):
        for m in re.finditer(r"([^{}/;]+)\{([^{}]*)\}", p.read_text()):
            body = m.group(2)
            if "var(--font-heading)" not in body:
                continue
            fw = re.search(r"font-weight\s*:\s*(\d+)", body)
            if fw and fw.group(1) != "400":
                wrong.append(f"{p.name}: {' '.join(m.group(1).split())} = {fw.group(1)}")
    assert not wrong, "вес, которого у антиквы нет: " + "; ".join(wrong)
    assert "font-synthesis-weight: none" in GLOBAL_CSS.read_text()


# ----------------------------------------------------------------- движение

def test_reduced_motion_is_switched_off_in_exactly_one_place():
    """Запрос, продублированный по файлам, рано или поздно расходится: один
    компонент перестаёт его читать, и никто не замечает. Сплошное правило
    («*», с !important) должно быть ровно одно и жить в global.css.

    Частные блоки на отдельных страницах остаются: они не выключают движение,
    а возвращают конечное состояние элементам, которые без анимации появления
    остались бы невидимыми.
    """
    blanket = []
    for p in (ROOT / "static" / "src" / "css").rglob("*.css"):
        text = p.read_text()
        for m in re.finditer(r"@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{",
                             text):
            # тело блока до парной скобки
            depth, i = 1, m.end()
            while depth and i < len(text):
                depth += (text[i] == "{") - (text[i] == "}")
                i += 1
            body = text[m.end():i]
            if re.search(r"^\s*\*\s*[,{]", body, re.M) and "!important" in body:
                blanket.append(p.name)
    assert blanket == ["global.css"], f"сплошных правил: {blanket}"


def test_motion_module_is_the_only_one_deciding_motion_policy():
    """Новый слой спрашивает систему через motion.js, а не сам: иначе пресеты
    пружин и правило reduced-motion разъедутся по вызовам."""
    assert "prefers-reduced-motion" in MOTION_JS.read_text()
    js = ROOT / "static" / "src" / "js"
    for name in ("ui-feedback.js", "guest-booking.js"):
        src = (js / name).read_text()
        assert "matchMedia" not in src, f"{name} спрашивает систему мимо motion.js"
        assert "./motion.js" in src, f"{name} двигает что-то не через motion.js"


def test_spring_presets_match_the_apple_values():
    """Перемещение 1.0/0.4, лист снизу 0.8/0.3, поворот 0.8/0.4.
    bounce = 1 − демпфирование, visualDuration = отклик."""
    src = MOTION_JS.read_text()
    for name, duration, bounce in (("move", "0.4", "0"),
                                   ("sheet", "0.3", "0.2"),
                                   ("turn", "0.4", "0.2")):
        m = re.search(rf"{name}:\s*\{{[^}}]*visualDuration:\s*([\d.]+),"
                      rf"\s*bounce:\s*([\d.]+)", src)
        assert m, f"пресет {name} не найден"
        assert m.group(1) == duration and m.group(2) == bounce, (
            f"{name}: {m.group(1)}/{m.group(2)} вместо {duration}/{bounce}")


def test_only_motion_one_was_added():
    """Единственная новая зависимость — Motion One."""
    import json
    deps = json.loads((ROOT / "package.json").read_text())["dependencies"]
    assert set(deps) == {"choices.js", "flatpickr", "motion"}


def test_no_hardcoded_white_label_on_an_accent_fill():
    """Главный источник провалов контраста в тёмной теме: правило, где
    заливка берётся из токена акцента, а подпись написана как #fff.
    В светлой теме всё хорошо, в тёмной акцент светлеет — и получается
    2,64:1 на кнопке, по которой и надо нажать.

    Подпись на заливке акцентом берётся ТОЛЬКО из --color-btn-text: он белый
    в светлой теме и тёмный в тёмной.
    """
    accent = re.compile(r"background(-color)?\s*:[^;]*var\(--color-(accent|primary)\b[^;]*;")
    white = re.compile(r"color\s*:\s*(#fff(?:fff)?|white)\s*(?:!important)?\s*;", re.I)
    bad = []
    for p in sorted((ROOT / "static" / "src" / "css").rglob("*.css")):
        for m in re.finditer(r"([^{}/;]+)\{([^{}]*)\}", p.read_text()):
            body = m.group(2)
            if accent.search(body) and white.search(body):
                bad.append(f"{p.name}: {' '.join(m.group(1).split())[:50]}")
    assert not bad, "белая подпись на заливке акцентом: " + "; ".join(bad)
