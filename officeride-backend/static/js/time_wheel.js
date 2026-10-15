// Time popup: tap the time box and a small card opens with three scroll wheels (hour, minute, am/pm)
// and four quick buttons. There is no Done button: the box updates as you scroll, a quick button also
// closes the card, and so does a tap outside it or the Esc key.
// The server draws a normal <input type="time" data-time-wheel data-presets="09:00,12:00">. This file
// swaps it for the popup. Without JavaScript the browser's own time box is used and still posts "HH:MM".
(function () {
  var ROW = 44; // height of one wheel row, in pixels
  var SHOWN = 5; // rows visible at once

  var css = [
    ".tw{position:relative}",
    ".tw-box{display:flex;align-items:center;justify-content:space-between;text-align:left;width:100%}",
    ".tw-pop{position:absolute;z-index:1060;left:0;top:calc(100% + 6px);width:min(320px,100%);min-width:280px;background:#fff;",
    "border:1px solid #dee2e6;border-radius:18px;box-shadow:0 12px 32px rgba(0,0,0,.18);padding:14px 16px 16px}",
    ".tw-pop[hidden]{display:none}",
    ".tw-title{text-align:center;font-weight:700;margin-bottom:6px}",
    ".tw-wheels{position:relative;display:flex;justify-content:center;gap:6px;height:" + ROW * SHOWN + "px}",
    ".tw-band{position:absolute;left:0;right:0;top:" + ROW * 2 + "px;height:" + ROW + "px;background:#f4f5f7;border-radius:12px;pointer-events:none}",
    ".tw-wheel{position:relative;width:76px;height:100%;overflow-y:scroll;scroll-snap-type:y mandatory;scrollbar-width:none;",
    "padding:" + ROW * 2 + "px 0;box-sizing:border-box;-webkit-overflow-scrolling:touch}",
    ".tw-wheel::-webkit-scrollbar{display:none}",
    ".tw-item{height:" + ROW + "px;line-height:" + ROW + "px;text-align:center;scroll-snap-align:center;font-size:1.15rem;color:#adb5bd;cursor:pointer;user-select:none}",
    ".tw-item.on{color:#111;font-size:1.6rem;font-weight:500}",
    ".tw-colon{position:relative;line-height:" + ROW * SHOWN + "px;font-size:1.6rem;font-weight:700;width:10px;text-align:center}",
    ".tw-fade{position:absolute;left:0;right:0;height:" + ROW * 1.5 + "px;pointer-events:none}",
    ".tw-fade.top{top:0;background:linear-gradient(#fff,rgba(255,255,255,0))}",
    ".tw-fade.bottom{bottom:0;background:linear-gradient(rgba(255,255,255,0),#fff)}",
    ".tw-label{margin:10px 0 6px;font-size:.9rem}",
    ".tw-presets{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}",
    ".tw-preset{border:2px solid #eceef1;background:#fff;border-radius:14px;padding:9px 0;font-weight:600;font-size:.95rem}",
    ".tw-preset.on{border-color:#0d6efd;background:#f2f7ff}"
  ].join("");
  var style = document.createElement("style");
  style.textContent = css;
  document.head.appendChild(style);

  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function parse(value) {
    var m = /^(\d{1,2}):(\d{2})/.exec(value || "");
    if (!m) return null;
    var h = +m[1], min = +m[2];
    if (h > 23 || min > 59) return null;
    return { h24: h, min: min };
  }
  function label(t) { return (t.h24 % 12 || 12) + ":" + pad(t.min) + " " + (t.h24 >= 12 ? "PM" : "AM"); }
  function short(t) { return (t.h24 % 12 || 12) + (t.min ? ":" + pad(t.min) : "") + " " + (t.h24 >= 12 ? "pm" : "am"); }

  function wheel(items) {
    var el = document.createElement("div");
    el.className = "tw-wheel";
    items.forEach(function (text) {
      var item = document.createElement("div");
      item.className = "tw-item";
      item.textContent = text;
      el.appendChild(item);
    });
    return el;
  }

  function build(input) {
    var presets = (input.dataset.presets || "").split(",").map(parse).filter(Boolean);
    var current = parse(input.value);

    // The real box becomes a hidden field, so the form still posts "HH:MM" and nothing blocks the submit.
    input.type = "hidden";
    input.required = false;

    var wrap = document.createElement("div");
    wrap.className = "tw";
    input.insertAdjacentElement("afterend", wrap);

    var box = document.createElement("button");
    box.type = "button";
    box.className = "form-select tw-box";
    box.setAttribute("aria-haspopup", "dialog");
    wrap.appendChild(box);

    var pop = document.createElement("div");
    pop.className = "tw-pop";
    pop.hidden = true;
    pop.setAttribute("role", "dialog");
    pop.setAttribute("aria-label", "Pick a time");
    wrap.appendChild(pop);

    var title = document.createElement("div");
    title.className = "tw-title";
    title.textContent = "Time";
    pop.appendChild(title);

    var wheels = document.createElement("div");
    wheels.className = "tw-wheels";
    var hours = wheel(Array.from({ length: 12 }, function (_, i) { return String(i + 1); }));
    var mins = wheel(Array.from({ length: 60 }, function (_, i) { return pad(i); }));
    var ampm = wheel(["am", "pm"]);
    var colon = document.createElement("div");
    colon.className = "tw-colon";
    colon.textContent = ":";
    var band = document.createElement("div");
    band.className = "tw-band";
    wheels.appendChild(band);
    [hours, colon, mins, ampm].forEach(function (n) { wheels.appendChild(n); });
    ["top", "bottom"].forEach(function (side) {
      var fade = document.createElement("div");
      fade.className = "tw-fade " + side;
      wheels.appendChild(fade);
    });
    pop.appendChild(wheels);

    var presetBox = null;
    var presetButtons = [];
    if (presets.length) {
      var heading = document.createElement("div");
      heading.className = "tw-label";
      heading.textContent = "Presets";
      pop.appendChild(heading);
      presetBox = document.createElement("div");
      presetBox.className = "tw-presets";
      presets.forEach(function (t) {
        var b = document.createElement("button");
        b.type = "button";
        b.className = "tw-preset";
        b.textContent = short(t);
        b.addEventListener("click", function () {
          setWheels(t);
          commit(t);
          close();
        });
        b.dataset.value = pad(t.h24) + ":" + pad(t.min);
        presetButtons.push(b);
        presetBox.appendChild(b);
      });
      pop.appendChild(presetBox);
    }

    function setWheels(t) {
      hours.scrollTop = ((t.h24 % 12 || 12) - 1) * ROW;
      mins.scrollTop = t.min * ROW;
      ampm.scrollTop = (t.h24 >= 12 ? 1 : 0) * ROW;
      mark();
    }

    function read() {
      var h = Math.min(11, Math.max(0, Math.round(hours.scrollTop / ROW)));
      var m = Math.min(59, Math.max(0, Math.round(mins.scrollTop / ROW)));
      var pm = Math.round(ampm.scrollTop / ROW) >= 1;
      return { h24: (h + 1) % 12 + (pm ? 12 : 0), min: m };
    }

    function mark() {
      [hours, mins, ampm].forEach(function (w) {
        var at = Math.round(w.scrollTop / ROW);
        Array.prototype.forEach.call(w.children, function (item, i) { item.classList.toggle("on", i === at); });
      });
      var value = pad(read().h24) + ":" + pad(read().min);
      presetButtons.forEach(function (b) { b.classList.toggle("on", b.dataset.value === value); });
    }

    function commit(t) {
      current = t;
      input.value = pad(t.h24) + ":" + pad(t.min);
      paint();
      input.dispatchEvent(new Event("change", { bubbles: true }));
    }

    function paint() {
      box.textContent = "";
      var text = document.createElement("span");
      text.textContent = current ? label(current) : "Pick a time";
      if (!current) text.className = "text-secondary";
      box.appendChild(text);
      var icon = document.createElement("i");
      icon.className = "bi bi-clock text-secondary";
      box.appendChild(icon);
    }

    // The box follows the wheels once they stop moving.
    [hours, mins, ampm].forEach(function (w) {
      var timer;
      w.addEventListener("scroll", function () {
        mark();
        clearTimeout(timer);
        timer = setTimeout(function () { if (!pop.hidden) commit(read()); }, 120);
      });
      w.addEventListener("click", function (e) {
        var i = Array.prototype.indexOf.call(w.children, e.target);
        if (i >= 0) w.scrollTo({ top: i * ROW, behavior: "smooth" });
      });
    });

    function open() {
      pop.hidden = false;
      box.setAttribute("aria-expanded", "true");
      var start = current || presets[0] || { h24: 9, min: 0 };
      setWheels(start);
      if (!current) commit(start); // the card shows what will be posted
    }
    function close() {
      pop.hidden = true;
      box.setAttribute("aria-expanded", "false");
    }

    box.addEventListener("click", function () { pop.hidden ? open() : close(); });
    document.addEventListener("click", function (e) { if (!wrap.contains(e.target)) close(); });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !pop.hidden) { close(); box.focus(); }
    });

    // The label for this field points at the button, so tapping the label opens the card too.
    if (input.id) {
      var lab = document.querySelector('label[for="' + input.id + '"]');
      if (lab) {
        box.id = input.id + "_box";
        lab.setAttribute("for", box.id);
      }
    }
    paint();
  }

  document.querySelectorAll("input[data-time-wheel]").forEach(build);
})();