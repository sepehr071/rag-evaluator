// RAG Evaluator Dashboard JavaScript

document.addEventListener('DOMContentLoaded', function() {
    // Initialize tooltips
    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function(tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });

    // Table sorting
    const tables = document.querySelectorAll('table.sortable');
    tables.forEach(table => {
        const headers = table.querySelectorAll('th');
        headers.forEach((header, index) => {
            header.style.cursor = 'pointer';
            header.addEventListener('click', () => sortTable(table, index));
        });
    });

    // Search functionality
    const searchInput = document.getElementById('searchInput');
    if (searchInput) {
        searchInput.addEventListener('input', function() {
            filterTable(this.value);
        });
    }
});

// Sort table by column
function sortTable(table, columnIndex) {
    const tbody = table.querySelector('tbody');
    const rows = Array.from(tbody.querySelectorAll('tr'));

    const isAscending = table.dataset.sortOrder === 'asc';
    table.dataset.sortOrder = isAscending ? 'desc' : 'asc';

    rows.sort((a, b) => {
        const aValue = a.cells[columnIndex].textContent.trim();
        const bValue = b.cells[columnIndex].textContent.trim();

        // Try to parse as number
        const aNum = parseFloat(aValue);
        const bNum = parseFloat(bValue);

        if (!isNaN(aNum) && !isNaN(bNum)) {
            return isAscending ? bNum - aNum : aNum - bNum;
        }

        return isAscending
            ? bValue.localeCompare(aValue, 'fa')
            : aValue.localeCompare(bValue, 'fa');
    });

    rows.forEach(row => tbody.appendChild(row));
}

// Filter table rows
function filterTable(searchTerm) {
    const table = document.getElementById('resultsTable');
    if (!table) return;

    const rows = table.querySelectorAll('tbody tr');
    const term = searchTerm.toLowerCase();

    rows.forEach(row => {
        const text = row.textContent.toLowerCase();
        row.style.display = text.includes(term) ? '' : 'none';
    });
}

// Show loading overlay
function showLoading(message = 'در حال پردازش...') {
    const overlay = document.createElement('div');
    overlay.className = 'spinner-overlay';
    overlay.id = 'loadingOverlay';
    overlay.innerHTML = `
        <div class="spinner-content">
            <div class="spinner-border text-primary" style="width: 3rem; height: 3rem;" role="status">
                <span class="visually-hidden">Loading...</span>
            </div>
            <p class="mt-3">${message}</p>
        </div>
    `;
    document.body.appendChild(overlay);
}

// Hide loading overlay
function hideLoading() {
    const overlay = document.getElementById('loadingOverlay');
    if (overlay) {
        overlay.remove();
    }
}

// Format number with Persian digits (optional)
function toPersianDigits(num) {
    const persianDigits = ['۰', '۱', '۲', '۳', '۴', '۵', '۶', '۷', '۸', '۹'];
    return num.toString().replace(/\d/g, d => persianDigits[d]);
}

// Calculate average score
function calculateAverage(scores) {
    if (!scores || scores.length === 0) return 0;
    const sum = scores.reduce((a, b) => a + b, 0);
    return (sum / scores.length).toFixed(2);
}

// Export to CSV (client-side)
function exportToCSV(data, filename) {
    const csvContent = data.map(row => row.join(',')).join('\n');
    const blob = new Blob(['\ufeff' + csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    link.click();
}

// Confirm before long operation
function confirmEvaluation(questionCount) {
    const estimatedTime = Math.ceil(questionCount * 2 / 60); // ~2 seconds per question
    return confirm(
        `آیا مطمئن هستید؟\n\n` +
        `تعداد سوالات: ${questionCount}\n` +
        `زمان تخمینی: حدود ${estimatedTime} دقیقه`
    );
}

// ========================================
// Mobile Responsiveness
// ========================================

// Filter card toggle on mobile
document.addEventListener('DOMContentLoaded', function() {
    const filterCard = document.getElementById('filterCard');
    const filterHeader = filterCard?.querySelector('.card-header');

    if (filterHeader && window.innerWidth < 768) {
        filterCard.classList.add('collapsed');
        filterHeader.addEventListener('click', function() {
            filterCard.classList.toggle('collapsed');
        });
    }

    // Sync filtering between table and mobile cards
    const filters = {
        overall: document.getElementById('filterOverall'),
        accuracy: document.getElementById('filterAccuracy'),
        completeness: document.getElementById('filterCompleteness'),
        relevance: document.getElementById('filterRelevance'),
        faithfulness: document.getElementById('filterFaithfulness'),
        humanEval: document.getElementById('filterHumanEval')
    };

    // Mobile card filtering
    function applyFiltersToMobile() {
        if (!filters.overall) return;

        const minOverall = parseFloat(filters.overall.value);
        const minAccuracy = parseFloat(filters.accuracy.value);
        const minCompleteness = parseFloat(filters.completeness.value);
        const minRelevance = parseFloat(filters.relevance.value);
        const minFaithfulness = parseFloat(filters.faithfulness.value);
        const humanEvalFilter = filters.humanEval.value;

        // Filter mobile cards
        const mobileCards = document.querySelectorAll('.mobile-result-item');
        mobileCards.forEach(card => {
            const avg = parseFloat(card.dataset.avg);
            const accuracy = parseFloat(card.dataset.accuracy);
            const completeness = parseFloat(card.dataset.completeness);
            const relevance = parseFloat(card.dataset.relevance);
            const faithfulness = parseFloat(card.dataset.faithfulness);
            const humanEvaluated = card.dataset.humanEvaluated === 'true';

            let show = avg >= minOverall &&
                       accuracy >= minAccuracy &&
                       completeness >= minCompleteness &&
                       relevance >= minRelevance &&
                       faithfulness >= minFaithfulness;

            if (humanEvalFilter === 'evaluated') show = show && humanEvaluated;
            else if (humanEvalFilter === 'not-evaluated') show = show && !humanEvaluated;

            card.style.display = show ? '' : 'none';
        });
    }

    // Attach filter listeners
    if (filters.overall) {
        Object.keys(filters).forEach(key => {
            filters[key].addEventListener('input', applyFiltersToMobile);
            filters[key].addEventListener('change', applyFiltersToMobile);
        });
    }

    // Handle window resize - remove collapsed state on desktop
    let resizeTimer;
    window.addEventListener('resize', function() {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(function() {
            const filterCard = document.getElementById('filterCard');
            if (filterCard && window.innerWidth >= 768) {
                filterCard.classList.remove('collapsed');
            }
        }, 250);
    });
});
