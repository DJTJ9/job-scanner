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
