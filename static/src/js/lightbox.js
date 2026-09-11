// Открывает фотографии в полноэкранном просмотрщике на всех страницах.
(function () {
    let overlay;
    let image;
    let counter;
    let photos = [];
    let currentIndex = 0;

    function close() {
        if (!overlay) return;
        overlay.classList.remove('active');
        document.body.classList.remove('lightbox-open');
        image.removeAttribute('src');
    }

    function showPhoto(index) {
        if (!photos.length) return;
        currentIndex = (index + photos.length) % photos.length;
        const photo = photos[currentIndex];
        image.src = photo.src;
        image.alt = photo.alt || '';
        counter.textContent = photos.length > 1
            ? `${currentIndex + 1} / ${photos.length}`
            : '';
    }

    function open(target) {
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.className = 'photo-lightbox';
            overlay.innerHTML = `
                <button type="button" class="photo-lightbox-close" aria-label="Закрыть">×</button>
                <button type="button" class="photo-lightbox-nav photo-lightbox-prev" aria-label="Предыдущее фото">‹</button>
                <img class="photo-lightbox-image" alt="">
                <button type="button" class="photo-lightbox-nav photo-lightbox-next" aria-label="Следующее фото">›</button>
                <span class="photo-lightbox-counter" aria-live="polite"></span>
            `;
            document.body.appendChild(overlay);
            image = overlay.querySelector('.photo-lightbox-image');
            counter = overlay.querySelector('.photo-lightbox-counter');
            overlay.addEventListener('click', function (event) {
                if (event.target === overlay || event.target.closest('.photo-lightbox-close')) {
                    close();
                } else if (event.target.closest('.photo-lightbox-prev')) {
                    showPhoto(currentIndex - 1);
                } else if (event.target.closest('.photo-lightbox-next')) {
                    showPhoto(currentIndex + 1);
                }
            });
        }
        const group = target.dataset.lightboxGroup;
        const selector = group
            ? `[data-lightbox-src][data-lightbox-group="${group}"]`
            : '[data-lightbox-src]';
        const seen = new Set();
        photos = Array.from(document.querySelectorAll(selector))
            .map(element => ({
                src: element.dataset.lightboxSrc,
                alt: element.dataset.lightboxAlt || '',
            }))
            .filter(photo => photo.src && !seen.has(photo.src) && seen.add(photo.src));
        const selectedIndex = photos.findIndex(photo => photo.src === target.dataset.lightboxSrc);
        showPhoto(selectedIndex >= 0 ? selectedIndex : 0);
        overlay.querySelectorAll('.photo-lightbox-nav').forEach(button => {
            button.hidden = photos.length < 2;
        });
        overlay.classList.add('active');
        document.body.classList.add('lightbox-open');
    }

    document.addEventListener('click', function (event) {
        const target = event.target.closest('[data-lightbox-src]');
        if (!target) return;
        event.preventDefault();
        event.stopPropagation();
        open(target);
    }, true);

    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') close();
        if (!overlay || !overlay.classList.contains('active') || photos.length < 2) return;
        if (event.key === 'ArrowLeft') showPhoto(currentIndex - 1);
        if (event.key === 'ArrowRight') showPhoto(currentIndex + 1);
    });
})();
