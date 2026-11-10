// Webcam capture for the registration form. Works without any outside library.
// If the browser has no camera API (or the page is not on localhost/https), only the normal file picker shows.
(function () {
  var input = document.getElementById("id_photo");
  var preview = document.getElementById("photo-preview");
  var box = document.getElementById("camera-box");
  if (!input) return;

  input.addEventListener("change", function () {
    if (input.files && input.files[0] && preview) preview.src = URL.createObjectURL(input.files[0]);
  });

  if (!box || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return;
  box.hidden = false;

  var live = document.getElementById("camera-live");
  var video = document.getElementById("camera-video");
  var stream = null;

  function stop() {
    if (stream) stream.getTracks().forEach(function (t) { t.stop(); });
    stream = null;
    live.hidden = true;
  }

  document.getElementById("camera-open").addEventListener("click", function () {
    navigator.mediaDevices.getUserMedia({ video: { facingMode: "user" } }).then(function (s) {
      stream = s;
      video.srcObject = s;
      live.hidden = false;
    }).catch(function () {
      alert("The camera could not be opened. Use the file picker instead.");
    });
  });

  document.getElementById("camera-cancel").addEventListener("click", stop);

  document.getElementById("camera-snap").addEventListener("click", function () {
    var w = video.videoWidth, h = video.videoHeight;
    if (!w || !h) return;
    var scale = Math.min(1, 800 / Math.max(w, h));
    var canvas = document.createElement("canvas");
    canvas.width = Math.round(w * scale);
    canvas.height = Math.round(h * scale);
    canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob(function (blob) {
      var file = new File([blob], "camera.jpg", { type: "image/jpeg" });
      var transfer = new DataTransfer();
      transfer.items.add(file);
      input.files = transfer.files;
      if (preview) preview.src = URL.createObjectURL(file);
      stop();
    }, "image/jpeg", 0.9);
  });
})();
