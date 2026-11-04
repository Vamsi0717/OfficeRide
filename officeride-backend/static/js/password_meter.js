// Password strength meter: four bars that fill as the password meets the rules, and a line that says what is still missing.
// The rules are the same ones the server checks (8 characters, a letter, a number, a symbol), so this is only a help.
// Without JavaScript the normal help text under the field is shown instead.
(function () {
  var input = document.querySelector("input[data-password-meter]");
  if (!input) return;

  var rules = [
    { ok: function (v) { return v.length >= 8; }, need: "8 or more characters" },
    { ok: function (v) { return /[A-Za-z]/.test(v); }, need: "a letter" },
    { ok: function (v) { return /\d/.test(v); }, need: "a number" },
    { ok: function (v) { return /[^A-Za-z0-9]/.test(v); }, need: "a symbol" }
  ];

  var meter = document.createElement("div");
  meter.className = "or-meter";
  meter.setAttribute("aria-hidden", "true");
  for (var i = 0; i < rules.length; i++) meter.appendChild(document.createElement("i"));
  var text = document.createElement("div");
  text.className = "or-meter-text";
  text.setAttribute("aria-live", "polite");

  var help = input.closest(".mb-3").querySelector(".form-text");
  if (help) help.hidden = true;
  input.insertAdjacentElement("afterend", meter);
  meter.insertAdjacentElement("afterend", text);

  function update() {
    var v = input.value;
    var missing = rules.filter(function (r) { return !r.ok(v); });
    var done = rules.length - missing.length;
    Array.prototype.forEach.call(meter.children, function (bar, i) { bar.classList.toggle("on", i < done); });
    meter.classList.toggle("weak", done > 0 && done < rules.length);
    if (!v) {
      text.textContent = "Use 8 or more characters, with a letter, a number and a symbol.";
    } else if (!missing.length) {
      text.innerHTML = "<b>Strong password.</b> 8 or more characters, with a letter, a number and a symbol.";
    } else {
      text.textContent = "Still needed: " + missing.map(function (r) { return r.need; }).join(", ") + ".";
    }
  }
  input.addEventListener("input", update);
  update();
})();