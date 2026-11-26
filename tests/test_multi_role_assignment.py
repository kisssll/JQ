"""Тесты назначения нескольких ролей пользователю и проверки совмещения (решение 0019).

Проверяет:
1. Методы модели User: has_role, is_admin, all_roles.
2. Эндпоинт /api/v1/admin/users/assign-roles (назначение ролей модератора + бизнеса, защита последнего админа).
3. Доступность интерфейсов (header, require_role) пользователю с несколькими ролями.
"""
from urllib.parse import urlencode

import pytest
from sqlalchemy import select

from app.api.deps import require_role
from app.core.security import get_password_hash
from app.models.models import User, UserRole, AdminAudit
from app.web.components.header import render_header

PW = get_password_hash("TestPass123")


def test_user_model_role_helpers():
    """Проверка has_role, is_admin и all_roles на модели User."""
    user = User(
        phone="+79991110001",
        hashed_password=PW,
        role=UserRole.ADMIN,
        additional_roles=["business"],
        is_senior_admin=True,
    )
    assert user.has_role("admin") is True
    assert user.has_role(UserRole.ADMIN) is True
    assert user.has_role("business") is True
    assert user.has_role(UserRole.BUSINESS) is True
    assert user.has_role("client") is False
    assert user.is_admin is True
    assert set(user.all_roles) == {"admin", "business"}

    # Добавление флага модели
    user.is_model = True
    assert user.has_role("model") is True
    assert set(user.all_roles) == {"admin", "business", "model"}


@pytest.mark.asyncio
async def test_assign_roles_endpoint_success(client, db_session):
    """Старший модератор назначает пользователю роли модератора и бизнеса."""
    async with db_session() as db:
        admin = User(
            phone="+79990001122",
            full_name="Admin Senior",
            hashed_password=PW,
            role=UserRole.ADMIN,
            is_senior_admin=True,
        )
        target = User(
            phone="+79998887766",
            full_name="Target User",
            hashed_password=PW,
            role=UserRole.CLIENT,
        )
        db.add_all([admin, target])
        await db.commit()
        target_id = target.id

    # Авторизуемся старшим админом
    login_res = await client.post(
        "/api/v1/auth/login",
        json={"phone": "+79990001122", "password": "TestPass123"},
    )
    assert login_res.status_code == 200
    client.cookies.set("access_token", login_res.json()["access_token"])

    # Назначаем роли target: admin (старший) + business
    body = urlencode([
        ("phone", "+7 (999) 888-77-66"),
        ("roles", "admin"),
        ("roles", "business"),
        ("is_senior", "1"),
        ("return_tab", "overview"),
    ])
    res = await client.post(
        "/api/v1/admin/users/assign-roles",
        content=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )
    assert res.status_code == 302
    assert "ok=" in res.headers["location"]
    assert "tab=overview" in res.headers["location"]

    # Проверяем в БД
    async with db_session() as db:
        updated = (await db.execute(select(User).where(User.id == target_id))).scalar_one()
        assert updated.role == UserRole.ADMIN
        assert "business" in updated.additional_roles
        assert updated.is_senior_admin is True
        assert updated.has_role("admin") is True
        assert updated.has_role("business") is True

        # Проверяем аудит
        audit = (
            await db.execute(
                select(AdminAudit).where(
                    AdminAudit.target_id == target_id,
                    AdminAudit.action == "assign_roles",
                )
            )
        ).scalar_one_or_none()
        assert audit is not None
        assert "роли →" in audit.detail


@pytest.mark.asyncio
async def test_assign_roles_protect_last_admin(client, db_session):
    """Нельзя снять роль админа с единственного администратора."""
    async with db_session() as db:
        admin = User(
            phone="+79991112233",
            full_name="Solo Admin",
            hashed_password=PW,
            role=UserRole.ADMIN,
            is_senior_admin=True,
        )
        db.add(admin)
        await db.commit()
        admin_id = admin.id

    login_res = await client.post(
        "/api/v1/auth/login",
        json={"phone": "+79991112233", "password": "TestPass123"},
    )
    client.cookies.set("access_token", login_res.json()["access_token"])

    # Пытаемся сделать единственного админа просто клиентом
    body = urlencode([
        ("user_id", str(admin_id)),
        ("roles", "client"),
        ("return_tab", "overview"),
    ])
    res = await client.post(
        "/api/v1/admin/users/assign-roles",
        content=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )
    assert res.status_code == 302
    assert "err=" in res.headers["location"]

    # Проверяем, что роль не изменилась
    async with db_session() as db:
        u = (await db.execute(select(User).where(User.id == admin_id))).scalar_one()
        assert u.role == UserRole.ADMIN


@pytest.mark.asyncio
async def test_multi_role_permissions_and_header(client, db_session):
    """Пользователь с ролями admin + business имеет доступ к обоим контекстам."""
    user = User(
        phone="+79995554433",
        full_name="Combo User",
        hashed_password=PW,
        role=UserRole.ADMIN,
        additional_roles=["business"],
        is_senior_admin=True,
    )

    # Проверка require_role для обоих типов
    checker_admin = require_role(UserRole.ADMIN)
    checker_business = require_role(UserRole.BUSINESS)

    # Не должно выбрасывать HTTPException 403
    await checker_admin(current_user=user)
    await checker_business(current_user=user)

    # Шапка сайта должна отображать ссылки и в кабинет бизнеса, и в админку
    header_html = render_header(current_page="admin", user=user)
    assert "Админка" in header_html
    assert "Панель бизнеса" in header_html
