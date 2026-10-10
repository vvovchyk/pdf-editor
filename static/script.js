let pages = [];
let currentPage = 0;

// AUTO LOAD PDF
document.getElementById("pdfFile").addEventListener("change", async function () {
    const file = this.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append("pdf", file);

    const res = await fetch("/load_pdf", {
        method: "POST",
        body: formData
    });

    const data = await res.json();
    pages = data.pages;

    currentPage = 0;
    renderPages();
    renderMainPage();
});

// RENDER THUMBNAILS
function renderPages() {
    const container = document.getElementById("thumbnails");
    container.innerHTML = "";

    pages.forEach((b64, index) => {
        const img = document.createElement("img");
        img.src = "data:image/jpeg;base64," + b64;
        img.classList.add("page-thumb");

        if (document.getElementById("modeToggle").checked) {
            if (index === currentPage) img.classList.add("active");
        } else {
            img.classList.add("active");
        }

        img.addEventListener("click", () => {
            currentPage = index;
            renderMainPage();
            updateActiveState();
        });

        container.appendChild(img);
    });

    updatePageInfo();
}

// RENDER MAIN PAGE
function renderMainPage() {
    document.getElementById("pageImage").src =
        "data:image/jpeg;base64," + pages[currentPage];
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
function goFirst() { currentPage = 0; renderMainPage(); updateActiveState(); updatePageInfo(); }
function goPrev() { if (currentPage > 0) currentPage--; renderMainPage(); updateActiveState(); updatePageInfo(); }
function goNext() { if (currentPage < pages.length - 1) currentPage++; renderMainPage(); updateActiveState(); updatePageInfo(); }
function goLast() { currentPage = pages.length - 1; renderMainPage(); updateActiveState(); updatePageInfo(); }

function updatePageInfo() {
    document.getElementById("pageInfo").innerText =
        `Page ${currentPage + 1} / ${pages.length}`;
}

// UNDO / REDO
async function undo() {
    const res = await fetch(`/undo/${currentPage}`, { method: "POST" });
    const data = await res.json();
    pages[currentPage] = data.preview;
    renderMainPage();
    renderPages();
}

async function redo() {
    const res = await fetch(`/redo/${currentPage}`, { method: "POST" });
    const data = await res.json();
    pages[currentPage] = data.preview;
    renderMainPage();
    renderPages();
}

// ENHANCEMENTS
async function updateEnhancement(mode, value) {
    const res = await fetch(`/enhance/${currentPage}/${mode}/${value}`, { method: "POST" });
    const data = await res.json();
    pages[currentPage] = data.preview;
    renderMainPage();
    renderPages();
}

async function applyAuto(mode) {
    const res = await fetch(`/enhance/${currentPage}/${mode}/1`, { method: "POST" });
    const data = await res.json();
    pages[currentPage] = data.preview;
    renderMainPage();
    renderPages();
}

// ROTATE
async function rotateLeft() {
    const res = await fetch(`/rotate/${currentPage}/left`, { method: "POST" });
    const data = await res.json();
    pages[currentPage] = data.preview;
    renderMainPage();
    renderPages();
}

async function rotateRight() {
    const res = await fetch(`/rotate/${currentPage}/right`, { method: "POST" });
    const data = await res.json();
    pages[currentPage] = data.preview;
    renderMainPage();
    renderPages();
}

// SAVE PDF
async function savePDF() {
    const quality = document.getElementById("compressSlider").value;

    const res = await fetch("/save_pdf", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pages, quality })
    });

    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "cleaned.pdf";
    a.click();
}

// DISCARD
function discardPDF() {
    location.reload();
}
