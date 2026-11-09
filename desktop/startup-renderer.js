"use strict";
const bridge = window.ankiDesktop;
const elements = Object.fromEntries(
  [
    "title",
    "message",
    "details",
    "actions",
    "progress",
    "feedback",
    "retry",
    "export",
    "logs",
  ].map((id) => [id, document.getElementById(id)]),
);
function render(info) {
  const failed = info.status === "failed";
  elements.title.textContent = failed
    ? "Let’s get your workspace back."
    : info.status === "stopping"
      ? "Saving the work that matters."
      : "Your next idea is taking shape.";
  elements.message.textContent = info.message;
  elements.details.textContent =
    info.details || "Your documents and saved work stay on this device.";
  elements.actions.hidden = !failed;
  elements.progress.hidden = failed;
}
bridge
  .info()
  .then(render)
  .catch(() => {
    elements.message.textContent =
      "The desktop connection is unavailable. Relaunch Anki Generator.";
  });
bridge.onState(render);
function action(button, operation) {
  button.addEventListener("click", async () => {
    button.disabled = true;
    elements.feedback.textContent = "";
    try {
      const result = await operation();
      if (result?.saved)
        elements.feedback.textContent =
          "Diagnostics saved. They exclude API keys and course document contents.";
    } catch (error) {
      elements.feedback.textContent =
        error.message || "This action could not finish.";
    } finally {
      button.disabled = false;
    }
  });
}
action(elements.retry, () => bridge.restartBackend());
action(elements.export, () => bridge.exportDiagnostics());
action(elements.logs, () => bridge.openDirectory("logs"));
