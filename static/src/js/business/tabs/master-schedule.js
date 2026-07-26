// static/src/js/business/tabs/master-schedule.js
// Редактор индивидуального недельного графика мастера (вкладка «Расписание»).
(function () {
    function rowHtml(start, end) {
        return `<div class="mschedule-edit-row">
            <input type="time" class="ms-start" value="${start || ''}">
            <span class="mschedule-edit-dash">–</span>
            <input type="time" class="ms-end" value="${end || ''}">
            <button type="button" class="mschedule-edit-del" onclick="this.closest('.mschedule-edit-row').remove()">&times;</button>
        </div>`;
    }

    window.openMasterScheduleModal = function () {
        const modal = document.getElementById('masterScheduleModal');
        if (modal) modal.classList.add('active');
    };

    window.msAddRow = function (day) {
        const container = document.getElementById('msRows' + day);
        if (!container) return;
        container.insertAdjacentHTML('beforeend', rowHtml('', ''));
    };

    window.saveMasterSchedule = async function () {
        const masterId = document.getElementById('msMasterId')?.value;
        if (!masterId) return;

        const shifts = [];
        const days = document.querySelectorAll('.mschedule-edit-day');
        for (const dayEl of days) {
            const day = parseInt(dayEl.dataset.day, 10);
            const rows = dayEl.querySelectorAll('.mschedule-edit-row');
            for (const row of rows) {
                const start = row.querySelector('.ms-start')?.value;
                const end = row.querySelector('.ms-end')?.value;
                if (!start || !end) {
                    alert('Заполните начало и конец во всех интервалах (или удалите пустые).');
                    return;
                }
                if (end <= start) {
                    alert('Начало смены должно быть раньше конца.');
                    return;
                }
                shifts.push({ day_of_week: day, start, end });
            }
        }

        const res = await fetch(`/api/v1/schedule/master/${masterId}/schedule`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ shifts })
        });

        if (res.ok) {
            const data = await res.json();
            if (data.warning) alert(data.warning);
            location.reload();
        } else {
            const d = await res.json().catch(() => ({}));
            alert(d.detail || 'Не удалось сохранить график');
        }
    };
})();
