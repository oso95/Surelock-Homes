const runBtn = document.getElementById("runBtn");
const queryInput = document.getElementById("query");
const offlineToggle = document.getElementById("offlineToggle");
const resultContainer = document.getElementById("result");

runBtn.addEventListener("click", async () => {
  runBtn.disabled = true;
  runBtn.textContent = "Running...";
  const query = queryInput.value.trim();
  try {
    const response = await fetch("/api/investigate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query,
        offline: offlineToggle.checked
      })
    });
    const payload = await response.json();
    resultContainer.textContent = JSON.stringify(payload, null, 2);
  } catch (error) {
    resultContainer.textContent = String(error);
  } finally {
    runBtn.disabled = false;
    runBtn.textContent = "Run investigation";
  }
});
