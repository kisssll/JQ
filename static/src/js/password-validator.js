// static/src/js/password-validator.js
(function() {
    var pw = document.getElementById('pw');
    var btn = document.getElementById('submitBtn');
    if (!pw || !btn) return;

    var rules = {
        len: function(v) { return v.length >= 8; },
        lower: function(v) { return /[a-zа-яё]/.test(v); },
        upper: function(v) { return /[A-ZА-ЯЁ]/.test(v); },
        digit: function(v) { return /[0-9]/.test(v); }
    };

    function update() {
        var v = pw.value;
        var all = true;
        Object.keys(rules).forEach(function(k) {
            var ok = rules[k](v);
            all = all && ok;
            var li = document.querySelector('[data-rule="' + k + '"]');
            if (li) {
                var mark = li.querySelector('.mark');
                if (mark) mark.textContent = ok ? '✓' : '✗';
                li.style.color = ok ? 'var(--color-success)' : 'var(--color-muted)';
            }
        });
        btn.disabled = !all;
        btn.style.opacity = all ? '1' : '0.6';
        btn.style.cursor = all ? 'pointer' : 'not-allowed';
    }

    pw.addEventListener('input', update);
    update();
})();