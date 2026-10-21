let pages = [];
let originalPages = [];
let sourceIndexes = [];
let currentPage = 0;
let activeTool = null;
let selectedArea = null;
let pointerStart = null;
let pointerPosition = null;
let selectionFrame = null;
let zoom = 100;
let lastAction = null;
const dirtyPages = new Set();

const pageImage = document.getElementById("pageImage");
const selectionBox = document.getElementById("selectionBox");
const viewer = document.getElementById("viewer");
const alignmentPrompt = document.getElementById("alignmentPrompt");
const paymentPrompt = document.getElementById("paymentPrompt");
let billingState = { enabled: false, paid: false };

async function responsePreview(response) {
    const data = await response.json();
    if (!response.ok) {
        const error = new Error(data.error || "The operation failed.");
        error.paymentRequired = data.payment_required === true;
        throw error;
    }
    return data.preview;
}

function showError(error) {
    if (error.paymentRequired) {
        showPaymentPrompt(error.message);
        return;
    }
    window.alert(error.message || "The operation failed.");
}

function updateBilling(state) {
    billingState = state;
    paymentPrompt.hidden = !(
        state.enabled && (state.requiresPurchase || state.showPrompt)
    );
    if (!paymentPrompt.hidden) {
        const message = document.getElementById("paymentMessage");
        message.innerText = state.requiresPurchase
            ? `This document exceeds the free limit of ${state.freePageLimit} pages or 25 MB. Unlock it for ${state.price} to continue.`
            : `Unlock this document for ${state.price} to process more than ${state.freeBatchLimit} pages at once or use higher compression.`;
    }
}

function showPaymentPrompt(message) {
    if (!billingState.enabled) {
        window.alert(message || "This action requires payment.");
        return;
    }
    billingState.showPrompt = true;
    updateBilling(billingState);
    if (message) {
        document.getElementById("paymentMessage").innerText =
            `${message} Unlock this PDF for ${billingState.price} to continue.`;
    }
}

async function refreshBillingStatus() {
    const response = await fetch("/billing/status");
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not check payment status.");
    updateBilling(data);
}

document.getElementById("unlockDocumentBtn").addEventListener("click", async () => {
    const checkoutWindow = window.open("about:blank", "_blank");
    if (!checkoutWindow) {
        window.alert("Allow pop-ups to open secure checkout.");
        return;
    }
    checkoutWindow.document.title = "Opening secure checkout";
    try {
        const response = await fetch("/billing/checkout", { method: "POST" });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Could not start checkout.");
        checkoutWindow.location = data.url;
    } catch (error) {
        checkoutWindow.close();
        showError(error);
    }
});

window.addEventListener("message", async event => {
    if (
        event.origin !== window.location.origin
        || !["pdf-payment-complete", "pdf-payment-pending"].includes(event.data?.type)
    ) {
        return;
    }
    try {
        await refreshBillingStatus();
        if (event.data.type === "pdf-payment-pending" && !billingState.paid) {
            let attempts = 0;
            const interval = window.setInterval(async () => {
                attempts += 1;
                try {
                    await refreshBillingStatus();
                } catch (error) {
                    window.clearInterval(interval);
                    showError(error);
                }
                if (billingState.paid || attempts >= 60) {
                    window.clearInterval(interval);
                }
            }, 3000);
        }
    } catch (error) {
        showError(error);
    }
});

function markPageEdited(index) {
    if (pages[index] === originalPages[index]) dirtyPages.delete(index);
    else dirtyPages.add(index);
}

function renderCurrentPage() {
    if (pages.length === 0) return;
    pageImage.src = `data:image/jpeg;base64,${pages[currentPage]}`;
    pageImage.style.width = `${zoom}%`;
    pageImage.style.maxWidth = zoom === 100 ? "100%" : "none";
}

function setPreview(preview, index = currentPage) {
    pages[index] = preview;
    markPageEdited(index);
    renderCurrentPage();
    renderPages();
}

function updateSelectionBox(start, end) {
    const left = Math.min(start.x, end.x);
    const top = Math.min(start.y, end.y);
    selectionBox.style.left = `${left}px`;
    selectionBox.style.top = `${top}px`;
    selectionBox.style.width = `${Math.abs(end.x - start.x)}px`;
    selectionBox.style.height = `${Math.abs(end.y - start.y)}px`;
    selectionBox.hidden = false;
}

function imagePoint(event) {
    const rect = pageImage.getBoundingClientRect();
    const x = Math.max(0, Math.min(rect.width, event.clientX - rect.left));
    const y = Math.max(0, Math.min(rect.height, event.clientY - rect.top));
    return {
        x: Math.round(x * pageImage.naturalWidth / rect.width),
        y: Math.round(y * pageImage.naturalHeight / rect.height),
        displayX: x,
        displayY: y
    };
}

function updateSelectionFromPointer(clientX, clientY) {
    const point = imagePoint({ clientX, clientY });
    updateSelectionBox(
        { x: pointerStart.displayX, y: pointerStart.displayY },
        { x: point.displayX, y: point.displayY }
    );
}

function autoScrollStep(position, start, end) {
    const edgeSize = 36;
    const maxStep = 18;
    if (position < start + edgeSize) {
        return -Math.min(maxStep, Math.ceil((start + edgeSize - position) / 3));
    }
    if (position > end - edgeSize) {
        return Math.min(maxStep, Math.ceil((position - (end - edgeSize)) / 3));
    }
    return 0;
}

function continueSelectionDrag() {
    if (!pointerStart || !pointerPosition) {
        selectionFrame = null;
        return;
    }

    const bounds = viewer.getBoundingClientRect();
    viewer.scrollLeft += autoScrollStep(
        pointerPosition.x,
        bounds.left,
        bounds.right
    );
    viewer.scrollTop += autoScrollStep(
        pointerPosition.y,
        bounds.top,
        bounds.bottom
    );
    updateSelectionFromPointer(pointerPosition.x, pointerPosition.y);
    selectionFrame = window.requestAnimationFrame(continueSelectionDrag);
}

function stopSelectionDrag() {
    pointerStart = null;
    pointerPosition = null;
    if (selectionFrame !== null) {
        window.cancelAnimationFrame(selectionFrame);
        selectionFrame = null;
    }
}

function cancelSelection() {
    stopSelectionDrag();
    selectedArea = null;
    activeTool = null;
    selectionBox.hidden = true;
    pageImage.classList.remove("selecting");
    setSelectionActionsEnabled(false);
}

function setTool(tool) {
    activeTool = tool;
    if (tool !== null) {
        selectedArea = null;
        selectionBox.hidden = true;
        setSelectionActionsEnabled(false);
    } else if (!selectedArea) {
        selectionBox.hidden = true;
    }
    pageImage.classList.toggle("selecting", Boolean(tool));
}

function setSelectionActionsEnabled(enabled) {
    document.getElementById("enhanceAreaBtn").disabled = !enabled;
    document.getElementById("clearAreaBtn").disabled = !enabled;
}

function updateZoom() {
    document.getElementById("zoomValue").innerText = `${zoom}%`;
    renderCurrentPage();
}

async function editPage(action, pageIndex) {
    let response;
    if (action.type === "enhance") {
        response = await fetch(
            `/enhance/${sourceIndexes[pageIndex]}/${action.mode}/${encodeURIComponent(action.value)}`,
            { method: "POST" }
        );
    } else if (action.type === "rotate") {
        response = await fetch(
            `/rotate/${sourceIndexes[pageIndex]}/${action.direction}`,
            { method: "POST" }
        );
    } else {
        throw new Error("Unsupported action.");
    }
    pages[pageIndex] = await responsePreview(response);
    markPageEdited(pageIndex);
}

async function applyAction(action, pageIndexes) {
    try {
        if (pageIndexes.length > 1) {
            const payload = {
                type: action.type,
                pages: pageIndexes.map(index => sourceIndexes[index]),
                ...action
            };
            const response = await fetch("/batch_action", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            const data = await response.json();
            if (!response.ok) {
                const error = new Error(data.error || "The operation failed.");
                error.paymentRequired = data.payment_required === true;
                throw error;
            }
            pageIndexes.forEach(index => {
                pages[index] = data.previews[String(sourceIndexes[index])];
                markPageEdited(index);
            });
            renderCurrentPage();
            renderPages();
            return;
        }
        for (const index of pageIndexes) {
            await editPage(action, index);
        }
        renderCurrentPage();
        renderPages();
    } catch (error) {
        showError(error);
    }
}

function targetPages() {
    if (document.getElementById("modeToggle").checked) return [currentPage];
    return pages.map((_, index) => index);
}

// AUTO LOAD PDF
document.getElementById("pdfFile").addEventListener("change", async function () {
    const file = this.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append("pdf", file);

    try {
        const res = await fetch("/load_pdf", { method: "POST", body: formData });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Could not load PDF.");
        pages = data.pages;
        originalPages = data.pages.slice();
        sourceIndexes = data.pages.map((_, index) => index);
        dirtyPages.clear();
        currentPage = 0;
        setTool(null);
        updateBilling(data.billing || { enabled: false, paid: false });
        alignmentPrompt.hidden = !data.alignment?.needed;
        if (data.alignment?.needed) {
            document.getElementById("alignmentMessage").innerText =
                `This PDF has ${data.alignment.formatCount} page sizes. Align all pages to ${data.alignment.format}?`;
        }
        renderPages();
        renderCurrentPage();
    } catch (error) {
        showError(error);
    }
});

document.getElementById("applyAlignmentBtn").addEventListener("click", async () => {
    try {
        const response = await fetch("/align_pages", { method: "POST" });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || "Could not align pages.");
        }
        pages = sourceIndexes.map(index => data.pages[index]);
        pages.forEach((_, index) => markPageEdited(index));
        alignmentPrompt.hidden = true;
        renderPages();
        renderCurrentPage();
    } catch (error) {
        showError(error);
    }
});

document.getElementById("dismissAlignmentBtn").addEventListener("click", () => {
    alignmentPrompt.hidden = true;
});

if (new URLSearchParams(window.location.search).get("payment") === "cancelled") {
    window.history.replaceState({}, "", window.location.pathname);
}

// RENDER THUMBNAILS
function renderPages() {
    const container = document.getElementById("thumbnails");
    container.innerHTML = "";

    pages.forEach((b64, index) => {
        const card = document.createElement("div");
        card.classList.add("thumbnail-card");
        card.draggable = pages.length > 1;
        card.dataset.index = index;

        const img = document.createElement("img");
        img.src = "data:image/jpeg;base64," + b64;
        img.classList.add("page-thumb");
        img.alt = `Page ${index + 1}`;
        img.draggable = false;

        if (document.getElementById("modeToggle").checked) {
            if (index === currentPage) img.classList.add("active");
        } else {
            img.classList.add("active");
        }

        img.addEventListener("click", () => {
            currentPage = index;
            renderMainPage();
            updateActiveState();
            updatePageInfo();
        });

        const controls = document.createElement("div");
        controls.classList.add("thumbnail-controls");

        const pageLabel = document.createElement("span");
        pageLabel.innerText = `Page ${index + 1}`;

        const moveUp = document.createElement("button");
        moveUp.type = "button";
        moveUp.innerText = "↑";
        moveUp.title = `Move page ${index + 1} up`;
        moveUp.setAttribute("aria-label", moveUp.title);
        moveUp.disabled = index === 0;
        moveUp.addEventListener("click", () => movePage(index, index - 1));

        const moveDown = document.createElement("button");
        moveDown.type = "button";
        moveDown.innerText = "↓";
        moveDown.title = `Move page ${index + 1} down`;
        moveDown.setAttribute("aria-label", moveDown.title);
        moveDown.disabled = index === pages.length - 1;
        moveDown.addEventListener("click", () => movePage(index, index + 1));

        const remove = document.createElement("button");
        remove.type = "button";
        remove.innerText = "×";
        remove.title = `Delete page ${index + 1}`;
        remove.setAttribute("aria-label", remove.title);
        remove.disabled = pages.length === 1;
        remove.addEventListener("click", () => deletePage(index));

        controls.append(pageLabel, moveUp, moveDown, remove);
        card.append(img, controls);
        card.addEventListener("dragstart", event => {
            event.dataTransfer.setData("text/plain", String(index));
            event.dataTransfer.effectAllowed = "move";
        });
        card.addEventListener("dragover", event => {
            event.preventDefault();
            event.dataTransfer.dropEffect = "move";
        });
        card.addEventListener("drop", event => {
            event.preventDefault();
            const from = Number(event.dataTransfer.getData("text/plain"));
            movePage(from, index);
        });
        container.appendChild(card);
    });

    updatePageInfo();
}

function movePage(from, to) {
    if (from < 0 || to < 0 || from >= pages.length || to >= pages.length || from === to) {
        return;
    }
    const selectedSource = sourceIndexes[currentPage];
    for (const items of [pages, originalPages, sourceIndexes]) {
        const [item] = items.splice(from, 1);
        items.splice(to, 0, item);
    }
    currentPage = sourceIndexes.indexOf(selectedSource);
    dirtyPages.clear();
    pages.forEach((_, index) => markPageEdited(index));
    renderPages();
    renderCurrentPage();
    updateActiveState();
}

function deletePage(index) {
    if (pages.length <= 1) return;
    if (!window.confirm(`Delete page ${index + 1}? This page will be removed from the saved PDF.`)) {
        return;
    }
    const selectedSource = sourceIndexes[currentPage];
    for (const items of [pages, originalPages, sourceIndexes]) {
        items.splice(index, 1);
    }
    currentPage = sourceIndexes.indexOf(selectedSource);
    if (currentPage < 0) currentPage = Math.min(index, pages.length - 1);
    dirtyPages.clear();
    pages.forEach((_, pageIndex) => markPageEdited(pageIndex));
    renderPages();
    renderCurrentPage();
    updateActiveState();
}

// RENDER MAIN PAGE
function renderMainPage() {
    renderCurrentPage();
}

// UPDATE ACTIVE STATE
function updateActiveState() {
    const thumbs = document.querySelectorAll(".page-thumb");
    const onlyActive = document.getElementById("modeToggle").checked;

    if (onlyActive) {
        thumbs.forEach((t, i) => {
            if (i === currentPage) t.classList.add("active");
            else t.classList.remove("active");
        });
    } else {
        thumbs.forEach(t => t.classList.add("active"));
    }
}

document.getElementById("modeToggle").addEventListener("change", () => {
    updateActiveState();
});

// NAVIGATION
function goFirst() { if (pages.length) currentPage = 0; renderMainPage(); updateActiveState(); updatePageInfo(); }
function goPrev() { if (currentPage > 0) currentPage--; renderMainPage(); updateActiveState(); updatePageInfo(); }
function goNext() { if (currentPage < pages.length - 1) currentPage++; renderMainPage(); updateActiveState(); updatePageInfo(); }
function goLast() { if (pages.length) currentPage = pages.length - 1; renderMainPage(); updateActiveState(); updatePageInfo(); }

function updatePageInfo() {
    document.getElementById("pageInfo").innerText =
        `Page ${currentPage + 1} / ${pages.length}`;
}

// UNDO / REDO
async function undo() {
    try {
        const res = await fetch(`/undo/${sourceIndexes[currentPage]}`, { method: "POST" });
        setPreview(await responsePreview(res));
    } catch (error) { showError(error); }
}

async function redo() {
    try {
        const res = await fetch(`/redo/${sourceIndexes[currentPage]}`, { method: "POST" });
        setPreview(await responsePreview(res));
    } catch (error) { showError(error); }
}

// ENHANCEMENTS
async function updateEnhancement(mode, value) {
    lastAction = { type: "enhance", mode, value };
    await applyAction(lastAction, targetPages());
}

async function applyAuto(mode) {
    lastAction = { type: "enhance", mode, value: 1 };
    await applyAction(lastAction, targetPages());
}

// ROTATE
async function rotateLeft() {
    lastAction = { type: "rotate", direction: "left" };
    await applyAction(lastAction, targetPages());
}

async function rotateRight() {
    lastAction = { type: "rotate", direction: "right" };
    await applyAction(lastAction, targetPages());
}

function startCrop() { setTool("crop"); }
function startSelection() { setTool("selection"); }

pageImage.addEventListener("pointerdown", event => {
    if (!activeTool || pages.length === 0 || !event.isPrimary || event.button !== 0) return;
    event.preventDefault();
    const point = imagePoint(event);
    pointerStart = point;
    pointerPosition = { x: event.clientX, y: event.clientY };
    selectedArea = null;
    updateSelectionBox(
        { x: point.displayX, y: point.displayY },
        { x: point.displayX, y: point.displayY }
    );
    pageImage.setPointerCapture(event.pointerId);
    selectionFrame = window.requestAnimationFrame(continueSelectionDrag);
});

pageImage.addEventListener("pointermove", event => {
    if (!pointerStart) return;
    pointerPosition = { x: event.clientX, y: event.clientY };
    updateSelectionFromPointer(event.clientX, event.clientY);
});

pageImage.addEventListener("pointerup", async event => {
    if (!pointerStart) return;
    const end = imagePoint(event);
    const start = pointerStart;
    stopSelectionDrag();
    if (start.x === end.x || start.y === end.y) {
        cancelSelection();
        return;
    }
    selectedArea = {
        start: { x: start.x, y: start.y },
        end: { x: end.x, y: end.y }
    };
    updateSelectionBox(
        { x: start.displayX, y: start.displayY },
        { x: end.displayX, y: end.displayY }
    );

    if (activeTool === "crop") {
        try {
            const response = await fetch("/crop_page", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ page: sourceIndexes[currentPage], ...selectedArea })
            });
            setPreview(await responsePreview(response));
            selectedArea = null;
            setSelectionActionsEnabled(false);
            setTool(null);
        } catch (error) { showError(error); }
    } else {
        activeTool = null;
        pageImage.classList.remove("selecting");
        setSelectionActionsEnabled(true);
    }
});

pageImage.addEventListener("pointercancel", cancelSelection);
window.addEventListener("keydown", event => {
    if (event.key === "Escape" && (pointerStart || activeTool || selectedArea)) {
        cancelSelection();
    }
});

async function applySelection(endpoint) {
    if (!selectedArea) return;
    try {
        const response = await fetch(endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ page: sourceIndexes[currentPage], ...selectedArea })
        });
        setPreview(await responsePreview(response));
        selectedArea = null;
        selectionBox.hidden = true;
        setSelectionActionsEnabled(false);
    } catch (error) { showError(error); }
}

function applySelectionEnhance() { return applySelection("/selection_enhance"); }
function clearSelectedArea() { return applySelection("/clear_area"); }

function showBefore() {
    if (originalPages[currentPage]) {
        pageImage.src = `data:image/jpeg;base64,${originalPages[currentPage]}`;
    }
}

function showAfter() { renderCurrentPage(); }
function zoomIn() { zoom = Math.min(200, zoom + 10); updateZoom(); }
function zoomOut() { zoom = Math.max(50, zoom - 10); updateZoom(); }

async function applyToAll() {
    if (!lastAction || pages.length === 0) return;
    const targets = pages.map((_, index) => index).filter(index => index !== currentPage);
    await applyAction(lastAction, targets);
}

// SAVE PDF
async function savePDF() {
    const quality = document.getElementById("compressSlider").value;

    try {
        const res = await fetch("/save_pdf", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                quality,
                changedPages: [...dirtyPages],
                pageOrder: sourceIndexes
            })
        });
        if (!res.ok) {
            const data = await res.json();
            const error = new Error(data.error || "Could not save PDF.");
            error.paymentRequired = data.payment_required === true;
            throw error;
        }
        const url = window.URL.createObjectURL(await res.blob());
        const link = document.createElement("a");
        link.href = url;
        link.download = "cleaned.pdf";
        link.click();
        window.URL.revokeObjectURL(url);
    } catch (error) { showError(error); }
}

// DISCARD
function discardPDF() {
    location.reload();
}
