// static/src/js/motion.js — единственная точка движения в сервисе.
//
// Зачем обёртка, а не вызовы animate() по месту: значения пружин, правило
// прерывания и уважение prefers-reduced-motion должны быть решены ОДИН раз.
// Иначе каждый следующий экран выберет свою длительность, и сервис будет
// двигаться по-разному в зависимости от того, кто писал раздел.
//
// Значения взяты из iOS (docs/design.md, решение 0011): движение — отклик,
// а не представление.
import { animate, spring } from 'motion';

/* ---------- Пресеты ----------
   Apple описывает пружину парой «демпфирование / отклик», Motion — парой
   «bounce / visualDuration». Это одно и то же другими словами:
   visualDuration = response (за сколько секунд движение визуально
   заканчивается), bounce = 1 − dampingFraction (перелёт).

   Перелёт (bounce > 0) — только там, где жест нёс инерцию: лист, который
   человек тянет пальцем, и поворот. У обычного перемещения перелёта нет:
   интерфейс, который пружинит без причины, читается как игрушка. */
export const SPRING = {
    // перемещение: демпфирование 1.0, отклик 0.4 с
    move: { type: spring, visualDuration: 0.4, bounce: 0 },
    // лист снизу: 0.8 / 0.3
    sheet: { type: spring, visualDuration: 0.3, bounce: 0.2 },
    // поворот: 0.8 / 0.4
    turn: { type: spring, visualDuration: 0.4, bounce: 0.2 },
};

/* Короткие переходы без пружины — там, где меняется только цвет или
   прозрачность: пружинить нечему, а экспоненциальный выход читается как
   «быстро началось и успокоилось». Числа те же, что в CSS-токенах. */
export const EASE = {
    quick: { duration: 0.12, ease: [0.22, 1, 0.36, 1] },
    base: { duration: 0.2, ease: [0.22, 1, 0.36, 1] },
    slow: { duration: 0.32, ease: [0.22, 1, 0.36, 1] },
};

/* ---------- prefers-reduced-motion ----------
   Спрашиваем систему при каждом вызове, а не один раз при загрузке: человек
   может включить настройку, не перезагружая страницу (на macOS и iOS это
   один тумблер в «Универсальном доступе»). */
const reduceQuery =
    typeof window !== 'undefined' && window.matchMedia
        ? window.matchMedia('(prefers-reduced-motion: reduce)')
        : null;

export function prefersReducedMotion() {
    return !!(reduceQuery && reduceQuery.matches);
}

/* Заглушка с тем же интерфейсом, что у анимации Motion: код, который ждёт
   .finished или зовёт .stop(), не должен знать, что движения не было. */
function instant() {
    return { finished: Promise.resolve(), stop() {}, cancel() {}, complete() {} };
}

/* ---------- Прерываемость ----------
   «Схватил на середине — не дёргается» значит: новая анимация того же
   элемента начинается с текущих ЖИВЫХ значений, а не с нуля. Motion делает
   это сам, если предыдущую анимацию не отменять принудительно, а просто
   запустить новую на тех же свойствах — поэтому .stop() здесь нет.
   Храним последнюю анимацию, только чтобы вызывающий код мог её дождаться. */
const running = new WeakMap();

/**
 * Единственный способ подвигать элемент в этом сервисе.
 * @param {Element} el
 * @param {object} keyframes — что меняем (transform/opacity/filter…)
 * @param {object} options — пресет из SPRING/EASE плюс delay и т.п.
 */
export function move(el, keyframes, options = SPRING.move) {
    if (!el) return instant();
    if (prefersReducedMotion()) {
        // Движения нет, но КОНЕЧНОЕ состояние обязано наступить: иначе
        // элемент останется прозрачным или сдвинутым и просто пропадёт.
        animate(el, keyframes, { duration: 0 });
        return instant();
    }
    const a = animate(el, keyframes, options);
    running.set(el, a);
    return a;
}

/** Появление: снизу и из прозрачности. */
export function enter(el, { y = 8, preset = SPRING.move } = {}) {
    if (!el) return instant();
    return move(el, { opacity: [0, 1], transform: [`translateY(${y}px)`, 'translateY(0px)'] }, preset);
}

/** Исчезновение. Возвращает промис: вызывающий сам решает, когда снимать узел. */
export function exit(el, { y = 8, preset = EASE.quick } = {}) {
    if (!el) return instant();
    return move(el, { opacity: [1, 0], transform: [`translateY(${y}px)`] }, preset);
}

/** Лист снизу — на телефоне диалог приезжает оттуда, где палец. */
export function sheetIn(el) {
    if (!el) return instant();
    return move(el, { transform: ['translateY(16px) scale(0.97)', 'translateY(0px) scale(1)'], opacity: [0, 1] }, SPRING.sheet);
}

export { animate };
