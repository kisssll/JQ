"""Страницы нормативных документов.

Документы должны открываться текстом по свободному адресу — ч.2 ст.18.1
152-ФЗ требует свободного доступа к Политике, и на практике это значит
живую страницу, а не файл на скачивание.
"""
import pytest

from app.web.pages.legal import DOCUMENTS, LEGAL_VERSION, LEGAL_VERSION_HUMAN


@pytest.mark.parametrize("slug", sorted(DOCUMENTS))
async def test_document_page_opens(client, slug):
    r = await client.get(f"/{slug}")
    assert r.status_code == 200, slug
    assert DOCUMENTS[slug]["title"] in r.text
    assert LEGAL_VERSION_HUMAN in r.text


def test_all_documents_have_a_file():
    """Запись в DOCUMENTS без файла = 500 на живой странице."""
    import pathlib

    legal_dir = pathlib.Path("app/web/legal")
    for slug, doc in DOCUMENTS.items():
        assert (legal_dir / doc["file"]).exists(), slug


def test_revision_date_is_the_eighteenth():
    """Дата уходит в журнал согласий вместе с отметкой пользователя, поэтому
    расхождение с текстом документов не косметическое: потом не докажешь, с
    какой редакцией человек согласился."""
    assert LEGAL_VERSION == "2026-08-18"
    assert LEGAL_VERSION_HUMAN == "18 августа 2026"


@pytest.mark.parametrize("slug", ["offer", "license", "cookies"])
async def test_new_documents_carry_their_substance(client, slug):
    """Не пустая страница-заглушка: проверяем реквизиты и ключевой раздел."""
    r = await client.get(f"/{slug}")
    assert "1267000004370" in r.text, "ОГРН оператора"
    assert "7000036144" in r.text, "ИНН оператора"


async def test_cookie_policy_points_to_itself_not_to_tariffs():
    """В исходном тексте адрес самой Политики и ссылка на Политику ПДн вели
    на /tariffs — очевидная опечатка, из-за которой документ ссылался на
    страницу с ценами."""
    import pathlib

    text = pathlib.Path("app/web/legal/cookies.html").read_text(encoding="utf-8")
    assert "rrumi.ru/tariffs" not in text
    assert "/cookies" in text
    assert "/privacy" in text


async def test_documents_listed_in_footer(client):
    r = await client.get("/")
    for slug in ("terms", "privacy", "consent", "offer", "license", "cookies"):
        assert f'href="/{slug}"' in r.text, slug
