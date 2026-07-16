// progressive enhancement, kein Feature hängt hiervon ab
document.addEventListener("DOMContentLoaded", () => {
  const criteriaForm = document.querySelector("form[data-criteria-form]");
  if (criteriaForm) {
    const btn = criteriaForm.querySelector(".btn-primary");
    criteriaForm.querySelectorAll("input[type=range]").forEach((slider) => {
      slider.addEventListener("input", () => btn && btn.classList.add("dirty"));
    });
  }

  document.querySelectorAll("[data-onboarding-open]").forEach((trigger) => {
    trigger.addEventListener("click", () => {
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
});
