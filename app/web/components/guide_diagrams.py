# app/web/components/guide_diagrams.py
"""Схемы-иллюстрации к инструкциям на /tariffs.

Текст инструкций объясняет шаги словами; схема показывает весь путь целиком,
чтобы человек до чтения понимал, сколько шагов впереди и чем всё кончится.

Рисуем «от руки»: у прямых линий и ровных прямоугольников вид технической
документации, а здесь уместнее набросок. Неровность даёт _sketch_box —
детерминированный генератор, поэтому картинка одинакова при каждом рендере
(случайные отклонения меняли бы разметку между запросами и ломали бы кэш и
сравнение снимков).

Цвета — через currentColor и переменные темы: SVG инлайновый, CSS-переменные
в нём работают, поэтому схема переедет в тёмную тему вместе со страницей.
"""

# Отклонения в пикселях для «дрожащей» линии. Числа подобраны на глаз: больше
# 2.5 уже читается как кривизна, меньше 1 — незаметно.
_WOBBLE = (1.6, -1.2, 2.0, -1.8, 1.1, -2.2, 1.4, -1.5)


def _w(i: int) -> float:
    return _WOBBLE[i % len(_WOBBLE)]


def _sketch_box(x: float, y: float, w: float, h: float, seed: int = 0) -> str:
    """Прямоугольник со скруглением, нарисованный дрожащей линией.

    Каждая сторона — кривая Безье, отклоняющаяся от прямой на пару пикселей;
    углы срезаны радиусом r. Seed сдвигает выборку отклонений, чтобы соседние
    блоки не выглядели штампованными.
    """
    r = 10.0
    x2, y2 = x + w, y + h
    d = (
        f"M{x + r:.1f},{y:.1f} "
        f"Q{(x + x2) / 2:.1f},{y + _w(seed):.1f} {x2 - r:.1f},{y:.1f} "
        f"Q{x2:.1f},{y:.1f} {x2:.1f},{y + r:.1f} "
        f"Q{x2 + _w(seed + 1):.1f},{(y + y2) / 2:.1f} {x2:.1f},{y2 - r:.1f} "
        f"Q{x2:.1f},{y2:.1f} {x2 - r:.1f},{y2:.1f} "
        f"Q{(x + x2) / 2:.1f},{y2 + _w(seed + 2):.1f} {x + r:.1f},{y2:.1f} "
        f"Q{x:.1f},{y2:.1f} {x:.1f},{y2 - r:.1f} "
        f"Q{x + _w(seed + 3):.1f},{(y + y2) / 2:.1f} {x:.1f},{y + r:.1f} "
        f"Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} Z"
    )
    return f'<path class="gd-box" d="{d}"/>'


def _sketch_arrow(x: float, y: float, length: float = 34.0, seed: int = 0) -> str:
    """Стрелка между блоками: слегка провисающая линия и галочка-наконечник."""
    x2 = x + length
    dip = _w(seed)
    body = f'<path class="gd-arrow" d="M{x:.1f},{y:.1f} Q{x + length / 2:.1f},{y + dip:.1f} {x2:.1f},{y:.1f}"/>'
    head = (
        f'<path class="gd-arrow" d="M{x2 - 7:.1f},{y - 4.5:.1f} L{x2:.1f},{y:.1f} '
        f'L{x2 - 7:.1f},{y + 4.5:.1f}"/>'
    )
    return body + head


def _step(x: float, y: float, w: float, h: float, num: int, title: str, sub: str, seed: int) -> str:
    """Один шаг: номер в кружке, заголовок и уточнение под ним."""
    cx = x + w / 2
    return (
        f'{_sketch_box(x, y, w, h, seed)}'
        f'<circle class="gd-num-bg" cx="{x + 18:.1f}" cy="{y + 18:.1f}" r="11"/>'
        f'<text class="gd-num" x="{x + 18:.1f}" y="{y + 18:.1f}" '
        f'text-anchor="middle" dominant-baseline="central">{num}</text>'
        f'<text class="gd-title" x="{cx:.1f}" y="{y + h / 2 + 6:.1f}" text-anchor="middle">{title}</text>'
        f'<text class="gd-sub" x="{cx:.1f}" y="{y + h / 2 + 24:.1f}" text-anchor="middle">{sub}</text>'
    )


def _flow(steps: list[tuple[str, str]], title: str) -> str:
    """Горизонтальная цепочка шагов.

    Ширина блока фиксирована, ширина viewBox считается от числа шагов — так
    схема с четырьмя и с пятью шагами имеет одинаковые пропорции блоков, а не
    сплющенные под общий размер.
    """
    box_w, box_h, gap = 150.0, 96.0, 34.0
    pad = 6.0
    total_w = len(steps) * box_w + (len(steps) - 1) * gap + pad * 2
    total_h = box_h + pad * 2

    parts = []
    for i, (head, sub) in enumerate(steps):
        x = pad + i * (box_w + gap)
        parts.append(_step(x, pad, box_w, box_h, i + 1, head, sub, seed=i * 3))
        if i < len(steps) - 1:
            parts.append(_sketch_arrow(x + box_w + 7, pad + box_h / 2, gap - 14, seed=i))

    return (
        f'<figure class="gd-figure">'
        f'<div class="gd-scroll">'
        f'<svg class="gd-svg" viewBox="0 0 {total_w:.0f} {total_h:.0f}" '
        f'role="img" aria-label="{title}" style="width:{total_w:.0f}px">'
        f'{"".join(parts)}'
        f'</svg>'
        f'</div>'
        f'<figcaption class="gd-caption">{title}</figcaption>'
        f'</figure>'
    )


BOOKING_FLOW = _flow(
    [
        ("Выбрать салон", "по городу и услуге"),
        ("Выбрать услугу", "и мастера"),
        ("Выбрать время", "из свободных окон"),
        ("Записаться", "запись в «Мои записи»"),
    ],
    "Путь клиента: от поиска салона до записи",
)

SALON_FLOW = _flow(
    [
        ("Заявка", "название и адрес"),
        ("Заполнение", "услуги, мастера, часы"),
        ("Модерация", "1–2 рабочих дня"),
        ("Тариф", "14 дней бесплатно"),
        ("Публикация", "салон виден клиентам"),
    ],
    "Путь салона: от заявки до публикации",
)
