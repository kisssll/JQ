// Открывает фотографии в полноэкранном просмотрщике на всех страницах.
(function () {
    let overlay;
    let image;

    function close() {
        if (!overlay) return;
        overlay.classList.remove('active');
        document.body.classList.remove('lightbox-open');
        image.removeAttribute('src');
    }

    function open(src, alt) {
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.className = 'photo-lightbox';
            overlay.innerHTML = `
                <button type="button" class="photo-lightbox-close" aria-label="Закрыть">×</button>
                <img class="photo-lightbox-image" alt="">
            `;
            document.body.appendChild(overlay);
            image = overlay.querySelector('.photo-lightbox-image');
            overlay.addEventListener('click', function (event) {
                if (event.target === overlay || event.target.closest('.photo-lightbox-close')) close();
            });
        }
        image.src = src;
        image.alt = alt || '';
        overlay.classList.add('active');
        document.body.classList.add('lightbox-open');
    }

    document.addEventListener('click', function (event) {
        const target = event.target.closest('[data-lightbox-src]');
        if (!target) return;
        event.preventDefault();
        event.stopPropagation();
        open(target.dataset.lightboxSrc, target.dataset.lightboxAlt);
    });

    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') close();
    });
})();
