const dropZone = document.getElementById('dropZone');
const fileInput = document.getElementById('fileInput');
const previewGrid = document.getElementById('previewGrid');
const fileCounter = document.getElementById('fileCounter');
const uploadBtnWrapper = document.getElementById('uploadBtnWrapper');
const btnUpload = document.getElementById('btnUpload');
const statusEl = document.getElementById('status');
const resultArea = document.getElementById('resultArea');
const reportEl = document.getElementById('report');
const btnNew = document.getElementById('btnNew');
const ratingTable = document.querySelector('.rating-table');
const ratingTableBody = document.getElementById('ratingTableBody');
const ratingEmpty = document.getElementById('ratingEmpty');

const RATING_STORAGE_KEY = 'cameraQualityRating';

/** 
 * @typedef {Object} SelectedFile
 * @property {File} originalFile - Оригинал для отправки на сервер
 * @property {string} previewUrl - URL для отображения в <img>
 * @property {Blob} [previewBlob] - Blob превью (для очистки памяти, если это конвертированный HEIC)
 */

/** @type {Array<SelectedFile>} */
let selectedFiles = [];
let pollInterval = null;
let isProcessing = false;

// ── Drop Zone ──
dropZone.addEventListener('click', () => !isProcessing && fileInput.click());

dropZone.addEventListener('dragover', e => {
    if (isProcessing) return;
    e.preventDefault();
    dropZone.classList.add('drag-over');
});

dropZone.addEventListener('dragleave', e => {
    if (e.target === dropZone) {
        dropZone.classList.remove('drag-over');
    }
});

dropZone.addEventListener('drop', e => {
    if (isProcessing) return;
    e.preventDefault();
    dropZone.classList.remove('drag-over');
    if (e.dataTransfer.files.length) handleFiles(e.dataTransfer.files);
});

fileInput.addEventListener('change', () => {
    if (isProcessing) return;
    if (fileInput.files.length) handleFiles(fileInput.files);
    fileInput.value = '';
});

// ── Handle Files (async для поддержки HEIC конвертации) ──
async function handleFiles(list) {
    showStatus('Processing images...', 'processing');

    for (const file of Array.from(list)) {
        // Базовые валидации
        if (!file.type.startsWith('image/') || file.size > 16 * 1024 * 1024) {
            showStatus(`Skipped "${file.name}": invalid or too large`, 'error');
            continue;
        }

        // Проверка на дубликаты
        if (selectedFiles.some(x => x.originalFile.name === file.name && x.originalFile.size === file.size)) {
            continue;
        }

        let previewUrl = null;
        let previewBlob = null;
        const isHeic = file.type === 'image/heic' || file.type === 'image/heif' || file.name.toLowerCase().endsWith('.heic');

        try {
            if (isHeic && typeof heic2any !== 'undefined') {
                // Конвертация HEIC → JPEG только для превью
                const blob = await heic2any({
                    blob: file,
                    toType: 'image/jpeg',
                    quality: 0.7
                });
                previewBlob = blob;
                previewUrl = URL.createObjectURL(blob);
            } else {
                // Обычные форматы или фоллбэк
                previewUrl = URL.createObjectURL(file);
            }

            selectedFiles.push({
                originalFile: file,
                previewUrl,
                previewBlob
            });

        } catch (err) {
            console.error('Preview generation error:', err);
            // Фоллбэк: пробуем показать оригинал
            previewUrl = URL.createObjectURL(file);
            selectedFiles.push({ originalFile: file, previewUrl, previewBlob: null });
        }
    }

    renderPreviews();
    updateUI();
    hideStatus();
}

// ── Render Previews ──
function renderPreviews() {
    previewGrid.innerHTML = '';

    if (selectedFiles.length === 0) {
        previewGrid.style.display = 'none';
        dropZone.classList.remove('compact');
        return;
    }

    previewGrid.style.display = 'grid';
    dropZone.classList.add('compact');

    selectedFiles.forEach(({ originalFile, previewUrl }, index) => {
        const item = document.createElement('div');
        item.className = 'preview-item';
        item.title = `${originalFile.name}\nClick to view`;

        const img = document.createElement('img');
        img.src = previewUrl;
        img.alt = originalFile.name;
        img.loading = 'lazy';

        const removeBtn = document.createElement('button');
        removeBtn.className = 'preview-remove';
        removeBtn.innerHTML = '✕';
        removeBtn.title = 'Remove';
        removeBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            removeFile(index);
        });

        const meta = document.createElement('div');
        meta.className = 'preview-meta';
        meta.textContent = `${(originalFile.size / 1024).toFixed(0)} KB`;

        // Бейдж для HEIC
        if (originalFile.name.toLowerCase().endsWith('.heic') || originalFile.type.includes('heic')) {
            const badge = document.createElement('div');
            badge.style.cssText = 'position:absolute;top:6px;left:6px;background:#f39c12;color:#fff;padding:2px 6px;border-radius:4px;font-size:0.65rem;z-index:2;pointer-events:none;';
            badge.textContent = 'HEIC';
            item.appendChild(badge);
        }

        item.addEventListener('click', () => {
            window.open(previewUrl, '_blank');
        });

        item.appendChild(img);
        item.appendChild(removeBtn);
        item.appendChild(meta);
        previewGrid.appendChild(item);
    });
}

// ── Remove File ──
function removeFile(index) {
    if (isProcessing) return;
    const item = selectedFiles[index];
    URL.revokeObjectURL(item.previewUrl);
    selectedFiles.splice(index, 1);
    renderPreviews();
    updateUI();
}

// ── Update UI State ──
function updateUI() {
    fileCounter.textContent = `${selectedFiles.length} file(s) selected`;
    fileCounter.style.display = selectedFiles.length ? 'block' : 'none';
    uploadBtnWrapper.style.display = selectedFiles.length && !isProcessing ? 'block' : 'none';

    const dropText = dropZone.querySelector('.drop-zone-text');
    const dropHint = dropZone.querySelector('.drop-zone-hint');

    if (isProcessing) {
        dropText.innerHTML = 'Processing…';
        dropHint.textContent = 'Please wait for the report';
        dropZone.style.pointerEvents = 'none';
        dropZone.style.opacity = '0.6';
    } else if (selectedFiles.length > 0) {
        dropText.innerHTML = 'Drop <strong>more</strong> images to add, or <strong>click to browse</strong>';
        dropHint.textContent = 'PNG, JPG, WEBP, HEIC — up to 16 MB each';
        dropZone.style.pointerEvents = '';
        dropZone.style.opacity = '1';
    } else {
        dropText.innerHTML = 'Drag & drop images here, or <strong>click to browse</strong>';
        dropHint.textContent = 'PNG, JPG, WEBP, HEIC — up to 16 MB each';
        dropZone.style.pointerEvents = '';
        dropZone.style.opacity = '1';
    }
}

// ── Reset ──
function reset() {
    selectedFiles.forEach(({ previewUrl }) => URL.revokeObjectURL(previewUrl));
    selectedFiles = [];
    fileInput.value = '';
    previewGrid.innerHTML = '';
    previewGrid.style.display = 'none';
    fileCounter.style.display = 'none';
    uploadBtnWrapper.style.display = 'none';
    dropZone.classList.remove('compact');
    dropZone.style.pointerEvents = '';
    dropZone.style.opacity = '1';
    resultArea.style.display = 'none';
    reportEl.textContent = '';
    stopPolling();
    hideStatus();
    isProcessing = false;
    btnUpload.disabled = false;
    updateUI();
}

btnNew.addEventListener('click', reset);

// ── Upload & Polling ──
btnUpload.addEventListener('click', async () => {
    if (!selectedFiles.length || isProcessing) return;

    isProcessing = true;
    btnUpload.disabled = true;
    resultArea.style.display = 'none';
    updateUI();
    showStatus('Uploading files…', 'processing');

    const formData = new FormData();
    selectedFiles.forEach(({ originalFile }) => formData.append('files', originalFile));

    const uploadUrl = '/evaluate';

    try {
        const res = await fetch(uploadUrl, { method: 'POST', body: formData });
        if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
        const { job_id } = await res.json();
        if (!job_id) throw new Error('No job_id in response');

        showStatus('Processing…', 'processing');
        startPolling(job_id);
    } catch (err) {
        showStatus(err.message, 'error');
        isProcessing = false;
        updateUI();
    }
});

// ── Polling ──
function startPolling(jobId) {
    const statusUrl = '/evaluate/status';
    const poll = async () => {
        try {
            const res = await fetch(`${statusUrl}?job_id=${encodeURIComponent(jobId)}`);
            if (!res.ok) throw new Error(`Status check failed: ${res.status}`);
            const data = await res.json();

            if (data.status === 'completed') {
                stopPolling();
                showStatus('Done!', 'success');
                showReport(data.result ?? data);
                isProcessing = false;
                updateUI();
            } else if (data.status === 'failed') {
                stopPolling();
                showStatus(data.error || 'Processing failed', 'error');
                isProcessing = false;
                updateUI();
            } else {
                const eta = data.eta ? ` (~${data.eta}s)` : '';
                showStatus(`Processing…${eta}`, 'processing');
            }
        } catch (err) {
            stopPolling();
            showStatus('Polling error: ' + err.message, 'error');
            isProcessing = false;
            updateUI();
        }
    };
    poll();
    pollInterval = setInterval(poll, 2000);
}

function stopPolling() {
    if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
    }
}

// ── UI Helpers ──
function showStatus(msg, type) {
    statusEl.className = `status ${type}`;
    statusEl.innerHTML = type === 'processing'
        ? `<span class="spinner"></span>${msg}`
        : msg;
    statusEl.style.display = 'block';
}

function hideStatus() {
    statusEl.style.display = 'none';
}

function extractReport(data) {
    if (!data || typeof data !== 'object') return null;
    if (data.report && typeof data.report === 'object') return data.report;
    if (
        'primary_camera' in data ||
        'camera_score' in data ||
        'images_processed' in data
    ) {
        return data;
    }
    return null;
}

function formatReportNumber(value, mode = 'score') {
    if (value === null || value === undefined) return '—';
    if (typeof value !== 'number' || Number.isNaN(value)) return String(value);

    if (mode === 'noise') {
        if (Math.abs(value) < 1) {
            return value.toLocaleString('ru-RU', { maximumSignificantDigits: 4 });
        }
        return value.toLocaleString('ru-RU', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }

    return value.toLocaleString('ru-RU', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    });
}

function renderReportTable(report) {
    const table = document.createElement('table');
    table.className = 'report-table';

    const tbody = document.createElement('tbody');

    const addRow = (label, value, { format } = {}) => {
        if (value === null || value === undefined || value === '') return;
        const tr = document.createElement('tr');
        const th = document.createElement('th');
        th.scope = 'row';
        th.textContent = label;
        const td = document.createElement('td');
        if (format === 'number') {
            td.textContent = formatReportNumber(value, 'score');
        } else if (format === 'noise') {
            td.textContent = formatReportNumber(value, 'noise');
        } else {
            td.textContent = String(value);
        }
        tr.append(th, td);
        tbody.appendChild(tr);
    };

    const addPerImageScoresRow = (scores) => {
        if (!Array.isArray(scores) || !scores.length) return;
        const tr = document.createElement('tr');
        const th = document.createElement('th');
        th.scope = 'row';
        th.textContent = 'Оценка каждого изображения';
        const td = document.createElement('td');
        const grid = document.createElement('div');
        grid.className = 'report-scores';
        scores.forEach((score, index) => {
            const chip = document.createElement('span');
            chip.className = 'report-score-chip';
            chip.title = `Изображение ${index + 1}`;
            const label = document.createElement('span');
            label.className = 'report-score-chip__label';
            label.textContent = `${index + 1}`;
            const valueEl = document.createElement('span');
            valueEl.className = 'report-score-chip__value';
            valueEl.textContent = formatReportNumber(score, 'score');
            chip.append(label, valueEl);
            grid.appendChild(chip);
        });
        td.appendChild(grid);
        tr.append(th, td);
        tbody.appendChild(tr);
    };

    const addSection = (label) => {
        const tr = document.createElement('tr');
        tr.className = 'report-section';
        const th = document.createElement('th');
        th.colSpan = 2;
        th.textContent = label;
        tr.appendChild(th);
        tbody.appendChild(tr);
    };

    const addRecommendationsRow = (items) => {
        if (!Array.isArray(items) || !items.length) return;
        const tr = document.createElement('tr');
        const th = document.createElement('th');
        th.scope = 'row';
        th.textContent = 'Рекомендации';
        const td = document.createElement('td');
        const list = document.createElement('ul');
        list.className = 'report-recommendations';
        items.forEach((text) => {
            const li = document.createElement('li');
            li.textContent = text;
            list.appendChild(li);
        });
        td.appendChild(list);
        tr.append(th, td);
        tbody.appendChild(tr);
    };

    addRow('Название камеры', report.primary_camera);
    addRow('Количество изображений', report.images_processed);
    addRow('Оценка камеры', report.camera_score, { format: 'number' });
    addRow('Вывод', report.grade);
    addRow('Консистенция', report.consistency_score, { format: 'number' });

    const metrics = report.aggregated_metrics;
    if (metrics && typeof metrics === 'object') {
        addSection('Агрегированные метрики');
        addRow('Sharpness median', metrics.sharpness_median, { format: 'number' });
        addRow('Noise median', metrics.noise_median, { format: 'noise' });
        addRow('Color vibrancy median', metrics.color_vibrancy_median, { format: 'number' });
        addRow('Brisque median', metrics.brisque_median, { format: 'number' });
    }

    addPerImageScoresRow(report.per_image_scores);
    addRecommendationsRow(report.recommendations);

    table.appendChild(tbody);
    return table;
}

function showReport(data) {
    resultArea.style.display = 'block';
    reportEl.innerHTML = '';

    const report = extractReport(data);
    if (!report) {
        reportEl.textContent = 'Нет данных отчёта';
        return;
    }

    reportEl.appendChild(renderReportTable(report));
    saveReportToRating(report);
}

// ── Camera rating (localStorage) ──

function loadRatingEntries() {
    try {
        const raw = localStorage.getItem(RATING_STORAGE_KEY);
        if (!raw) return [];
        const data = JSON.parse(raw);
        if (!Array.isArray(data)) return [];
        return data.filter(
            (entry) =>
                entry &&
                typeof entry.cameraName === 'string' &&
                typeof entry.score === 'number' &&
                !Number.isNaN(entry.score)
        );
    } catch {
        return [];
    }
}

function saveRatingEntries(entries) {
    localStorage.setItem(RATING_STORAGE_KEY, JSON.stringify(entries));
}

function upsertCameraRating(cameraName, score) {
    const name = String(cameraName).trim();
    if (!name || typeof score !== 'number' || Number.isNaN(score)) return;

    const entries = loadRatingEntries();
    const nameKey = name.toLowerCase();
    const index = entries.findIndex(
        (entry) => entry.cameraName.toLowerCase() === nameKey
    );
    const record = { cameraName: name, score, updatedAt: Date.now() };

    if (index >= 0) {
        entries[index] = record;
    } else {
        entries.push(record);
    }

    saveRatingEntries(entries);
}

function getRankedCameras() {
    const entries = [...loadRatingEntries()];
    entries.sort((a, b) => {
        if (b.score !== a.score) return b.score - a.score;
        return a.cameraName.localeCompare(b.cameraName, 'ru');
    });
    return entries.map((entry, index) => ({
        place: index + 1,
        cameraName: entry.cameraName,
        score: entry.score,
    }));
}

function renderRatingTable() {
    const ranked = getRankedCameras();
    ratingTableBody.innerHTML = '';

    if (!ranked.length) {
        ratingTable.hidden = true;
        ratingEmpty.hidden = false;
        return;
    }

    ratingTable.hidden = false;
    ratingEmpty.hidden = true;

    ranked.forEach(({ place, cameraName, score }) => {
        const tr = document.createElement('tr');
        if (place <= 3) {
            tr.classList.add('rating-place', `rating-place--${place}`);
        }

        const tdPlace = document.createElement('td');
        tdPlace.className = 'rating-place-cell';
        tdPlace.textContent = String(place);

        const tdName = document.createElement('td');
        tdName.textContent = cameraName;

        const tdScore = document.createElement('td');
        tdScore.className = 'rating-score-cell';
        tdScore.textContent = formatReportNumber(score, 'score');

        tr.append(tdPlace, tdName, tdScore);
        ratingTableBody.appendChild(tr);
    });
}

function saveReportToRating(report) {
    const cameraName = report.primary_camera;
    const score = report.camera_score;
    if (!cameraName || score === null || score === undefined) return;
    upsertCameraRating(cameraName, Number(score));
    renderRatingTable();
}

renderRatingTable();
