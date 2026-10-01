"""Из чего состоит знакомство с панелью и кому его показывать (решение 0008).

Тур — это пролог, три акта по трём целям владельца и финал (п. 4). Шаги
строятся из разделов ЭТОГО салона: набор задаёт режим, порядок и выключенные
разделы — владелец (panel_sections), а права добивают видимость. В выключенный
или закрытый правами раздел тур не ведёт никогда — иначе он привёл бы человека
на вкладку, которой у него нет, и вместо знакомства вышел бы «Обзор».

Чего здесь НЕТ намеренно:
  * разметки — полосу рисует app/web/components/panel_tour.py;
  * текстов разделов — они в app/services/panel_guide.py, одни и те же на тур
    и на справочник;
  * обращений к БД: build() и decide() работают на значениях, поэтому состав
    шагов и правила запуска проверяются без базы и без HTTP
    (tests/test_panel_tour_steps.py). Читать и писать состояние — дело панели.

Про хранение. Шаг лежит в users.panel_tour_step КЛЮЧОМ, а не номером: состав
шагов у каждого свой, и «шаг 7» завтра означал бы другое, стоило владельцу
убрать раздел. Если шага с таким ключом больше нет, resolve_step() поднимает
тур на первом существующем — панель обязана открыться при любом содержимом
столбца.
"""
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

from app.models.models import SalonPanelMode
from app.services import panel_guide, panel_sections

# Акты. Подпись акта стоит в полосе рядом с номером шага («Шаг 4 из 13 — чтобы
# вас было видно»): человек должен понимать, зачем его сейчас ведут.
ACT_PROLOGUE = "prologue"
ACT_VISIBLE = "visible"
ACT_CHOSEN = "chosen"
ACT_WATCH = "watch"
ACT_FINALE = "finale"

ACT_TITLES: Dict[str, str] = {
    ACT_PROLOGUE: "что такое Руми",
    ACT_VISIBLE: "чтобы вас было видно",
    ACT_CHOSEN: "чтобы выбирали вас",
    ACT_WATCH: "что отслеживать",
    ACT_FINALE: "что есть ещё",
}

#: Порядок актов — он же порядок шагов.
_ACT_ORDER = (ACT_PROLOGUE, ACT_VISIBLE, ACT_CHOSEN, ACT_WATCH, ACT_FINALE)

# Разделы по актам (решение 0008, п. 4). Порядок внутри акта — это порядок
# действий, а не алфавит: сначала сам салон, потом мастер, услуги, расписание и
# только затем тариф с публикацией. Раздела, которого у салона нет, в туре не
# будет — фильтрация ниже.
_ACT_SECTIONS: Dict[str, Sequence[str]] = {
    ACT_VISIBLE: ("edit", "employees", "services", "schedule", "billing"),
    ACT_CHOSEN: ("reviews", "promos", "models"),
    ACT_WATCH: ("overview", "records", "crm", "analytics"),
}

#: Разделы, про которые финал говорит списком, а не отдельным шагом. Водить
#: человека по складу в день регистрации — шум (решение 0008, п. 4).
#: «Инструкции» в списке нет намеренно: финал на ней и заканчивается и называет
#: её следующей же фразой — перечислять её среди «мы туда не ходили» странно.
_FINALE_SECTIONS = ("warehouse", "payroll", "cost")

# Пролог. Он и так открывается на «Обзоре» (это вход в панель), поэтому своего
# раздела у шага нет — переключать нечего.
_PROLOGUE_TEXT = (
    "Руми — это лента салонов и мастеров, где клиенты ищут, к кому пойти, и "
    "ваша собственная страница записи. Клиент открывает вашу ссылку или "
    "сканирует QR-код, выбирает услугу и время — регистрация ему для этого не "
    "нужна, а заявка приходит вам в Telegram, MAX или ВКонтакте. Сейчас "
    "пройдём по вашим разделам: сначала то, без чего салона нет в ленте, потом "
    "то, чем можно выделиться, и напоследок — куда смотреть дальше."
)

_FINALE_HEAD = "Это всё, что нужно для начала."
_FINALE_TAIL = (
    "Пройти знакомство заново можно в разделе «Инструкция» — там же подробное "
    "описание каждого раздела. А кнопка «Настроить панель» справа в ленте "
    "разделов убирает лишние разделы и меняет их порядок: панель можно собрать "
    "под себя."
)

# Значения параметра ?tour= в адресе панели. Обычный шаг передаётся своим
# ключом; эти четыре — команды.
REQUEST_ON = "on"            # продолжить с сохранённого шага (или начать)
REQUEST_OFF = "off"          # выйти, шаг оставить как есть
REQUEST_DONE = "done"        # дошёл до конца
REQUEST_RESTART = "restart"  # пройти знакомство заново


@dataclass(frozen=True)
class Step:
    """Один шаг тура.

    key — то, что лежит в базе; act — к какому акту относится (нужен подписи и
    кнопке «пропустить акт»); tab — раздел панели, на который тур переключает
    (None — остаёмся там, где человек стоит); text — реплика в полосе.
    """
    key: str
    act: str
    tab: Optional[str]
    text: str

    @property
    def act_title(self) -> str:
        return ACT_TITLES.get(self.act, "")


def build(salon, *, visible_keys: Iterable[str]) -> List[Step]:
    """Шаги тура для этого салона.

    visible_keys — итоговая видимость разделов из панели: раздел включён у
    салона И право на него есть. Передаётся готовым списком, а не вычисляется
    здесь, чтобы у тура и у меню не могло разойтись представление о том, что
    человеку доступно.
    """
    visible = [k for k in visible_keys]
    present = frozenset(visible)
    solo = panel_sections.is_solo(salon)
    mode = getattr(salon, "panel_mode", None) or SalonPanelMode.TEAM

    steps: List[Step] = [Step(
        key="intro", act=ACT_PROLOGUE, tab=None, text=_PROLOGUE_TEXT,
    )]

    for act in (ACT_VISIBLE, ACT_CHOSEN, ACT_WATCH):
        for key in _ACT_SECTIONS[act]:
            if key not in present:
                continue
            steps.append(Step(
                key=f"{act}:{key}", act=act, tab=key,
                text=panel_guide.tour_line(key, solo=solo),
            ))

    steps.append(Step(
        key="finale", act=ACT_FINALE,
        # Финал заканчивается там, где лежит ссылка «пройти заново». Если
        # владелец выключил «Инструкцию», переключать некуда — остаёмся.
        tab="instructions" if "instructions" in present else None,
        text=_finale_text(present, mode),
    ))
    return steps


def _finale_text(present: frozenset, mode: SalonPanelMode) -> str:
    """«Что есть ещё» — списком и только то, что у салона действительно есть."""
    extras = [panel_sections.label(k, mode) for k in _FINALE_SECTIONS if k in present]
    middle = ""
    if extras:
        middle = (
            " По остальным разделам мы не ходили, они пригодятся позже: "
            + ", ".join(f"«{name}»" for name in extras) + "."
        )
    return f"{_FINALE_HEAD}{middle} {_FINALE_TAIL}"


# ─────────────────────── переходы ───────────────────────


def _index(steps: Sequence[Step], key: Optional[str]) -> Optional[int]:
    for i, s in enumerate(steps):
        if s.key == key:
            return i
    return None


def resolve_step(steps: Sequence[Step], key: Optional[str]) -> Optional[Step]:
    """Шаг по ключу из базы; нет такого — первый.

    Ключ мог устареть: владелец убрал раздел, и шаг про него исчез. Поднимать
    тур в этом случае надо, а не падать — человек не виноват, что состав
    поменялся.
    """
    if not steps:
        return None
    i = _index(steps, key)
    return steps[i] if i is not None else steps[0]


def next_key(steps: Sequence[Step], key: Optional[str]) -> Optional[str]:
    i = _index(steps, key)
    if i is None or i + 1 >= len(steps):
        return None
    return steps[i + 1].key


def prev_key(steps: Sequence[Step], key: Optional[str]) -> Optional[str]:
    i = _index(steps, key)
    if i is None or i == 0:
        return None
    return steps[i - 1].key


def skip_act_key(steps: Sequence[Step], key: Optional[str]) -> Optional[str]:
    """Первый шаг следующего акта: «пропустить» — это про акт целиком, а не
    про шаг, и не означает выход из тура (решение 0008, п. 4)."""
    i = _index(steps, key)
    if i is None:
        return None
    act = steps[i].act
    for s in steps[i + 1:]:
        if s.act != act:
            return s.key
    return None


# ─────────────────────── кому и когда показывать ───────────────────────


@dataclass(frozen=True)
class Decision:
    """Что панель делает с туром на этом запросе.

    step — шаг, на котором рисуем полосу (None — полосы нет);
    invite_step — шаг, на который зовём скромным приглашением (None — не зовём);
    save_step — какой ключ записать в users.panel_tour_step (None — не трогать);
    start_now — поставить отметку «запустили впервые», если её ещё нет;
    finish_now — поставить «прошли до конца»;
    clear_done — снять «прошли до конца» (пройти заново).
    """
    step: Optional[Step] = None
    invite_step: Optional[Step] = None
    save_step: Optional[str] = None
    start_now: bool = False
    finish_now: bool = False
    clear_done: bool = False


def decide(
    *,
    steps: Sequence[Step],
    requested: Optional[str],
    stored_step: Optional[str],
    started: bool,
    done: bool,
    can_manage: bool,
    already_working: bool,
) -> Decision:
    """Показывать ли тур и на каком шаге.

    requested — параметр ?tour= из адреса: ключ шага или одна из команд
    REQUEST_*. Через адрес, а не через AJAX, потому что вкладки панели и так
    открываются полной навигацией: один переход на шаг, состояние пишется на
    сервере, и перезагрузка поднимает тур там же.

    already_working — «у этого уже всё работает» (решение 0008, п. 5): нет
    блокирующих причин в booking_readiness и есть хотя бы одна запись. Такому
    тур сам не всплывает, но приглашение видит — вести человека, который и так
    принимает клиентов, по шагам «как попасть в ленту» значило бы учить его
    тому, что он уже сделал.
    """
    # Почти все действия тура требуют права менять салон. Наёмному мастеру и
    # участнику без manage_salon показывать его незачем: он пришёл бы в раздел,
    # где ничего не может (решение 0008, п. 5).
    if not can_manage or not steps:
        return Decision()

    if requested == REQUEST_RESTART:
        first = steps[0]
        return Decision(step=first, save_step=first.key,
                        start_now=not started, clear_done=done)

    if requested == REQUEST_OFF:
        # Выход. Шаг НЕ затираем: он и есть «на каком шаге вышли», по нему же
        # человек вернётся — с любого устройства, а не только из этой вкладки.
        return Decision(invite_step=resolve_step(steps, stored_step))

    if requested == REQUEST_DONE:
        return Decision(finish_now=True)

    if requested == REQUEST_ON:
        step = resolve_step(steps, stored_step)
        return Decision(step=step, save_step=step.key, start_now=not started)

    if requested:
        # Пришёл ключ шага. Неизвестный ключ (устаревшая ссылка, правка руками)
        # не ошибка: поднимаем тур на первом шаге.
        step = resolve_step(steps, requested)
        return Decision(step=step, save_step=step.key, start_now=not started)

    # Параметра нет — решаем сами.
    if done:
        # Прошёл до конца: больше не навязываемся. Вернуться можно ссылкой в
        # «Инструкции».
        return Decision()

    if started:
        # Уже начинал и ушёл — зовём продолжить с того же шага, но полосу
        # поверх панели сами не поднимаем: человек её однажды закрыл.
        return Decision(invite_step=resolve_step(steps, stored_step))

    if already_working:
        return Decision(invite_step=steps[0])

    # Первый заход владельца — тот самый случай, ради которого всё и делалось.
    first = steps[0]
    return Decision(step=first, save_step=first.key, start_now=True)
