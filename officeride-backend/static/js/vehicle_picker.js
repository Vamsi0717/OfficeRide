// Vehicle picker: choosing a make shows only that make's models.
// Every model option carries data-make, written by the server. Mileage is never sent to the page.
(function () {
  document.querySelectorAll("[data-vehicle-picker]").forEach(function (box) {
    var make = box.querySelector('select[name="make"]');
    var model = box.querySelector('select[name="mileage_rate"]');
    if (!make || !model) return;

    function filter(keepSelection) {
      var chosen = make.value;
      Array.prototype.forEach.call(model.options, function (opt) {
        if (!opt.value) return; // the "Choose model" line always stays
        var show = opt.dataset.make === chosen;
        opt.hidden = !show;
        opt.disabled = !show;
      });
      var current = model.options[model.selectedIndex];
      if (!keepSelection || !current || (current.value && current.dataset.make !== chosen)) model.value = "";
      model.disabled = !chosen;
    }

    make.addEventListener("change", function () { filter(false); });
    filter(true);
  });
})();