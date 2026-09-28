"""
Media URL Utility Functions
Handles URL normalization, Google Drive direct link extraction, and media path resolution.
"""
from __future__ import annotations
import re


def extract_google_drive_file_id(url: str) -> str | None:
    """
    Extract the Google Drive file ID from any public Google Drive URL pattern.
    Returns the file ID string, or None if the URL is not a Google Drive link.
    """
    if not url or not isinstance(url, str):
        return None
    url_str = url.strip()
    if "drive.google.com" not in url_str and "docs.google.com" not in url_str:
        return None

    # Pattern 1: /file/d/FILE_ID/view or /file/d/FILE_ID
    match = re.search(r"drive\.google\.com/file/d/([a-zA-Z0-9_-]+)", url_str)
    if match:
        return match.group(1)

    # Pattern 2: open?id=FILE_ID
    match = re.search(r"drive\.google\.com/open\?id=([a-zA-Z0-9_-]+)", url_str)
    if match:
        return match.group(1)

    # Pattern 3: uc?id=FILE_ID or uc?export=view&id=FILE_ID
    match = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", url_str)
    if match:
        return match.group(1)

    # Pattern 4: /d/FILE_ID (Google Docs/Sheets/Slides embeds)
    match = re.search(r"docs\.google\.com/[a-z]+/d/([a-zA-Z0-9_-]+)", url_str)
    if match:
        return match.group(1)

    # Pattern 5: thumbnail?id=FILE_ID
    match = re.search(r"thumbnail\?id=([a-zA-Z0-9_-]+)", url_str)
    if match:
        return match.group(1)

    return None


def transform_google_drive_url(url: str) -> str:
    """
    Transforms public Google Drive share/view URLs into direct renderable image URLs.

    Strategy (ordered by reliability for WhatsApp Cloud API image rendering):
      1. drive.google.com/thumbnail?id=FILE_ID&sz=w1600  — Google's thumbnail API,
         renders reliably in WhatsApp as it returns a direct image with proper
         Content-Type headers. sz=w1600 requests high-resolution.
      2. lh3.googleusercontent.com/d/FILE_ID — legacy direct link, used as fallback.

    Examples:
      https://drive.google.com/file/d/1A2B3C4D5E/view?usp=sharing
        -> https://drive.google.com/thumbnail?id=1A2B3C4D5E&sz=w1600
      https://drive.google.com/open?id=1A2B3C4D5E
        -> https://drive.google.com/thumbnail?id=1A2B3C4D5E&sz=w1600
      https://drive.google.com/uc?export=view&id=1A2B3C4D5E
        -> https://drive.google.com/thumbnail?id=1A2B3C4D5E&sz=w1600
    """
    if not url or not isinstance(url, str):
        return url

    url_str = url.strip()
    file_id = extract_google_drive_file_id(url_str)

    if file_id:
        # Primary: Google thumbnail API — reliable, returns proper image headers
        return f"https://drive.google.com/thumbnail?id={file_id}&sz=w1600"

    return url_str


def get_direct_download_url(url: str) -> str:
    """
    Returns a direct download URL for Google Drive files.
    Use this as a secondary fallback if the thumbnail URL fails.
    """
    file_id = extract_google_drive_file_id(url)
    if file_id:
        return f"https://drive.google.com/uc?export=download&id={file_id}"
    return url


def extract_maps_coordinates(url: str) -> tuple[float, float] | None:
    """
    Extract latitude and longitude from Google Maps URLs.
    Supports formats:
      - /@17.4003212,78.4882647
      - !3d17.4003212!4d78.4908396
      - ?q=17.4003212,78.4882647
      - &ll=17.4003212,78.4882647
    """
    if not url or not isinstance(url, str):
        return None
    url_str = url.strip()

    # Pattern 1: @17.4003212,78.4882647
    m = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", url_str)
    if m:
        try:
            return float(m.group(1)), float(m.group(2))
        except ValueError:
            pass

    # Pattern 2: !3d17.4003212!4d78.4908396
    m_lat = re.search(r"!3d(-?\d+\.\d+)", url_str)
    m_lng = re.search(r"!4d(-?\d+\.\d+)", url_str)
    if m_lat and m_lng:
        try:
            return float(m_lat.group(1)), float(m_lng.group(1))
        except ValueError:
            pass

    # Pattern 3: q=17.4003212,78.4882647 or ll=17.4003212,78.4882647
    m = re.search(r"[?&](?:q|ll)=(-?\d+\.\d+),(-?\d+\.\d+)", url_str)
    if m:
        try:
            return float(m.group(1)), float(m.group(2))
        except ValueError:
            pass

    return None

