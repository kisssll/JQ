// Снимок, который не отдался, убираем из разметки — под ним лежит монограмма
// (components/ui.py, mark()). Без этого Chrome рисует на месте картинки свой
// значок-заглушку поверх буквы: карточка выглядит сломанной, хотя запасной
// вариант предусмотрен.
//
// Слушаем на document в фазе ПЕРЕХВАТА: событие error у <img> не всплывает, а
// карточки приезжают и позже (догрузка каталога «показать ещё», избранное).
document.addEventListener(
    'error',
    (event) => {
        const img = event.target;
        if (img instanceof HTMLImageElement && img.closest('.r-mark--photo')) {
            img.remove();
        }
    },
    true,
);
