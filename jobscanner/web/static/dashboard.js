// progressive enhancement, kein Feature hängt hiervon ab
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-tab-target]").forEach((tabBtn) => {
    tabBtn.addEventListener("click", () => {
      const target = tabBtn.dataset.tabTarget;
      document.querySelectorAll("[data-tab-target]").forEach((t) => {
        t.classList.toggle("active", t === tabBtn);
      });
      document.querySelectorAll("[data-tab-panel]").forEach((panel) => {
        panel.classList.toggle("panel-hidden", panel.dataset.tabPanel !== target);
      });
    });
  });

  document.querySelectorAll("[data-vote-form]").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const btn = event.submitter;
      if (!btn || btn.disabled) return;
      const card = form.closest(".job-card");
      const buttons = card.querySelectorAll("[data-vote-btn]");
      buttons.forEach((b) => { b.disabled = true; });
      try {
        const resp = await fetch(form.action, {
          method: "POST",
          headers: { "Accept": "application/json" },
          body: new URLSearchParams({ vote: btn.value }),
        });
        if (!resp.ok) return;
        const data = await resp.json();
        buttons.forEach((b) => {
          b.classList.toggle("active-up", data.vote === "up" && b.dataset.voteBtn === "up");
          b.classList.toggle("active-down", data.vote === "down" && b.dataset.voteBtn === "down");
        });
        const badge = card.querySelector("[data-feedback-badge]");
        if (badge && data.vote === "up") {
          badge.textContent = "✓ bewertet 👍";
          badge.className = "feedback-badge feedback-badge-up";
        } else if (badge && data.vote === "down") {
          badge.textContent = "✓ bewertet 👎";
          badge.className = "feedback-badge feedback-badge-down";
        }
      } finally {
        buttons.forEach((b) => { b.disabled = false; });
      }
    });
  });
});
