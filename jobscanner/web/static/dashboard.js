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

  // Lernen: Status pollen, bei Wechsel neu laden (Karten sind server-rendered)
  const lernenPanel = document.querySelector('[data-tab-panel="lernen"]');
  if (lernenPanel) {
    const status = lernenPanel.dataset.analysisStatus;
    if (status === "analyzing" || status === "synthesizing") {
      const poll = setInterval(async () => {
        try {
          const resp = await fetch(window.location.pathname + "/analysis",
                                   { headers: { "Accept": "application/json" } });
          if (!resp.ok) return;
          const data = await resp.json();
          if (data.status !== status) { clearInterval(poll); window.location.reload(); }
        } catch (e) { /* transient */ }
      }, 3000);
    }
  }

  // Widerspruchs-Antworten vor dem Finalize als JSON speichern
  const answersForm = document.querySelector("[data-answers-form]");
  if (answersForm) {
    answersForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const answers = {};
      answersForm.querySelectorAll('input[type="text"]').forEach((inp) => {
        answers[inp.name] = inp.value;
      });
      const base = window.location.pathname.replace(/\/$/, "");
      try {
        await fetch(base + "/analysis/answers", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ analysis_id: Number(answersForm.dataset.analysisId), answers }),
        });
      } catch (e) { /* answers optional */ }
      const finalize = document.createElement("form");
      finalize.method = "post";
      finalize.action = base + "/finalize";
      document.body.appendChild(finalize);
      finalize.submit();
    });
  }
});
