# app/services/vk_community.py
"""Два сообщества ВКонтакте: клиентское и бизнесовое (решение 0013).

Сообщество не может написать первым: разрешение на переписку человек даёт
КОНКРЕТНОМУ сообществу, когда сам ему пишет. Поэтому у каждого сообщества свой
токен, свой адрес человека и своя отметка «отказал». Письмо чужим токеном на
чужой адрес ВК отвергнет кодом 901, а мы приняли бы это за «человек закрыл
сообщения» и пометили канал сломанным — человек молча остался бы без
уведомлений. Всё, что отправляет во ВК, обязано сначала выбрать сообщество
здесь, а не брать «токен по умолчанию».

Какое сообщество у сообщения, решает его СМЫСЛ, а не получатель:
  * CLIENT — то, что человек получает как клиент: запись, отмена, напоминание,
    вопрос об отзыве, вечерние окна;
  * BUSINESS — то, что получает мастер или салон: новая запись к нему, тариф и
    оплата, поддержка, конкурс, алерты админам.
Список всех мест отправки с выбором — в отчёте к решению 0013 и в тестах
tests/test_vk_two_communities.py.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass


class Audience(str, enum.Enum):
    CLIENT = "client"
    BUSINESS = "business"


@dataclass(frozen=True)
class Community:
    audience: Audience
    #: Поля пользователя: куда писать и когда сообщество отказало.
    peer_field: str
    broken_field: str
    #: Имена настроек — значения читаем при вызове: тесты перезагружают конфиг.
    _token_setting: str
    _group_setting: str
    _address_property: str

    @property
    def token(self) -> str:
        from app.core.config import settings

        return getattr(settings, self._token_setting) or ""

    @property
    def group_id(self) -> int:
        from app.core.config import settings

        return int(getattr(settings, self._group_setting) or 0)

    @property
    def address(self) -> str:
        """Адрес сообщества для vk.me-ссылок или пустая строка."""
        from app.core.config import settings

        return getattr(settings, self._address_property)


CLIENT = Community(
    Audience.CLIENT, "vk_client_peer_id", "vk_client_broken_at",
    "VK_CLIENTS_BOT_TOKEN", "VK_CLIENTS_GROUP_ID", "vk_clients_bot_address",
)
BUSINESS = Community(
    Audience.BUSINESS, "vk_business_peer_id", "vk_business_broken_at",
    "VK_BOT_TOKEN", "VK_GROUP_ID", "vk_bot_address",
)
ALL = (CLIENT, BUSINESS)


def get(audience) -> Community:
    """Сообщество по типу сообщения. Неизвестное значение — ошибка, а не
    «какое-нибудь»: молча выбранное не то сообщество и есть та поломка,
    от которой защищает этот модуль."""
    return CLIENT if Audience(audience) == Audience.CLIENT else BUSINESS


def for_process() -> Community:
    """Сообщество, которое обслуживает этот процесс бота (VK_BOT_ROLE)."""
    from app.core.config import settings

    return get((settings.VK_BOT_ROLE or "").strip().lower())
