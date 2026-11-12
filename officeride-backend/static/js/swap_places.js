// The swap button on Find a ride: pickup and drop trade places (their typed text and their hidden name, lat and lng).
(function () {
  document.querySelectorAll("[data-swap-places]").forEach(function (button) {
    var boxes = button.parentElement.querySelectorAll("[data-place-picker]");
    if (boxes.length !== 2) return;

    function fields(box) {
      return [
        box.querySelector(".place-input"),
        box.querySelector('input[name$="_name"]'),
        box.querySelector('input[name$="_lat"]'),
        box.querySelector('input[name$="_lng"]'),
      ];
    }

    button.addEventListener("click", function () {
      var first = fields(boxes[0]);
      var second = fields(boxes[1]);
      first.forEach(function (field, i) {
        var keep = field.value;
        field.value = second[i].value;
        second[i].value = keep;
      });
    });
  });
})();