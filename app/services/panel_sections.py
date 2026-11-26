"""Какие разделы бизнес-панели есть у этого салона (решение 0007).

Одно место на все правила видимости разделов: набор по режиму, что владелец
может выключить, как пустой список превращается в «как по режиму» и как
нормализовать присланный формой выбор. Без этого модуля те же правила
пришлось бы держать в трёх файлах сразу — в панели, в настройках и в
эндпоинте сохранения — и они бы разъехались.

Чего здесь НЕТ намеренно:
  - прав: SALON_PERMISSION_KEYS решают, КТО из команды что может, и режимом не
    управляются. Итоговая видимость = «раздел включён» И «право есть»;
  - иконок и счётчиков: это оформление, оно остаётся в панели;
  - обращений к БД: функции работают со значениями, поэтому проверяются без
    базы и без HTTP.
"""
from typing import Iterable, List, Optional

from app.models.models import SalonPanelMode

# Канонический порядок разделов: с него салон начинает и к нему же возвращается,
# когда своего порядка нет. Дальше порядок принадлежит владельцу — он переставляет
# разделы в самой панели, и тогда список лежит в salons.panel_sections.
# Ключи совпадают с ?tab=<key> в панели.
ALL_KEYS: tuple = (
    "overview", "analytics", "schedule", "employees", "services", "payroll",
    "cost", "records", "warehouse", "models", "promos", "reviews", "crm",
    "billing", "edit", "instructions",
)

# Базовые подписи (без счётчиков — их дописывает панель).
LABELS = {
    "overview": "Обзор",
    "analytics": "Аналитика",
    "schedule": "Расписание",
    "employees": "Сотрудники",
    "services": "Услуги",
    "payroll": "Зарплаты",
    "cost": "Себестоимость",
    "records": "Записи",
    "warehouse": "Склад",
    "models": "Модели",
    "promos": "Акции",
    "reviews": "Отзывы",
    "crm": "Клиенты",
    "billing": "Тариф",
    "edit": "Редактировать салон",
    "instructions": "Инструкция",
}

# Чем раздел называется в соло-режиме, если называется иначе. «Сотрудники» там
# не про сотрудников: человек ходит туда завести САМОГО СЕБЯ мастером.
SOLO_LABELS = {
    "employees": "Моя карточка мастера",
}

# Без этих разделов панель не работает: «Обзор» — вход, «Услуги» и «Расписание»
# без которых нет записи, «Записи» — сами записи, «Тариф» — оплата (иначе салон
# молча выпадет из каталога), «Настройки» — единственный путь назад.
# Это набор командного режима; в соло место «Редактировать салон» занимает
# «Моя карточка мастера» — см. locked_keys().
LOCKED_KEYS = frozenset({"overview", "services", "schedule", "records", "billing", "edit"})

# Разделы, которых в режиме НЕ СУЩЕСТВУЕТ вовсе — не «выключены владельцем», а
# не имеют смысла. В соло такой раздел один: «Редактировать салон». Его
# содержимое переехало в «Мою карточку мастера» (решение 0009, п. 2), и второй
# раздел с теми же формами был бы не выбором, а двумя источниками правды.
# Поэтому ключ отбрасывается даже из сохранённого порядка и не предлагается к
# возврату в режиме редактирования панели.
_UNAVAILABLE = {
    SalonPanelMode.SOLO: frozenset({"edit"}),
    SalonPanelMode.TEAM: frozenset(),
}

# Чем в этом режиме дополняется LOCKED_KEYS. В соло выключить «Мою карточку
# мастера» нельзя, и это не вкусовщина: в ней живёт переключатель режима —
# единственная дверь из «работаю один» в «у меня команда» (решение 0009, п. 3).
# Спрятав раздел, человек запер бы себя в соло навсегда и не смог бы нанять
# мастера.
_LOCKED_EXTRA = {
    SalonPanelMode.SOLO: frozenset({"employees"}),
    SalonPanelMode.TEAM: frozenset(),
}

# «Работаю один»: из доступного набора убраны разделы, которые существуют только
# при наличии штата — аналитика, зарплаты, себестоимость, склад. «Модели»
# оставлены намеренно (решение владельца: отличительная черта сервиса).
_SOLO_HIDDEN = frozenset({"analytics", "payroll", "cost", "warehouse"})

_DEFAULTS = {
    SalonPanelMode.SOLO: frozenset(ALL_KEYS) - _SOLO_HIDDEN - _UNAVAILABLE[SalonPanelMode.SOLO],
    SalonPanelMode.TEAM: frozenset(ALL_KEYS),
}


def _mode_or_team(mode) -> SalonPanelMode:
    return mode if mode in _DEFAULTS else SalonPanelMode.TEAM


def default_keys(mode: SalonPanelMode) -> frozenset:
    """Набор разделов, который даёт сам режим, без правок владельца."""
    return _DEFAULTS[_mode_or_team(mode)]


def unavailable_keys(mode: SalonPanelMode) -> frozenset:
    """Разделы, которых в этом режиме не существует вовсе."""
    return _UNAVAILABLE[_mode_or_team(mode)]


def available_keys(mode: SalonPanelMode) -> frozenset:
    """Разделы, которые в этом режиме вообще бывают.

    Шире default_keys: сюда входит и то, что владелец может включить сам
    (склад в соло, например). Но не входит то, чего в режиме нет, — такой
    раздел не вернуть ни формой, ни правкой JSON.
    """
    return frozenset(ALL_KEYS) - unavailable_keys(mode)


def locked_keys(mode: SalonPanelMode) -> frozenset:
    """Разделы, которые в этом режиме нельзя выключить."""
    m = _mode_or_team(mode)
    return (LOCKED_KEYS | _LOCKED_EXTRA[m]) & available_keys(m)


# Якоря на группы внутри раздела настроек соло-режима (решение 0009, п. 2).
# Те же строки стоят в разметке раздела (tabs/employees.py) и нужны трём
# читателям сразу: шагам тура, действиям блока готовности и ссылкам «где это»
# в справочнике. Лежат здесь, а не в panel_tour, потому что panel_tour
# импортирует panel_guide, а справочнику они нужны тоже — из panel_guide в
# panel_tour пути нет, в panel_sections есть у обоих.
ANCHOR_CARD_PUBLIC = "panel-card-public"
ANCHOR_CARD_WORK = "panel-card-work"


def settings_key(mode: SalonPanelMode) -> str:
    """Раздел, в котором в этом режиме лежат настройки салона.

    Одно место на все ссылки «иди поправь это»: действия блока готовности,
    редирект /business/my-salon, подсказки в справочнике. В соло настройки
    живут в «Моей карточке мастера», в команде — в «Редактировать салон».
    """
    return "employees" if mode is SalonPanelMode.SOLO else "edit"


def ordered_keys(salon) -> List[str]:
    """Разделы салона по порядку — так, как их расставил владелец.

    Пустое salon.panel_sections означает «как по режиму»: тогда берём
    канонический порядок. Иначе порядок из списка — это и есть настройка,
    сделанная в панели, и приводить его к каноническому нельзя.

    Список чиним, а не доверяем: в JSON могли остаться переименованный раздел,
    потерянный обязательный или «Обзор» не на первом месте. Панель обязана
    открыться при любом содержимом столбца.
    """
    stored = getattr(salon, "panel_sections", None)
    mode = getattr(salon, "panel_mode", None) or SalonPanelMode.TEAM
    if not stored:
        return [k for k in ALL_KEYS if k in default_keys(mode)]
    return _repair(stored, mode)


def _repair(requested: Iterable[str], mode: SalonPanelMode) -> List[str]:
    """Присланный порядок → порядок, который панель точно выдержит.

    Неизвестные ключи, повторы и разделы, которых в этом режиме не бывает,
    отбрасываем; обязательные дописываем в конец (в начало нельзя: это сдвинуло
    бы порядок владельца), «Обзор» ставим первым — он вход в панель и место,
    куда уводит скрытая ссылка.

    Режим нужен не для красоты: в соло «Редактировать салон» не существует, и
    если он остался в сохранённом JSON (список пережил смену режима, кто-то
    поправил столбец руками), раздел нельзя поднимать обратно — его содержимое
    уже лежит в «Моей карточке мастера».
    """
    available = available_keys(mode)
    result: List[str] = []
    for key in requested:
        if key in LABELS and key in available and key not in result:
            result.append(key)
    result += [k for k in ALL_KEYS if k in locked_keys(mode) and k not in result]
    return ["overview"] + [k for k in result if k != "overview"]


def enabled_keys(salon) -> frozenset:
    """Включённые разделы салона.

    Отвечает о том же списке, что ordered_keys, — иначе раздел появился бы в
    меню и не открывался (или наоборот).
    """
    return frozenset(ordered_keys(salon))


def is_enabled(salon, key: str) -> bool:
    return key in enabled_keys(salon)


def is_solo(salon) -> bool:
    return getattr(salon, "panel_mode", None) is SalonPanelMode.SOLO


def label(key: str, mode: SalonPanelMode) -> str:
    if mode is SalonPanelMode.SOLO and key in SOLO_LABELS:
        return SOLO_LABELS[key]
    return LABELS.get(key, key)


def normalize(mode: SalonPanelMode, requested: Iterable[str]) -> Optional[List[str]]:
    """Что положить в salon.panel_sections по присланному из панели порядку.

    Возвращает None, если и состав, и порядок совпали с набором режима: хранить
    копию defaults нельзя — тогда смена режима перестала бы обновлять набор.
    Именно поэтому сравниваем со списком, а не с множеством: тот же состав,
    но переставленный, — это правка владельца, и потерять её нельзя.
    """
    ordered = _repair(requested, mode)
    if ordered == [k for k in ALL_KEYS if k in default_keys(mode)]:
        return None
    return ordered


def mode_for_master_count(active_masters: int) -> SalonPanelMode:
    """Порог, по которому разводим уже существующие салоны: один активный
    мастер или меньше — человек работает один. Тот же порог зашит в SQL
    миграции b7d1c4e93a25 (в SQL питон не позвать)."""
    return SalonPanelMode.TEAM if active_masters > 1 else SalonPanelMode.SOLO
