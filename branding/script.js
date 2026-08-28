/* ============================================================
   KACHOW — Landing / Pitch site interactions
   Vanilla JS · no dependencies
   ============================================================ */
(function () {
  "use strict";

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------- Sticky nav ---------- */
  const nav = document.getElementById("nav");
  const onScroll = () => nav.classList.toggle("is-stuck", window.scrollY > 12);
  onScroll();
  window.addEventListener("scroll", onScroll, { passive: true });

  /* ---------- Reveal on scroll ---------- */
  const reveals = document.querySelectorAll(".reveal");
  if (reduceMotion || !("IntersectionObserver" in window)) {
    reveals.forEach((el) => el.classList.add("is-in"));
  } else {
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-in");
            io.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.16, rootMargin: "0px 0px -8% 0px" }
    );
    reveals.forEach((el) => io.observe(el));
  }

  /* ---------- Count-up numbers ---------- */
  const easeOut = (t) => 1 - Math.pow(1 - t, 3);

  function animateCount(el) {
    const target = parseFloat(el.dataset.count);
    const decimals = parseInt(el.dataset.decimals || "0", 10);
    const prefix = (el.dataset.prefix || "").replace(/&lt;/g, "<").replace(/&gt;/g, ">");
    const suffix = el.dataset.suffix || "";
    const raw = el.dataset.raw;

    if (Number.isNaN(target)) return;
    if (reduceMotion) {
      el.textContent = raw || prefix + target.toFixed(decimals) + suffix;
      return;
    }

    const duration = 1400;
    const start = performance.now();
    function tick(now) {
      const p = Math.min(1, (now - start) / duration);
      const val = target * easeOut(p);
      el.textContent = prefix + val.toFixed(decimals) + suffix;
      if (p < 1) {
        requestAnimationFrame(tick);
      } else {
        el.textContent = raw || prefix + target.toFixed(decimals) + suffix;
      }
    }
    requestAnimationFrame(tick);
  }

  const counters = document.querySelectorAll("[data-count]");
  if (!("IntersectionObserver" in window)) {
    counters.forEach(animateCount);
  } else {
    const cio = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            animateCount(entry.target);
            cio.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.6 }
    );
    counters.forEach((el) => cio.observe(el));
  }

  /* ---------- Pipeline runner ---------- */
  const pipeline = document.getElementById("pipeline");
  if (pipeline) {
    const nodes = Array.from(pipeline.querySelectorAll(".pnode"));
    let timer = null;
    let idx = 0;

    function step() {
      nodes.forEach((n) => n.classList.remove("is-active"));
      const node = nodes[idx];
      node.classList.add("is-active");
      // keep active node visible inside the horizontal scroller
      const track = node.parentElement;
      const targetLeft = node.offsetLeft - track.clientWidth / 2 + node.clientWidth / 2;
      track.scrollTo({ left: Math.max(0, targetLeft), behavior: reduceMotion ? "auto" : "smooth" });
      idx = (idx + 1) % nodes.length;
      // pause a beat on the human-gate node
      const delay = node.classList.contains("pnode--human") ? 2200 : 1100;
      timer = setTimeout(step, delay);
    }

    const pio = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting && !timer) {
            step();
          } else if (!entry.isIntersecting && timer) {
            clearTimeout(timer);
            timer = null;
          }
        });
      },
      { threshold: 0.3 }
    );
    pio.observe(pipeline);
  }

  /* ---------- Demo card: reveal human gate, handle actions ---------- */
  const demoCard = document.getElementById("demoCard");
  if (demoCard) {
    const steps = demoCard.querySelectorAll("#demoSteps li");
    const gate = document.getElementById("demoGate");
    let played = false;

    function playDemo() {
      if (played) return;
      played = true;
      const seq = [
        () => setState(3, "done", "Mevzuat bulundu · 2 ilgili madde"),
        () => setState(4, "run", "Taslak üretiliyor…"),
        () => setState(4, "done", "Taslak hazır · 1 sayfa"),
        () => setState(5, "run", "Kaynak doğrulama…"),
        () => {
          setState(5, "done", "Doğrulama: 1 kritik bulgu");
          gate.classList.add("is-shown");
        },
      ];
      seq.forEach((fn, i) => setTimeout(fn, reduceMotion ? 0 : 900 * (i + 1)));
    }

    function setState(i, state, text) {
      if (!steps[i]) return;
      steps[i].dataset.state = state;
      if (text) steps[i].innerHTML = text;
    }

    const dio = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            playDemo();
            dio.disconnect();
          }
        });
      },
      { threshold: 0.4 }
    );
    dio.observe(demoCard);

    demoCard.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-demo]");
      if (!btn) return;
      const gateEl = document.getElementById("demoGate");
      if (btn.dataset.demo === "approve") {
        gateEl.innerHTML =
          '<span class="demo__gate-tag" style="color:var(--emerald)">Onaylandı</span>' +
          "<p>Taslak kaydedildi ve <b>Yazı İşleri Müdürlüğü</b>'ne yönlendirildi. İşlem iz kaydına yazıldı.</p>";
      } else {
        gateEl.innerHTML =
          '<span class="demo__gate-tag">Revizyon İstendi</span>' +
          "<p>Akış aynı noktadan devam edecek. Tarih alanı için kaynak evrak yeniden istenecek.</p>";
      }
    });
  }

  /* ---------- Active section in nav ---------- */
  const navLinks = Array.from(document.querySelectorAll(".nav__links a"));
  const idToLink = new Map(navLinks.map((a) => [a.getAttribute("href").slice(1), a]));
  const targets = navLinks
    .map((a) => document.getElementById(a.getAttribute("href").slice(1)))
    .filter(Boolean);

  if (targets.length && "IntersectionObserver" in window) {
    const sio = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            navLinks.forEach((a) => a.classList.remove("is-current"));
            const link = idToLink.get(entry.target.id);
            if (link) link.classList.add("is-current");
          }
        });
      },
      { threshold: 0.5, rootMargin: "-20% 0px -60% 0px" }
    );
    targets.forEach((t) => sio.observe(t));
  }
})();
