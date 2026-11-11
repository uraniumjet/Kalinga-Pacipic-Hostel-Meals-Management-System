// Camera QR scanning for the counter. Uses the browser's built-in QR reader (BarcodeDetector),
// so it needs no outside library. Where the browser cannot do it (some desktop browsers, or a
// page that is not on localhost/https) the button stays hidden and the USB scanner or typing still work.
(function () {
  var box = document.getElementById("scan-box");
  var input = document.getElementById("scan-input");
  var form = document.getElementById("scan-form");
  if (!box || !input || !form) return;
  if (!("BarcodeDetector" in window) || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return;

  var live = document.getElementById("scan-live");
  var video = document.getElementById("scan-video");
  var detector = null, stream = null, timer = null, busy = false;
  box.hidden = false;

  function stop() {
    if (timer) clearInterval(timer);
    timer = null;
    if (stream) stream.getTracks().forEach(function (t) { t.stop(); });
    stream = null;
    live.hidden = true;
  }

  function look() {
    if (busy || !video.videoWidth) return;
    busy = true;
    detector.detect(video).then(function (codes) {
      if (codes.length && codes[0].rawValue) {
        input.value = codes[0].rawValue;
        stop();
        if (form.requestSubmit) form.requestSubmit(); else form.submit();
      }
    }).catch(function () {}).then(function () { busy = false; });
  }

  document.getElementById("scan-open").addEventListener("click", function () {
    try { detector = new BarcodeDetector({ formats: ["qr_code"] }); }
    catch (e) { alert("This browser cannot read QR codes. Use a USB scanner or type the roll number."); return; }
    navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } }).then(function (s) {
      stream = s;
      video.srcObject = s;
      live.hidden = false;
      timer = setInterval(look, 300);
    }).catch(function () {
      alert("The camera could not be opened. Use a USB scanner or type the roll number.");
    });
  });

  document.getElementById("scan-stop").addEventListener("click", stop);
})();
