"""Ссылка и QR-код для записи — один блок на две вкладки панели.

Это то, ради чего мастер подключался: адрес, который он даёт клиентам, и
картинка, которую печатает и ставит на ресепшн. Раньше блок жил только во
вкладке «Редактировать салон» (восьмое место по посещаемости из шестнадцати),
и в «Обзоре» его пришлось бы написать второй раз — с риском, что одна копия
со временем начнёт говорить не то же самое, что другая.

Сама страница — /book/{salon_id} (app/web/pages/guest_booking.py), картинка —
/book/{salon_id}/qr. Блок ничего не проверяет сам: состояние приходит
параметрами. Причины, по которым ссылка может не работать, перечисляет блок
готовности («Можно ли к вам записаться», app/services/booking_readiness.py);
здесь говорим только про тумблер «запись без регистрации» — тот, о котором
прямо написано в приписке.
"""
from app.web.components.icons import ICON_COPY


_DEFAULT_OFF_NOTE = (
    "Сейчас ссылка не работает: запись без регистрации выключена. "
    "Включите её в разделе «Редактировать салон»."
)


def render_booking_link_block(
    salon_id: int,
    *,
    enabled: bool = True,
    heading: str = "Ссылка и QR для записи",
    off_note: str = _DEFAULT_OFF_NOTE,
    hint: bool = True,
) -> str:
    """enabled=False — запись без регистрации выключена: ссылка открывается, но
    отвечает «Этот салон сейчас не принимает записи без регистрации». Молча
    показывать её в таком виде нельзя, поэтому говорим прямо.

    off_note="" — для вкладки «Редактировать салон»: там тумблер стоит прямо
    над блоком и сам показывает состояние, а совет «включите в разделе
    „Редактировать салон"» читался бы как насмешка — человек уже в нём.
    """
    off_html = "" if (enabled or not off_note) else (
        f'<p class="booking-link-off">{off_note}</p>'
    )
    heading_html = f'<h3 class="booking-link-title">{heading}</h3>' if heading else ""
    hint_html = (
        '<p class="booking-link-hint">Клиент открывает ссылку, выбирает услугу и время — '
        'заявка приходит вам на подтверждение. Регистрация ему не нужна.</p>'
    ) if hint else ""
    return f"""
    <div class="booking-link">
        {heading_html}
        {off_html}
        <div class="booking-link-row">
            <img class="booking-link-qr" src="/book/{salon_id}/qr"
                 alt="QR-код для записи в ваш салон" loading="lazy" width="150" height="150">
            <div class="booking-link-side">
                <a class="booking-link-url js-booking-link-url" href="/book/{salon_id}"
                   target="_blank" rel="noopener">…/book/{salon_id}</a>
                <div class="booking-link-actions">
                    <button type="button" class="booking-link-copy js-copy-booking-link"
                            data-salon-id="{salon_id}">{ICON_COPY} Скопировать ссылку</button>
                    <a class="booking-link-download" href="/book/{salon_id}/qr"
                       download="rumi-qr-{salon_id}.png">Скачать QR</a>
                </div>
                <p class="booking-link-copied js-copy-booking-msg" role="status"></p>
                {hint_html}
            </div>
        </div>
    </div>
    """
