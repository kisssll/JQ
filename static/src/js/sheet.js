// static/src/js/sheet.js — лист снизу.
//
// Открывается по [data-sheet-open="id"], закрывается по [data-sheet-close],
// по затемнению, по Escape и жестом «потянуть вниз».
//
// Почему жест, а не только кнопка: лист приезжает оттуда, где палец, и палец
// ждёт, что его можно будет отправить обратно. Кнопка-крестик остаётся — жест
// не единственный способ (его не видно с клавиатуры).
//
// Движение берётся из motion.js: пресет sheet (демпфирование 0.8, отклик 0.3)
// и уважение prefers-reduced-motion решены там один раз.
import { move, EASE, SPRING, prefersReducedMotion } from './motion.js';

// Насколько далеко надо утянуть лист, чтобы он закрылся: четверть высоты либо
// быстрый бросок. Одного порога по расстоянию мало — короткий резкий свайп
// ощущается как «закрой», даже если палец прошёл сантиметр.
const CLOSE_FRACTION = 0.25;
const CLOSE_VELOCITY = 0.6; // px/мс

let openSheet = null;
let lastOpener = null;
//: Пружина открытия продолжает писать transform ещё доли секунды после того,
//: как лист визуально встал на место. Если в этот момент схватить его пальцем,
//: наш сдвиг будет затёрт следующим кадром анимации — палец тянет, а лист
//: стоит. Поэтому анимацию запоминаем и доводим до конца в начале жеста.
let settling = null;

function panelOf(sheet) {
    return sheet.querySelector('.r-sheet__panel');
}

function lockScroll(on) {
    // И на <html>, и на <body>: прокручиваемым элементом бывает любой из них
    // (зависит от стилей страницы), и запрет только на body оставлял страницу
    // под листом ездящей вместе с ним.
    document.body.style.overflow = on ? 'hidden' : '';
    document.documentElement.style.overflow = on ? 'hidden' : '';
}

export function open(sheet, opener) {
    if (!sheet || openSheet === sheet) return;
    openSheet = sheet;
    lastOpener = opener || null;
    sheet.hidden = false;
    lockScroll(true);

    const panel = panelOf(sheet);
    // Прошлое закрытие оставляет на панели свой конечный transform (Motion
    // дописывает его уже после того, как мы очистили стиль). Снимаем сами,
    // иначе первый кадр нового показа берётся из старого состояния.
    panel.style.transform = '';
    const scrim = sheet.querySelector('.r-sheet__scrim');
    move(scrim, { opacity: [0, 1] }, EASE.base);
    settling = move(panel, { transform: ['translateY(100%)', 'translateY(0%)'] }, SPRING.sheet);

    // Фокус уезжает в лист: иначе человек с клавиатуры продолжает ходить по
    // странице ПОД листом и не понимает, куда делся курсор.
    const focusable = panel.querySelector(
        'button:not([disabled]), [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    (focusable || panel).focus({ preventScroll: true });
    sheet.dispatchEvent(new CustomEvent('sheet:open', { bubbles: true }));
}

export function close(sheet) {
    sheet = sheet || openSheet;
    if (!sheet) return;
    const panel = panelOf(sheet);
    const scrim = sheet.querySelector('.r-sheet__scrim');
    openSheet = null;
    lockScroll(false);

    move(scrim, { opacity: [1, 0] }, EASE.quick);
    const anim = move(panel, { transform: 'translateY(100%)' }, EASE.base);
    const finish = () => {
        sheet.hidden = true;
        // Сбрасываем сдвиг, иначе следующий показ начнётся с уехавшей панели.
        panel.style.transform = '';
        if (lastOpener && document.contains(lastOpener)) {
            lastOpener.focus({ preventScroll: true });
        }
        lastOpener = null;
        sheet.dispatchEvent(new CustomEvent('sheet:close', { bubbles: true }));
    };
    if (prefersReducedMotion()) finish();
    else anim.finished.then(finish).catch(finish);
}

/** Потянуть вниз. Работает только за «голову» листа: если тянуть за тело, жест
 *  отбирал бы у него прокрутку, и список окон стало бы невозможно пролистать. */
function enableDrag(sheet) {
    const panel = panelOf(sheet);
    const head = sheet.querySelector('.r-sheet__head');
    if (!panel || !head) return;

    let startY = 0;
    let startT = 0;
    let dy = 0;
    let dragging = false;

    head.addEventListener('pointerdown', (ev) => {
        if (ev.button !== undefined && ev.button !== 0) return;
        // На крестике жест не нужен: он и так закрывает.
        if (ev.target.closest('[data-sheet-close]')) return;
        // Довести пружину открытия до конца, иначе её следующий кадр затрёт
        // сдвиг под пальцем.
        if (settling) { try { settling.complete(); } catch (e) { /* уже завершилась */ } }
        settling = null;
        dragging = true;
        startY = ev.clientY;
        startT = ev.timeStamp;
        dy = 0;
        head.setPointerCapture(ev.pointerId);
    });

    head.addEventListener('pointermove', (ev) => {
        if (!dragging) return;
        // Вверх лист не тянется: резина вверх здесь означала бы, что лист
        // может стать выше, а он уже во всю доступную высоту.
        dy = Math.max(0, ev.clientY - startY);
        panel.style.transform = `translateY(${dy}px)`;
    });

    function release(ev) {
        if (!dragging) return;
        dragging = false;
        const elapsed = Math.max(1, ev.timeStamp - startT);
        const velocity = dy / elapsed;
        const far = dy > panel.offsetHeight * CLOSE_FRACTION;
        if (far || velocity > CLOSE_VELOCITY) {
            close(sheet);
        } else {
            // Не доехал — возвращается пружиной с ТЕКУЩЕГО места, а не прыжком:
            // схватил на середине, отпустил — не дёргается.
            settling = move(panel, { transform: 'translateY(0px)' }, SPRING.sheet);
        }
    }

    head.addEventListener('pointerup', release);
    head.addEventListener('pointercancel', release);
}

document.addEventListener('click', (ev) => {
    const opener = ev.target.closest('[data-sheet-open]');
    if (opener) {
        const sheet = document.getElementById(opener.dataset.sheetOpen);
        if (sheet) {
            ev.preventDefault();
            open(sheet, opener);
        }
        return;
    }
    if (ev.target.closest('[data-sheet-close]')) {
        ev.preventDefault();
        close();
    }
});

document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape' && openSheet) close();
});

document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.r-sheet').forEach(enableDrag);
});
