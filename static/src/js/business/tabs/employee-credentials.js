// static/src/js/business/tabs/employee-credentials.js
// Реквизиты нового сотрудника/мастера: AJAX-добавление (пароль не в URL) →
// попап с логином/паролем, копирование, отправка на почту салона, сброс пароля.
(function () {
    let current = null; // {name, login, password}

    function showCredentials(c) {
        current = c;
        const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v || '—'; };
        set('credName', c.name);
        set('credLogin', c.login);
        set('credPassword', c.password);
        const res = document.getElementById('credEmailResult');
        if (res) { res.textContent = ''; res.className = 'creds-email-result'; }
        document.getElementById('credentialsModal')?.classList.add('active');
    }

    async function postForm(url, formData) {
        const res = await fetch(url, { method: 'POST', body: formData });
        let data = {};
        try { data = await res.json(); } catch (e) { /* not json */ }
        if (!res.ok || data.status === 'error') {
            alert(data.detail || 'Не удалось выполнить действие');
            return null;
        }
        return data;
    }

    async function handleAdd(form, url) {
        const data = await postForm(url, new FormData(form));
        if (!data) return;
        form.reset();
        form.closest('.modal-overlay')?.classList.remove('active');
        if (data.credentials) {
            showCredentials(data.credentials);      // новый аккаунт — показываем реквизиты
        } else {
            location.reload();                       // существующий аккаунт — просто обновляем список
        }
    }

    document.addEventListener('submit', function (e) {
        const f = e.target;
        if (f.id === 'employeeForm') {               // добавление мастера
            e.preventDefault();
            handleAdd(f, '/api/v1/master/create-web');
        } else if (f.id === 'staffAddForm') {        // добавление сотрудника
            e.preventDefault();
            handleAdd(f, '/api/v1/business/staff/add-web');
        }
    });

    async function resetPassword(url, confirmMsg) {
        if (!confirm(confirmMsg)) return;
        const data = await postForm(url, new FormData());
        if (data && data.credentials) showCredentials(data.credentials);
    }

    window.resetMasterPassword = function (masterId) {
        resetPassword(`/api/v1/master/${masterId}/reset-password`,
            'Сбросить пароль мастеру? Старый перестанет работать — понадобится передать новый.');
    };
    window.resetMemberPassword = function (memberId) {
        resetPassword(`/api/v1/business/staff/${memberId}/reset-password`,
            'Сбросить пароль сотруднику? Старый перестанет работать — понадобится передать новый.');
    };

    window.copyCredentials = function () {
        if (!current) return;
        const text = `Вход в Руми\nЛогин (телефон): ${current.login}\nПароль: ${current.password}\nСайт: https://rrumi.ru/login`;
        navigator.clipboard.writeText(text).then(
            () => { const b = document.getElementById('credCopyBtn'); if (b) { const t = b.textContent; b.textContent = 'Скопировано ✓'; setTimeout(() => b.textContent = t, 1500); } },
            () => alert('Не удалось скопировать')
        );
    };

    window.sendCredentialsToSalonEmail = async function () {
        if (!current) return;
        const res = document.getElementById('credEmailResult');
        const resp = await fetch('/api/v1/business/staff/send-credentials', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                salon_id: window.salonId, name: current.name,
                login: current.login, password: current.password,
            }),
        });
        let data = {};
        try { data = await resp.json(); } catch (e) { /* */ }
        if (!resp.ok || data.status === 'error') {
            if (res) { res.textContent = data.detail || 'Не удалось отправить'; res.className = 'creds-email-result err'; }
            return;
        }
        if (res) { res.textContent = 'Отправлено на ' + (data.sent_to || 'почту салона'); res.className = 'creds-email-result ok'; }
    };
})();
