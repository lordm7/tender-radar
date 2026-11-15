// Client-side filters for the dashboard. Works the same in the live app and the
// static demo, because it only reads data-* attributes already in the page.
(function () {
  const score = document.getElementById("f-score");
  const agency = document.getElementById("f-agency");
  const days = document.getElementById("f-days");
  const count = document.getElementById("f-count");
  if (!score) return;
  const cards = Array.from(document.querySelectorAll("#results .card"));

  function apply() {
    const minScore = Number(score.value);
    const maxDays = days.value === "" ? null : Number(days.value);
    let shown = 0;
    for (const card of cards) {
      const left = card.dataset.daysLeft;
      const ok =
        Number(card.dataset.score) >= minScore &&
        (agency.value === "" || card.dataset.agency === agency.value) &&
        (maxDays === null || (left !== "" && Number(left) >= 0 && Number(left) <= maxDays));
      card.style.display = ok ? "" : "none";
      if (ok) shown++;
    }
    count.textContent = shown + " of " + cards.length + " shown";
  }

  [score, agency, days].forEach((el) => el.addEventListener("change", apply));
  apply();
})();
