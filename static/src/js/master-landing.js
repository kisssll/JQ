/* static/src/js/master-landing.js — эффекты лендинга /dlya-masterov. */
(function () {
    "use strict";

    var reduce = window.matchMedia &&
        window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce || !("IntersectionObserver" in window)) {
        return;
    }

    document.documentElement.classList.add("ml-js");

    var targets = document.querySelectorAll(".ml-reveal");
    var counters = new Map();

    targets.forEach(function (el) {
        var parent = el.parentElement;
        var i = counters.get(parent) || 0;
        el.style.setProperty("--i", Math.min(i, 5));
        counters.set(parent, i + 1);
    });

    var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
            if (entry.isIntersecting) {
                entry.target.classList.add("is-visible");
                io.unobserve(entry.target);
            }
        });
    }, { threshold: 0.15, rootMargin: "0px 0px -8% 0px" });

    targets.forEach(function (el) { io.observe(el); });
})();
