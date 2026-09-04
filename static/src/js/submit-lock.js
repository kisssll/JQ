// static/src/js/submit-lock.js
// Защита от двойной отправки формы.
//
// Инцидент 04.09.2026: регистрация отвечает ~1,5 с (bcrypt + запросы в базу),
// всё это время кнопка молчала и оставалась активной. Человек нажал ещё раз —
// первый запрос успел создать аккаунт, второй увидел этот же номер занятым и
// вернул «Пользователь с таким телефоном уже зарегистрирован» на номер,
// который зарегистрировался секунду назад.
//
// Включается атрибутом data-submit-lock на <form> — только там, где повтор
// действительно вреден (вход, регистрация, сброс пароля). Вешать на всё
// подряд нельзя: AJAX-формы остаются на странице, и кнопка залипла бы.
(function () {
    var LOCKED = 'data-submit-lock';

    function buttonOf(form) {
        return form.querySelector('button[type="submit"], input[type="submit"]');
    }

    function unlock(form) {
        form.dataset.submitting = '';
        var btn = buttonOf(form);
        if (!btn) return;
        btn.disabled = false;
        btn.style.opacity = '1';
        btn.style.cursor = 'pointer';
        if (btn.dataset.lockLabel) {
            btn.textContent = btn.dataset.lockLabel;
            btn.dataset.lockLabel = '';
        }
    }

    document.addEventListener('submit', function (e) {
        var form = e.target;
        if (!(form instanceof HTMLFormElement)) return;
        if (!form.hasAttribute(LOCKED)) return;

        // Сабмит мог отменить кто-то другой (диалог подтверждения из
        // ui-feedback.js делает это в capture-фазе) — запрос ещё не ушёл,
        // гасить нечего: замок поставим на следующем, настоящем сабмите.
        if (e.defaultPrevented) return;

        if (form.dataset.submitting === '1') {
            e.preventDefault();
            return;
        }
        form.dataset.submitting = '1';

        var btn = buttonOf(form);
        if (!btn) return;
        // Гасим кнопку СЛЕДУЮЩИМ тиком: отключённый контрол не попадает в
        // тело запроса, а submitter у формы может нести name/value.
        setTimeout(function () {
            btn.disabled = true;
            btn.style.opacity = '0.6';
            btn.style.cursor = 'not-allowed';
            if (btn.tagName === 'BUTTON') {
                btn.dataset.lockLabel = btn.textContent;
                btn.textContent = 'Отправляем…';
            }
        }, 0);
    });

    // Возврат «назад» отдаёт страницу из bfcache в том же виде, в каком её
    // покинули, — с погашенной кнопкой. Снимаем замок.
    window.addEventListener('pageshow', function (e) {
        if (!e.persisted) return;
        var forms = document.querySelectorAll('form[' + LOCKED + ']');
        for (var i = 0; i < forms.length; i++) unlock(forms[i]);
    });
})();
