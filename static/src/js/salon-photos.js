// salon-photos.js — удобная загрузка фото салона: несколько файлов за раз,
// drag&drop, мгновенные превью, статус по каждому файлу.
// НЕ выполняется на странице редактирования салона (там используется my-salon.js)
// Возможно следует сделать логику загрузки фото универсальной, использовать ее также для мастеров, моделей, пользователей. 
// Имеет проблемы с лишними редиректами, для использование необходимы исправления.

(function () {
  // Если мы на странице редактирования салона (есть элемент #salonEditCard) — выходим
  if (document.getElementById('salonEditCard')) return;

  var zone = document.getElementById('photoDropZone');
  if (!zone) return;

  var input = document.getElementById('photoFileInput');
  var statusBox = document.getElementById('photoUploadStatus');
  var uploadUrl = zone.dataset.uploadUrl;
  var busy = false;

  function note(text, isError) {
    var p = document.createElement('div');
    p.textContent = text;
    p.style.cssText = 'font-size:0.85rem;margin-top:0.25rem;color:' +
      (isError ? '#991B1B' : 'var(--color-muted)');
    statusBox.appendChild(p);
  }

  function previews(files) {
    statusBox.innerHTML = '';
    var strip = document.createElement('div');
    strip.style.cssText = 'display:flex;gap:0.5rem;flex-wrap:wrap;margin-top:0.5rem';
    Array.from(files).forEach(function (f) {
      if (!f.type.startsWith('image/')) return;
      var img = document.createElement('img');
      img.src = URL.createObjectURL(f);
      img.style.cssText = 'width:72px;height:52px;object-fit:cover;border-radius:0.4rem;opacity:0.6';
      strip.appendChild(img);
    });
    statusBox.appendChild(strip);
  }

  async function upload(files) {
    if (busy || !files.length) return;
    busy = true;
    previews(files);
    note('Загружаем ' + files.length + ' файл(а)…');

    var fd = new FormData();
    Array.from(files).forEach(function (f) { fd.append('files', f); });

    try {
      var res = await fetch(uploadUrl, { method: 'POST', body: fd });
      var data = await res.json();
      if (!res.ok) {
        note(data.detail || 'Не удалось загрузить', true);
        return;
      }
      (data.errors || []).forEach(function (e) {
        note(e.file + ': ' + e.detail, true);
      });
      if ((data.saved || []).length) {
        note('Загружено: ' + data.saved.length + '. Обновляем…');
        // Убираем перезагрузку, так как страница сама обновится через my-salon.js
        // setTimeout(function () { location.reload(); }, (data.errors || []).length ? 1600 : 400);
        // Вместо этого просто показываем сообщение
        note('Фото загружены. Обновите страницу, если они не отобразились.', false);
      }
    } catch (e) {
      note('Сеть недоступна, попробуйте ещё раз', true);
    } finally {
      busy = false;
      input.value = '';
    }
  }

  zone.addEventListener('click', function () { input.click(); });
  input.addEventListener('change', function () { upload(input.files); });

  ['dragenter', 'dragover'].forEach(function (ev) {
    zone.addEventListener(ev, function (e) {
      e.preventDefault();
      zone.style.borderColor = 'var(--color-primary)';
      zone.style.background = 'var(--color-accent-light)';
    });
  });
  ['dragleave', 'drop'].forEach(function (ev) {
    zone.addEventListener(ev, function (e) {
      e.preventDefault();
      zone.style.borderColor = '';
      zone.style.background = '';
    });
  });
  zone.addEventListener('drop', function (e) {
    upload(e.dataTransfer.files);
  });
})();