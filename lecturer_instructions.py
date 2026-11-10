"""GitHub-backed course instructions shared by the student and lecturer apps."""

import base64
from pathlib import Path

import requests
import streamlit as st

GITHUB_INSTRUCTIONS_PATH = "lecturer_instructions.txt"
INSTRUCTIONS_FILE = Path(__file__).resolve().with_name(GITHUB_INSTRUCTIONS_PATH)


def github_settings():
    """Separate PRIVATE repository avoids redeploying the student app on every edit."""
    repo = st.secrets.get("GITHUB_DATA_REPO", "").strip()
    token = st.secrets.get("GITHUB_DATA_TOKEN", "").strip()
    branch = st.secrets.get("GITHUB_DATA_BRANCH", "main").strip()
    if not repo or not token:
        return None
    if len(repo.split("/")) != 2 or not all(repo.split("/")):
        raise RuntimeError("GITHUB_DATA_REPO חייב להיות בפורמט owner/repository")
    return repo, token, branch


def github_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def fetch_github_instructions(settings):
    """Return (file text, GitHub blob SHA), or (None, None) when file does not exist."""
    repo, token, branch = settings
    url = f"https://api.github.com/repos/{repo}/contents/{GITHUB_INSTRUCTIONS_PATH}"
    response = requests.get(
        url, headers=github_headers(token), params={"ref": branch}, timeout=15
    )
    if response.status_code == 404:
        # GitHub returns 404 for an inaccessible repository too: don't silently
        # treat missing/incorrect credentials as a new instructions file.
        check = requests.get(
            f"https://api.github.com/repos/{repo}",
            headers=github_headers(token), timeout=15,
        )
        check.raise_for_status()
        if check.json().get("default_branch") != branch:
            branch_check = requests.get(
                f"https://api.github.com/repos/{repo}/branches/{branch}",
                headers=github_headers(token), timeout=15,
            )
            branch_check.raise_for_status()
        return None, None
    response.raise_for_status()
    data = response.json()
    if data.get("type") != "file" or data.get("encoding") != "base64":
        raise RuntimeError("תשובת GitHub לא מכילה קובץ טקסט תקין")
    decoded = base64.b64decode(data["content"]).decode("utf-8")
    return decoded, data["sha"]


def legacy_instructions():
    # Used only during migration, before the new GitHub data file is created.
    if INSTRUCTIONS_FILE.exists():
        return INSTRUCTIONS_FILE.read_text(encoding="utf-8")
    return st.secrets.get("LECTURER_INSTRUCTIONS", "")


@st.cache_data(ttl=60, show_spinner=False)
def load_lecturer_instructions_record():
    settings = github_settings()
    if settings is None:
        return legacy_instructions(), None
    text, sha = fetch_github_instructions(settings)
    if text is None:
        return legacy_instructions(), None
    return text, sha


def save_lecturer_instructions(text, expected_sha):
    settings = github_settings()
    if settings is None:
        raise RuntimeError(
            "שמירה קבועה אינה מוגדרת. יש להוסיף GITHUB_DATA_REPO "
            "ו-GITHUB_DATA_TOKEN ל-Secrets של Streamlit."
        )
    repo, token, branch = settings
    current_text, current_sha = fetch_github_instructions(settings)
    if current_sha != expected_sha:
        raise RuntimeError(
            "ההנחיות שונו ב-GitHub מאז שטענת את העמוד. "
            "רענן את העמוד, בדוק את השינויים ונסה שוב."
        )
    if current_text == text:
        return
    payload = {
        "message": "Update lecturer instructions from Streamlit",
        "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
        "branch": branch,
    }
    if current_sha is not None:
        payload["sha"] = current_sha
    response = requests.put(
        f"https://api.github.com/repos/{repo}/contents/{GITHUB_INSTRUCTIONS_PATH}",
        headers=github_headers(token), json=payload, timeout=20,
    )
    if response.status_code in (409, 422):
        raise RuntimeError(
            "GitHub דחה את השמירה. ייתכן שהקובץ השתנה במקביל; "
            "רענן את הדף ונסה שוב."
        )
    response.raise_for_status()
    # Refresh the editor now. The student deployment reads the same file
    # after its own cache expires.
    load_lecturer_instructions_record.clear()


