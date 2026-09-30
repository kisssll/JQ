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

# Канонический порядок разделов — он же порядок вкладок в меню и порядок
# переключателей в настройках. Ключи совпадают с ?tab=<key> в панели.
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
LOCKED_KEYS = frozenset({"overview", "services", "schedule", "records", "billing", "edit"})

# «Работаю один»: из полного набора убраны разделы, которые существуют только
# при наличии штата — аналитика, зарплаты, себестоимость, склад. «Модели»
# оставлены намеренно (решение владельца: отличительная черта сервиса).
_SOLO_HIDDEN = frozenset({"analytics", "payroll", "cost", "warehouse"})

_DEFAULTS = {
    SalonPanelMode.SOLO: frozenset(ALL_KEYS) - _SOLO_HIDDEN,
    SalonPanelMode.TEAM: frozenset(ALL_KEYS),
}


def default_keys(mode: SalonPanelMode) -> frozenset:
    """Набор разделов, который даёт сам режим, без правок владельца."""
    return _DEFAULTS.get(mode, _DEFAULTS[SalonPanelMode.TEAM])


def enabled_keys(salon) -> frozenset:
    """Включённые разделы салона.

    Пустое salon.panel_sections означает «как по режиму» — именно поэтому смена
    режима сама обновляет набор, а не оставляет застывшую копию. Неизвестные
    ключи в сохранённом списке отбрасываем (раздел могли переименовать), а
    обязательные добавляем всегда.
    """
    stored = getattr(salon, "panel_sections", None)
    mode = getattr(salon, "panel_mode", None) or SalonPanelMode.TEAM
    if not stored:
        return default_keys(mode)
    known = frozenset(k for k in stored if k in LABELS)
    return known | LOCKED_KEYS


def is_enabled(salon, key: str) -> bool:
    return key in enabled_keys(salon)


def is_solo(salon) -> bool:
    return getattr(salon, "panel_mode", None) is SalonPanelMode.SOLO


def label(key: str, mode: SalonPanelMode) -> str:
    if mode is SalonPanelMode.SOLO and key in SOLO_LABELS:
        return SOLO_LABELS[key]
    return LABELS.get(key, key)


def normalize(mode: SalonPanelMode, requested: Iterable[str]) -> Optional[List[str]]:
    """Что положить в salon.panel_sections по присланному формой выбору.

    Отбрасывает неизвестные ключи, добавляет обязательные, раскладывает в
    канонический порядок. Возвращает None, если выбор совпал с набором режима:
    хранить копию defaults нельзя — тогда смена режима перестала бы работать.
    """
    chosen = frozenset(k for k in requested if k in LABELS) | LOCKED_KEYS
    if chosen == default_keys(mode):
        return None
    return [k for k in ALL_KEYS if k in chosen]


def mode_for_master_count(active_masters: int) -> SalonPanelMode:
    """Порог, по которому разводим уже существующие салоны: один активный
    мастер или меньше — человек работает один. Тот же порог зашит в SQL
    миграции b7d1c4e93a25 (в SQL питон не позвать)."""
    return SalonPanelMode.TEAM if active_masters > 1 else SalonPanelMode.SOLO
