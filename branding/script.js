/* ============================================================
   KACHOW — Landing / Pitch site interactions
   Vanilla JS · no dependencies
   ============================================================ */
(function () {
  "use strict";

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------- Sticky nav + scroll progress ---------- */
  const nav = document.getElementById("nav");
  const scrollbar = document.getElementById("scrollbar");
  const gridLines = document.querySelector(".grid-lines");
  const heroAurora = document.querySelector(".hero__aurora");
  function onScroll() {
    const y = window.scrollY;
    nav.classList.toggle("is-stuck", y > 12);
    if (scrollbar) {
      const max = document.documentElement.scrollHeight - window.innerHeight;
      scrollbar.style.width = (max > 0 ? (y / max) * 100 : 0) + "%";
    }
    if (!reduceMotion) {
      if (gridLines) gridLines.style.transform = "translate3d(0," + (y * 0.12).toFixed(1) + "px,0)";
      // .style.translate composes with the rotate() animation on the aurora
      if (heroAurora && y < window.innerHeight * 1.4) {
        heroAurora.style.translate = "0 " + (y * 0.25).toFixed(1) + "px";
      }
    }
  }
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
    // Safety net: never leave content permanently invisible if the observer
    // is starved (e.g. page loaded in a background tab, exotic browsers).
    window.addEventListener("load", () => {
      setTimeout(() => reveals.forEach((el) => el.classList.add("is-in")), 4000);
    });
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
    el.classList.add("is-counting");
    function tick(now) {
      const p = Math.min(1, (now - start) / duration);
      const val = target * easeOut(p);
      el.textContent = prefix + val.toFixed(decimals) + suffix;
      if (p < 1) {
        requestAnimationFrame(tick);
      } else {
        el.textContent = raw || prefix + target.toFixed(decimals) + suffix;
        el.classList.remove("is-counting");
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
    const packet = pipeline.querySelector(".pipeline__packet");
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
      if (packet && !reduceMotion) {
        packet.style.transition = idx === 0 ? "none" : "transform .9s var(--ease), opacity .3s";
        packet.style.transform =
          "translate(" + (node.offsetLeft + node.clientWidth / 2 - 5) + "px, 26px)";
        packet.style.opacity = "1";
      }
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

  /* ---------- Hero title: split into words, reveal on load ---------- */
  const heroSection = document.getElementById("hero");
  const heroTitle = document.querySelector("[data-split]");
  if (heroTitle && heroSection) {
    if (reduceMotion) {
      heroSection.classList.add("is-ready");
    } else {
      const walk = (node) => {
        Array.from(node.childNodes).forEach((child) => {
          if (child.nodeType === 3) {
            const frag = document.createDocumentFragment();
            child.textContent.split(/(\s+)/).forEach((tok) => {
              if (tok.trim() === "") {
                frag.appendChild(document.createTextNode(tok));
              } else {
                const w = document.createElement("span");
                w.className = "word";
                const inner = document.createElement("span");
                inner.textContent = tok;
                w.appendChild(inner);
                frag.appendChild(w);
              }
            });
            node.replaceChild(frag, child);
          } else if (child.nodeType === 1 && child.tagName !== "BR") {
            // keep <span class="grad"> as one animated unit
            if (child.classList.contains("grad")) {
              const w = document.createElement("span");
              w.className = "word";
              child.parentNode.insertBefore(w, child);
              w.appendChild(child);
            } else {
              walk(child);
            }
          }
        });
      };
      try {
        walk(heroTitle);
      } catch (err) {
        /* if splitting fails for any reason, fall through to just showing it */
      }
      requestAnimationFrame(() => heroSection.classList.add("is-ready"));
    }
    // Hard safety net: the title must never stay invisible.
    setTimeout(() => heroSection.classList.add("is-ready"), 2500);
  }

  /* ---------- Card spotlight (mouse-follow glow) ---------- */
  if (!reduceMotion && window.matchMedia("(pointer:fine)").matches) {
    const spotCards = document.querySelectorAll(".pain, .task, .diff, .trust, .metric");
    spotCards.forEach((card) => {
      card.addEventListener("pointermove", (e) => {
        const r = card.getBoundingClientRect();
        card.style.setProperty("--mx", ((e.clientX - r.left) / r.width) * 100 + "%");
        card.style.setProperty("--my", ((e.clientY - r.top) / r.height) * 100 + "%");
      });
    });

    /* ---------- Magnetic primary buttons ---------- */
    document.querySelectorAll(".btn--primary").forEach((btn) => {
      btn.addEventListener("pointermove", (e) => {
        const r = btn.getBoundingClientRect();
        const mx = e.clientX - r.left - r.width / 2;
        const my = e.clientY - r.top - r.height / 2;
        btn.style.transform = "translate(" + mx * 0.18 + "px," + my * 0.28 + "px)";
      });
      btn.addEventListener("pointerleave", () => { btn.style.transform = ""; });
    });
  }

  /* ---------- Product showcase marquee + lightbox ---------- */
  const marquee = document.querySelector("[data-marquee]");
  if (marquee && !reduceMotion) {
    // duplicate each row's cards so the -50% keyframe loops seamlessly
    marquee.querySelectorAll(".marquee__row").forEach((row) => {
      row.innerHTML += row.innerHTML;
    });
  }

  const shots = Array.from(document.querySelectorAll(".shot"));
  const lightbox = document.getElementById("lightbox");
  if (shots.length && lightbox) {
    const lbImg = document.getElementById("lightboxImg");
    const lbCap = document.getElementById("lightboxCap");
    // de-duplicate the (possibly cloned) list into unique sources, in order
    const gallery = [];
    const seen = new Set();
    shots.forEach((fig) => {
      const img = fig.querySelector("img");
      if (!seen.has(img.src)) {
        seen.add(img.src);
        gallery.push({ src: img.src, cap: (fig.querySelector("figcaption") || {}).textContent || "" });
      }
    });
    let cur = 0;

    const show = (i) => {
      cur = (i + gallery.length) % gallery.length;
      lbImg.src = gallery[cur].src;
      lbImg.alt = gallery[cur].cap;
      lbCap.textContent = gallery[cur].cap;
    };
    const open = (i) => {
      show(i);
      lightbox.classList.add("is-open");
      lightbox.setAttribute("aria-hidden", "false");
      document.body.style.overflow = "hidden";
    };
    const close = () => {
      lightbox.classList.remove("is-open");
      lightbox.setAttribute("aria-hidden", "true");
      document.body.style.overflow = "";
    };

    shots.forEach((fig) => {
      fig.addEventListener("click", () => {
        const src = fig.querySelector("img").src;
        open(gallery.findIndex((g) => g.src === src));
      });
    });
    lightbox.querySelector(".lightbox__close").addEventListener("click", close);
    lightbox.querySelector(".lightbox__prev").addEventListener("click", () => show(cur - 1));
    lightbox.querySelector(".lightbox__next").addEventListener("click", () => show(cur + 1));
    lightbox.addEventListener("click", (e) => { if (e.target === lightbox) close(); });
    document.addEventListener("keydown", (e) => {
      if (!lightbox.classList.contains("is-open")) return;
      if (e.key === "Escape") close();
      else if (e.key === "ArrowLeft") show(cur - 1);
      else if (e.key === "ArrowRight") show(cur + 1);
    });
  }
})();
