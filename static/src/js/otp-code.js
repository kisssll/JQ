// otp-code.js — подтверждение телефона кодом на странице регистрации.
// Подключается только при включённом OTP (см. app/web/pages/register.py).
import { toastNetworkError } from './ui-feedback.js';

(function () {
  var btn = document.getElementById('sendCodeBtn');
  if (!btn) return;

  var codeGroup = document.getElementById('codeGroup');
  var codeHint = document.getElementById('codeHint');
  var requestIdInput = document.getElementById('request_id');

  function startCooldown(seconds) {
    btn.disabled = true;
    var left = seconds;
    var t = setInterval(function () {
      left -= 1;
      if (left <= 0) {
        clearInterval(t);
        btn.disabled = false;
        btn.textContent = 'Получить код';
      } else {
        btn.textContent = 'Повторно через ' + left + 'с';
      }
    }, 1000);
  }

  btn.addEventListener('click', async function () {
    var phone = document.getElementById('phone').value;
    if (!phone) {
      alert('Сначала введите номер телефона');
      return;
    }
    btn.disabled = true;
    btn.textContent = 'Отправляем...';
    try {
      var res = await fetch('/api/v1/auth/register/send-code', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phone: phone })
      });
      var data = await res.json();
      if (res.ok) {
        requestIdInput.value = data.request_id;
        codeGroup.style.display = '';
        var hint = 'Код отправлен на ' + (data.masked_phone || phone);
        if (data.dev_code) {
          hint += ' (dev-код: ' + data.dev_code + ')';
        }
        codeHint.textContent = hint;
        startCooldown(60);
      } else {
        alert(data.detail || 'Не удалось отправить код');
        btn.disabled = false;
        btn.textContent = 'Получить код';
      }
    } catch (e) {
      toastNetworkError();
      btn.disabled = false;
      btn.textContent = 'Получить код';
    }
  });
})();
