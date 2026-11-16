// Opens Razorpay Checkout with UPI first. The order was made on the server; this page only shows it.
(function () {
  var box = document.getElementById("checkout");
  if (!box || typeof Razorpay === "undefined") { return; }
  var form = document.getElementById("confirm-form");
  var options = {
    key: box.dataset.key,
    amount: box.dataset.amount,
    currency: "INR",
    name: "OfficeRide",
    description: box.dataset.description,
    order_id: box.dataset.order,
    config: {
      display: {
        blocks: { upi: { name: "Pay using UPI", instruments: [{ method: "upi" }] } },
        sequence: ["block.upi"],
        preferences: { show_default_blocks: true }
      }
    },
    handler: function (response) {
      form.razorpay_payment_id.value = response.razorpay_payment_id;
      form.razorpay_order_id.value = response.razorpay_order_id;
      form.razorpay_signature.value = response.razorpay_signature;
      form.submit();
    },
    theme: { color: "#10B981" }
  };
  document.getElementById("pay-now").addEventListener("click", function () {
    new Razorpay(options).open();
  });
})();