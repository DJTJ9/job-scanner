// progressive enhancement, kein Feature hängt hiervon ab
document.addEventListener("DOMContentLoaded", () => {
  const criteriaForm = document.querySelector("form[data-criteria-form]");
  if (criteriaForm) {
    const btn = criteriaForm.querySelector(".btn-primary");
    criteriaForm.querySelectorAll("input[type=range]").forEach((slider) => {
      slider.addEventListener("input", () => btn && btn.classList.add("dirty"));
    });
  }

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
        headers: { "Content-Type": "application/json" },
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

  // /mitmachen: Befehle kopieren
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

  // /mitmachen: Tiefenlinie füllt sich beim Scrollen, Stationen blenden ein
  const profil = document.querySelector("[data-tauchprofil]");
  if (profil) {
    const fuellung = profil.querySelector("[data-tauchprofil-fuellung]");
    const stationen = Array.from(profil.querySelectorAll("[data-station]"));
    const ruhig = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (ruhig || !("IntersectionObserver" in window)) {
      stationen.forEach(s => s.classList.add("sichtbar"));
      if (fuellung) fuellung.dataset.fuellstand = String(stationen.length);
    } else {
      let erreicht = 0;
      const beobachter = new IntersectionObserver(eintraege => {
        eintraege.forEach(e => {
          if (!e.isIntersecting) return;
          e.target.classList.add("sichtbar");
          erreicht = Math.max(erreicht, stationen.indexOf(e.target) + 1);
          if (fuellung) fuellung.dataset.fuellstand = String(erreicht);
          beobachter.unobserve(e.target);
        });
      }, { rootMargin: "0px 0px -25% 0px" });
      stationen.forEach(s => beobachter.observe(s));
    }
  }
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
