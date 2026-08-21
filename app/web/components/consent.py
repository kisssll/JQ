# app/web/components/consent.py
"""Согласие на обработку персональных данных под формами.

Почему именно так:

* Отдельная галочка, а не строка «нажимая кнопку, вы соглашаетесь». С 1 сентября
  2025 согласие должно быть самостоятельным и не может быть спрятано внутри
  пользовательского соглашения или склеено с принятием оферты.
* Галочка пустая по умолчанию и обязательная — предзаполненная отметка согласием
  не считается.
* Формулировка взята дословно из п.8 самого Согласия: моментом согласия там
  назван факт проставления этой отметки.
* Рядом — ссылка на текст, потому что согласие должно быть доступно там, где
  человек его даёт.

Скрытое поле consent_version уходит в журнал согласий вместе с датой, чтобы
потом можно было сказать, с какой редакцией документа человек согласился.
"""
from app.web.pages.legal import LEGAL_VERSION

CONSENT_TEXT = "Я даю согласие на обработку персональных данных"
CONSENT_FIELD = "pd_consent"


def render_consent_checkbox(field: str = CONSENT_FIELD, required: bool = True) -> str:
    """Обязательная отметка согласия на обработку ПДн со ссылкой на текст."""
    req = " required" if required else ""
    return f"""
    <label class="consent-check">
        <input type="checkbox" name="{field}" value="1" class="consent-check-input"{req}>
        <span class="consent-check-text">{CONSENT_TEXT} на условиях
            <a href="/consent" target="_blank" rel="noopener">Согласия</a>.</span>
    </label>
    <input type="hidden" name="consent_version" value="{LEGAL_VERSION}">
    """


def render_legal_note(action: str = "Продолжая") -> str:
    """Строка со ссылками на соглашение и политику.

    Пользовательское соглашение по его п.9.1 акцептуется самим фактом
    использования сервиса, поэтому здесь достаточно ссылки — отдельная галочка
    нужна именно согласию на ПДн.
    """
    return f"""
    <p class="consent-note">{action}, вы принимаете
        <a href="/terms" target="_blank" rel="noopener">Пользовательское соглашение</a>
        и подтверждаете, что ознакомились с
        <a href="/privacy" target="_blank" rel="noopener">Политикой обработки персональных данных</a>.</p>
    """


def render_consent_block(field: str = CONSENT_FIELD, action: str = "Продолжая") -> str:
    """Галочка согласия + строка со ссылками. Обычный случай для формы."""
    return f'<div class="consent-block">{render_consent_checkbox(field)}{render_legal_note(action)}</div>'
