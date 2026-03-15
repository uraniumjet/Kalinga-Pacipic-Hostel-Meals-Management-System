let mealChart; // Global variable to hold the chart instance

document.addEventListener("DOMContentLoaded", function() {
    updateDashboardData();
    
    // Live Search for Logs
    document.getElementById('logSearch').addEventListener('input', function(e) {
        let val = e.target.value.toLowerCase();
        document.querySelectorAll('.log-row').forEach(row => {
            row.style.display = row.innerText.toLowerCase().includes(val) ? '' : 'none';
        });
    });

    // Chart Type Switcher
    document.getElementById('chartType').addEventListener('change', function() {
        updateDashboardData(); // Re-render with new type
    });
});

function updateDashboardData() {
    fetch("/api/meals/stats/")
        .then(res => res.json())
        .then(data => {
            // Update Card Stats
            const totalServed = data.breakfast + data.lunch + data.dinner;
            document.getElementById("servedToday").innerText = totalServed;
            document.getElementById("currentMealDisplay").innerText = "Last Sync: " + new Date().toLocaleTimeString();
            
            // Render Chart
            renderChart(data);
        });
}

function renderChart(data) {
    const ctx = document.getElementById('mealChart').getContext('2d');
    const type = document.getElementById('chartType').value;

    // If chart already exists, destroy it before creating a new one
    if (mealChart) {
        mealChart.destroy();
    }

    mealChart = new Chart(ctx, {
        type: type,
        data: {
            labels: ['Breakfast', 'Lunch', 'Dinner'],
            datasets: [{
                label: 'Meals Taken Today',
                data: [data.breakfast, data.lunch, data.dinner],
                backgroundColor: ['#0d6efd', '#198754', '#ffc107'],
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: (type === 'pie') }
            }
        }
    });
}