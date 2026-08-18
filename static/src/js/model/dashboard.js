// static/src/js/model/dashboard.js — саб-табы (Приглашения/Кастинги/История),
// колода свайпов с drag и запись на реальный свободный слот расписания
// мастера после мэтча (цена/услуга уже зафиксированы мэтчем — оффера нет).
import { toastNetworkError } from '../ui-feedback.js';

(function () {
  var root = document.getElementById('modelInvitationsList') || document.getElementById('modelDeckStack');
  if (!root) return;

  var deckQueue = [];
  var matchesById = {};

  window.modelDashShowSubtab = function (name) {
    document.querySelectorAll('.models-subtab-btn').forEach(function (b) {
      b.classList.toggle('active', b.dataset.subtab === name);
    });
    ['invitations', 'casting', 'history'].forEach(function (n) {
      var panel = document.getElementById('models-subtab-' + n);
      if (panel) panel.style.display = n === name ? '' : 'none';
    });
  };

  function statusLabel(status) {
    return { matched: 'Ждёт запись', booked: 'Забронировано', declined: 'Отклонено' }[status] || status;
  }

  function inviteCardHtml(inv) {
    return '<div class="invite-card">' +
      '<div style="display:flex;gap:1rem;align-items:start">' +
      (inv.photo_url ? '<img src="' + inv.photo_url + '" style="width:56px;height:56px;border-radius:0.75rem;object-fit:cover;flex-shrink:0">' : '') +
      '<div style="flex:1">' +
      '<div style="display:flex;justify-content:space-between;align-items:start;gap:0.5rem">' +
      '<strong>' + inv.salon_name + '</strong>' +
      (inv.salon_rating ? '<span class="text-muted" style="font-size:0.8rem">⭐ ' + inv.salon_rating + '</span>' : '') +
      '</div>' +
      '<p class="text-muted" style="font-size:0.8rem;margin:0.15rem 0">' + inv.service_name + ' · ' + (inv.price ? inv.price + ' ₽' : 'бесплатно') + ' · ' + inv.specialization + '</p>' +
      (inv.description ? '<p style="font-size:0.85rem;background:var(--color-surface-alt,#f9fafb);border-radius:0.75rem;padding:0.6rem;margin-top:0.4rem">' + inv.description + '</p>' : '') +
      '</div></div>' +
      '<div style="display:flex;gap:0.5rem;margin-top:0.75rem;border-top:1px solid var(--color-border);padding-top:0.75rem">' +
      '<button class="btn-outline" style="flex:1;font-size:0.8rem;color:#ef4444;border-color:#fecaca" onclick="window.modelRespondInvitation(' + inv.service_id + ', false, this)">✕ Отклонить</button>' +
      '<button class="btn-primary" style="flex:1;font-size:0.8rem" onclick="window.modelRespondInvitation(' + inv.service_id + ', true, this)">✓ Принять</button>' +
      '</div></div>';
  }

  async function loadInvitations() {
    var list = document.getElementById('modelInvitationsList');
    var badge = document.getElementById('modelInvitationsBadge');
    if (!list) return;
    var invitesHtml = '', matchesHtml = '', total = 0;
    try {
      var res = await fetch('/api/v1/model-matching/invitations');
      var invites = res.ok ? await res.json() : [];
      total += invites.length;
      invitesHtml = invites.map(inviteCardHtml).join('');
    } catch (e) { /* покажем хотя бы мэтчи */ }
    try {
      var res2 = await fetch('/api/v1/model-matching/matches');
      var matches = res2.ok ? await res2.json() : [];
      matches.forEach(function (m) { matchesById[m.match_id] = m; });
      total += matches.length;
      matchesHtml = matches.map(matchCardHtml).join('');
    } catch (e) { /* покажем хотя бы приглашения */ }
    if (badge) badge.textContent = total || '';
    list.innerHTML = (invitesHtml + matchesHtml) || '<p class="text-muted" style="padding:2rem;text-align:center">Пока ничего нет — полайкайте мастеров во вкладке «Кастинги»</p>';
    Object.keys(matchesById).forEach(function (id) {
      if (matchesById[id].status === 'matched') window.modelDashLoadSlots(Number(id));
    });
  }

  window.modelRespondInvitation = async function (serviceId, like, btn) {
    var card = btn.closest('.invite-card');
    try {
      await fetch('/api/v1/model-matching/feed/' + serviceId + '/swipe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ like: like }),
      });
    } catch (e) { /* карточку всё равно уберём */ }
    if (card) card.remove();
    loadInvitations();
  };

  function renderDeckCard(c) {
    var photoCount = (c.photos || []).length + (c.photo_url ? 1 : 0);
    return '<div class="models-swipe-card">' +
      '<div class="models-swipe-card-photo" style="background-image:url(\'' + (c.photo_url || '') + '\')">' +
      '<div class="models-swipe-card-name"><h3 style="margin:0;font-size:1.2rem;font-weight:700">' + c.master_name + '</h3>' +
      '<p style="margin:0.2rem 0 0;font-size:0.8rem;opacity:0.9">' + c.service_name + ' · ' + (c.price ? c.price + ' ₽' : 'бесплатно') + ' · «' + c.salon_name + '»</p></div></div>' +
      '<div class="models-swipe-card-body">' +
      (c.description ? '<p style="font-size:0.85rem;margin:0;line-height:1.4">' + c.description + '</p>' : '<p class="text-muted" style="font-size:0.85rem">Без описания</p>') +
      (photoCount ? '<p class="text-muted" style="font-size:0.75rem;margin-top:0.5rem">📷 ' + photoCount + ' фото портфолио</p>' : '') +
      '</div></div>';
  }

  function renderDeck() {
    var stack = document.getElementById('modelDeckStack');
    if (!stack) return;
    if (!deckQueue.length) {
      stack.innerHTML = '<p class="text-muted" style="text-align:center;padding:2rem 0">Новых предложений нет — загляните позже</p>';
      return;
    }
    stack.innerHTML = deckQueue.slice(0, 2).reverse().map(renderDeckCard).join('');
    attachDeckDrag();
  }

  function attachDeckDrag() {
    var cards = document.querySelectorAll('#modelDeckStack .models-swipe-card');
    var top = cards[cards.length - 1];
    if (!top) return;
    var startX = 0, dx = 0, dragging = false;

    top.addEventListener('pointerdown', function (e) {
      dragging = true; startX = e.clientX;
      top.setPointerCapture(e.pointerId);
    });
    top.addEventListener('pointermove', function (e) {
      if (!dragging) return;
      dx = e.clientX - startX;
      top.style.transform = 'translateX(' + dx + 'px) rotate(' + (dx / 12) + 'deg)';
    });
    function endDrag() {
      if (!dragging) return;
      dragging = false;
      if (Math.abs(dx) > 100) { commitDeckSwipe(dx > 0); } else { top.style.transform = ''; }
      dx = 0;
    }
    top.addEventListener('pointerup', endDrag);
    top.addEventListener('pointercancel', endDrag);
  }

  function commitDeckSwipe(like) {
    var card = deckQueue.shift();
    renderDeck();
    window.modelDeckSwipe(card.service_id, like);
  }

  window.modelDeckButtonSwipe = function (like) {
    if (!deckQueue.length) return;
    commitDeckSwipe(like);
  };

  window.modelDeckSwipe = async function (serviceId, like) {
    try {
      var res = await fetch('/api/v1/model-matching/feed/' + serviceId + '/swipe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ like: like }),
      });
      if (res.ok) loadInvitations();
    } catch (e) { /* карточка уже убрана из очереди */ }
  };

  async function loadDeck() {
    var stack = document.getElementById('modelDeckStack');
    if (!stack) return;
    try {
      var res = await fetch('/api/v1/model-matching/feed');
      deckQueue = res.ok ? await res.json() : [];
    } catch (e) {
      deckQueue = [];
    }
    renderDeck();
  }

  async function loadHistory() {
    var list = document.getElementById('modelHistoryList');
    if (!list) return;
    try {
      var res = await fetch('/api/v1/model-matching/history');
      var history = res.ok ? await res.json() : [];
      list.innerHTML = history.length ? history.map(function (h) {
        var when = h.chosen_slot ? new Date(h.chosen_slot).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—';
        var priceText = h.price ? h.price + ' ₽' : 'бесплатно';
        var statusText = h.booking_status === 'completed' ? 'Завершено' : (h.booking_status === 'no_show' ? 'Неявка' : 'Предстоит');
        return '<div class="card" style="padding:1rem;margin-bottom:0.75rem;display:flex;justify-content:space-between;gap:1rem;flex-wrap:wrap">' +
          '<div><strong>' + h.service_name + '</strong><p class="text-muted" style="font-size:0.85rem;margin:0.15rem 0">' + h.master_name + ' · ' + h.salon_name + '</p></div>' +
          '<div style="text-align:right"><p style="margin:0;font-size:0.85rem">' + when + '</p><p class="text-muted" style="font-size:0.8rem;margin:0.15rem 0">' + priceText + ' · ' + statusText + '</p></div>' +
          '</div>';
      }).join('') : '<p class="text-muted" style="padding:2rem;text-align:center">Пока нет визитов</p>';
    } catch (e) {
      list.innerHTML = '<p class="text-muted">Не удалось загрузить историю</p>';
    }
  }

  function todayIso() {
    var d = new Date();
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }

  function matchCardHtml(m) {
    var actions = '';
    if (m.status === 'matched') {
      actions = '<p style="margin-top:0.5rem;font-size:0.85rem">' + m.service_name + ' · ' + (m.price ? m.price + ' ₽' : 'бесплатно') + '</p>' +
        '<div style="display:flex;gap:0.5rem;margin-top:0.5rem;flex-wrap:wrap;align-items:center">' +
        '<input type="date" id="dashdate-' + m.match_id + '" min="' + todayIso() + '" value="' + todayIso() + '" onchange="window.modelDashLoadSlots(' + m.match_id + ')" style="padding:0.4rem;border:1px solid var(--color-border);border-radius:0.5rem">' +
        '<select id="dashslot-' + m.match_id + '" style="padding:0.4rem;border:1px solid var(--color-border);border-radius:0.5rem"><option value="">Выберите время</option></select>' +
        '<button class="btn-primary" style="font-size:0.8rem" onclick="window.modelDashAcceptSlot(' + m.match_id + ')">Записаться</button>' +
        '</div>' +
        '<p class="text-muted" style="font-size:0.75rem;margin-top:0.3rem" id="dashslothint-' + m.match_id + '"></p>';
    } else if (m.status === 'booked') {
      actions = '<p style="margin-top:0.5rem;color:var(--color-success,#065f46);font-size:0.85rem">Вы записаны</p>';
    }
    return '<div class="invite-card" data-match-id="' + m.match_id + '"><div style="display:flex;justify-content:space-between;align-items:start">' +
      '<h3 style="font-weight:600;font-size:0.9rem;margin:0">' + m.master_name + '</h3>' +
      '<span class="status-badge status-' + m.status + '">' + statusLabel(m.status) + '</span>' +
      '</div>' + actions + '</div>';
  }

  window.modelDashLoadSlots = async function (matchId) {
    var m = matchesById[matchId];
    var dateInput = document.getElementById('dashdate-' + matchId);
    var select = document.getElementById('dashslot-' + matchId);
    var hint = document.getElementById('dashslothint-' + matchId);
    if (!m || !dateInput || !select || !dateInput.value) return;
    select.innerHTML = '<option value="">Загрузка…</option>';
    if (hint) hint.textContent = '';
    try {
      var url = '/api/v1/bookings/available/' + m.master_id + '?date=' + dateInput.value + '&service_id=' + m.service_id;
      var res = await fetch(url);
      var data = res.ok ? await res.json() : { slots: [], message: 'Ошибка загрузки' };
      if (!data.slots || !data.slots.length) {
        select.innerHTML = '<option value="">Нет свободного времени</option>';
        if (hint) hint.textContent = data.message || 'На эту дату свободных слотов нет — попробуйте другой день';
        return;
      }
      select.innerHTML = data.slots.map(function (s) {
        var d = new Date(s);
        return '<option value="' + s + '">' + d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }) + '</option>';
      }).join('');
    } catch (e) {
      select.innerHTML = '<option value="">Ошибка загрузки</option>';
    }
  };

  window.modelDashAcceptSlot = async function (matchId) {
    var select = document.getElementById('dashslot-' + matchId);
    if (!select || !select.value) { alert('Выберите время'); return; }
    try {
      var res = await fetch('/api/v1/model-matching/matches/' + matchId + '/accept-slot', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ slot: select.value }),
      });
      if (res.ok) {
        loadHistory();
        loadInvitations();
      } else {
        var data = await res.json().catch(function () { return {}; });
        alert(data.detail || 'Не удалось записаться — возможно, время уже занято');
        window.modelDashLoadSlots(matchId);
      }
    } catch (e) {
      toastNetworkError();
    }
  };

  loadInvitations();
  loadDeck();
  loadHistory();
})();
