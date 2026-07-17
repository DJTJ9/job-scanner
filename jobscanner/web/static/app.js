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
});
