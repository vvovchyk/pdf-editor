let pages = [];
let editedPages = [];
let currentPage = 0;
let showOriginal = false;
let zoomLevel = 1;

let lastAction = null;
let history = [];

let selectionMode = false;
let cropMode = false;
let selectionStart = null;
let selectionEnd = null;

/* ========================= ZOOM ========================= */

function zoomIn() { zoomLevel += 0.1; updateZoom(); }
function zoomOut() { zoomLevel = Math.max(0.3, zoomLevel - 0.1); updateZoom(); }

function updateZoom() {
    document.getElementById("pageImage").style.transform = `scale(${zoomLevel})`;
    document.getElementById("zoomValue").innerText = Math.round(zoomLevel * 100) + "%";
}

/* ========================= MODE ========================= */

function getSelectedPages() {
    return [...document.querySelectorAll(".thumb-check:checked")]
        .map(cb => parseInt(cb.dataset.page));
}

function getEditMode() {
    const toggle = document.getElementById("modeToggle");
    const selected = getSelectedPages();

    if (selected.length > 1 && selected.length < pages.length) {
        toggle.checked = false;
        return "selected";
    }

    if (selected.length === pages.length && pages.length > 0) {
        toggle.checked = false;
        return "all";
    }

    if (selected.length === 1) {
        currentPage = selected[0];
        toggle.checked = true;
        return "single";
    }

    if (toggle.checked) return "single";
    return "all";
}

function updateMode() {
    const mode = getEditMode();
    const disableAreas = (mode === "all" || mode === "selected");

    document.getElementById("cropBtn").disabled = disableAreas;
    document.getElementById("selectBtn").disabled = disableAreas;
    document.getElementById("enhanceAreaBtn").disabled = disableAreas;
    document.getElementById("clearAreaBtn").disabled = disableAreas;
}

/* ========================= LOAD PDF ========================= */

function loadPDF() {
    const fileInput = document.getElementById("pdfFile");
    if (!fileInput.files.length) {
        alert("Select a PDF first.");
        return;
    }

    const formData = new FormData();
    formData.append("pdf", fileInput.files[0]);

    fetch("/load_pdf", { method: "POST", body: formData })
        .then(r => r.json())
        .then(data => {
            pages = data.pages;
            editedPages = [...pages];
            currentPage = 0;
            history = [];
            renderThumbnails();
            renderHistory();
            showPage();
            updateMode();
        });
}

/* ========================= THUMBNAILS ========================= */

function renderThumbnails() {
    const container = document.getElementById("thumbnails");
    container.innerHTML = "";

    pages.forEach((b64, i) => {
        const wrapper = document.createElement("div");
        wrapper.className = "thumb-wrapper";

        const img = document.createElement("img");
        img.src = "data:image/jpeg;base64," + b64;
        img.className = "thumbnail";
        img.onclick = () => {
            currentPage = i;
            showPage();
            highlightThumbnail();
            updateMode();
        };

        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.className = "thumb-check";
        checkbox.dataset.page = i;
        checkbox.onclick = () => updateMode();

        wrapper.appendChild(img);
        wrapper.appendChild(checkbox);
        container.appendChild(wrapper);
    });

    highlightThumbnail();
}

function highlightThumbnail() {
    const thumbs = document.querySelectorAll(".thumbnail");
    thumbs.forEach((t, i) => {
        t.classList.toggle("active", i === currentPage);
    });
}

/* ========================= SHOW PAGE ========================= */

function showPage() {
    const img = document.getElementById("pageImage");
    img.src = "data:image/jpeg;base64," +
        (showOriginal ? pages[currentPage] : editedPages[currentPage]);

    document.getElementById("pageInfo").innerText =
        `Page ${currentPage + 1} / ${pages.length}`;

    highlightThumbnail();
}

/* ========================= NAVIGATION ========================= */

function goFirst() { currentPage = 0; showPage(); updateMode(); }
function goLast() { currentPage = pages.length - 1; showPage(); updateMode(); }
function goPrev() { if (currentPage > 0) currentPage--; showPage(); updateMode(); }
function goNext() { if (currentPage < pages.length - 1) currentPage++; showPage(); updateMode(); }

/* ========================= HISTORY ========================= */

function addHistory(action) {
    history.push({
        time: new Date().toLocaleTimeString(),
        page: currentPage,
        action
    });
    renderHistory();
}

function renderHistory() {
    const panel = document.getElementById("historyPanel");
    panel.innerHTML = "";

    history.forEach((h, idx) => {
        const item = document.createElement("div");
        item.className = "history-item";

        const info = document.createElement("div");
        info.innerHTML = `<b>${h.time}</b> — Page ${h.page + 1}: ${h.action}`;

        const buttons = document.createElement("div");
        const restoreBtn = document.createElement("button");
        restoreBtn.textContent = "Restore";
        restoreBtn.onclick = () => restoreHistory(idx);

        const deleteBtn = document.createElement("button");
        deleteBtn.textContent = "Delete";
        deleteBtn.onclick = () => deleteHistory(idx);

        buttons.appendChild(restoreBtn);
        buttons.appendChild(deleteBtn);

        item.appendChild(info);
        item.appendChild(buttons);
        panel.appendChild(item);
    });
}

function restoreHistory(idx) {
    const h = history[idx];
    currentPage = h.page;
    undo();
}

function deleteHistory(idx) {
    history.splice(idx, 1);
    renderHistory();
}

/* ========================= SLIDERS ========================= */

function updateEnhancement(type, value) {
    lastAction = { kind: "enhance", type, value };
    addHistory(`Enhance: ${type}=${value}`);
    applyEnhancementToPage(currentPage, type, value);
}

function applyEnhancementToPage(pageIndex, type, value) {
    fetch(`/enhance/${pageIndex}/${type}/${value}`, { method: "POST" })
        .then(r => r.json())
        .then(data => {
            editedPages[pageIndex] = data.preview;
            if (pageIndex === currentPage) showPage();
        });
}

/* ========================= AUTO TOOLS ========================= */

function applyAuto(type) {
    lastAction = { kind: "auto", type };
    addHistory(`Auto: ${type}`);
    applyAutoToPage(currentPage, type);
}

function applyAutoToPage(pageIndex, type) {
    fetch(`/enhance/${pageIndex}/${type}/1`, { method: "POST" })
        .then(r => r.json())
        .then(data => {
            editedPages[pageIndex] = data.preview;
            if (pageIndex === currentPage) showPage();
        });
}

/* ========================= UNDO / REDO ========================= */

function undo() {
    fetch(`/undo/${currentPage}`, { method: "POST" })
        .then(r => r.json())
        .then(data => {
            editedPages[currentPage] = data.preview;
            showPage();
        });
}

function redo() {
    fetch(`/redo/${currentPage}`, { method: "POST" })
        .then(r => r.json())
        .then(data => {
            editedPages[currentPage] = data.preview;
            showPage();
        });
}

/* ========================= BEFORE / AFTER ========================= */

function showBefore() { showOriginal = true; showPage(); }
function showAfter() { showOriginal = false; showPage(); }

/* ========================= SELECTION (FIXED COORDINATES) ========================= */

function convertToImageCoords(domX, domY) {
    const viewer = document.getElementById("viewer");
    const pageImage = document.getElementById("pageImage");

    const naturalWidth = pageImage.naturalWidth;
    const naturalHeight = pageImage.naturalHeight;

    const displayWidth = pageImage.clientWidth;
    const displayHeight = pageImage.clientHeight;

    const rect = pageImage.getBoundingClientRect();
    const scrollTop = viewer.scrollTop;

    const x = (domX - rect.left) / zoomLevel * (naturalWidth / displayWidth);
    const y = (domY - rect.top + scrollTop) / zoomLevel * (naturalHeight / displayHeight);

    return { x: Math.round(x), y: Math.round(y) };
}

function startCrop() {
    cropMode = true;
    selectionMode = false;
    attachSelectionHandlers();
}

function startSelection() {
    selectionMode = true;
    cropMode = false;
    attachSelectionHandlers();
}

function attachSelectionHandlers() {
    const wrapper = document.getElementById("imageWrapper");
    const box = document.getElementById("selectionBox");
    const pageImage = document.getElementById("pageImage");

    wrapper.onmousedown = (e) => {
        selectionStart = convertToImageCoords(e.clientX, e.clientY);
        box.style.display = "block";
    };

    wrapper.onmousemove = (e) => {
        if (!selectionStart) return;

        selectionEnd = convertToImageCoords(e.clientX, e.clientY);

        const naturalWidth = pageImage.naturalWidth;
        const naturalHeight = pageImage.naturalHeight;
        const displayWidth = pageImage.clientWidth;
        const displayHeight = pageImage.clientHeight;

        const x = Math.min(selectionStart.x, selectionEnd.x);
        const y = Math.min(selectionStart.y, selectionEnd.y);
        const w = Math.abs(selectionEnd.x - selectionStart.x);
        const h = Math.abs(selectionEnd.y - selectionStart.y);

        box.style.left = `${(x / naturalWidth) * displayWidth}px`;
        box.style.top = `${(y / naturalHeight) * displayHeight}px`;
        box.style.width = `${(w / naturalWidth) * displayWidth}px`;
        box.style.height = `${(h / naturalHeight) * displayHeight}px`;
    };

    wrapper.onmouseup = () => {
        wrapper.onmousemove = null;
        wrapper.onmouseup = null;
    };
}

/* ========================= CROP ========================= */

function applyCropToPage(pageIndex, start, end) {
    addHistory("Crop");
    fetch("/crop_page", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ page: pageIndex, start, end })
    })
        .then(r => r.json())
        .then(data => {
            editedPages[pageIndex] = data.preview;
            if (pageIndex === currentPage) showPage();
        });
}

/* ========================= SELECTION ENHANCE ========================= */

function applySelectionEnhance() {
    if (!selectionStart || !selectionEnd) {
        alert("Select area first.");
        return;
    }

    lastAction = { kind: "selection_enhance", selection: { start: selectionStart, end: selectionEnd } };
    addHistory("Selection Enhance");

    applySelectionEnhanceToPage(currentPage, selectionStart, selectionEnd);
}

function applySelectionEnhanceToPage(pageIndex, start, end) {
    fetch("/selection_enhance", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ page: pageIndex, start, end })
    })
        .then(r => r.json())
        .then(data => {
            editedPages[pageIndex] = data.preview;
            if (pageIndex === currentPage) showPage();
        });
}

/* ========================= CLEAR AREA ========================= */

function clearSelectedArea() {
    if (!selectionStart || !selectionEnd) {
        alert("Select area first.");
        return;
    }

    lastAction = { kind: "clear_area", selection: { start: selectionStart, end: selectionEnd } };
    addHistory("Clear Area");

    applyClearAreaToPage(currentPage, selectionStart, selectionEnd);
}

function applyClearAreaToPage(pageIndex, start, end) {
    fetch("/clear_area", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ page: pageIndex, start, end })
    })
        .then(r => r.json())
        .then(data => {
            editedPages[pageIndex] = data.preview;
            if (pageIndex === currentPage) showPage();
        });
}

/* ========================= ROTATE ========================= */

function rotateLeft() {
    lastAction = { kind: "rotate", direction: "left" };
    addHistory("Rotate Left");
    applyRotateToPage(currentPage, "left");
}

function rotateRight() {
    lastAction = { kind: "rotate", direction: "right" };
    addHistory("Rotate Right");
    applyRotateToPage(currentPage, "right");
}

function applyRotateToPage(pageIndex, direction) {
    fetch(`/rotate/${pageIndex}/${direction}`, { method: "POST" })
        .then(r => r.json())
        .then(data => {
            editedPages[pageIndex] = data.preview;
            if (pageIndex === currentPage) showPage();
        });
}

/* ========================= REPEAT LAST ACTION ========================= */

function applyToAll() {
    if (!lastAction) {
        alert("No action to repeat.");
        return;
    }

    const mode = getEditMode();
    let targetPages = [];

    if (mode === "single") {
        targetPages = [currentPage];
    } else if (mode === "all") {
        targetPages = pages.map((_, i) => i);
    } else {
        targetPages = getSelectedPages();
    }

    addHistory(`Repeat: ${lastAction.kind}`);

    for (let p of targetPages) {
        if (lastAction.kind === "enhance")
            applyEnhancementToPage(p, lastAction.type, lastAction.value);

        if (lastAction.kind === "auto")
            applyAutoToPage(p, lastAction.type);

        if (lastAction.kind === "rotate")
            applyRotateToPage(p, lastAction.direction);

        if (lastAction.kind === "crop")
            applyCropToPage(p, lastAction.selection.start, lastAction.selection.end);

        if (lastAction.kind === "selection_enhance")
            applySelectionEnhanceToPage(p, lastAction.selection.start, lastAction.selection.end);

        if (lastAction.kind === "clear_area")
            applyClearAreaToPage(p, lastAction.selection.start, lastAction.selection.end);
    }
}

/* ========================= SAVE / DISCARD ========================= */

function savePDF() {
    const quality = document.getElementById("compressSlider").value;

    fetch("/save_pdf", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pages: editedPages, quality })
    })
    .then(async response => {
        const original = response.headers.get("X-Original-Size");
        const final = response.headers.get("X-Final-Size");

        alert(
            `Original: ${(original/1024/1024).toFixed(2)} MB\n` +
            `Final: ${(final/1024/1024).toFixed(2)} MB\n` +
            `Compression: ${Math.round(100 - (final / original * 100))}%`
        );

        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "cleaned.pdf";
        a.click();
    });
}

function discardPDF() {
    editedPages = [...pages];
    showPage();
}
