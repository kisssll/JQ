(function () {
    const calculator = document.querySelector('[data-price-calculator]');
    if (!calculator) return;

    const countInput = calculator.querySelector('#bl-calc-count');
    const countWrap = calculator.querySelector('[data-count-wrap]');
    const priceOutput = calculator.querySelector('[data-price]');
    const periodOutput = calculator.querySelector('[data-period]');
    const detailOutput = calculator.querySelector('[data-detail]');
    const checkoutLink = calculator.querySelector('[data-checkout-link]');
    const contactForm = calculator.querySelector('[data-contact-form]');
    const contactSuccess = calculator.querySelector('[data-contact-success]');
    const contactError = calculator.querySelector('[data-contact-error]');
    const contactSubmit = calculator.querySelector('[data-contact-submit]');
    const commentInput = calculator.querySelector('#bl-calc-comment');
    const commentCount = calculator.querySelector('[data-comment-count]');
    const roleInputs = calculator.querySelectorAll('input[name="bl-calc-role"]');
    const pricing = JSON.parse(calculator.dataset.pricing);

    function formatPrice(amount) {
        return `${amount.toLocaleString('ru-RU')} ₽`;
    }

    function update() {
        const role = calculator.querySelector('input[name="bl-calc-role"]:checked').value;
        const count = role === 'master' ? 1 : Number.parseInt(countInput.value, 10);
        if (!Number.isInteger(count) || (role === 'salon' && (count < 2 || count > 500))) {
            checkoutLink.disabled = true;
            detailOutput.textContent = 'Укажите число мастеров от 2 до 500.';
            contactForm.hidden = true;
            contactSuccess.hidden = true;
            return;
        }

        checkoutLink.disabled = false;
        countWrap.hidden = role !== 'salon';

        const quote = pricing[String(count)];
        const plan = quote ? quote.plan : 'custom';
        const amount = quote ? quote.amount : null;
        let detail;

        if (role === 'master') {
            detail = 'Тариф для частного мастера.';
            checkoutLink.dataset.href = '/business/checkout?plan=lite&for=master';
            checkoutLink.textContent = 'Подключить';
        } else if (plan === 'lite') {
            detail = count === 2
                ? 'Тариф «Лайт» для команды из двух мастеров.'
                : `${formatPrice(pricing['2'].amount)} за первых двух мастеров + ` +
                    `${formatPrice(pricing['3'].amount - pricing['2'].amount)} за каждого следующего.`;
            checkoutLink.dataset.href =
                `/business/checkout?plan=lite&employees=${count}&panel_mode=team`;
            checkoutLink.textContent = 'Подключить';
        } else if (plan === 'business') {
            detail = 'Тариф «Бизнес» для команды от 6 до 10 мастеров.';
            checkoutLink.dataset.href = '/business/checkout?plan=business';
            checkoutLink.textContent = 'Подключить';
        } else if (plan === 'corporate') {
            detail = 'Тариф «Корпоративный» для команды от 11 до 20 мастеров.';
            checkoutLink.dataset.href = '/business/checkout?plan=corporate';
            checkoutLink.textContent = 'Подключить';
        } else {
            detail = 'Свяжитесь с нами для индивидуального предложения.';
            checkoutLink.textContent = 'Связаться с нами';
        }

        priceOutput.textContent = amount === null ? 'Индивидуально' : formatPrice(amount);
        periodOutput.textContent = amount === null ? '' : '/мес';
        detailOutput.textContent = detail;
        calculator.dataset.plan = plan;
        calculator.dataset.employees = String(count);
        checkoutLink.textContent = plan === 'custom' ? 'Связаться с нами' : 'Подключить';
        contactForm.hidden = true;
        contactSuccess.hidden = true;
        contactError.hidden = true;
    }

    roleInputs.forEach((input) => input.addEventListener('change', update));
    commentInput.addEventListener('input', () => {
        commentCount.textContent = `${commentInput.value.length} / 1000`;
    });
    countInput.addEventListener('input', update);
    countInput.addEventListener('change', () => {
        const count = Number.parseInt(countInput.value, 10);
        countInput.value = String(Number.isInteger(count) && count >= 2 ? count : 2);
        update();
    });
    calculator.querySelectorAll('[data-count-step]').forEach((button) => {
        button.addEventListener('click', () => {
            const count = Number.parseInt(countInput.value, 10) || 2;
            countInput.value = String(Math.max(2, Math.min(500, count + Number(button.dataset.countStep))));
            update();
        });
    });

    checkoutLink.addEventListener('click', () => {
        if (calculator.dataset.plan === 'custom') {
            contactForm.hidden = false;
            contactForm.querySelector('input[type="email"]').focus();
            return;
        }
        window.location.assign(checkoutLink.dataset.href);
    });

    contactForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        contactError.hidden = true;
        contactSubmit.disabled = true;
        try {
            const formData = new FormData(contactForm);
            const response = await fetch('/api/v1/business/custom-plan-request', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: formData.get('name'),
                    email: formData.get('email'),
                    phone: formData.get('phone'),
                    comment: formData.get('comment'),
                    employees: Number.parseInt(calculator.dataset.employees, 10),
                }),
            });
            const result = await response.json();
            if (!response.ok) {
                throw new Error(result.detail || 'Не удалось отправить запрос. Попробуйте ещё раз.');
            }
            contactForm.hidden = true;
            contactSuccess.hidden = false;
            checkoutLink.disabled = true;
            checkoutLink.textContent = 'Запрос отправлен';
        } catch (error) {
            contactError.textContent = error.message || 'Ошибка сети. Попробуйте ещё раз.';
            contactError.hidden = false;
        } finally {
            contactSubmit.disabled = false;
        }
    });

    const requestedCount = Number.parseInt(
        new URLSearchParams(window.location.search).get('employees'),
        10,
    );
    if (Number.isInteger(requestedCount) && requestedCount >= 21 && requestedCount <= 500) {
        calculator.querySelector('input[name="bl-calc-role"][value="salon"]').checked = true;
        countInput.value = String(requestedCount);
        update();
        contactForm.hidden = false;
    } else {
        update();
    }
})();
