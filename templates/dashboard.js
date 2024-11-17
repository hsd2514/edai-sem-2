// dashboard.js
document.addEventListener("DOMContentLoaded", function () {
  // Real-time updates
  function updateReadings() {
    fetch("/api/readings")
      .then((response) => response.json())
      .then((data) => {
        // Update DOM elements
      });
  }

  function updateDashboard(data) {
    ["1", "2"].forEach((id) => {
      const value = data[`ldr${id}`];
      document.getElementById(`value-ldr${id}`).textContent = value;

      // Update flickering status
      const flickerStatus = data[`ldr${id}_flickering`] === true;
      const statusElement = document.getElementById(`status-ldr${id}`);

      if (flickerStatus) {
        statusElement.className = "badge bg-danger";
        statusElement.textContent = "FLICKERING";
      } else {
        const status = value < 500 ? "OFF" : value > 1000 ? "ON" : "DIM";
        statusElement.className = `badge bg-${
          status === "ON" ? "success" : status === "OFF" ? "danger" : "warning"
        }`;
        statusElement.textContent = status;
      }
    });
  }

  setInterval(() => {
    fetch("/update")
      .then((response) => response.json())
      .then((data) => {
        console.log("Firebase update:", new Date().toISOString());
        updateDashboard(data);
      });
  }, 5000); // Poll every 5 seconds
});
