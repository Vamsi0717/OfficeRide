// Place picker: type a place, pick a suggestion, and the hidden name/lat/lng fields are filled.
// Suggestions come from our own server (/rides/places/search/), so the maps key never reaches the browser.
(function () {
  function debounce(fn, ms) {
    var timer;
    return function () {
      clearTimeout(timer);
      timer = setTimeout(fn, ms);
    };
  }

  document.querySelectorAll("[data-place-picker]").forEach(function (box) {
    var url = box.dataset.searchUrl;
    var input = box.querySelector(".place-input");
    var list = box.querySelector(".place-results");
    var nameField = box.querySelector('input[name$="_name"]');
    var latField = box.querySelector('input[name$="_lat"]');
    var lngField = box.querySelector('input[name$="_lng"]');

    input.value = nameField.value || "";

    function clearChoice() {
      nameField.value = "";
      latField.value = "";
      lngField.value = "";
    }

    function showMessage(text) {
      list.textContent = "";
      var note = document.createElement("div");
      note.className = "list-group-item text-muted small";
      note.textContent = text;
      list.appendChild(note);
    }

    function choose(item) {
      nameField.value = item.name;
      latField.value = item.lat;
      lngField.value = item.lng;
      input.value = item.name;
      list.textContent = "";
    }

    function show(items) {
      list.textContent = "";
      if (!items.length) {
        showMessage("No places found. Try another name.");
        return;
      }
      items.forEach(function (item) {
        var button = document.createElement("button");
        button.type = "button";
        button.className = "list-group-item list-group-item-action";
        var title = document.createElement("div");
        title.textContent = item.name;
        var sub = document.createElement("div");
        sub.className = "small text-muted";
        sub.textContent = item.address;
        button.appendChild(title);
        button.appendChild(sub);
        button.addEventListener("click", function () {
          choose(item);
        });
        list.appendChild(button);
      });
    }

    var search = debounce(function () {
      var query = input.value.trim();
      if (query.length < 3) {
        list.textContent = "";
        return;
      }
      fetch(url + "?q=" + encodeURIComponent(query), {
        headers: { Accept: "application/json" },
        credentials: "same-origin",
      })
        .then(function (response) {
          return response.json().then(function (data) {
            if (!response.ok) {
              throw new Error(data.error || "Search is not available right now.");
            }
            return data;
          });
        })
        .then(function (data) {
          show(data.results);
        })
        .catch(function (error) {
          showMessage(error.message);
        });
    }, 300);

    input.addEventListener("input", function () {
      clearChoice(); // typing again means the old choice no longer applies
      search();
    });
  });
})();