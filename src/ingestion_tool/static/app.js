// Upload form: drag-and-drop + progress indicator
document.addEventListener("DOMContentLoaded", function () {
  var dropZone = document.getElementById("drop-zone");
  var fileInput = document.getElementById("file-input");
  var dropText = document.getElementById("drop-text");
  var form = document.getElementById("upload-form");
  var submitBtn = document.getElementById("submit-btn");
  var progress = document.getElementById("upload-progress");

  if (!dropZone || !fileInput) return;

  // Show selected file name
  fileInput.addEventListener("change", function () {
    if (fileInput.files.length > 0) {
      dropText.textContent = fileInput.files[0].name;
    }
  });

  // Drag and drop
  ["dragenter", "dragover"].forEach(function (evt) {
    dropZone.addEventListener(evt, function (e) {
      e.preventDefault();
      dropZone.classList.add("drop-active");
    });
  });

  ["dragleave", "drop"].forEach(function (evt) {
    dropZone.addEventListener(evt, function (e) {
      e.preventDefault();
      dropZone.classList.remove("drop-active");
    });
  });

  dropZone.addEventListener("drop", function (e) {
    if (e.dataTransfer.files.length > 0) {
      fileInput.files = e.dataTransfer.files;
      dropText.textContent = e.dataTransfer.files[0].name;
    }
  });

  // Submit progress
  if (form && submitBtn && progress) {
    form.addEventListener("submit", function () {
      submitBtn.disabled = true;
      submitBtn.textContent = "Processing...";
      progress.classList.remove("hidden");
    });
  }
});
