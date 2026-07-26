// static/src/js/pages/my-salon.js

document.addEventListener('DOMContentLoaded', function() {
    // Глобальное предотвращение поведения по умолчанию для drag-and-drop
    document.addEventListener('dragover', function(e) {
        e.preventDefault();
        e.stopPropagation();
    });
    document.addEventListener('drop', function(e) {
        e.preventDefault();
        e.stopPropagation();
    });

    // Логика карточки салона
    const card = document.getElementById('salonEditCard');
    if (!card) return;

    const toggleContainer = document.getElementById('salonEditToggleContainer');
    const staticBlock = card.querySelector('.salon-edit-static');
    const inputsBlock = card.querySelector('.salon-edit-inputs');

    const displayName = document.getElementById('salonEditNameDisplay');
    const displayAddress = document.getElementById('salonEditAddressDisplay');
    const displayPhone = document.getElementById('salonEditPhoneDisplay');
    const displayDesc = document.getElementById('salonEditDescDisplay');

    const inputName = document.getElementById('salonEditNameInput');
    const inputAddress = document.getElementById('salonEditAddressInput');
    const inputPhone = document.getElementById('salonEditPhoneInput');
    const inputDesc = document.getElementById('salonEditDescInput');

    const photoContainer = document.getElementById('salonEditPhotoContainer');
    const photoUploadLabel = document.getElementById('salonEditPhotoUpload');
    const photoInput = document.getElementById('salonEditPhotoInput');

    let isEditing = false;
    let isPreview = false;
    let originalValues = {};
    let isUploading = false;
    let currentPhotos = [];
    let currentLogo = '';

    const ICON_EDIT = window.ICON_EDIT || '';
    const ICON_EYE = window.ICON_EYE || '';
    const ICON_SAVE = window.ICON_SAVE || '';
    const ICON_X = window.ICON_X || '';

    // ===== Вспомогательные функции =====

    function saveOriginalValues() {
        originalValues = {
            name: displayName.textContent.trim(),
            address: displayAddress.textContent.trim(),
            phone: displayPhone.textContent.trim(),
            desc: displayDesc.textContent.trim(),
            photos: currentPhotos.map(p => ({id: p.id, url: p.url})),
            logo: currentLogo
        };
    }

    function restoreOriginalValues() {
        displayName.textContent = originalValues.name || 'Название салона';
        displayAddress.textContent = originalValues.address || 'Адрес не указан';
        displayPhone.textContent = originalValues.phone || '';
        displayDesc.textContent = originalValues.desc || '';
        inputName.value = originalValues.name;
        inputAddress.value = originalValues.address;
        inputPhone.value = originalValues.phone;
        inputDesc.value = originalValues.desc;
        currentPhotos = (originalValues.photos || []).map(p => ({id: p.id, url: p.url}));
        currentLogo = originalValues.logo || '';
        renderGallery();
        updateLogoInCard();
    }

    function applyInputsToStatic() {
        displayName.textContent = inputName.value || 'Название салона';
        displayAddress.textContent = inputAddress.value || 'Адрес не указан';
        displayPhone.textContent = inputPhone.value || '';
        displayDesc.textContent = inputDesc.value || '';
    }

    function setButtons(html) {
        toggleContainer.innerHTML = html;
        const previewBtn = document.getElementById('salonEditPreviewBtn');
        const saveBtn = document.getElementById('salonEditSaveBtn');
        const cancelBtn = document.getElementById('salonEditCancelBtn');
        const backBtn = document.getElementById('salonEditBackBtn');

        if (previewBtn) previewBtn.addEventListener('click', togglePreview);
        if (saveBtn) saveBtn.addEventListener('click', saveChanges);
        if (cancelBtn) cancelBtn.addEventListener('click', exitEditMode);
        if (backBtn) {
            backBtn.addEventListener('click', function() {
                isPreview = false;
                staticBlock.style.display = 'none';
                inputsBlock.style.display = 'block';
                setButtons(`
                    <button class="btn-outline salon-edit-preview-btn" id="salonEditPreviewBtn">${ICON_EYE} Просмотр результата</button>
                    <button class="btn-primary salon-edit-save-btn" id="salonEditSaveBtn">${ICON_SAVE} Сохранить</button>
                    <button class="btn-outline salon-edit-cancel-btn" id="salonEditCancelBtn">${ICON_X} Отменить</button>
                `);
            });
        }
    }

    // ===== Рендер галереи =====
    function renderGallery() {
        const gallery = document.querySelector('.my-salon-photos');
        if (!gallery) return;
        gallery.innerHTML = '';
        if (currentPhotos.length === 0) {
            gallery.innerHTML = '<p style="color:var(--color-muted);margin:0">Пока нет фотографий</p>';
            return;
        }
        currentPhotos.forEach(photo => {
            const isCover = (photo.url === currentLogo);
            const borderClass = isCover ? 'cover-border' : 'default-border';
            const item = document.createElement('div');
            item.className = 'my-salon-photo-item';
            item.innerHTML = `
                <img src="${photo.url}" alt="" class="${borderClass}">
                <button class="delete-btn" data-action="delete" data-url="${photo.url}" title="Удалить фото">&times;</button>
                ${isCover ? '<span class="cover-badge">★ Обложка</span>' : `<button class="cover-btn" data-action="cover" data-url="${photo.url}" title="Сделать обложкой">Сделать обложкой</button>`}
            `;
            gallery.appendChild(item);
        });
    }

    function updateLogoInCard() {
        const wrapper = document.querySelector('.salon-edit-photo-wrapper');
        if (!wrapper) return;
        const existingImg = wrapper.querySelector('img');
        const placeholder = wrapper.querySelector('.salon-edit-photo-placeholder');
        if (currentLogo) {
            if (existingImg) {
                existingImg.src = currentLogo + '?t=' + Date.now();
            } else if (placeholder) {
                const newImg = document.createElement('img');
                newImg.src = currentLogo + '?t=' + Date.now();
                newImg.alt = 'Фото салона';
                newImg.className = 'salon-edit-photo';
                wrapper.replaceChild(newImg, placeholder);
            } else {
                const newImg = document.createElement('img');
                newImg.src = currentLogo + '?t=' + Date.now();
                newImg.alt = 'Фото салона';
                newImg.className = 'salon-edit-photo';
                wrapper.appendChild(newImg);
            }
        } else {
            if (existingImg) {
                existingImg.remove();
                const newPlaceholder = document.createElement('div');
                newPlaceholder.className = 'salon-edit-photo-placeholder';
                newPlaceholder.textContent = displayName.textContent[0].toUpperCase() || '?';
                wrapper.appendChild(newPlaceholder);
            } else if (!placeholder) {
                const newPlaceholder = document.createElement('div');
                newPlaceholder.className = 'salon-edit-photo-placeholder';
                newPlaceholder.textContent = displayName.textContent[0].toUpperCase() || '?';
                wrapper.appendChild(newPlaceholder);
            }
        }
    }

    // ===== Локальные действия с фото =====

    function localSetCover(url) {
        const found = currentPhotos.some(p => p.url === url);
        if (found) {
            currentLogo = url;
            renderGallery();
            updateLogoInCard();
        }
    }

    function localDeletePhoto(url) {
        const index = currentPhotos.findIndex(p => p.url === url);
        if (index !== -1) {
            const removed = currentPhotos[index];
            currentPhotos.splice(index, 1);
            if (currentLogo === url) {
                currentLogo = currentPhotos.length > 0 ? currentPhotos[0].url : '';
            }
            renderGallery();
            updateLogoInCard();
        }
    }

    // ===== Загрузка новых фото =====
    async function uploadPhotos(files) {
        if (isUploading) return;
        if (!files || files.length === 0) return;

        const dropZone = document.getElementById('photoDropZone');
        const statusDiv = document.getElementById('photoUploadStatus');
        const url = dropZone.dataset.uploadUrl;
        const salonId = window.salonId;

        if (!url || !salonId) {
            return;
        }

        isUploading = true;
        statusDiv.innerHTML = '<p style="color:var(--color-muted)">Загрузка...</p>';

        const formData = new FormData();
        for (const file of files) {
            formData.append('files', file);
        }

        try {
            const res = await fetch(url, {
                method: 'POST',
                body: formData,
                credentials: 'include',
            });
            if (res.ok) {
                const data = await res.json();
                if (data.saved && data.saved.length) {
                    data.saved.forEach(url => {
                        currentPhotos.push({ id: null, url: url });
                        if (!currentLogo) {
                            currentLogo = url;
                        }
                    });
                    renderGallery();
                    updateLogoInCard();
                    statusDiv.innerHTML = '<p style="color:#22c55e">Фото загружены</p>';
                } else {
                    statusDiv.innerHTML = '<p style="color:#ef4444">Ошибка: фото не сохранены</p>';
                }
                setTimeout(() => { statusDiv.innerHTML = ''; }, 3000);
            } else {
                const d = await res.json();
                statusDiv.innerHTML = `<p style="color:#ef4444">Ошибка: ${d.detail || 'Неизвестная ошибка'}</p>`;
            }
        } catch (e) {
            statusDiv.innerHTML = '<p style="color:#ef4444">Ошибка сети</p>';
        } finally {
            isUploading = false;
            const fileInput = document.getElementById('photoFileInputMySalon');
            if (fileInput) fileInput.value = '';
        }
    }

    // ===== Обработчики для галереи (делегирование) =====
    document.addEventListener('click', function(e) {
        const target = e.target;
        if (target.classList.contains('cover-btn')) {
            e.preventDefault();
            const url = target.dataset.url;
            if (url) localSetCover(url);
        }
        if (target.classList.contains('delete-btn')) {
            e.preventDefault();
            if (!confirm('Удалить фото?')) return;
            const url = target.dataset.url;
            if (url) localDeletePhoto(url);
        }
    });

    // ===== Режимы редактирования =====

    function enterEditMode() {
        isEditing = true;
        isPreview = false;
        saveOriginalValues();
        inputName.value = displayName.textContent.trim();
        inputAddress.value = displayAddress.textContent.trim();
        inputPhone.value = displayPhone.textContent.trim();
        inputDesc.value = displayDesc.textContent.trim();
        staticBlock.style.display = 'none';
        inputsBlock.style.display = 'block';
        setButtons(`
            <button class="btn-outline salon-edit-preview-btn" id="salonEditPreviewBtn">${ICON_EYE} Просмотр результата</button>
            <button class="btn-primary salon-edit-save-btn" id="salonEditSaveBtn">${ICON_SAVE} Сохранить</button>
            <button class="btn-outline salon-edit-cancel-btn" id="salonEditCancelBtn">${ICON_X} Отменить</button>
        `);
    }

    function exitEditMode() {
        isEditing = false;
        isPreview = false;
        restoreOriginalValues();
        staticBlock.style.display = 'flex';
        inputsBlock.style.display = 'none';
        setButtons(`
            <button class="btn-outline salon-edit-toggle-btn" id="salonEditToggleBtn">${ICON_EDIT} Редактировать</button>
        `);
        document.getElementById('salonEditToggleBtn').addEventListener('click', function() {
            if (isEditing) {
                exitEditMode();
            } else {
                enterEditMode();
            }
        });
    }

    function togglePreview() {
        if (!isEditing) return;
        isPreview = !isPreview;
        if (isPreview) {
            applyInputsToStatic();
            staticBlock.style.display = 'flex';
            inputsBlock.style.display = 'none';
            setButtons(`
                <button class="btn-outline salon-edit-back-btn" id="salonEditBackBtn">${ICON_EDIT} Редактировать</button>
                <button class="btn-primary salon-edit-save-btn" id="salonEditSaveBtn">${ICON_SAVE} Сохранить</button>
                <button class="btn-outline salon-edit-cancel-btn" id="salonEditCancelBtn">${ICON_X} Отменить</button>
            `);
        } else {
            staticBlock.style.display = 'none';
            inputsBlock.style.display = 'block';
            setButtons(`
                <button class="btn-outline salon-edit-preview-btn" id="salonEditPreviewBtn">${ICON_EYE} Просмотр результата</button>
                <button class="btn-primary salon-edit-save-btn" id="salonEditSaveBtn">${ICON_SAVE} Сохранить</button>
                <button class="btn-outline salon-edit-cancel-btn" id="salonEditCancelBtn">${ICON_X} Отменить</button>
            `);
        }
    }

    // ===== СОХРАНЕНИЕ =====
    async function saveChanges() {
        if (!isEditing) return;
        const data = {
            name: inputName.value,
            phone: inputPhone.value,
            address: inputAddress.value,
            description: inputDesc.value,
            photos: currentPhotos.map(p => p.url),
            logo_url: currentLogo
        };
        const salonId = window.salonId;
        try {
            const res = await fetch('/api/v1/business/my-salon?salon_id=' + salonId, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            if (res.ok) {
                const logoChanged = (currentLogo !== originalValues.logo);
                if (logoChanged && currentLogo) {
                    const photoObj = currentPhotos.find(p => p.url === currentLogo);
                    if (photoObj && photoObj.id !== null) {
                        await fetch('/api/v1/upload/salon/' + salonId + '/photo/' + photoObj.id + '/cover', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                            body: 'next=/business/dashboard?tab=edit'
                        });
                    }
                }

                applyInputsToStatic();
                originalValues = {
                    name: data.name,
                    address: data.address,
                    phone: data.phone,
                    desc: data.description,
                    photos: currentPhotos.map(p => ({id: p.id, url: p.url})),
                    logo: currentLogo
                };
                isEditing = false;
                isPreview = false;
                staticBlock.style.display = 'flex';
                inputsBlock.style.display = 'none';
                setButtons(`
                    <button class="btn-outline salon-edit-toggle-btn" id="salonEditToggleBtn">${ICON_EDIT} Редактировать</button>
                `);
                document.getElementById('salonEditToggleBtn').addEventListener('click', function() {
                    if (isEditing) {
                        exitEditMode();
                    } else {
                        enterEditMode();
                    }
                });
                const msg = document.createElement('div');
                msg.className = 'alert success';
                msg.textContent = 'Изменения сохранены';
                msg.style.marginTop = '1rem';
                card.parentNode.insertBefore(msg, card.nextSibling);
                setTimeout(() => { msg.remove(); }, 3000);
            } else {
                const d = await res.json();
                alert(d.detail || 'Ошибка при сохранении');
            }
        } catch (err) {
            alert('Ошибка сети');
        }
    }

    // ===== Загрузка логотипа через кнопку "Изменить фото" =====
    async function uploadLogo(file) {
        const salonId = window.salonId;
        const formData = new FormData();
        formData.append('file', file);
        try {
            const res = await fetch('/api/v1/upload/salon/' + salonId + '/photo', {
                method: 'POST',
                body: formData,
                credentials: 'include',
            });
            if (!res.ok) {
                const d = await res.json();
                alert(d.detail || 'Ошибка загрузки фото');
                return;
            }
            const data = await res.json();
            const url = data.saved && data.saved.length ? data.saved[0] : null;
            if (!url) {
                alert('Не удалось получить URL загруженного фото');
                return;
            }
            currentPhotos.push({ id: null, url: url });
            if (!currentLogo) {
                currentLogo = url;
            }
            renderGallery();
            updateLogoInCard();
            const msg = document.createElement('div');
            msg.className = 'alert success';
            msg.textContent = 'Фото добавлено';
            msg.style.marginTop = '1rem';
            card.parentNode.insertBefore(msg, card.nextSibling);
            setTimeout(() => { msg.remove(); }, 3000);
        } catch (err) {
            alert('Ошибка сети при загрузке фото');
        }
    }

    // ===== Инициализация =====
    if (window.initialPhotos !== undefined) {
        currentPhotos = window.initialPhotos.map(p => ({id: p.id, url: p.url}));
    }
    if (window.initialLogo !== undefined) {
        currentLogo = window.initialLogo;
    }
    renderGallery();
    updateLogoInCard();

    // ===== Обработчики для загрузки фото (drag-and-drop и выбор) =====
    const dropZone = document.getElementById('photoDropZone');
    const fileInput = document.getElementById('photoFileInputMySalon');
    const statusDiv = document.getElementById('photoUploadStatus');

    if (dropZone && fileInput) {
        dropZone.addEventListener('click', function(e) {
            e.preventDefault();
            if (isUploading) return;
            fileInput.click();
        });

        dropZone.addEventListener('dragover', function(e) {
            e.preventDefault();
            dropZone.style.borderColor = 'var(--color-primary)';
            dropZone.style.background = 'var(--color-surface-alt)';
        });

        dropZone.addEventListener('dragleave', function(e) {
            e.preventDefault();
            dropZone.style.borderColor = '';
            dropZone.style.background = '';
        });

        dropZone.addEventListener('drop', function(e) {
            e.preventDefault();
            dropZone.style.borderColor = '';
            dropZone.style.background = '';
            if (isUploading) return;
            if (e.dataTransfer.files.length) {
                uploadPhotos(e.dataTransfer.files);
            }
        });

        fileInput.addEventListener('change', function(e) {
            e.preventDefault();
            e.stopPropagation();
            if (isUploading) {
                this.value = '';
                return;
            }
            if (this.files && this.files.length > 0) {
                const files = this.files;
                uploadPhotos(files);
                this.value = '';
            }
        });
    }

    // ===== Обработчики для кнопки "Изменить фото" в карточке =====
    if (photoUploadLabel && photoInput) {
        photoUploadLabel.addEventListener('click', function(e) {
            e.stopPropagation();
            if (isUploading) return;
            photoInput.click();
        });
        photoInput.addEventListener('change', function(e) {
            if (e.target.files.length) {
                uploadLogo(e.target.files[0]);
                e.target.value = '';
            }
        });
    }

    // ===== Кнопка "Редактировать" (начальная) =====
    const initialToggle = document.getElementById('salonEditToggleBtn');
    if (initialToggle) {
        initialToggle.addEventListener('click', function() {
            if (isEditing) {
                exitEditMode();
            } else {
                enterEditMode();
            }
        });
    }

    // ===== Существующие функции =====
    window.deletePromo = function(id, title) {
        if (confirm('Удалить акцию "' + title + '"? Это действие нельзя отменить.')) {
            fetch('/api/v1/business/my-salon/promotions/' + id + '/delete', { method: 'POST' })
                .then(r => { if (r.ok) location.reload(); else alert('Ошибка при удалении'); });
        }
    };

    const WH_DAY_KEYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];

    window.toggleDayClosed = function(day, isClosed) {
        document.getElementById('wh-start-' + day).disabled = isClosed;
        document.getElementById('wh-end-' + day).disabled = isClosed;
    };

    window.copyMondayToWeekdays = function() {
        const start = document.getElementById('wh-start-mon').value;
        const end = document.getElementById('wh-end-mon').value;
        const mondayClosed = document.querySelector('.wh-closed[data-day="mon"]').checked;
        ['tue', 'wed', 'thu', 'fri'].forEach(day => {
            document.querySelector(`.wh-closed[data-day="${day}"]`).checked = mondayClosed;
            document.getElementById('wh-start-' + day).value = start;
            document.getElementById('wh-end-' + day).value = end;
            toggleDayClosed(day, mondayClosed);
        });
    };

    window.saveWorkingHours = async function(salonId) {
        const hours = {};
        for (const day of WH_DAY_KEYS) {
            const closed = document.querySelector(`.wh-closed[data-day="${day}"]`).checked;
            if (closed) {
                hours[day] = 'closed';
            } else {
                const start = document.getElementById('wh-start-' + day).value;
                const end = document.getElementById('wh-end-' + day).value;
                if (!start || !end) { alert('Укажите время начала и конца для рабочего дня'); return; }
                hours[day] = start + '-' + end;
            }
        }
        try {
            const res = await fetch(`/api/v1/business/my-salon?salon_id=${salonId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ working_hours: JSON.stringify(hours) })
            });
            if (res.ok) { alert('Часы работы сохранены'); location.reload(); }
            else { const d = await res.json(); alert(d.detail || 'Ошибка'); }
        } catch (e) { alert('Ошибка сети'); }
    };

    window.saveLoyaltySettings = async function(salonId) {
        const body = {
            regular_client_discount_percent: parseInt(document.getElementById('loyaltyRegularPercent').value) || 0,
            regular_client_visits_threshold: document.getElementById('loyaltyVisitsThreshold').value
                ? parseInt(document.getElementById('loyaltyVisitsThreshold').value) : null,
            bonus_accrual_percent: parseFloat(document.getElementById('loyaltyBonusAccrual').value) || 0,
        };
        try {
            const res = await fetch(`/api/v1/loyalty/salon/${salonId}/settings`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });
            if (res.ok) { alert('Настройки лояльности сохранены'); }
            else { const d = await res.json(); alert(d.detail || 'Ошибка'); }
        } catch (e) { alert('Ошибка сети'); }
    };

    window.addLoyaltyOffer = async function(salonId) {
        const title = document.getElementById('loyaltyOfferTitle').value.trim();
        const discount_percent = parseInt(document.getElementById('loyaltyOfferPercent').value);
        const promo_code = document.getElementById('loyaltyOfferCode').value.trim() || null;
        if (!title || !discount_percent) { alert('Заполните название и размер скидки'); return; }
        try {
            const res = await fetch(`/api/v1/loyalty/salon/${salonId}/offers`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title, discount_percent, promo_code })
            });
            if (res.ok) { location.reload(); }
            else { const d = await res.json(); alert(d.detail || 'Ошибка'); }
        } catch (e) { alert('Ошибка сети'); }
    };

    window.deleteLoyaltyOffer = function(id, title) {
        if (!confirm(`Удалить скидку «${title}»?`)) return;
        const salonId = window.salonId;
        fetch(`/api/v1/loyalty/salon/${salonId}/offers/${id}`, { method: 'DELETE' })
            .then(r => { if (r.ok) location.reload(); else r.json().then(d => alert(d.detail || 'Ошибка')); });
    };

    // Модалки
    document.querySelectorAll('.my-salon-modal-close').forEach(btn => {
        btn.addEventListener('click', function() {
            this.closest('.my-salon-modal-overlay').classList.remove('active');
        });
    });

    document.querySelectorAll('.my-salon-modal-overlay').forEach(overlay => {
        overlay.addEventListener('click', function(e) {
            if (e.target === this) {
                this.classList.remove('active');
            }
        });
    });

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            document.querySelectorAll('.my-salon-modal-overlay.active').forEach(el => el.classList.remove('active'));
        }
    });

    // ===== Опасная зона: скрыть/показать салон, удалить салон =====
    const visibilityBtn = document.getElementById('salonVisibilityBtn');
    if (visibilityBtn) {
        visibilityBtn.addEventListener('click', async function() {
            const wasHidden = this.dataset.hidden === '1';
            this.disabled = true;
            try {
                const res = await fetch(`/api/v1/business/my-salon/visibility-toggle?salon_id=${this.dataset.salonId}`, { method: 'POST' });
                if (!res.ok) { alert('Не удалось изменить видимость салона'); this.disabled = false; return; }
                const data = await res.json();
                const hint = document.getElementById('salonVisibilityHint');
                const icon = window.ICON_EYE || '';
                if (data.is_hidden) {
                    hint.textContent = 'Салон скрыт: его не видно в каталоге, поиске и записи. Включите обратно в любой момент.';
                    this.innerHTML = icon + ' Показать салон';
                    this.classList.remove('my-salon-btn-outline');
                    this.classList.add('my-salon-btn-primary');
                } else {
                    hint.textContent = 'Салон скрыт не будет — он виден клиентам в каталоге, поиске и доступен для записи.';
                    this.innerHTML = icon + ' Скрыть салон';
                    this.classList.remove('my-salon-btn-primary');
                    this.classList.add('my-salon-btn-outline');
                }
                this.dataset.hidden = data.is_hidden ? '1' : '0';
            } catch (e) {
                alert('Ошибка сети, попробуйте ещё раз');
            }
            this.disabled = false;
        });
    }

    const deleteBtn = document.getElementById('salonDeleteBtn');
    if (deleteBtn) {
        deleteBtn.addEventListener('click', async function() {
            if (!confirm('Удалить салон? Он пропадёт из каталога и записи. Брони, отзывы и мастера сохранятся в истории, но самостоятельно восстановить салон будет нельзя.')) return;
            this.disabled = true;
            try {
                const res = await fetch(`/api/v1/business/my-salon?salon_id=${this.dataset.salonId}`, { method: 'DELETE' });
                if (res.ok) {
                    alert('Салон удалён.');
                    window.location.href = '/business/dashboard';
                } else {
                    const d = await res.json().catch(() => ({}));
                    alert(d.detail || 'Не удалось удалить салон');
                    this.disabled = false;
                }
            } catch (e) {
                alert('Ошибка сети, попробуйте ещё раз');
                this.disabled = false;
            }
        });
    }

    // ===== Сеть салонов: поиск партнёра, запрос, голосование, выход =====
    const chainSearchInput = document.getElementById('chainSearchInput');
    if (chainSearchInput) {
        const resultsBox = document.getElementById('chainSearchResults');
        const sendBtn = document.getElementById('chainSendRequestBtn');
        let selectedSalonId = null;
        let searchTimer = null;

        chainSearchInput.addEventListener('input', function() {
            selectedSalonId = null;
            if (sendBtn) sendBtn.disabled = true;
            clearTimeout(searchTimer);
            const q = this.value.trim();
            if (q.length < 2) { resultsBox.innerHTML = ''; return; }
            searchTimer = setTimeout(async () => {
                try {
                    const res = await fetch(`/api/v1/business/chain/search-salons?q=${encodeURIComponent(q)}&exclude_salon_id=${sendBtn.dataset.salonId}`);
                    const items = res.ok ? await res.json() : [];
                    resultsBox.innerHTML = '';
                    if (!items.length) {
                        resultsBox.innerHTML = '<div class="chain-search-empty">Ничего не найдено</div>';
                        return;
                    }
                    items.forEach(item => {
                        const row = document.createElement('div');
                        row.className = 'chain-search-item';
                        row.textContent = item.name + (item.address ? ' — ' + item.address : '');
                        row.addEventListener('click', () => {
                            selectedSalonId = item.id;
                            chainSearchInput.value = item.name;
                            resultsBox.innerHTML = '';
                            if (sendBtn) sendBtn.disabled = false;
                        });
                        resultsBox.appendChild(row);
                    });
                } catch (e) { /* сеть моргнула */ }
            }, 300);
        });

        if (sendBtn) {
            sendBtn.addEventListener('click', async function() {
                if (!selectedSalonId) return;
                this.disabled = true;
                try {
                    const res = await fetch('/api/v1/business/chain/request', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ from_salon_id: parseInt(this.dataset.salonId), to_salon_id: selectedSalonId }),
                    });
                    if (res.ok) {
                        const data = await res.json();
                        alert(data.status === 'accepted' ? 'Салоны объединены в сеть!' : 'Запрос отправлен, ждём согласия второй стороны.');
                        location.reload();
                    } else {
                        const d = await res.json().catch(() => ({}));
                        alert(d.detail || 'Не удалось отправить запрос');
                        this.disabled = false;
                    }
                } catch (e) {
                    alert('Ошибка сети, попробуйте ещё раз');
                    this.disabled = false;
                }
            });
        }
    }

    document.querySelectorAll('.chain-cancel-btn').forEach(btn => {
        btn.addEventListener('click', async function() {
            if (!confirm('Отменить запрос на объединение?')) return;
            this.disabled = true;
            try {
                const res = await fetch(`/api/v1/business/chain/request/${this.dataset.requestId}/cancel`, { method: 'POST' });
                if (res.ok) { location.reload(); return; }
                const d = await res.json().catch(() => ({}));
                alert(d.detail || 'Ошибка');
                this.disabled = false;
            } catch (e) { alert('Ошибка сети'); this.disabled = false; }
        });
    });

    document.querySelectorAll('.chain-vote-btn').forEach(btn => {
        btn.addEventListener('click', async function() {
            const approve = this.dataset.approve === '1';
            if (!confirm(approve ? 'Согласиться на объединение в сеть?' : 'Отклонить запрос на объединение?')) return;
            this.disabled = true;
            try {
                const res = await fetch(`/api/v1/business/chain/request/${this.dataset.requestId}/vote`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ salon_id: parseInt(this.dataset.salonId), approve }),
                });
                if (res.ok) {
                    const data = await res.json();
                    if (approve && data.status === 'pending') alert('Ваш голос учтён, ждём остальных владельцев.');
                    location.reload();
                } else {
                    const d = await res.json().catch(() => ({}));
                    alert(d.detail || 'Ошибка');
                    this.disabled = false;
                }
            } catch (e) { alert('Ошибка сети'); this.disabled = false; }
        });
    });

    const chainLeaveBtn = document.getElementById('chainLeaveBtn');
    if (chainLeaveBtn) {
        chainLeaveBtn.addEventListener('click', async function() {
            if (!confirm('Покинуть сеть? Салон перестанет показываться как «другой адрес» для партнёров.')) return;
            this.disabled = true;
            try {
                const res = await fetch('/api/v1/business/chain/leave', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ salon_id: parseInt(this.dataset.salonId) }),
                });
                if (res.ok) { location.reload(); return; }
                const d = await res.json().catch(() => ({}));
                alert(d.detail || 'Ошибка');
                this.disabled = false;
            } catch (e) { alert('Ошибка сети'); this.disabled = false; }
        });
    }

});
