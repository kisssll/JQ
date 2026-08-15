# app/web/service_categories.py
"""Категории бьюти-услуг — единый источник для тегов на карточках салонов,
фильтра на /salons и подбора по описанию/названиям услуг мастеров.

Каждая запись: (slug, label, keywords). slug идёт в data-атрибуты и value
чекбоксов, label — что видит пользователь, keywords — словоформы/синонимы,
по которым ищем совпадение в свободном тексте описания салона."""

SERVICE_CATEGORY_GROUPS = [
    ("strizhki", "Стрижки", ["стрижк"]),
    ("okrashivanie", "Окрашивание", ["окраш", "мелирован", "тонирован", "колорирован", "балаяж"]),
    ("ukladka", "Укладка и причёски", ["укладк", "причёск", "прическ"]),
    ("narashchivanie_volos", "Наращивание волос", ["наращивание волос", "нарощенн"]),
    ("boroda", "Борода и барбер", ["бород", "усы", "барбер"]),
    ("manikur", "Маникюр", ["маникюр"]),
    ("pedikur", "Педикюр", ["педикюр"]),
    ("narashchivanie_nogtei", "Наращивание ногтей", ["наращивание ногт", "гель-лак", "шеллак"]),
    ("brovi", "Брови", ["бров"]),
    ("resnicy", "Ресницы", ["реснич", "ресниц"]),
    ("makiyazh", "Макияж и визаж", ["макияж", "визаж"]),
    ("depilyaciya", "Депиляция и шугаринг", ["депиляц", "шугаринг", "эпиляц", "воск"]),
    ("kosmetologiya", "Косметология", ["косметолог", "чистка лица", "пилинг", "уход за лицом"]),
    ("massazh", "Массаж и SPA", ["массаж", "спа", "spa"]),
    ("tatuazh", "Татуаж", ["татуаж", "перманентн"]),
    ("solyariy", "Солярий", ["солярий"]),
]

_LABEL_BY_SLUG = {slug: label for slug, label, _keywords in SERVICE_CATEGORY_GROUPS}


def match_category_slugs(text: str) -> list[str]:
    """Слаги категорий, чьи ключевые слова встречаются в тексте (регистр не важен)."""
    haystack = text.lower()
    return [
        slug for slug, _label, keywords in SERVICE_CATEGORY_GROUPS
        if any(kw in haystack for kw in keywords)
    ]


def slug_to_label(slug: str) -> str:
    return _LABEL_BY_SLUG.get(slug, slug)
