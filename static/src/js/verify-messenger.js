// verify-messenger.js — подтверждение телефона через бота Telegram ИЛИ MAX.
// Одна механика на оба канала: кнопка → POST <data-start-url> → deep link →
// поллинг /tg-status до confirmed → ✓ (вторая кнопка гаснет — канал не важен).
import { toastNetworkError } from './ui-feedback.js';

(function () {
  var buttons = Array.from(document.querySelectorAll('.msgr-verify-btn'));
  if (!buttons.length) return;

  var hint = document.getElementById('msgrHint');
  var requestIdInput = document.getElementById('request_id');
  var pollTimer = null;
  var deadline = 0;

  function setHint(text) { if (hint) hint.textContent = text; }

  function stopPolling() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  }

  function resetButtons() {
    buttons.forEach(function (b) {
      b.disabled = false;
      b.textContent = b.dataset.label;
    });
  }

  function markConfirmed() {
    stopPolling();
    buttons.forEach(function (b) {
      b.disabled = true;
      b.textContent = 'Номер подтверждён ✓';
    });
    setHint('Готово! Заполните остальные поля и завершите регистрацию.');
  }

  async function poll() {
    if (Date.now() > deadline) {
      stopPolling();
      resetButtons();
      setHint('Время подтверждения вышло — нажмите кнопку ещё раз.');
      return;
    }
    try {
      var res = await fetch(
        '/api/v1/auth/register/tg-status?request_id=' +
          encodeURIComponent(requestIdInput.value)
      );
      if (!res.ok) return; // транзиентная ошибка/лимит — следующий тик
      var data = await res.json();
      if (data.status === 'confirmed') markConfirmed();
      if (data.status === 'not_found') {
        stopPolling();
        resetButtons();
        setHint('Подтверждение устарело — нажмите кнопку ещё раз.');
      }
    } catch (e) { /* сеть моргнула — ждём следующий тик */ }
  }

  buttons.forEach(function (btn) {
    btn.dataset.label = btn.textContent;
    btn.addEventListener('click', async function () {
      var phone = document.getElementById('phone').value;
      if (!phone) {
        alert('Сначала введите номер телефона');
        return;
      }
      buttons.forEach(function (b) { b.disabled = true; });
      btn.textContent = 'Открываем ' + btn.dataset.channel + '…';
      try {
        var res = await fetch(btn.dataset.startUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ phone: phone })
        });
        var data = await res.json();
        if (!res.ok) {
          alert(data.detail || 'Не удалось начать подтверждение');
          resetButtons();
          return;
        }
        requestIdInput.value = data.request_id;
        deadline = Date.now() + (data.expires_in_seconds || 600) * 1000;
        window.open(data.deep_link, '_blank');
        btn.textContent = 'Ждём подтверждения…';
        setHint('В боте нажмите «Поделиться контактом». Эта страница поймёт всё сама.');
        stopPolling();
        pollTimer = setInterval(poll, 2500);
      } catch (e) {
        toastNetworkError();
        resetButtons();
      }
    });
  });
})();
