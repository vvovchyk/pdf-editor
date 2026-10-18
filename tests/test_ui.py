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
    page.mouse.move(image_box["x"] + 20, image_box["y"] + 30)
    page.mouse.down()
    page.mouse.move(image_box["x"] + 120, image_box["y"] + 130)
    page.mouse.up()

    selection_box = page.locator("#selectionBox")
    expect(selection_box).to_be_visible()
    expect(page.locator("#clearAreaBtn")).to_be_enabled()
    assert selection_box.evaluate(
        "(element) => getComputedStyle(element).borderTopColor"
    ) == "rgb(255, 59, 48)"
    assert selection_box.evaluate(
        "(element) => getComputedStyle(element).outlineColor"
    ) == "rgb(255, 255, 255)"

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
