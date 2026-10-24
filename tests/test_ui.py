import io
import json
import threading

import pymupdf
import pytest
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

import app as app_module
from services.page_store import PageStore


@pytest.fixture
def browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture
def app_url(tmp_path, monkeypatch):
    monkeypatch.setattr(
        app_module,
        "PAGE_STORE",
        PageStore(tmp_path / "browser-test.sqlite3"),
    )
    server = make_server("127.0.0.1", 0, app_module.app, threaded=True)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server_thread.join()


def make_pdf():
    document = pymupdf.open()
    page = document.new_page(width=400, height=500)
    page.insert_text((40, 50), "Browser test document")
    return document.tobytes()


def make_mixed_size_pdf():
    document = pymupdf.open()
    document.new_page(width=200, height=300)
    document.new_page(width=100, height=150)
    return document.tobytes()


def make_labeled_pdf(labels):
    document = pymupdf.open()
    for label in labels:
        page = document.new_page(width=400, height=500)
        page.insert_text((40, 50), label)
    return document.tobytes()


def load_pdf(page, app_url, content=None, page_count=1):
    page.goto(app_url)
    page.locator("#pdfFile").set_input_files(
        {
            "name": "browser-test.pdf",
            "mimeType": "application/pdf",
            "buffer": content or make_pdf(),
        }
    )
    expect(page.locator("#pageImage")).to_be_visible()
    expect(page.locator("#pageInfo")).to_contain_text(f"Page 1 / {page_count}")


def test_area_selection_is_visible_and_can_be_cleared(browser, app_url):
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    load_pdf(page, app_url)
    image = page.locator("#pageImage")
    image_box = image.bounding_box()
    assert image_box is not None
    page.get_by_role("button", name="Select Area").click()
    start_x = image_box["x"] + 20
    start_y = image_box["y"] + 30
    end_x = image_box["x"] + 120
    end_y = image_box["y"] + 130
    page.mouse.move(start_x, start_y)
    page.mouse.down()
    page.mouse.move(end_x, end_y)

    selection_box = page.locator("#selectionBox")
    expect(selection_box).to_be_visible()
    assert selection_box.evaluate("(element) => element.style.left") == "20px"
    assert selection_box.evaluate("(element) => element.style.top") == "30px"
    assert selection_box.evaluate("(element) => element.style.width") == "100px"
    assert selection_box.evaluate("(element) => element.style.height") == "100px"
    page.mouse.up()

    expect(selection_box).to_be_visible()
    expect(page.locator("#clearAreaBtn")).to_be_enabled()
    assert selection_box.evaluate(
        "(element) => getComputedStyle(element).borderTopColor"
    ) == "rgb(201, 241, 220)"
    assert selection_box.evaluate(
        "(element) => getComputedStyle(element).outlineColor"
    ) == "rgb(255, 255, 255)"
    assert selection_box.evaluate(
        "(element) => getComputedStyle(element).backgroundColor"
    ) == "rgba(0, 0, 0, 0)"

    requests = []
    page.on(
        "request",
        lambda request: requests.append(json.loads(request.post_data))
        if request.url.endswith("/clear_area")
        else None,
    )
    page.get_by_role("button", name="Clear Selected Area").click()
    expect(selection_box).to_be_hidden()
    assert len(requests) == 1
    assert requests[0]["page"] == 0
    assert requests[0]["start"]["x"] < requests[0]["end"]["x"]
    assert requests[0]["start"]["y"] < requests[0]["end"]["y"]
    page.close()


def test_selection_works_after_zoom_and_viewer_scroll(browser, app_url):
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    load_pdf(page, app_url)
    page.locator('button[onclick="zoomIn()"]').click(click_count=10)

    viewer = page.locator("#viewer")
    viewer.evaluate("(element) => { element.scrollTop = 100; }")
    assert viewer.evaluate("(element) => element.scrollTop") > 0

    image = page.locator("#pageImage")
    image_box = image.bounding_box()
    assert image_box is not None
    viewer.evaluate("(element) => { element.scrollLeft = 200; }")
    image_box = image.bounding_box()
    page.get_by_role("button", name="Select Area").click()
    page.mouse.move(image_box["x"] + 500, image_box["y"] + 350)
    page.mouse.down()
    page.mouse.move(image_box["x"] + 300, image_box["y"] + 150)

    selection_box = page.locator("#selectionBox")
    expect(selection_box).to_be_visible()
    assert selection_box.evaluate("(element) => element.style.left") == "300px"
    assert selection_box.evaluate("(element) => element.style.top") == "150px"
    assert selection_box.evaluate("(element) => element.style.width") == "200px"
    assert selection_box.evaluate("(element) => element.style.height") == "200px"
    page.mouse.up()

    requests = []
    page.on(
        "request",
        lambda request: requests.append(json.loads(request.post_data))
        if request.url.endswith("/clear_area")
        else None,
    )
    page.get_by_role("button", name="Clear Selected Area").click()
    expect(selection_box).to_be_hidden()
    assert len(requests) == 1
    assert requests[0]["start"]["x"] > requests[0]["end"]["x"]
    assert requests[0]["start"]["y"] > requests[0]["end"]["y"]
    page.close()


def test_selection_auto_scrolls_viewer_during_drag(browser, app_url):
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    load_pdf(page, app_url)
    page.locator('button[onclick="zoomIn()"]').click(click_count=10)

    viewer = page.locator("#viewer")
    viewer_box = viewer.bounding_box()
    image_box = page.locator("#pageImage").bounding_box()
    assert viewer_box is not None
    assert image_box is not None
    page.get_by_role("button", name="Select Area").click()
    page.mouse.move(image_box["x"] + 100, image_box["y"] + 100)
    page.mouse.down()
    page.mouse.move(image_box["x"] + 200, viewer_box["y"] + viewer_box["height"] - 10)

    page.wait_for_function(
        "document.getElementById('viewer').scrollTop > 0"
    )
    assert viewer.evaluate("(element) => element.scrollTop") > 0
    page.mouse.up()
    expect(page.locator("#selectionBox")).to_be_visible()
    page.close()


def test_escape_and_pointer_cancel_discard_area_selection(browser, app_url):
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    load_pdf(page, app_url)
    image = page.locator("#pageImage")
    image_box = image.bounding_box()
    assert image_box is not None
    selection_box = page.locator("#selectionBox")

    page.get_by_role("button", name="Select Area").click()
    page.mouse.move(image_box["x"] + 20, image_box["y"] + 30)
    page.mouse.down()
    page.mouse.move(image_box["x"] + 120, image_box["y"] + 130)
    page.keyboard.press("Escape")
    expect(selection_box).to_be_hidden()
    expect(page.locator("#clearAreaBtn")).to_be_disabled()
    page.mouse.up()

    page.get_by_role("button", name="Select Area").click()
    image_box = image.bounding_box()
    assert image_box is not None
    page.mouse.move(image_box["x"] + 20, image_box["y"] + 30)
    page.mouse.down()
    page.mouse.move(image_box["x"] + 120, image_box["y"] + 130)
    image.dispatch_event("pointercancel")
    expect(selection_box).to_be_hidden()
    expect(page.locator("#clearAreaBtn")).to_be_disabled()
    page.mouse.up()
    page.close()


def test_click_without_drag_does_not_create_empty_selection(browser, app_url):
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    load_pdf(page, app_url)
    image_box = page.locator("#pageImage").bounding_box()
    assert image_box is not None
    page.get_by_role("button", name="Select Area").click()
    page.mouse.click(image_box["x"] + 20, image_box["y"] + 30)

    expect(page.locator("#selectionBox")).to_be_hidden()
    expect(page.locator("#clearAreaBtn")).to_be_disabled()
    page.close()


def test_zoom_controls_update_page_scale(browser, app_url):
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    load_pdf(page, app_url)
    image = page.locator("#pageImage")
    original_width = image.bounding_box()["width"]

    page.get_by_role("button", name="➕").click()

    expect(page.locator("#zoomValue")).to_have_text("110%")
    expect(image).to_have_attribute("style", "width: 110%; max-width: none;")
    assert image.bounding_box()["width"] > original_width

    page.get_by_role("button", name="➖").click()
    expect(page.locator("#zoomValue")).to_have_text("100%")
    assert image.bounding_box()["width"] == pytest.approx(original_width)
    page.close()


def test_user_can_accept_detected_page_alignment(browser, app_url):
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    load_pdf(page, app_url, make_mixed_size_pdf(), page_count=2)

    prompt = page.locator("#alignmentPrompt")
    expect(prompt).to_be_visible()
    expect(page.locator("#alignmentMessage")).to_contain_text(
        "Align all pages to 200 × 300 pt"
    )

    page.get_by_role("button", name="Align pages").click()

    expect(prompt).to_be_hidden()
    expect(page.locator("#pageInfo")).to_contain_text("Page 1 / 2")
    page.locator(".page-thumb").nth(1).click()
    expect(page.locator("#pageImage")).to_have_js_property("naturalWidth", 200)
    expect(page.locator("#pageImage")).to_have_js_property("naturalHeight", 300)
    page.close()


def test_user_can_decline_detected_page_alignment(browser, app_url):
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    load_pdf(page, app_url, make_mixed_size_pdf(), page_count=2)
    alignment_requests = []
    page.on(
        "request",
        lambda request: alignment_requests.append(request)
        if request.url.endswith("/align_pages")
        else None,
    )

    page.get_by_role("button", name="Keep original sizes").click()

    expect(page.locator("#alignmentPrompt")).to_be_hidden()
    page.locator(".page-thumb").nth(1).click()
    expect(page.locator("#pageImage")).to_have_js_property("naturalWidth", 100)
    expect(page.locator("#pageImage")).to_have_js_property("naturalHeight", 150)
    assert alignment_requests == []
    page.close()


def test_user_can_delete_and_reorder_pages_before_saving(browser, app_url):
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.on("dialog", lambda dialog: dialog.accept())
    load_pdf(
        page,
        app_url,
        make_labeled_pdf(["first page", "delete this page", "third page"]),
        page_count=3,
    )

    page.get_by_role("button", name="Delete page 2").click()
    expect(page.locator("#pageInfo")).to_contain_text("Page 1 / 2")
    expect(page.locator(".thumbnail-card")).to_have_count(2)
    page.get_by_role("button", name="Move page 2 up").click()

    expect(page.locator("#pageInfo")).to_contain_text("Page 2 / 2")
    with page.expect_download() as download_info:
        page.locator('button[onclick="savePDF()"]').click()
    download = download_info.value

    saved_pdf = pymupdf.open(download.path())
    assert len(saved_pdf) == 2
    assert "third page" in saved_pdf[0].get_text()
    assert "first page" in saved_pdf[1].get_text()
    assert "delete this page" not in "".join(
        pdf_page.get_text() for pdf_page in saved_pdf
    )
    page.close()


def test_batch_over_free_limit_shows_unlock_prompt(browser, app_url, monkeypatch):
    monkeypatch.setitem(app_module.app.config, "PAYMENTS_ENABLED", True)
    monkeypatch.setitem(app_module.app.config, "STRIPE_SECRET_KEY", "sk_test_configured")
    monkeypatch.setitem(
        app_module.app.config,
        "STRIPE_WEBHOOK_SECRET",
        "whsec_configured",
    )
    monkeypatch.setitem(
        app_module.app.config,
        "PUBLIC_BASE_URL",
        "https://sackofhacks.com/pdf-cleaner",
    )
    document = pymupdf.open()
    for _ in range(4):
        document.new_page(width=200, height=300)

    page = browser.new_page(viewport={"width": 1280, "height": 900})
    load_pdf(page, app_url, document.tobytes(), page_count=4)
    page.locator("#modeToggle").uncheck()
    page.get_by_role("button", name="✨ Auto Enhance").click()

    expect(page.locator("#paymentPrompt")).to_be_visible()
    expect(page.locator("#paymentMessage")).to_contain_text(
        "Batch editing more than 3 pages"
    )
    expect(page.get_by_role("button", name="Unlock this PDF")).to_be_visible()
    page.close()
