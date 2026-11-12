// Light/dark switch. The first choice follows the device; after that the saved choice wins.
(function () {
  var button = document.getElementById("theme-toggle");
  if (!button) return;
  function current() { return document.documentElement.getAttribute("data-bs-theme") || "light"; }
  function paint() {
    var icon = button.querySelector("i");
    if (icon) icon.className = current() === "dark" ? "bi bi-sun" : "bi bi-moon-stars";
  }
  button.addEventListener("click", function () {
    var next = current() === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-bs-theme", next);
    try { localStorage.setItem("theme", next); } catch (e) {}
    paint();
  });
  paint();
})();
