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

  document.querySelectorAll("[data-dash-search]").forEach((input) => {
    let timer;
    input.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(() => { input.form.submit(); }, 400);
    });
    // Full-Page-Submit laedt neu -> Fokus + Cursor zurueck ins Suchfeld,
    // damit man auf dem Handy nach jedem Buchstaben weitertippen kann
    if (input.value) {
      input.focus();
      const end = input.value.length;
      input.setSelectionRange(end, end);
    }
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
          body: new URLSearchParams({
            vote: btn.value,
            csrf_token: document.querySelector('meta[name="csrf-token"]').content,
          }),
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

  document.querySelectorAll("[data-fav-form]").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const btn = event.submitter;
      if (!btn || btn.disabled) return;
      btn.disabled = true;
      try {
        const resp = await fetch(form.action, {
          method: "POST",
          headers: { "Accept": "application/json" },
          body: new URLSearchParams({
            csrf_token: document.querySelector('meta[name="csrf-token"]').content,
          }),
        });
        if (!resp.ok) return;
        const data = await resp.json();
        btn.classList.toggle("fav-active", data.favorite);
        btn.textContent = data.favorite ? "★" : "☆";
      } finally {
        btn.disabled = false;
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
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": document.querySelector('meta[name="csrf-token"]').content,
          },
          body: JSON.stringify({ analysis_id: Number(answersForm.dataset.analysisId), answers }),
        });
      } catch (e) { /* answers optional */ }
      const finalize = document.createElement("form");
      finalize.method = "post";
      finalize.action = base + "/finalize";
      const csrfInput = document.createElement("input");
      csrfInput.type = "hidden";
      csrfInput.name = "csrf_token";
      csrfInput.value = document.querySelector('meta[name="csrf-token"]').content;
      finalize.appendChild(csrfInput);
      document.body.appendChild(finalize);
      finalize.submit();
    });
  }

  const hash = window.location.hash.replace("#", "");
  if (hash) {
    const btn = document.querySelector(`[data-tab-target="${hash}"]`);
    if (btn) btn.click();
  }
});
