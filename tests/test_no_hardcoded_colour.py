"""Цвет — только через токены.

До 21.10.2026 мимо токенов жили ~700 цветов (в CSS и в f-строках страниц):
в светлой теме это незаметно, а в тёмной даёт белое пятно или невидимый текст,
и каждая смена палитры стоила недели. Чистка сделана; этот тест не даёт
хардкоду вернуться — ни в CSS, ни в разметке внутри .py/.js.

Что допустимо буквально (и почему):
  • чёрный и белый с прозрачностью — тени, скримы под модальными окнами и
    плёнки на фотографиях: они затемняют/высветляют ЛЮБУЮ страницу одинаково;
  • фирменные цвета чужих брендов, которые мы обязаны воспроизвести как есть
    (Т-Банк: жёлтый и чернила на нём; Альфа-Банк, ВК, Яндекс ID);
  • письма (email_templates.py): почтовые клиенты не знают var();
  • значения для манифеста PWA и <meta name="theme-color">: браузер читает их
    до загрузки CSS.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

COLOUR = re.compile(r"#[0-9a-fA-F]{8}\b|#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b|"
                    r"rgba?\([^)]*\)|hsla?\([^)]*\)")

# Файлы, где буквальный цвет неизбежен.
EXEMPT_FILES = {
    "design-tokens.css",     # здесь цвета и объявляются
    "email_templates.py",    # почтовые клиенты не знают var()
}
# Строки, где буквальный цвет неизбежен (читает не CSS, а браузер/ОС).
EXEMPT_LINE = re.compile(r"theme[-_]color|background_color|color-scheme")
# Фирменные цвета партнёров и входа через чужой ID (чужой бренд не темизируем).
BRAND = {"#ffdd2d", "#1a1a1f", "#ee3424", "#0077ff", "#fc3f1d", "#000"}

_SKIP = ("node_modules", "/.git/", "static/dist", "/.venv/", "__pycache__",
         "docs/", "/alembic/", "/tests/")


def _scoped_files():
    for sub, suffixes in (("static/src/css", {".css"}), ("static/src/js", {".js"}),
                          ("app", {".py"})):
        for p in sorted((ROOT / sub).rglob("*")):
            s = str(p)
            if (not p.is_file() or p.suffix not in suffixes or p.name in EXEMPT_FILES
                    or any(x in s for x in _SKIP)):
                continue
            yield p


def _is_allowed(literal: str) -> bool:
    v = re.sub(r"\s+", "", literal.lower())
    if v in BRAND:
        return True
    m = re.fullmatch(r"rgba?\((\d+),(\d+),(\d+),[\d.]+\)", v)
    return bool(m) and (m.groups() == ("0", "0", "0") or m.groups() == ("255", "255", "255"))


def _violations(text: str) -> list[str]:
    bad = []
    for i, line in enumerate(text.splitlines(), 1):
        if EXEMPT_LINE.search(line):
            continue
        for m in COLOUR.finditer(line):
            # якорь/хэш не в CSS-значении: &#8203; &#x27; и href="#abc"
            before = line[max(0, m.start() - 2):m.start()]
            if m.group(0).startswith("#") and (before.endswith("&") or before[-1:] in ('"', "'", "/", "=")
                                               and re.search(r"(href|id|for|data-\w+)=[\"']?$", line[:m.start() + 0])):
                continue
            if not _is_allowed(m.group(0)):
                bad.append(f"{i}: {m.group(0)}")
    return bad


def test_no_literal_colour_outside_tokens():
    """Цвет страницы, панели и лендингов берётся из var(--color-*)."""
    report = {}
    for p in _scoped_files():
        bad = _violations(p.read_text(errors="replace"))
        if bad:
            report[p.relative_to(ROOT).as_posix()] = bad[:3]
    assert not report, "цвет мимо токенов: " + "; ".join(
        f"{f} → {', '.join(v)}" for f, v in sorted(report.items())[:15])


def test_guard_catches_a_hardcoded_colour():
    """Сам страж должен ловить нарушение, иначе он бесполезен."""
    assert _violations(".x { color: #cf3d78; }")
    assert _violations('<div style="background:#fff">')
    assert _violations(".x { box-shadow: 0 1px 2px rgba(54, 6, 27, .1); }")
    # допустимое страж пропускает
    assert not _violations(".x { box-shadow: 0 1px 2px rgba(0, 0, 0, .1); }")
    assert not _violations(".x { background: var(--color-accent); }")
    assert not _violations('<meta name="theme-color" content="#fff8f5">')


# --------------------------------------------------------------------- формы

# Литеральные радиусы, которые остаются: круг и нуль — формы, а не ступени.
_RADIUS = re.compile(
    r"border(?:-(?:top|bottom|start|end)-(?:left|right|start|end))?-radius\s*:\s*([^;}\"'{]+)")
_LENGTH = re.compile(r"(?<![\w.-])(\d*\.?\d+)(px|rem|em)\b")


def _radius_violations(text: str) -> list[str]:
    bad = []
    for m in _RADIUS.finditer(text):
        for ln in _LENGTH.finditer(m.group(1)):
            if float(ln.group(1)) != 0:
                bad.append(m.group(0).strip())
                break
    return bad


def test_radius_comes_from_the_three_step_scale():
    """Радиусы — 8 / 16 / 28 / пилюля (+ арка). Россыпь 10/12/14/18/20/22
    в дизайнерском прототипе — след Figma Make; в сервис она не переносится."""
    report = {}
    for p in _scoped_files():
        bad = _radius_violations(p.read_text(errors="replace"))
        if bad:
            report[p.relative_to(ROOT).as_posix()] = bad[:3]
    assert not report, "радиус мимо шкалы: " + "; ".join(
        f"{f} → {', '.join(v)}" for f, v in sorted(report.items())[:15])


def test_radius_guard_catches_a_loose_value():
    assert _radius_violations(".x { border-radius: 14px; }")
    assert _radius_violations('<div style="border-radius:0.75rem">')
    assert not _radius_violations(".x { border-radius: var(--radius-16); }")
    assert not _radius_violations(".x { border-radius: 50%; }")
    assert not _radius_violations(".x { border-radius: 0 0 var(--radius-16) var(--radius-16); }")
