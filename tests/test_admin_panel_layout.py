"""Порядок в админке (решение 0018): стражи вёрстки и сверка форм.

Заход про вид, не про поведение: ни одна форма не должна сменить action,
method или набор полей. Эталон снят с разметки ДО переверстки и лежит в
tests/fixtures/admin_forms.json; чтобы пересоздать его осознанно —
ADMIN_FORMS_WRITE=1 pytest tests/test_admin_panel_layout.py.
"""
import json
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

import pytest

from app.core.security import get_password_hash
from app.models.models import (
    AdminAudit, ContestEntry, Master, MasterPhoto, ModelModerationStatus, NotifyChannel,
    PhotoReport, Review, Salon, SalonModerationStatus, SupportRequest, SupportStatus,
    SupportTopic, User, UserRole,
)

ROOT = Path(__file__).resolve().parent.parent
BASELINE = Path(__file__).parent / "fixtures" / "admin_forms.json"
PAGE_SRC = ROOT / "app" / "web" / "pages" / "admin_panel.py"
ADMIN_CSS = ROOT / "static" / "src" / "css" / "admin.css"
PW = get_password_hash("Adminpass1")


def _salon(name, owner_id, **kw):
    base = dict(name=name, description="", address="Томск", latitude=56.5, longitude=84.9,
                phone="+79990000000", rating=4.5, reviews_count=2, is_active=True,
                moderation_status=SalonModerationStatus.APPROVED, creator_id=owner_id)
    base.update(kw)
    return Salon(**base)


async def _seed(db_session):
    """Страница со ВСЕМИ видами форм: каждая ветка условий в разметке задействована."""
    async with db_session() as db:
        me = User(phone="+79995553001", full_name="Старший", hashed_password=PW,
                  role=UserRole.ADMIN, is_senior_admin=True)
        junior = User(phone="+79995553002", full_name="Младший", hashed_password=PW,
                      role=UserRole.ADMIN)
        client = User(phone="+79995553003", full_name="Клиент", hashed_password=PW,
                      role=UserRole.CLIENT)
        model = User(phone="+79995553004", full_name="Модель", hashed_password=PW,
                     role=UserRole.MODEL, is_model=True,
                     model_moderation_status=ModelModerationStatus.PENDING, model_bio="о себе")
        blocked = User(phone="+79995553005", full_name="Блок", hashed_password=PW,
                       role=UserRole.CLIENT, is_active=False)
        owner = User(phone="+79995553006", full_name="Владелец", hashed_password=PW,
                     role=UserRole.BUSINESS)
        mu = User(phone="+79995553007", full_name="Мастер", hashed_password=PW,
                  role=UserRole.MASTER)
        db.add_all([me, junior, client, model, blocked, owner, mu])
        await db.commit()

        live = _salon("Живой", owner.id,
                      contest_winner_until=datetime.now(timezone.utc) + timedelta(days=30),
                      access_until=datetime.now(timezone.utc) + timedelta(days=10))
        winner_free = _salon("Без приза", owner.id)
        pending = _salon("Заявка", owner.id, moderation_status=SalonModerationStatus.PENDING)
        off = _salon("Выключен", owner.id, is_active=False)
        gone = _salon("Удалён", owner.id, is_deleted=True, is_active=False)
        db.add_all([live, winner_free, pending, off, gone])
        await db.commit()

        master = Master(user_id=mu.id, salon_id=live.id, specialization="м")
        db.add(master)
        await db.commit()
        photo = MasterPhoto(master_id=master.id, url="/x.jpg")
        db.add(photo)
        await db.commit()
        db.add(PhotoReport(master_photo_id=photo.id, reporter_id=client.id, reason="плохое"))
        db.add(Review(client_id=client.id, salon_id=live.id, master_id=master.id,
                      rating=5, comment="ок"))
        db.add(AdminAudit(actor_id=me.id, action="toggle_active", target_type="user",
                          target_id=client.id, detail="x"))
        db.add(ContestEntry(contest="c", channel=NotifyChannel.TG, name="Н", city="Т",
                            work_url="https://example.com/w", contact="@x"))
        db.add(SupportRequest(topic=SupportTopic.QUESTION, text="вопрос",
                              channel=NotifyChannel.TG, chat_id=1))
        db.add(SupportRequest(topic=SupportTopic.BUG, text="баг", channel=NotifyChannel.TG,
                              chat_id=2, status=SupportStatus.CLOSED, answer="починили"))
        await db.commit()
    return me.phone


async def admin_html(client, db_session) -> str:
    phone = await _seed(db_session)
    r = await client.post("/api/v1/auth/login", json={"phone": phone, "password": "Adminpass1"})
    client.cookies.set("access_token", r.json()["access_token"])
    page = await client.get("/admin")
    assert page.status_code == 200
    return page.text


class _Forms(HTMLParser):
    """Собирает формы вместе со вкладкой и всеми управляющими элементами."""

    def __init__(self):
        super().__init__()
        self.forms = []
        self._form = None
        self._tab = None
        self._select = None
        self._stack = []  # (тег, внутри ли .adm-danger) для незакрытых контейнеров

    _VOID = {"input", "img", "br", "hr", "meta", "link"}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        inside = bool(self._stack and self._stack[-1][1])
        is_danger = "adm-danger" in (a.get("class") or "").split()
        if tag not in self._VOID:
            self._stack.append((tag, inside or is_danger))
        if tag == "div" and (a.get("id") or "").startswith("tab-"):
            self._tab = a["id"]
        if tag == "form":
            self._form = {"tab": self._tab, "action": a.get("action"),
                          "method": (a.get("method") or "get").lower(),
                          "confirm": "data-confirm" in a, "fields": [],
                          "in_danger": inside or is_danger,
                          "label": ""}
            self.forms.append(self._form)
        elif self._form is not None and tag in ("input", "textarea", "select", "button"):
            name = a.get("name")
            if tag == "button" and not name:
                return
            item = [tag, name, a.get("type") or "", a.get("value") if a.get("type") == "hidden" else ""]
            self._form["fields"].append(item)
            self._select = item if tag == "select" else self._select
        elif self._form is not None and tag == "option" and self._select is not None:
            self._select[3] = (self._select[3] + "," if self._select[3] else "") + (a.get("value") or "")

    def handle_data(self, data):
        if self._form is not None:
            self._form["label"] += data.strip() + " "

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                del self._stack[i:]
                break
        if tag == "form":
            self._form = None
            self._select = None


def parse_forms(html: str):
    p = _Forms()
    p.feed(html)
    return p.forms


def _fingerprint(forms):
    out = []
    for f in forms:
        action = re.sub(r"\d+", "{id}", f["action"] or "")
        fields = sorted(map(tuple, f["fields"]), key=str)
        out.append([f["tab"], action, f["method"], [list(x) for x in fields]])
    return sorted(out, key=str)


async def test_forms_keep_action_method_and_fields(client, db_session):
    html = await admin_html(client, db_session)
    got = _fingerprint(parse_forms(html))
    if os.environ.get("ADMIN_FORMS_WRITE"):
        BASELINE.write_text(json.dumps(got, ensure_ascii=False, indent=1), encoding="utf-8")
    want = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert Counter(map(json.dumps, got)) == Counter(map(json.dumps, want))


# ── Стражи вёрстки ───────────────────────────────────────────────────────────
def _page_source() -> str:
    return PAGE_SRC.read_text(encoding="utf-8")


def _css_classes(css: str) -> set:
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return set(re.findall(r"\.(adm-[a-z0-9_-]+)", css))


def _used_adm_classes(html: str) -> set:
    used = set()
    for m in re.finditer(r'class="([^"]*)"', html):
        used.update(c for c in m.group(1).split() if c.startswith("adm-"))
    return used


def check_no_inline_style(html: str) -> list:
    return re.findall(r"<[a-z0-9]+[^>]*\sstyle=", html)


def check_classes_described(html: str, css: str) -> set:
    return _used_adm_classes(html) - _css_classes(css)


# Разрушающее: удаляет, отзывает, сбрасывает, отклоняет. Блокировка человека —
# отдельно (у неё тот же action, что у разблокировки, различает подпись кнопки).
_DESTRUCTIVE = re.compile(r"/(delete|revoke-access|reset-password|reject|resolve)$")


def _destructive(forms):
    for f in forms:
        action = f["action"] or ""
        if _DESTRUCTIVE.search(action):
            yield f
        elif "/users/" in action and action.endswith("/toggle-active") and f["label"].strip().startswith("Блок."):
            yield f
        elif action.endswith("/contest-winner") and ["input", "months", "hidden", "0"] in f["fields"]:
            yield f


def check_destructive_confirmed(forms) -> list:
    return [f["action"] for f in _destructive(forms) if not f["confirm"]]


def check_destructive_grouped(forms) -> list:
    """Опасная группа — .adm-danger; снятие победителя к ним не относится."""
    return [f["action"] for f in _destructive(forms)
            if not f["in_danger"] and not f["action"].endswith("/contest-winner")]


async def test_no_inline_style_in_markup(client, db_session):
    html = await admin_html(client, db_session)
    assert check_no_inline_style(html) == []
    # И в исходнике: ветки, которых тестовые данные не показывают, тоже без style=.
    src = _page_source()
    assert re.findall(r"""\sstyle=["'\\]""", src) == []
    assert "<style" not in src


async def test_every_adm_class_is_described(client, db_session):
    html = await admin_html(client, db_session)
    assert check_classes_described(html, ADMIN_CSS.read_text(encoding="utf-8")) == set()
    # Классы из исходника (в том числе из веток, которых нет на тестовой странице).
    src_used = set(re.findall(r"adm-[a-z0-9_-]+(?:--[a-z]+)?", _page_source()))
    src_used = {c for c in src_used if not c.endswith("-") and c != "adm-"}
    assert src_used - _css_classes(ADMIN_CSS.read_text(encoding="utf-8")) == set()


async def test_destructive_forms_have_confirm_and_sit_in_danger_group(client, db_session):
    html = await admin_html(client, db_session)
    forms = parse_forms(html)
    assert list(_destructive(forms)), "тест ничего не проверяет: нет разрушающих форм"
    assert check_destructive_confirmed(forms) == []
    assert check_destructive_grouped(forms) == []


def test_guards_catch_a_deliberate_break():
    """Каждый страж падает на испорченной КОПИИ разметки (не на файле в гите)."""
    good = ('<div class="adm-danger"><form method="post" action="/api/v1/admin/users/1/delete" '
            'data-confirm="?"><button>x</button></form></div>')
    assert check_no_inline_style(good) == []
    assert check_no_inline_style(good.replace('<div ', '<div style="color:red" ')) != []

    css = ".adm-danger { color: red }"
    assert check_classes_described(good, css) == set()
    assert check_classes_described(good.replace("adm-danger", "adm-ghost"), css) == {"adm-ghost"}

    assert check_destructive_confirmed(parse_forms(good)) == []
    no_confirm = good.replace(' data-confirm="?"', "")
    assert check_destructive_confirmed(parse_forms(no_confirm)) == ["/api/v1/admin/users/1/delete"]

    assert check_destructive_grouped(parse_forms(good)) == []
    outside = good.replace('class="adm-danger"', 'class="adm-actions"')
    assert check_destructive_grouped(parse_forms(outside)) == ["/api/v1/admin/users/1/delete"]
