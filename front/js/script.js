const dropZone        = document.getElementById('dropZone');
const fileInput       = document.getElementById('fileInput');
const previewGrid     = document.getElementById('previewGrid');
const fileCounter     = document.getElementById('fileCounter');
const uploadBtnWrapper= document.getElementById('uploadBtnWrapper');
const btnUpload       = document.getElementById('btnUpload');
const statusEl        = document.getElementById('status');
const resultArea      = document.getElementById('resultArea');
const reportEl        = document.getElementById('report');
const btnNew          = document.getElementById('btnNew');

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

function showReport(data) {
    resultArea.style.display = 'block';
    try {
        reportEl.textContent = JSON.stringify(data, null, 2);
    } catch {
        reportEl.textContent = String(data);
    }
}
