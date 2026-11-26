// static/src/js/salon-detail.js — запись на странице салона и мастера.
//
// Заход «витрина» (решение 0011, п. 13). Что изменилось по сравнению с прежней
// версией:
//
//   * шагов четыре, а не пять: шаг «Напоминание» убран, потому что его выбор
//     («за 30 минут / за час / за два / за день» и выключатель) никуда не
//     уходил — POST /api/v1/bookings принимает только мастера, услугу и время,
//     а напоминание сервер ставит сам за два часа. Страница теперь говорит об
//     этом словами вместо шага, которого нет;
//   * сводка одна. Раньше в разметке лежали четыре её копии с id вида
//     selected-master-name-4, и каждый шаг переписывал имя мастера в пяти
//     местах;
//   * виджет ОДИН на страницу и переезжает между липкой колонкой (широкий
//     экран) и листом снизу (телефон). Две копии одних и тех же полей — это
//     две копии одних и тех же id;
//   * в соло (один мастер) шага выбора мастера нет вовсе.
import { esc } from './escape-html.js';
import { toastNetworkError } from './ui-feedback.js';
import { open as openSheet, close as closeSheet } from './sheet.js';

const MONTHS = ['янв', 'фев', 'мар', 'апр', 'май', 'июн',
                'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
const WEEKDAYS = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'];

/** Ширина, с которой запись живёт в колонке справа, а не в листе снизу.
 *  То же число стоит в salon-detail.css — здесь оно нужно, чтобы перенести
 *  узел, и держать его в двух местах неизбежно; поэтому оно одно и названо. */
const WIDE = '(min-width: 900px)';
const wide = window.matchMedia(WIDE);

const DEFAULT_HAIR_TAGS = [
    "Обесцвеченные / блонд",
    "Окрашенные",
    "Натуральные (не окрашены)",
    "Седина",
    "Ранее делался кератин / ботокс",
    "Наращенные волосы",
    "Химическая завивка",
    "Сухие / секущиеся концы",
    "Густые и жесткие",
    "Пористые / пушащиеся",
    "Тонкие / склонные к ломкости",
    "Чувствительная кожа головы"
];

function money(service) {
    const low = service.price.toLocaleString('ru-RU');
    return service.price_max === null || service.price_max === undefined
        ? `${low} ₽`
        : `от ${low} до ${service.price_max.toLocaleString('ru-RU')} ₽`;
}

/** Локальная дата YYYY-MM-DD. Не toISOString: он переводит в UTC, и в поясах
 *  впереди UTC кнопка «27» отправляла «26». */
function ymd(d) {
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    return `${d.getFullYear()}-${mm}-${dd}`;
}

function hhmm(value) {
    // Слот приходит как «2026-10-04T15:00» — местное время салона, без зоны.
    // new Date() на такой строке в части браузеров трактует её как UTC, поэтому
    // время берём из самой строки, а не из объекта даты.
    const m = /T(\d{2}:\d{2})/.exec(value);
    return m ? m[1] : '';
}

document.addEventListener('DOMContentLoaded', function () {
    setupFavorites();

    const widget = document.getElementById('bookingWidget');
    if (!widget) return;

    const masters = JSON.parse(widget.dataset.masters || '[]');
    const userData = JSON.parse(widget.dataset.user || 'null');
    const preset = JSON.parse(widget.dataset.preset || '{}');
    // Текст подтверждения берём из data-атрибута, а не из строки здесь: он
    // разный у соло и команды и живёт в одном реестре (public_words).
    const doneText = widget.dataset.done || '';
    const maxDays = parseInt(widget.dataset.maxDays, 10) || 60;
    const solo = widget.dataset.solo === '1';
    const body = widget.querySelector('#bookBody');
    const back = widget.querySelector('[data-book-back]');
    const backLabel = widget.querySelector('[data-book-back-label]');

    const state = {
        master: solo ? masters[0] : null,
        service: null,
        date: null,
        time: null,
        hairSurvey: {
            lengthId: 4,
            lengthTitle: "Средние (до лопаток)",
            lengthCm: "~40–45 см",
            typeId: "straight",
            hairType: "Прямые, гладкие",
            densityId: "medium",
            hairDensity: "Средняя густота",
            tags: [],
            customAnswers: {},
        }
    };

    const LENGTH_OPTIONS = [
        { id: 1, title: 'Очень короткие', sub: 'пикси', cm: 'до 15 см' },
        { id: 2, title: 'Короткие', sub: 'боб / каре', cm: '~20 см' },
        { id: 3, title: 'До плеч', sub: 'до плеч', cm: '~30 см' },
        { id: 4, title: 'Средние', sub: 'до лопаток', cm: '~40–45 см' },
        { id: 5, title: 'Длинные', sub: 'до талии', cm: '~55–60 см' },
        { id: 6, title: 'Очень длинные', sub: 'до ягодиц', cm: '~70–75 см' },
        { id: 7, title: 'Экстремально длинные', sub: 'ниже бедер', cm: 'от 80 см' }
    ];

    const TYPE_OPTIONS = [
        { id: 'straight', title: 'Прямые, гладкие', desc: 'Ровные, легко укладываются', img: '/static/images/hair/hair_type_straight.webp' },
        { id: 'wavy', title: 'Легкая волна', desc: 'Пушатся во влажную погоду', img: '/static/images/hair/hair_type_wavy.webp' },
        { id: 'curly', title: 'Кудрявые / вьющиеся', desc: 'Четкий завиток', img: '/static/images/hair/hair_type_curly.webp' },
        { id: 'coarse', title: 'Жесткие, стекловидные', desc: 'Плохо поддаются укладке', img: '/static/images/hair/hair_type_coarse.webp' }
    ];

    const DENSITY_OPTIONS = [
        { id: 'thin', title: 'Не густые', desc: 'Тонкий хвост', img: '/static/images/hair/hair_density_thin.webp' },
        { id: 'medium', title: 'Средняя густота', desc: 'Стандартная', img: '/static/images/hair/hair_density_medium.webp' },
        { id: 'thick', title: 'Очень густые', desc: 'Объемный хвост', img: '/static/images/hair/hair_density_thick.webp' }
    ];

    function hasHairSurvey() {
        if (!state.master || !state.master.hair_survey || !state.master.hair_survey.enabled) return false;
        const s = getSurveySettings();
        const hasStd = (s.q_length_enabled !== false) ||
                       (s.q_density_enabled !== false) ||
                       (s.q_type_enabled !== false) ||
                       (s.q_tags_enabled !== false);
        const hasCq = Array.isArray(s.custom_questions) && s.custom_questions.some(function (q) { return q.enabled !== false; });
        return Boolean(hasStd || hasCq);
    }

    function currentSteps() {
        const survey = hasHairSurvey();
        if (solo) {
            return survey ? ['service', 'hair_survey', 'time', 'confirm'] : ['service', 'time', 'confirm'];
        }
        return survey ? ['master', 'service', 'hair_survey', 'time', 'confirm'] : ['master', 'service', 'time', 'confirm'];
    }

    const BACK_LABEL = {
        master: 'К мастерам',
        service: 'К мастерам',
        hair_survey: 'К услугам',
        time: 'К выбору',
        confirm: 'К времени'
    };
    let step = currentSteps()[0];

    function go(next) {
        step = next;
        const steps = currentSteps();
        const index = steps.indexOf(step);
        back.hidden = index <= 0;
        if (!back.hidden) {
            const prevStep = steps[index - 1];
            backLabel.textContent = (prevStep === 'hair_survey' ? 'К анкете волос' : (BACK_LABEL[prevStep] || 'Назад'));
        }
        render();
    }

    back.addEventListener('click', function () {
        const steps = currentSteps();
        const index = steps.indexOf(step);
        if (index <= 0) return;
        const prev = steps[index - 1];
        if (prev === 'master') { state.master = null; state.service = null; }
        if (prev === 'service') { state.service = null; }
        if (prev === 'time') { state.time = null; }
        go(prev);
    });

    function render() {
        if (step === 'master') return renderMasters();
        if (step === 'service') return renderServices();
        if (step === 'hair_survey') return renderHairSurvey();
        if (step === 'time') return renderTime();
        return renderConfirm();
    }

    // ---------- Мастер ----------
    function renderMasters() {
        body.innerHTML = masters.map(function (m) {
            const meta = [m.specialization, m.experience ? `опыт ${m.experience} лет` : '']
                .filter(Boolean).join(' · ');
            return `
                <button type="button" class="pick" data-master="${m.id}">
                    <span class="r-mark r-mark--md" aria-hidden="true">${esc(m.name[0] || '?')}</span>
                    <span class="pick__body">
                        <strong>${esc(m.name)}</strong>
                        <small>${esc(meta)}</small>
                    </span>
                </button>`;
        }).join('') || '<p class="r-text r-muted">Мастеров пока нет.</p>';
    }

    // ---------- Услуга ----------
    function renderServices() {
        const list = (state.master && state.master.services) || [];
        if (!list.length) {
            body.innerHTML = '<p class="r-text r-muted">У мастера пока нет услуг.</p>';
            return;
        }
        body.innerHTML = list.map(function (s) {
            return `
                <button type="button" class="pick" data-service="${s.id}">
                    <span class="pick__body">
                        <strong>${esc(s.name)}</strong>
                        <small>${esc(String(s.duration))} мин</small>
                    </span>
                    <span class="pick__price">${esc(money(s))}</span>
                </button>`;
        }).join('');
    }

    // ---------- Анкета волос ----------
    function getSurveySettings() {
        return (state.master && state.master.hair_survey && state.master.hair_survey.settings) || {};
    }

    function calcSurveyDeltas() {
        const settings = getSurveySettings();
        let addPrice = 0;
        let addDur = 0;

        // 1. Длина
        let lenPrice = 0;
        let lenDur = 0;
        if (settings.q_length_enabled !== false) {
            const lenRules = settings.length_rules || {};
            const curLenRule = lenRules[String(state.hairSurvey.lengthId)] || {};
            lenPrice = parseInt(curLenRule.price, 10) || 0;
            lenDur = parseInt(curLenRule.duration, 10) || 0;
            addPrice += lenPrice;
            addDur += lenDur;
        }

        // 2. Тип
        let typePrice = 0;
        let typeDur = 0;
        if (settings.q_type_enabled !== false) {
            const typeRules = settings.type_rules || {};
            const curTypeRule = typeRules[state.hairSurvey.typeId] || {};
            typePrice = parseInt(curTypeRule.price, 10) || 0;
            typeDur = parseInt(curTypeRule.duration, 10) || 0;
            addPrice += typePrice;
            addDur += typeDur;
        }

        // 3. Густота
        let densPrice = 0;
        let densDur = 0;
        if (settings.q_density_enabled !== false) {
            const densRules = settings.density_rules || {};
            const curDensRule = densRules[state.hairSurvey.densityId] || {};
            densPrice = parseInt(curDensRule.price, 10) || 0;
            densDur = parseInt(curDensRule.duration, 10) || 0;
            addPrice += densPrice;
            addDur += densDur;
        }

        // 4. Теги / особенности
        if (settings.q_tags_enabled !== false) {
            const customTags = settings.custom_tags || [];
            const tagMap = {};
            customTags.forEach(function (t) {
                if (typeof t === 'object' && t.name) tagMap[t.name] = t;
            });
            (state.hairSurvey.tags || []).forEach(function (tName) {
                const tObj = tagMap[tName];
                if (tObj) {
                    addPrice += parseInt(tObj.price, 10) || 0;
                    addDur += parseInt(tObj.duration, 10) || 0;
                }
            });
        }

        // 5. Произвольные вопросы конструктора Google Forms
        if (state.hairSurvey.customAnswers) {
            Object.values(state.hairSurvey.customAnswers).forEach(function (ans) {
                if (ans) {
                    addPrice += parseInt(ans.addPrice, 10) || 0;
                    addDur += parseInt(ans.addDur, 10) || 0;
                }
            });
        }

        state.hairSurvey.extraPrice = addPrice;
        state.hairSurvey.extraDuration = addDur;

        return {
            addPrice: addPrice,
            addDur: addDur,
            lenPrice: lenPrice,
            lenDur: lenDur,
            typePrice: typePrice,
            typeDur: typeDur,
            densPrice: densPrice,
            densDur: densDur,
        };
    }

    function formatDelta(price, dur) {
        if (!price && !dur) return '';
        const parts = [];
        if (price > 0) parts.push(`+${price.toLocaleString('ru-RU')} ₽`);
        if (dur > 0) parts.push(`+${dur} мин`);
        return parts.join(' · ');
    }

    function updateSurveySummaryView() {
        const deltas = calcSurveyDeltas();
        const extraVal = document.getElementById('hairSurveyExtraVal');
        const totalVal = document.getElementById('hairSurveyTotalVal');
        const lenDeltaEl = document.getElementById('hairLengthDelta');

        if (lenDeltaEl) {
            const lText = formatDelta(deltas.lenPrice, deltas.lenDur);
            lenDeltaEl.textContent = lText ? `Коррекция за длину: ${lText}` : 'Базовая длина без надбавки';
        }

        if (state.service) {
            const basePrice = state.service.price || 0;
            const baseDur = state.service.duration || 0;
            const totalPrice = basePrice + deltas.addPrice;
            const totalDur = baseDur + deltas.addDur;

            if (extraVal) {
                extraVal.textContent = deltas.addPrice || deltas.addDur
                    ? `+${deltas.addPrice.toLocaleString('ru-RU')} ₽ · +${deltas.addDur} мин`
                    : 'Без изменений (+0 ₽, +0 мин)';
            }
            if (totalVal) {
                totalVal.textContent = `${totalPrice.toLocaleString('ru-RU')} ₽ · ${totalDur} мин`;
            }
        }
    }

    function renderHairSurvey() {
        const settings = getSurveySettings();
        const customTags = settings.custom_tags || settings.tags || DEFAULT_HAIR_TAGS;
        const curLength = LENGTH_OPTIONS.find(function (x) { return x.id === state.hairSurvey.lengthId; }) || LENGTH_OPTIONS[3];
        const deltas = calcSurveyDeltas();

        let qCounter = 1;
        const sectionsHtml = [];

        // 1. Длина
        if (settings.q_length_enabled !== false) {
            const lenDeltaStr = formatDelta(deltas.lenPrice, deltas.lenDur);
            sectionsHtml.push(`
                <div class="hair-survey__section">
                    <div class="hair-survey__section-head">
                        <span class="hair-survey__label">${qCounter++}. Длина волос (шкала с ползунком)</span>
                        <span class="hair-survey__badge" id="hairLengthCm">${esc(curLength.cm)}</span>
                    </div>

                    <div class="hair-len-stage">
                        <div class="hair-len-figure-wrap">
                            <img id="hairLengthDynamicImg" src="/static/images/hair/hair_len_${curLength.id}.webp" class="hair-dynamic-img" alt="${esc(curLength.title)}">
                        </div>
                        <div class="hair-len-desc">
                            <div class="hair-len-title-row">
                                <strong id="hairLengthTitle" style="font-size:1rem;color:var(--color-heading);">${esc(curLength.title)} (${esc(curLength.sub)})</strong>
                            </div>
                            <div class="hair-len-delta" id="hairLengthDelta">
                                ${lenDeltaStr ? `Коррекция за длину: ${esc(lenDeltaStr)}` : 'Базовая длина без надбавки'}
                            </div>
                        </div>

                        <div class="hair-slider-wrap">
                            <input type="range" min="1" max="7" step="1" value="${curLength.id}"
                                   class="hair-range" id="hairLengthRange" aria-label="Длина волос">
                            <div class="hair-slider-labels">
                                <span>Пикси</span>
                                <span>До плеч</span>
                                <span>До талии</span>
                                <span>80+ см</span>
                            </div>
                        </div>

                        <!-- Иллюстрация со всеми вариантами длины под шкалой -->
                        <div class="hair-strip-overview">
                            <div class="hair-strip-overview__label">Все варианты длины со шкалой:</div>
                            <img src="/static/images/hair/hair_lengths_full.webp" class="hair-strip-img" alt="Все длины волос" loading="lazy">
                        </div>
                    </div>
                </div>
            `);
        }

        // 2. Густота карточки
        if (settings.q_density_enabled !== false) {
            const densRules = settings.density_rules || {};
            const densityCardsHtml = DENSITY_OPTIONS.map(function (opt) {
                const active = state.hairSurvey.densityId === opt.id ? ' is-active' : '';
                const rule = densRules[opt.id] || {};
                const dStr = formatDelta(parseInt(rule.price, 10) || 0, parseInt(rule.duration, 10) || 0);
                const deltaBadge = dStr ? `<span class="hair-card-btn__delta">${esc(dStr)}</span>` : '';
                return `
                    <button type="button" class="hair-card-btn${active}" data-hair-density="${esc(opt.id)}" aria-label="${esc(opt.title)}">
                        <span class="hair-card-btn__check" aria-hidden="true">✓</span>
                        <span class="hair-card-btn__thumb">
                            <img src="${opt.img}" class="hair-card-btn__img" alt="${esc(opt.title)}" loading="lazy">
                        </span>
                        <span class="hair-card-btn__title">${esc(opt.title)}</span>
                        <span class="hair-card-btn__desc">${esc(opt.desc)}</span>
                        ${deltaBadge}
                    </button>
                `;
            }).join('');

            sectionsHtml.push(`
                <div class="hair-survey__section">
                    <div class="hair-survey__section-head">
                        <span class="hair-survey__label">${qCounter++}. Густота волос</span>
                    </div>
                    <div class="hair-grid hair-grid--density">
                        ${densityCardsHtml}
                    </div>
                </div>
            `);
        }

        // 3. Тип карточки
        if (settings.q_type_enabled !== false) {
            const typeRules = settings.type_rules || {};
            const typeCardsHtml = TYPE_OPTIONS.map(function (opt) {
                const active = state.hairSurvey.typeId === opt.id ? ' is-active' : '';
                const rule = typeRules[opt.id] || {};
                const dStr = formatDelta(parseInt(rule.price, 10) || 0, parseInt(rule.duration, 10) || 0);
                const deltaBadge = dStr ? `<span class="hair-card-btn__delta">${esc(dStr)}</span>` : '';
                return `
                    <button type="button" class="hair-card-btn${active}" data-hair-type="${esc(opt.id)}" aria-label="${esc(opt.title)}">
                        <span class="hair-card-btn__check" aria-hidden="true">✓</span>
                        <span class="hair-card-btn__thumb">
                            <img src="${opt.img}" class="hair-card-btn__img" alt="${esc(opt.title)}" loading="lazy">
                        </span>
                        <span class="hair-card-btn__title">${esc(opt.title)}</span>
                        <span class="hair-card-btn__desc">${esc(opt.desc)}</span>
                        ${deltaBadge}
                    </button>
                `;
            }).join('');

            sectionsHtml.push(`
                <div class="hair-survey__section">
                    <div class="hair-survey__section-head">
                        <span class="hair-survey__label">${qCounter++}. Тип и структура волос</span>
                    </div>
                    <div class="hair-grid hair-grid--types">
                        ${typeCardsHtml}
                    </div>
                </div>
            `);
        }

        // 4. Особенности / теги
        if (settings.q_tags_enabled !== false) {
            const tagsHtml = customTags.map(function (t) {
                const tName = typeof t === 'object' ? t.name : t;
                const tPrice = typeof t === 'object' ? (parseInt(t.price, 10) || 0) : 0;
                const tDur = typeof t === 'object' ? (parseInt(t.duration, 10) || 0) : 0;
                const active = state.hairSurvey.tags.includes(tName) ? ' is-active' : '';
                const dStr = formatDelta(tPrice, tDur);
                const deltaBadge = dStr ? `<span class="hair-tag-delta">(${esc(dStr)})</span>` : '';
                return `
                    <button type="button" class="hair-tag-pill${active}" data-hair-tag="${esc(tName)}">
                        <span class="hair-tag-check">✓</span>
                        <span>${esc(tName)}</span>
                        ${deltaBadge}
                    </button>
                `;
            }).join('');

            sectionsHtml.push(`
                <div class="hair-survey__section">
                    <div class="hair-survey__section-head">
                        <span class="hair-survey__label">${qCounter++}. Особенности волос (отметьте подходящее)</span>
                    </div>
                    <div class="hair-tags">
                        ${tagsHtml}
                    </div>
                </div>
            `);
        }

        // 5. Конструкторские вопросы (Google Forms)
        const customQuestions = settings.custom_questions || [];
        customQuestions.forEach(function (q) {
            if (q.enabled === false) return;
            const qid = String(q.id);
            const currentAns = (state.hairSurvey.customAnswers && state.hairSurvey.customAnswers[qid]) || {};
            const qTitle = q.title || 'Вопрос';
            const qDesc = q.desc ? `<p style="margin:0 0 0.5rem;font-size:0.8125rem;color:var(--color-muted);">${esc(q.desc)}</p>` : '';
            const isReq = q.required ? '<span style="color:var(--color-accent-text);margin-left:3px;" title="Обязательный">*</span>' : '';

            let contentHtml = '';
            if (q.type === 'single') {
                const optHtml = (q.options || []).map(function (opt) {
                    const sel = (currentAns.option_ids || []).includes(opt.id) ? ' is-active' : '';
                    const dStr = formatDelta(parseInt(opt.price, 10) || 0, parseInt(opt.duration, 10) || 0);
                    const deltaBadge = dStr ? `<span class="hair-card-btn__delta">${esc(dStr)}</span>` : '';
                    return `
                        <button type="button" class="hair-card-btn${sel}" data-cq-single="${esc(qid)}" data-cq-opt="${esc(opt.id)}" style="padding:0.6rem 0.8rem;text-align:left;align-items:flex-start;">
                            <span class="hair-card-btn__check" aria-hidden="true">✓</span>
                            <span class="hair-card-btn__title">${esc(opt.title)}</span>
                            ${deltaBadge}
                        </button>
                    `;
                }).join('');
                contentHtml = `<div class="hair-grid" style="grid-template-columns:repeat(auto-fit, minmax(140px, 1fr));gap:0.5rem;">${optHtml}</div>`;
            } else if (q.type === 'multiple') {
                const optHtml = (q.options || []).map(function (opt) {
                    const sel = (currentAns.option_ids || []).includes(opt.id) ? ' is-active' : '';
                    const dStr = formatDelta(parseInt(opt.price, 10) || 0, parseInt(opt.duration, 10) || 0);
                    const deltaBadge = dStr ? `<span class="hair-tag-delta">(${esc(dStr)})</span>` : '';
                    return `
                        <button type="button" class="hair-tag-pill${sel}" data-cq-multi="${esc(qid)}" data-cq-opt="${esc(opt.id)}">
                            <span class="hair-tag-check">✓</span>
                            <span>${esc(opt.title)}</span>
                            ${deltaBadge}
                        </button>
                    `;
                }).join('');
                contentHtml = `<div class="hair-tags">${optHtml}</div>`;
            } else if (q.type === 'text') {
                contentHtml = `
                    <div>
                        <input type="text" class="r-input" data-cq-text="${esc(qid)}"
                               value="${esc(currentAns.text || '')}"
                               placeholder="Введите ваш ответ..." style="width:100%;font-size:0.875rem;padding:0.45rem 0.75rem;">
                    </div>
                `;
            }

            sectionsHtml.push(`
                <div class="hair-survey__section">
                    <div class="hair-survey__section-head">
                        <span class="hair-survey__label">${qCounter++}. ${esc(qTitle)}${isReq}</span>
                    </div>
                    ${qDesc}
                    ${contentHtml}
                </div>
            `);
        });

        const basePrice = state.service ? (state.service.price || 0) : 0;
        const baseDur = state.service ? (state.service.duration || 0) : 0;
        const totalPrice = basePrice + deltas.addPrice;
        const totalDur = baseDur + deltas.addDur;

        body.innerHTML = `
            <div class="hair-survey" role="region" aria-label="Консультация мастера">
                <div class="hair-survey__intro">
                    <p class="hair-survey__hint">
                        Перед выбором времени укажите параметры и особенности волос. Мы сразу рассчитаем точную стоимость и длительность процедуры для идеального результата.
                    </p>
                </div>

                ${sectionsHtml.join('')}

                <!-- Итоговый блок стоимости и тайминга -->
                <div class="hair-survey-summary">
                    <div class="hair-survey-summary__row">
                        <span>Базовая услуга:</span>
                        <span>${state.service ? esc(money(state.service)) : ''} (${baseDur} мин)</span>
                    </div>
                    <div class="hair-survey-summary__row hair-survey-summary__row--extra" id="hairSurveyExtraRow">
                        <span>Надбавка за параметры волос:</span>
                        <span id="hairSurveyExtraVal">${deltas.addPrice || deltas.addDur ? `+${deltas.addPrice.toLocaleString('ru-RU')} ₽ · +${deltas.addDur} мин` : 'Без изменений (+0 ₽, +0 мин)'}</span>
                    </div>
                    <div class="hair-survey-summary__total">
                        <span>Итоговая цена и время:</span>
                        <strong id="hairSurveyTotalVal">${totalPrice.toLocaleString('ru-RU')} ₽ · ${totalDur} мин</strong>
                    </div>
                </div>

                <div style="margin-top: var(--space-12);">
                    <button type="button" class="r-btn r-btn--primary r-btn--block" id="hairSurveyNext">
                        <span class="r-btn__label">Перейти к выбору времени</span>
                    </button>
                </div>
            </div>
        `;
    }

    // ---------- Дата и время ----------
    let slotsRequest = 0;

    function renderTime() {
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        let strip = '';
        for (let i = 0; i < maxDays; i++) {
            const d = new Date(today);
            d.setDate(d.getDate() + i);
            const key = ymd(d);
            strip += `
                <button type="button" class="day${key === state.date ? ' is-active' : ''}"
                        data-date="${key}">
                    <span class="day__dow">${i === 0 ? 'сегодня' : WEEKDAYS[d.getDay()]}</span>
                    <span class="day__num">${d.getDate()}</span>
                    <span class="day__mon">${MONTHS[d.getMonth()]}</span>
                </button>`;
        }
        body.innerHTML = `
            <div class="days" role="group" aria-label="Дата записи">${strip}</div>
            <div class="r-slots" id="bookSlots" aria-live="polite"></div>`;
        if (state.date) loadSlots();
        else document.getElementById('bookSlots').innerHTML =
            '<p class="book__empty">Выберите день — покажем свободное время.</p>';
    }

    function loadSlots() {
        const grid = document.getElementById('bookSlots');
        if (!grid) return;
        grid.innerHTML = '<p class="book__empty">Загрузка…</p>';
        // Быстро перещёлкивая дни, можно получить ответы не по порядку — рисуем
        // только ответ на ПОСЛЕДНИЙ выбор.
        const id = ++slotsRequest;
        const extraDur = (state.hairSurvey && state.hairSurvey.extraDuration) || 0;
        fetch(`/api/v1/bookings/available/${state.master.id}` +
              `?date=${state.date}&service_id=${state.service.id}&extra_duration=${extraDur}`)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (id !== slotsRequest) return;
                if (!data.slots || !data.slots.length) {
                    grid.innerHTML = '<p class="book__empty">' +
                        esc(data.message || 'В этот день свободного времени нет — выберите другой') +
                        '</p>';
                    return;
                }
                grid.innerHTML = data.slots.map(function (slotValue) {
                    return `<button type="button" class="r-slot` +
                        (slotValue === state.time ? ' is-active' : '') +
                        `" data-slot="${esc(slotValue)}">${esc(hhmm(slotValue))}</button>`;
                }).join('');
            })
            .catch(function () {
                if (id !== slotsRequest) return;
                grid.innerHTML = '<p class="book__empty">Не удалось загрузить время. ' +
                    'Проверьте связь и выберите день снова.</p>';
            });
    }

    // ---------- Подтверждение ----------
    function renderConfirm() {
        const m = state.master;
        const s = state.service;
        const dateObj = new Date(state.date + 'T00:00:00');
        const when = `${dateObj.getDate()} ${MONTHS[dateObj.getMonth()]}, ${hhmm(state.time)}`;
        const who = userData
            ? `<div class="book__row"><dt>Вы</dt><dd>${esc(userData.full_name || '')}` +
              `${userData.phone ? ' · ' + esc(userData.phone) : ''}</dd></div>`
            : '';
        let surveyRow = '';
        let priceDisplay = money(s);
        let durationDisplay = `${s.duration} мин`;

        if (hasHairSurvey() && state.hairSurvey) {
            const deltas = calcSurveyDeltas();
            const settings = getSurveySettings();
            const parts = [];
            if (settings.q_length_enabled !== false) {
                parts.push(`${state.hairSurvey.lengthTitle} (${state.hairSurvey.lengthCm})`);
            }
            if (settings.q_type_enabled !== false) {
                parts.push(state.hairSurvey.hairType);
            }
            if (settings.q_density_enabled !== false) {
                parts.push(state.hairSurvey.hairDensity);
            }
            if (settings.q_tags_enabled !== false && state.hairSurvey.tags && state.hairSurvey.tags.length) {
                parts.push(state.hairSurvey.tags.join(', '));
            }
            if (state.hairSurvey.customAnswers) {
                Object.values(state.hairSurvey.customAnswers).forEach(function (ans) {
                    if (!ans) return;
                    if (ans.type === 'single' || ans.type === 'multiple') {
                        if (ans.option_titles && ans.option_titles.length) {
                            parts.push(`${ans.question_title}: ${ans.option_titles.join(', ')}`);
                        }
                    } else if (ans.type === 'text' && ans.text) {
                        parts.push(`${ans.question_title}: ${ans.text}`);
                    }
                });
            }
            if (parts.length) {
                surveyRow = `
                    <div class="book__row book__row--survey"><dt>Волосы</dt>
                        <dd>${esc(parts.join(' · '))}</dd></div>`;
            }

            if (deltas.addPrice > 0 || deltas.addDur > 0) {
                const totalP = (s.price || 0) + deltas.addPrice;
                const totalD = (s.duration || 0) + deltas.addDur;
                priceDisplay = `${totalP.toLocaleString('ru-RU')} ₽ (базовая ${s.price} ₽ + ${deltas.addPrice} ₽ за параметры)`;
                durationDisplay = `${totalD} мин (${s.duration} + ${deltas.addDur} мин)`;
            }
        }
        body.innerHTML = `
            <dl class="book__sum">
                <div class="book__row"><dt>Мастер</dt><dd>${esc(m.name)}</dd></div>
                <div class="book__row"><dt>Услуга</dt>
                    <dd>${esc(s.name)} · ${esc(durationDisplay)}</dd></div>
                <div class="book__row"><dt>Цена</dt><dd class="tabular-nums">${esc(priceDisplay)}</dd></div>
                <div class="book__row"><dt>Когда</dt><dd class="tabular-nums">${esc(when)}</dd></div>
                ${surveyRow}
                ${who}
            </dl>
            <p class="book__error" id="bookError" role="alert"></p>
            <button type="button" class="r-btn r-btn--primary r-btn--block" id="bookSubmit">
                <span class="r-btn__label">${userData ? 'Записаться' : 'Войти и записаться'}</span>
                <span class="r-btn__spinner" aria-hidden="true"></span>
            </button>`;
    }

    async function submit(btn) {
        if (!userData) {
            // Гостя отправляем входить, запомнив выбор: вернувшись, он попадает
            // сразу на подтверждение, а не проходит три шага заново.
            localStorage.setItem('bookingState', JSON.stringify({
                masterId: state.master.id, serviceId: state.service.id,
                date: state.date, time: state.time,
                hairSurvey: state.hairSurvey,
            }));
            window.location.href = '/login?redirect=' +
                encodeURIComponent(window.location.pathname);
            return;
        }
        const error = document.getElementById('bookError');
        btn.classList.add('is-loading');
        try {
            const payload = {
                master_id: state.master.id,
                service_id: state.service.id,
                start_time: state.time,
            };
            if (hasHairSurvey()) {
                const deltas = calcSurveyDeltas();
                const settings = getSurveySettings();
                payload.hair_survey = {
                    length: (settings.q_length_enabled !== false) ? {
                        id: state.hairSurvey.lengthId,
                        title: state.hairSurvey.lengthTitle,
                        cm: state.hairSurvey.lengthCm,
                    } : null,
                    type: (settings.q_type_enabled !== false) ? {
                        id: state.hairSurvey.typeId,
                        title: state.hairSurvey.hairType,
                    } : null,
                    density: (settings.q_density_enabled !== false) ? {
                        id: state.hairSurvey.densityId,
                        title: state.hairSurvey.hairDensity,
                    } : null,
                    features: (settings.q_tags_enabled !== false) ? state.hairSurvey.tags : [],
                    custom_answers: Object.values(state.hairSurvey.customAnswers || {}),
                    extra_price: deltas.addPrice,
                    extra_duration: deltas.addDur,
                };
            }
            const res = await fetch('/api/v1/bookings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const data = await res.json().catch(function () { return {}; });
            if (res.ok && data.id) {
                renderDone();
                return;
            }
            // Отказ называет причину и выход из неё: «это время только что
            // заняли» означает «выберите другое», а не «что-то пошло не так».
            error.textContent = data.detail ||
                'Записаться не удалось. Возможно, это время только что заняли — выберите другое.';
        } catch (err) {
            toastNetworkError();
        } finally {
            btn.classList.remove('is-loading');
        }
    }

    /** Готово. Отдельный экран, а не alert и не переход в «Мои записи»:
     *  человек должен увидеть, ЧТО именно создалось, и сам решить, уходить ли
     *  со страницы. Прежняя версия показывала системный alert и уводила. */
    function renderDone() {
        const s = state.service;
        const dateObj = new Date(state.date + 'T00:00:00');
        const when = `${dateObj.getDate()} ${MONTHS[dateObj.getMonth()]}, ${hhmm(state.time)}`;
        back.hidden = true;
        let surveyDoneRow = '';
        if (hasHairSurvey() && state.hairSurvey) {
            const settings = getSurveySettings();
            const parts = [];
            if (settings.q_length_enabled !== false) {
                parts.push(`${state.hairSurvey.lengthTitle} (${state.hairSurvey.lengthCm})`);
            }
            if (settings.q_type_enabled !== false) {
                parts.push(state.hairSurvey.hairType);
            }
            if (settings.q_density_enabled !== false) {
                parts.push(state.hairSurvey.hairDensity);
            }
            if (parts.length) {
                surveyDoneRow = `
                    <div class="book__row"><dt>Волосы</dt>
                        <dd>${esc(parts.join(' · '))}</dd></div>`;
            }
        }
        body.innerHTML = `
            <p class="book__done-title">Заявка отправлена</p>
            <p class="book__done-text">${esc(doneText)}</p>
            <dl class="book__sum">
                <div class="book__row"><dt>Услуга</dt><dd>${esc(s.name)}</dd></div>
                <div class="book__row"><dt>Когда</dt>
                    <dd class="tabular-nums">${esc(when)}</dd></div>
                ${surveyDoneRow}
            </dl>
            <a class="r-btn r-btn--secondary r-btn--block" href="/bookings">
                <span class="r-btn__label">Мои записи</span></a>`;
    }

    // ---------- Один обработчик на весь виджет ----------
    // Делегирование, а не слушатель на каждой кнопке: содержимое шага
    // перерисовывается целиком, и развешенные слушатели умирали вместе с ним.
    widget.addEventListener('click', function (ev) {
        const master = ev.target.closest('[data-master]');
        if (master) {
            state.master = masters.find(function (m) { return m.id === +master.dataset.master; });
            state.service = null;
            go('service');
            return;
        }
        const service = ev.target.closest('[data-service]');
        if (service) {
            state.service = state.master.services.find(function (s) {
                return s.id === +service.dataset.service;
            });
            state.time = null;
            if (hasHairSurvey()) {
                go('hair_survey');
            } else {
                go('time');
            }
            return;
        }
        const hairTypeBtn = ev.target.closest('[data-hair-type]');
        if (hairTypeBtn) {
            const tid = hairTypeBtn.dataset.hairType;
            const topt = TYPE_OPTIONS.find(function (x) { return x.id === tid; });
            if (topt) {
                state.hairSurvey.typeId = topt.id;
                state.hairSurvey.hairType = topt.title;
                widget.querySelectorAll('[data-hair-type]').forEach(function (btn) {
                    btn.classList.toggle('is-active', btn.dataset.hairType === tid);
                });
                updateSurveySummaryView();
            }
            return;
        }
        const hairDensityBtn = ev.target.closest('[data-hair-density]');
        if (hairDensityBtn) {
            const did = hairDensityBtn.dataset.hairDensity;
            const dopt = DENSITY_OPTIONS.find(function (x) { return x.id === did; });
            if (dopt) {
                state.hairSurvey.densityId = dopt.id;
                state.hairSurvey.hairDensity = dopt.title;
                widget.querySelectorAll('[data-hair-density]').forEach(function (btn) {
                    btn.classList.toggle('is-active', btn.dataset.hairDensity === did);
                });
                updateSurveySummaryView();
            }
            return;
        }
        const hairTagBtn = ev.target.closest('[data-hair-tag]');
        if (hairTagBtn) {
            const tag = hairTagBtn.dataset.hairTag;
            const idx = state.hairSurvey.tags.indexOf(tag);
            if (idx >= 0) {
                state.hairSurvey.tags.splice(idx, 1);
                hairTagBtn.classList.remove('is-active');
            } else {
                state.hairSurvey.tags.push(tag);
                hairTagBtn.classList.add('is-active');
            }
            updateSurveySummaryView();
            return;
        }
        const cqSingleBtn = ev.target.closest('[data-cq-single]');
        if (cqSingleBtn) {
            const qid = cqSingleBtn.dataset.cqSingle;
            const oid = cqSingleBtn.dataset.cqOpt;
            const settings = getSurveySettings();
            const qDef = (settings.custom_questions || []).find(function (q) { return String(q.id) === qid; });
            if (qDef) {
                const opt = (qDef.options || []).find(function (o) { return String(o.id) === oid; });
                if (opt) {
                    state.hairSurvey.customAnswers[qid] = {
                        question_id: qid,
                        question_title: qDef.title,
                        type: 'single',
                        option_ids: [opt.id],
                        option_titles: [opt.title],
                        addPrice: parseInt(opt.price, 10) || 0,
                        addDur: parseInt(opt.duration, 10) || 0,
                    };
                    widget.querySelectorAll(`[data-cq-single="${qid}"]`).forEach(function (btn) {
                        btn.classList.toggle('is-active', btn.dataset.cqOpt === oid);
                    });
                    updateSurveySummaryView();
                }
            }
            return;
        }
        const cqMultiBtn = ev.target.closest('[data-cq-multi]');
        if (cqMultiBtn) {
            const qid = cqMultiBtn.dataset.cqMulti;
            const oid = cqMultiBtn.dataset.cqOpt;
            const settings = getSurveySettings();
            const qDef = (settings.custom_questions || []).find(function (q) { return String(q.id) === qid; });
            if (qDef) {
                let ans = state.hairSurvey.customAnswers[qid];
                if (!ans || !Array.isArray(ans.option_ids)) {
                    ans = {
                        question_id: qid,
                        question_title: qDef.title,
                        type: 'multiple',
                        option_ids: [],
                        option_titles: [],
                        addPrice: 0,
                        addDur: 0,
                    };
                    state.hairSurvey.customAnswers[qid] = ans;
                }
                const opt = (qDef.options || []).find(function (o) { return String(o.id) === oid; });
                const idx = ans.option_ids.indexOf(oid);
                if (idx >= 0) {
                    ans.option_ids.splice(idx, 1);
                    if (opt) {
                        const tIdx = ans.option_titles.indexOf(opt.title);
                        if (tIdx >= 0) ans.option_titles.splice(tIdx, 1);
                        ans.addPrice -= (parseInt(opt.price, 10) || 0);
                        ans.addDur -= (parseInt(opt.duration, 10) || 0);
                    }
                    cqMultiBtn.classList.remove('is-active');
                } else {
                    ans.option_ids.push(oid);
                    if (opt) {
                        ans.option_titles.push(opt.title);
                        ans.addPrice += (parseInt(opt.price, 10) || 0);
                        ans.addDur += (parseInt(opt.duration, 10) || 0);
                    }
                    cqMultiBtn.classList.add('is-active');
                }
                updateSurveySummaryView();
            }
            return;
        }
        const hairNextBtn = ev.target.closest('#hairSurveyNext');
        if (hairNextBtn) {
            const settings = getSurveySettings();
            const customQuestions = settings.custom_questions || [];
            for (let i = 0; i < customQuestions.length; i++) {
                const q = customQuestions[i];
                if (q.enabled !== false && q.required) {
                    const ans = state.hairSurvey.customAnswers[String(q.id)];
                    const answered = ans && ((ans.option_ids && ans.option_ids.length > 0) || (ans.text && ans.text.trim().length > 0));
                    if (!answered) {
                        alert('Пожалуйста, ответьте на обязательный вопрос: ' + (q.title || ''));
                        return;
                    }
                }
            }
            go('time');
            return;
        }
        const day = ev.target.closest('[data-date]');
        if (day) {
            state.date = day.dataset.date;
            state.time = null;
            widget.querySelectorAll('.day').forEach(function (b) {
                b.classList.toggle('is-active', b.dataset.date === state.date);
            });
            loadSlots();
            return;
        }
        const slotBtn = ev.target.closest('[data-slot]');
        if (slotBtn) {
            state.time = slotBtn.dataset.slot;
            go('confirm');
            return;
        }
        const submitBtn = ev.target.closest('#bookSubmit');
        if (submitBtn) submit(submitBtn);
    });

    widget.addEventListener('input', function (ev) {
        if (ev.target && ev.target.id === 'hairLengthRange') {
            const val = parseInt(ev.target.value, 10);
            const opt = LENGTH_OPTIONS.find(function (x) { return x.id === val; }) || LENGTH_OPTIONS[3];
            state.hairSurvey.lengthId = opt.id;
            state.hairSurvey.lengthTitle = opt.title;
            state.hairSurvey.lengthCm = opt.cm;

            const imgEl = document.getElementById('hairLengthDynamicImg');
            if (imgEl) imgEl.src = `/static/images/hair/hair_len_${opt.id}.webp`;

            const titleEl = document.getElementById('hairLengthTitle');
            const cmEl = document.getElementById('hairLengthCm');
            if (titleEl) titleEl.textContent = `${opt.title} (${opt.sub})`;
            if (cmEl) cmEl.textContent = opt.cm;

            updateSurveySummaryView();
            return;
        }
        if (ev.target && ev.target.dataset && ev.target.dataset.cqText) {
            const qid = ev.target.dataset.cqText;
            const settings = getSurveySettings();
            const qDef = (settings.custom_questions || []).find(function (q) { return String(q.id) === qid; });
            state.hairSurvey.customAnswers[qid] = {
                question_id: qid,
                question_title: qDef ? qDef.title : '',
                type: 'text',
                text: ev.target.value.trim(),
                addPrice: 0,
                addDur: 0,
            };
        }
    });

    // ---------- Кнопка «Записаться» у мастера в команде ----------
    document.addEventListener('click', function (ev) {
        const pick = ev.target.closest('[data-book-master]');
        if (!pick) return;
        ev.preventDefault();
        const m = masters.find(function (x) { return x.id === +pick.dataset.bookMaster; });
        if (!m) return;
        state.master = m;
        state.service = null;
        go('service');
        if (!wide.matches) {
            const sheet = document.getElementById('bookSheet');
            if (sheet) openSheet(sheet, pick);
        } else {
            widget.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
    });

    // ---------- Предвыбор из карточки каталога ----------
    // Окно в каталоге уже назвало мастера, услугу и время — повторять за
    // человеком те же три шага незачем. Слот проверяется живым запросом: если
    // его успели занять, человек увидит остальные окна того же дня.
    function applyPreset() {
        if (!preset || !preset.master) return false;
        const m = masters.find(function (x) { return x.id === preset.master; });
        if (!m) return false;
        const s = (m.services || []).find(function (x) { return x.id === preset.service; });
        if (!s) return false;
        state.master = m;
        state.service = s;
        if (preset.slot && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(preset.slot)) {
            state.date = preset.slot.slice(0, 10);
            state.time = preset.slot;
            go('confirm');
        } else {
            go('time');
        }
        // На телефоне выбор живёт в листе, и он закрыт. Человек нажал на время
        // в каталоге — показать ему результат этого нажатия, а не страницу, на
        // которой «ничего не произошло».
        if (!wide.matches) {
            const sheet = document.getElementById('bookSheet');
            if (sheet) openSheet(sheet, document.querySelector('[data-sheet-open]'));
        }
        return true;
    }

    // ---------- Возврат после входа ----------
    function restore() {
        const saved = localStorage.getItem('bookingState');
        if (!saved || !userData) return false;
        localStorage.removeItem('bookingState');
        try {
            const data = JSON.parse(saved);
            const m = masters.find(function (x) { return x.id === data.masterId; });
            const s = m && (m.services || []).find(function (x) { return x.id === data.serviceId; });
            if (!m || !s) return false;
            state.master = m;
            state.service = s;
            state.date = data.date;
            state.time = data.time;
            if (data.hairSurvey) state.hairSurvey = data.hairSurvey;
            go('confirm');
            return true;
        } catch (err) {
            return false;
        }
    }

    if (!restore() && !applyPreset()) go(currentSteps()[0]);
});

// ---------- Избранное ----------
function setupFavorites() {
    const buttons = document.querySelectorAll('.salon-top-fav, .master-fav-btn');
    if (!buttons.length) return;

    fetch('/api/v1/favorites/my')
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) {
            if (!data) return;
            buttons.forEach(function (btn) {
                const ids = btn.dataset.type === 'salon' ? data.salon_ids : data.master_ids;
                const liked = (ids || []).includes(parseInt(btn.dataset.id, 10));
                btn.classList.toggle('liked', liked);
                const icon = btn.querySelector('.heart-icon');
                if (icon) {
                    icon.innerHTML = liked ? btn.dataset.iconHeartFilled : btn.dataset.iconHeart;
                }
            });
        })
        .catch(function () { /* не авторизован — сердца остаются пустыми */ });

    buttons.forEach(function (btn) {
        btn.addEventListener('click', async function (ev) {
            ev.preventDefault();
            ev.stopPropagation();
            const liked = btn.classList.contains('liked');
            try {
                const res = await fetch(
                    `/api/v1/favorites/toggle-${btn.dataset.type}/${btn.dataset.id}`,
                    { method: 'POST', headers: { 'Content-Type': 'application/json' } }
                );
                if (res.redirected && res.url.includes('/login')) {
                    window.location.href = '/login?redirect=' +
                        encodeURIComponent(window.location.pathname);
                    return;
                }
                if (!res.ok) return;
                btn.classList.toggle('liked', !liked);
                const icon = btn.querySelector('.heart-icon');
                if (icon) {
                    icon.innerHTML = !liked ? btn.dataset.iconHeartFilled : btn.dataset.iconHeart;
                }
            } catch (err) {
                toastNetworkError();
            }
        });
    });
}
