import re
from io import BytesIO
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader


GOVUK_BASE_URL = "https://www.gov.uk"


def clean_pdf_text(value):
    if not value:
        return ""

    value = re.sub(r"\s+", " ", value)
    return value.strip()


def find_pdf_links_on_page(page_url):
    """
    Finds PDF links from a GOV.UK decision page.
    Returns absolute URLs.
    """

    if not page_url:
        return []

    try:
        response = requests.get(
            page_url,
            timeout=20,
            headers={
                "User-Agent": "PeopleSignal/1.0"
            },
        )
        response.raise_for_status()
    except Exception:
        return []

    soup = BeautifulSoup(response.text, "html.parser")

    pdf_links = []

    for link in soup.find_all("a", href=True):
        href = link.get("href") or ""

        if ".pdf" not in href.lower():
            continue

        absolute_url = urljoin(GOVUK_BASE_URL, href)

        if absolute_url not in pdf_links:
            pdf_links.append(absolute_url)

    return pdf_links


def extract_text_from_pdf_url(pdf_url, max_chars=3000):
    """
    Downloads a PDF and extracts text.
    Fails safely by returning an empty string.
    """

    if not pdf_url:
        return ""

    try:
        response = requests.get(
            pdf_url,
            timeout=25,
            headers={
                "User-Agent": "PeopleSignal/1.0"
            },
        )
        response.raise_for_status()

        pdf_bytes = BytesIO(response.content)
        reader = PdfReader(pdf_bytes)

        text_parts = []

        for page in reader.pages[:5]:
            try:
                page_text = page.extract_text() or ""
            except Exception:
                page_text = ""

            if page_text:
                text_parts.append(page_text)

            current_text = clean_pdf_text(" ".join(text_parts))

            if len(current_text) >= max_chars:
                return current_text[:max_chars] + "..."

        extracted_text = clean_pdf_text(" ".join(text_parts))

        if len(extracted_text) > max_chars:
            extracted_text = extracted_text[:max_chars] + "..."

        return extracted_text

    except Exception:
        return ""


def extract_first_pdf_context_from_page(page_url, max_chars=3000):
    """
    Finds the first PDF on a source page and extracts text from it.

    Returns:
        {
            "pdf_url": "...",
            "pdf_text": "..."
        }
    """

    pdf_links = find_pdf_links_on_page(page_url)

    if not pdf_links:
        return {
            "pdf_url": "",
            "pdf_text": "",
        }

    for pdf_url in pdf_links:
        pdf_text = extract_text_from_pdf_url(
            pdf_url=pdf_url,
            max_chars=max_chars,
        )

        if pdf_text:
            return {
                "pdf_url": pdf_url,
                "pdf_text": pdf_text,
            }

    return {
        "pdf_url": pdf_links[0],
        "pdf_text": "",
    }