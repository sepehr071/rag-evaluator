/**
 * Data Collection Progress Handler
 * Handles form submission, progress polling, and result display
 */

(function() {
    'use strict';

    // Persian messages for user feedback
    const PERSIAN_MESSAGES = {
        starting: 'در حال شروع جمع‌آوری داده‌ها...',
        collecting: 'در حال جمع‌آوری داده‌ها...',
        completed: 'جمع‌آوری داده‌ها با موفقیت انجام شد.',
        error: 'خطا در جمع‌آوری داده‌ها',
        download: 'دانلود فایل',
        processing: 'در حال پردازش درخواست...',
        invalidFile: 'لطفاً یک فایل معتبر انتخاب کنید',
        networkError: 'خطا در ارتباط با سرور',
        status: {
            pending: 'در انتظار',
            running: 'در حال اجرا',
            completed: 'تکمیل شده',
            failed: 'ناموفق'
        }
    };

    // DOM elements cache
    let elements = {};

    // Polling interval reference
    let pollInterval = null;
    let currentJobId = null;

    /**
     * Initialize the collector
     */
    function init() {
        cacheElements();
        attachEventListeners();
    }

    /**
     * Cache DOM elements for better performance
     */
    function cacheElements() {
        elements = {
            form: document.getElementById('collectForm'),
            fileInput: document.getElementById('datasetFile'),
            concurrentInput: document.getElementById('concurrentRequests'),
            startButton: document.getElementById('startBtn'),
            progressSection: document.getElementById('progressSection'),
            progressBar: document.getElementById('progressBar'),
            progressPercent: document.getElementById('progressPercent'),
            progressLabel: document.getElementById('progressLabel'),
            statusText: document.getElementById('statusText'),
            downloadSection: document.getElementById('downloadSection'),
            downloadLink: document.getElementById('downloadLink'),
            errorSection: document.getElementById('errorSection'),
            errorMessage: document.getElementById('errorMessage'),
            restartBtn: document.getElementById('restartBtn'),
            retryBtn: document.getElementById('retryBtn'),
            totalCount: document.getElementById('totalCount'),
            completedCount: document.getElementById('completedCount'),
            pendingCount: document.getElementById('pendingCount'),
            failedCount: document.getElementById('failedCount')
        };
    }

    /**
     * Attach event listeners
     */
    function attachEventListeners() {
        if (elements.form) {
            elements.form.addEventListener('submit', handleFormSubmit);
        }

        // Restart button
        if (elements.restartBtn) {
            elements.restartBtn.addEventListener('click', handleRestart);
        }

        // Retry button
        if (elements.retryBtn) {
            elements.retryBtn.addEventListener('click', handleRetry);
        }

        // Clear error on input change
        if (elements.fileInput) {
            elements.fileInput.addEventListener('change', clearError);
        }
    }

    /**
     * Handle restart button click
     */
    function handleRestart() {
        resetUI();
        if (elements.fileInput) {
            elements.fileInput.value = '';
        }
    }

    /**
     * Handle retry button click
     */
    function handleRetry() {
        if (elements.errorSection) {
            elements.errorSection.classList.add('d-none');
        }
    }

    /**
     * Clear error message
     */
    function clearError() {
        if (elements.errorSection) {
            elements.errorSection.classList.add('d-none');
        }
    }

    /**
     * Handle form submission
     */
    async function handleFormSubmit(event) {
        event.preventDefault();

        // Clear previous state
        clearError();
        resetUI();

        // Validate file input
        const file = elements.fileInput?.files[0];
        if (!file) {
            showError('لطفا فایل دیتاست را انتخاب کنید.');
            return;
        }

        // Disable form and show loading state
        setFormLoading(true);

        try {
            // Prepare form data - only send file (API config from env)
            const formData = new FormData();
            formData.append('file', file);

            const concurrent = elements.concurrentInput?.value;
            if (concurrent) {
                formData.append('concurrent', concurrent);
            }

            // Start collection
            const response = await fetch('/collect/start', {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.error || PERSIAN_MESSAGES.networkError);
            }

            const data = await response.json();

            // Show progress section
            if (elements.progressSection) {
                elements.progressSection.classList.remove('d-none');
            }

            // Update initial stats
            if (data.stats) {
                updateStats(data.stats);
            }

            if (data.job_id) {
                currentJobId = data.job_id;
                startProgressPolling(data.job_id);
            } else if (data.download_url) {
                // Already completed
                showDownloadLink(data.download_url);
                setFormLoading(false);
            }

        } catch (error) {
            console.error('Collection error:', error);
            showError(error.message || PERSIAN_MESSAGES.error);
            setFormLoading(false);
        }
    }

    /**
     * Start polling for progress updates
     */
    function startProgressPolling(jobId) {
        // Set up interval
        pollInterval = setInterval(() => {
            pollProgress(jobId);
        }, 1000);
    }

    /**
     * Poll for progress updates
     */
    async function pollProgress(jobId) {
        try {
            const response = await fetch(`/collect/progress/${jobId}`);

            if (!response.ok) {
                throw new Error('خطا در دریافت وضعیت');
            }

            const data = await response.json();

            // Map server response fields to UI stats
            var stats = {
                total: data.total || 0,
                completed: data.collected || 0,
                pending: (data.total || 0) - (data.collected || 0),
                failed: data.failed_count || 0
            };
            updateProgress(data.progress || 0, stats);
            updateStatus(data.status);

            // Check if complete
            if (data.status === 'completed') {
                stopPolling();
                setFormLoading(false);
                if (data.output_file) {
                    showDownloadLink('/collect/download/' + data.output_file);
                }
            }

            // Check if error
            if (data.status === 'error') {
                stopPolling();
                showError(data.error || PERSIAN_MESSAGES.error);
                setFormLoading(false);
            }

        } catch (error) {
            console.error('Polling error:', error);
            // Don't stop polling on transient errors
        }
    }

    /**
     * Stop polling
     */
    function stopPolling() {
        if (pollInterval) {
            clearInterval(pollInterval);
            pollInterval = null;
        }
        currentJobId = null;
    }

    /**
     * Update progress bar
     */
    function updateProgress(percent, stats) {
        if (elements.progressBar) {
            elements.progressBar.style.width = `${percent}%`;
            elements.progressBar.setAttribute('aria-valuenow', percent);
            elements.progressBar.textContent = `${percent}%`;
        }

        if (elements.progressPercent) {
            elements.progressPercent.textContent = `${percent}%`;
        }

        if (stats) {
            updateStats(stats);
        }
    }

    /**
     * Update statistics boxes
     */
    function updateStats(stats) {
        if (elements.totalCount) {
            elements.totalCount.textContent = stats.total || 0;
        }
        if (elements.completedCount) {
            elements.completedCount.textContent = stats.completed || 0;
        }
        if (elements.pendingCount) {
            elements.pendingCount.textContent = stats.pending || 0;
        }
        if (elements.failedCount) {
            elements.failedCount.textContent = stats.failed || 0;
        }
    }

    /**
     * Update status message
     */
    function updateStatus(status, currentQuestion) {
        const statusMessages = {
            'processing': 'در حال پردازش سوالات...',
            'completed': 'تکمیل شد!',
            'failed': 'خطا در فرآیند'
        };

        if (elements.progressLabel) {
            elements.progressLabel.textContent = statusMessages[status] || status;
        }

        if (elements.statusText) {
            if (currentQuestion) {
                elements.statusText.textContent = `سوال: ${currentQuestion}`;
            } else {
                elements.statusText.textContent = statusMessages[status] || 'در حال پردازش...';
            }
        }
    }

    /**
     * Show error message
     */
    function showError(message) {
        if (elements.errorSection) {
            elements.errorSection.classList.remove('d-none');
        }
        if (elements.errorMessage) {
            elements.errorMessage.textContent = message;
        }
    }

    /**
     * Show download link
     */
    function showDownloadLink(url) {
        if (elements.progressSection) {
            elements.progressSection.classList.add('d-none');
        }
        if (elements.downloadSection) {
            elements.downloadSection.classList.remove('d-none');
        }
        if (elements.downloadLink) {
            elements.downloadLink.href = url;
        }
    }

    /**
     * Reset UI to initial state
     */
    function resetUI() {
        stopPolling();

        if (elements.progressSection) {
            elements.progressSection.classList.add('d-none');
        }

        if (elements.progressBar) {
            elements.progressBar.style.width = '0%';
            elements.progressBar.setAttribute('aria-valuenow', 0);
            elements.progressBar.textContent = '0%';
        }

        if (elements.progressPercent) {
            elements.progressPercent.textContent = '0%';
        }

        if (elements.downloadSection) {
            elements.downloadSection.classList.add('d-none');
        }

        if (elements.totalCount) {
            elements.totalCount.textContent = '0';
        }
        if (elements.completedCount) {
            elements.completedCount.textContent = '0';
        }
        if (elements.pendingCount) {
            elements.pendingCount.textContent = '0';
        }
        if (elements.failedCount) {
            elements.failedCount.textContent = '0';
        }

        clearError();
    }

    /**
     * Set form loading state
     */
    function setFormLoading(isLoading) {
        const button = elements.startButton;

        if (button) {
            button.disabled = isLoading;

            const btnText = button.querySelector('.btn-text');
            const spinner = button.querySelector('.spinner-border');

            if (isLoading) {
                if (btnText) btnText.textContent = 'در حال ارسال...';
                if (spinner) spinner.classList.remove('d-none');
            } else {
                if (btnText) btnText.textContent = 'شروع جمع‌آوری';
                if (spinner) spinner.classList.add('d-none');
            }
        }

        // Disable inputs during loading
        [elements.fileInput, elements.concurrentInput].forEach(input => {
            if (input) {
                input.disabled = isLoading;
            }
        });
    }

    // Initialize on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // Cleanup on page unload
    window.addEventListener('beforeunload', stopPolling);

})();
