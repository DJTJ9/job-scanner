// progressive enhancement, kein Feature hängt hiervon ab
document.addEventListener("DOMContentLoaded", () => {
  const criteriaForm = document.querySelector("form[data-criteria-form]");
  if (criteriaForm) {
    const btn = criteriaForm.querySelector(".btn-primary");
    criteriaForm.querySelectorAll("input[type=range]").forEach((slider) => {
      slider.addEventListener("input", () => {
        if (btn) btn.classList.add("dirty");
        const out = slider.closest(".criterion")?.querySelector(".weight");
        if (out) out.textContent = slider.value;
      });
    });
  }

  document.querySelectorAll(".criterion input[type=range]").forEach((slider) => {
    if (slider.closest("form[data-criteria-form]")) return;  // Feintuning-Slider hat schon einen Listener
    const out = slider.closest(".criterion")?.querySelector(".weight");
    if (out) {
      out.textContent = slider.value;
      slider.addEventListener("input", () => { out.textContent = slider.value; });
    }
  });

  const drawer = document.getElementById("drawer");
  document.querySelectorAll("[data-drawer-open]").forEach((btn) => {
    btn.addEventListener("click", () => { if (drawer) drawer.classList.remove("panel-hidden"); });
  });
  document.querySelectorAll("[data-drawer-close]").forEach((btn) => {
    btn.addEventListener("click", () => { if (drawer) drawer.classList.add("panel-hidden"); });
  });

  // Im Mobile-Layout liegt der Drawer als Overlay über der Seite (.page ohne
  // margin-left). Ein In-Page-Sprunglink scrollt sonst auf ein Ziel, das hinter
  // der Sidebar liegt — deshalb hier schließen.
  const drawerHashClose = () => {
    if (drawer && window.matchMedia("(max-width: 900px)").matches) {
      drawer.classList.add("panel-hidden");
    }
  };
  document.querySelectorAll('a[href^="#"]').forEach((link) => {
    link.addEventListener("click", drawerHashClose);
  });

  const collapseBtn = document.querySelector("[data-drawer-collapse]");
  const applyDrawerCollapsed = (collapsed) => {
    if (drawer) drawer.classList.toggle("drawer-collapsed", collapsed);
    document.body.classList.toggle("drawer-collapsed", collapsed);
    if (collapseBtn) collapseBtn.textContent = collapsed ? "»" : "«";
  };
  if (drawer) applyDrawerCollapsed(localStorage.getItem("drawer_collapsed") === "1");
  if (collapseBtn) {
    collapseBtn.addEventListener("click", () => {
      const next = !drawer.classList.contains("drawer-collapsed");
      applyDrawerCollapsed(next);
      localStorage.setItem("drawer_collapsed", next ? "1" : "0");
    });
  }

  document.querySelectorAll("[data-onboarding-open]").forEach((trigger) => {
    trigger.addEventListener("click", () => {
      if (drawer) drawer.classList.add("panel-hidden");
      document.querySelectorAll(".onboarding-panel").forEach((p) => p.classList.add("panel-hidden"));
      const panel = document.getElementById(trigger.dataset.onboardingOpen);
      if (panel) panel.classList.remove("panel-hidden");
    });
  });
  document.querySelectorAll("[data-onboarding-close]").forEach((closeBtn) => {
    closeBtn.addEventListener("click", () => {
      const panel = document.getElementById(closeBtn.dataset.onboardingClose);
      if (panel) panel.classList.add("panel-hidden");
    });
  });

  const feedbackPanel = document.getElementById("feedback-panel");
  document.querySelectorAll("[data-feedback-toggle]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (feedbackPanel) feedbackPanel.classList.toggle("panel-hidden");
    });
  });
  document.querySelectorAll("[data-feedback-close]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (feedbackPanel) feedbackPanel.classList.add("panel-hidden");
    });
  });
  document.querySelectorAll("[data-feedback-submit]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const textarea = feedbackPanel.querySelector("[data-feedback-text]");
      const text = textarea ? textarea.value.trim() : "";
      if (!text) return;
      fetch("/api/feedback", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": document.querySelector('meta[name="csrf-token"]').content,
        },
        body: JSON.stringify({ text }),
      })
        .then((r) => r.json())
        .then((data) => {
          const body = feedbackPanel.querySelector(".feedback-panel-body");
          if (body && data.message) {
            body.innerHTML = "";
            const p = document.createElement("p");
            p.textContent = data.message;
            body.appendChild(p);
          }
        });
    });
  });

  // Befehle kopieren (geteilt: /anleitung)
  document.querySelectorAll("[data-copy]").forEach(btn => {
    btn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(btn.dataset.copy);
      } catch (e) {
        return;  // kein Clipboard-Zugriff: Befehl steht ohnehin sichtbar daneben
      }
      const alt = btn.textContent;
      btn.textContent = "✓";
      btn.classList.add("kopiert");
      setTimeout(() => { btn.textContent = alt; btn.classList.remove("kopiert"); }, 1200);
    });
  });

  // /einstellungen: Reiter umschalten (kein Reload, URL-Hash sync)
  const tabs = Array.from(document.querySelectorAll(".tab[data-tab]"));
  if (tabs.length) {
    const panels = document.querySelectorAll("[data-tab-panel]");
    const activate = name => {
      tabs.forEach(t => t.classList.toggle("tab-active", t.dataset.tab === name));
      panels.forEach(p => p.classList.toggle("tab-panel-active", p.dataset.tabPanel === name));
    };
    tabs.forEach(t => t.addEventListener("click", () => {
      activate(t.dataset.tab);
      history.replaceState(null, "", "#" + t.dataset.tab);
    }));
    const hash = window.location.hash.replace("#", "");
    if (hash && tabs.some(t => t.dataset.tab === hash)) activate(hash);
  }

  // /anleitung/vollstaendig: Lotleine — aktives Kapitel + Scrollfortschritt
  const rail = document.querySelector(".anl-rail");
  if (rail) {
    const fill = rail.querySelector(".anl-rail-fill");
    const links = Array.from(rail.querySelectorAll(".anl-rail-link"));
    const kapitel = Array.from(document.querySelectorAll(".anl-kapitel"));
    const schmal = () => window.matchMedia("(max-width: 900px)").matches;
    const setzeAktiv = id => links.forEach(a =>
      a.classList.toggle("anl-rail-link-active", a.getAttribute("href") === "#" + id));
    if (kapitel.length) {
      const beobachter = new IntersectionObserver(eintraege => {
        const sichtbar = eintraege.filter(e => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
        if (sichtbar) setzeAktiv(sichtbar.target.id);
      }, { rootMargin: "-20% 0px -70% 0px" });
      kapitel.forEach(k => beobachter.observe(k));
      setzeAktiv(kapitel[0].id);
    }
    const fortschritt = () => {
      const max = document.documentElement.scrollHeight - window.innerHeight;
      const anteil = max > 0 ? Math.min(1, window.scrollY / max) : 0;
      if (schmal()) { fill.style.width = (anteil * 100) + "%"; fill.style.height = "100%"; }
      else { fill.style.height = (anteil * 100) + "%"; fill.style.width = "100%"; }
    };
    window.addEventListener("scroll", fortschritt, { passive: true });
    window.addEventListener("resize", fortschritt);
    fortschritt();
  }

  document.querySelectorAll("[data-profile-switcher]").forEach((sel) => {
    sel.addEventListener("change", () => sel.form.submit());
  });
});

// Passwort-Stärke-Gauge (Tiefenlinie-Form): füllt sich veto→signal→beute
document.querySelectorAll("[data-strength-input]").forEach(function (input) {
  var gauge = document.querySelector("[data-strength-gauge]");
  if (!gauge) return;
  var bar = gauge.querySelector("span");
  input.addEventListener("input", function () {
    var v = input.value;
    var score = 0;
    if (v.length >= 6) score++;
    if (v.length >= 10) score++;
    if (/[0-9]/.test(v) && /[a-zA-Z]/.test(v)) score++;
    var level = Math.min(score, 3);
    gauge.setAttribute("data-level", String(level));
    bar.style.width = (level / 3 * 100) + "%";
  });
});

// Speichern-Bestätigung für die stillen Einstellungs-Forms: fetch-POST statt
// nativem Redirect, Button 2s auf "✓ Gespeichert". Ohne JS bleibt der native POST.
document.querySelectorAll("[data-confirm-save]").forEach(function (form) {
  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var btn = event.submitter || form.querySelector('button[type="submit"]');
    if (!btn || btn.disabled) return;
    var original = btn.textContent;
    fetch(form.action, { method: "POST", body: new FormData(form) })
      .then(function (res) {
        if (!res.ok) { form.submit(); return; }
        if (form.hasAttribute("data-reload-on-save")) {
          sessionStorage.setItem("restoreScroll", String(window.scrollY));
          window.location = res.url || window.location.href;
          return;
        }
        btn.textContent = "✓ Gespeichert";
        btn.disabled = true;
        setTimeout(function () {
          btn.textContent = original;
          btn.disabled = false;
        }, 2000);
      })
      .catch(function () { form.submit(); });
  });
});

// Scroll-Position nach einem data-reload-on-save-Reload wiederherstellen.
window.addEventListener("load", function () {
  var y = sessionStorage.getItem("restoreScroll");
  if (y !== null) {
    sessionStorage.removeItem("restoreScroll");
    window.scrollTo(0, parseInt(y, 10) || 0);
  }
});

// Profil-Karte: "Löschen" blendet ein Bestätigungs-Panel in derselben Karte ein statt
// direkt zu submitten. Ohne JS bleibt das native onsubmit-confirm des Formulars stehen;
// mit JS wird es beim Aufklappen entfernt, damit nicht zweimal nachgefragt wird.
document.querySelectorAll("[data-profile-delete]").forEach(function (btn) {
  btn.addEventListener("click", function () {
    var id = btn.dataset.profileDelete;
    var body = document.getElementById("profile-body-" + id);
    var panel = document.getElementById("profile-confirm-" + id);
    if (!body || !panel) return;
    var form = panel.querySelector("form");
    if (form) form.removeAttribute("onsubmit");
    body.classList.add("panel-hidden");
    panel.classList.remove("panel-hidden");
    panel.focus();
  });
});
document.querySelectorAll("[data-profile-delete-cancel]").forEach(function (btn) {
  btn.addEventListener("click", function () {
    var id = btn.dataset.profileDeleteCancel;
    var body = document.getElementById("profile-body-" + id);
    var panel = document.getElementById("profile-confirm-" + id);
    if (!body || !panel) return;
    panel.classList.add("panel-hidden");
    body.classList.remove("panel-hidden");
  });
});
// --- Onboarding-Tour: Sonar-Spotlight über der Übersicht ---
// Auto-Start bei data-tour-auto am <body> (Erstbesuch), Wiederholung über
// [data-tour-start]. Schritte ohne sichtbares Ziel werden übersprungen.
(() => {
  const TOUR = [
    { sel: "#drawer", titel: "Dein Menü", text: "Hier kommst du überall hin: Job-Angebote, Favoriten, dein Profil und das Feintuning." },
    { sel: "[data-drawer-open]", titel: "Dein Menü", text: "Hinter dem ☰ steckt alles: Job-Angebote, Favoriten, dein Profil und das Feintuning." },
    { sel: ".bob-intro", titel: "Wer ich bin", text: "Kurz vorgestellt: was ich kann und wie ich arbeite. Aufklappen lohnt sich." },
    { sel: ".anl-check", titel: "Deine To-do-Liste", text: "Vier Schritte, ganz ohne eigenes Claude-Abo: Profil anlegen, Job-Angebote ansehen, fünf Jobs bewerten, Feintuning anpassen." },
    { sel: ".sonar-band", titel: "Mein Sonar", text: "Hier siehst du, wann ich zuletzt gescannt habe und wie viele Anzeigen im Netz sind.", extra: '.drawer-item[href="/jobs"]' },
    { sel: ".job-card", titel: "Dein Treffer", text: "So sieht ein Treffer aus — mit Passung von 0 bis 100 und Begründung pro Kriterium.", extra: '.drawer-item[href="/jobs"]' },
    { sel: "[data-vote-btn]", titel: "Bewerten", text: "👍 oder 👎 — jede Bewertung schärft meine Suche für dich." },
  ];
  const reduziert = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let schritte = [], idx = 0, spot = null, spot2 = null, bubble = null, letzterFokus = null;
  let tourName = "tour_seen", introOffen = false;

  const sichtbar = (el) => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };

  const setzeSpot = (el, ziel) => {
    const r = ziel.getBoundingClientRect();
    const pad = 6;
    el.style.top = `${r.top - pad}px`;
    el.style.left = `${r.left - pad}px`;
    el.style.width = `${r.width + 2 * pad}px`;
    el.style.height = `${r.height + 2 * pad}px`;
  };

  const positioniere = () => {
    const s = schritte[idx];
    setzeSpot(spot, s.el);
    const neben = s.extra ? document.querySelector(s.extra) : null;
    if (neben && sichtbar(neben)) {
      spot2.style.display = "";
      setzeSpot(spot2, neben);
    } else {
      spot2.style.display = "none";
    }
  };

  const zeige = (i) => {
    idx = i;
    const s = schritte[i];
    s.el.scrollIntoView({ block: "center", behavior: reduziert ? "auto" : "smooth" });
    spot.classList.remove("tour-ping");
    void spot.offsetWidth;  // Reflow, damit der Sweep bei jedem Schritt neu läuft
    if (!reduziert) spot.classList.add("tour-ping");
    spot2.classList.remove("tour-ping");
    void spot2.offsetWidth;
    if (!reduziert) spot2.classList.add("tour-ping");
    bubble.querySelector("h3").textContent = s.titel;
    bubble.querySelector("p").textContent = s.text;
    bubble.querySelector(".tour-zaehler").textContent = `${i + 1}/${schritte.length}`;
    bubble.querySelector("[data-tour-prev]").disabled = i === 0;
    bubble.querySelector("[data-tour-next]").textContent =
      i === schritte.length - 1 ? "Fertig" : "Weiter";
    positioniere();
  };

  const beende = () => {
    document.removeEventListener("keydown", tastatur, true);
    window.removeEventListener("scroll", positioniere, true);
    window.removeEventListener("resize", positioniere);
    spot.remove(); spot2.remove(); bubble.remove();
    spot = spot2 = bubble = null;
    if (introOffen) {
      const intro = document.querySelector(".bob-intro");
      if (intro) intro.open = true;
      introOffen = false;
    }
    if (document.body.hasAttribute("data-tour-auto")) {
      document.body.removeAttribute("data-tour-auto");
      fetch("/tour/seen", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": document.querySelector('meta[name="csrf-token"]').content,
        },
        body: JSON.stringify({ tour: tourName }),
      });
    }
    if (letzterFokus) letzterFokus.focus();
  };

  const tastatur = (e) => {
    if (e.key === "Escape") { e.preventDefault(); beende(); return; }
    if (e.key !== "Tab") return;
    const foki = bubble.querySelectorAll("button:not(:disabled)");
    const erste = foki[0], letzte = foki[foki.length - 1];
    if (e.shiftKey && document.activeElement === erste) { e.preventDefault(); letzte.focus(); }
    else if (!e.shiftKey && document.activeElement === letzte) { e.preventDefault(); erste.focus(); }
  };

  function starte(startIndex = 0) {
    if (spot) return;  // läuft schon
    const intro = document.querySelector(".bob-intro");
    if (intro && intro.open) { intro.open = false; introOffen = true; }
    schritte = TOUR
      .map((s) => ({ ...s, el: document.querySelector(s.sel) }))
      .filter((s) => s.el && sichtbar(s.el));
    if (!schritte.length) return;
    letzterFokus = document.activeElement;
    spot = document.createElement("div");
    spot.className = "tour-spot";
    spot2 = document.createElement("div");
    spot2.className = "tour-spot tour-spot-neben";
    spot2.style.display = "none";
    bubble = document.createElement("div");
    bubble.className = "tour-bubble";
    bubble.setAttribute("role", "dialog");
    bubble.setAttribute("aria-modal", "true");
    bubble.setAttribute("aria-label", "Onboarding-Tour");
    bubble.innerHTML =
      '<img class="bob-avatar" src="/static/img/bob/bob-pose-winken.png" alt="">' +
      '<h3></h3><p aria-live="polite"></p>' +
      '<div class="tour-fuss"><span class="tour-zaehler mono"></span>' +
      '<button type="button" class="btn btn-secondary" data-tour-prev>Zurück</button>' +
      '<button type="button" class="btn btn-primary" data-tour-next>Weiter</button></div>' +
      '<button type="button" class="tour-beenden" data-tour-exit>Tour beenden</button>';
    document.body.append(spot, spot2, bubble);
    bubble.querySelector("[data-tour-prev]").addEventListener("click", () => zeige(idx - 1));
    bubble.querySelector("[data-tour-next]").addEventListener("click", () => {
      if (idx === schritte.length - 1) beende(); else zeige(idx + 1);
    });
    bubble.querySelector("[data-tour-exit]").addEventListener("click", beende);
    document.addEventListener("keydown", tastatur, true);
    window.addEventListener("scroll", positioniere, true);
    window.addEventListener("resize", positioniere);
    zeige(Math.min(Math.max(0, startIndex), schritte.length - 1));
    bubble.querySelector("[data-tour-next]").focus();
  }

  document.querySelectorAll("[data-tour-start]").forEach((b) => b.addEventListener("click", () => starte()));
  const auto = document.body.getAttribute("data-tour-auto");
  if (auto !== null) {
    tourName = auto ? "tour2_seen" : "tour_seen";
    starte(auto ? Number(auto) : 0);
  }
})();
