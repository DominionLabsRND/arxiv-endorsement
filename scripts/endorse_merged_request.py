#!/usr/bin/env python3
"""Register an approved, merged endorsement request with arXiv.

Credentials are intentionally read only from the ARXIV_USERNAME and
ARXIV_PASSWORD environment variables.  The arXiv endpoints used here mirror
the browser flow recorded in the repository HAR capture.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

from validate_request_files import REQUIRED_FIELDS, parse_request_file


LOGIN_URL = "https://arxiv.org/login?next_page=https%3A//arxiv.org/user"
ENDORSE_URL = "https://arxiv.org/auth/endorse"
USER_AGENT = "arxiv-endorsement-github-action/1.0"

ALLOWED_SUBJECT = "cs.SE"
# Matches e.g. "cs.SE (Software Engineering) subject category of arXiv" on the
# confirmation page returned for an endorsement code.
SUBJECT_RE = re.compile(r"\b([a-z-]+\.[A-Z-]+) \(([^)]+)\) subject category")


def write_action_output(name: str, value: str) -> None:
    """Append a key=value pair to $GITHUB_OUTPUT when running on Actions."""
    output_file = os.environ.get("GITHUB_OUTPUT")
    if not output_file:
        return
    with open(output_file, "a", encoding="utf-8") as handle:
        handle.write(f"{name}={value}\n")


class EndorsementFormParser(HTMLParser):
    """Extract the confirmation form's hidden endorsement code."""

    def __init__(self) -> None:
        super().__init__()
        self.code: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "input":
            return
        attributes = dict(attrs)
        if attributes.get("name") == "x" and attributes.get("type") == "hidden":
            self.code = attributes.get("value")


def confirm_subject(page: str, allowed: str = ALLOWED_SUBJECT) -> tuple[str | None, str | None]:
    """Return (error message, mismatching subject) for a wrong-subject page.

    The second value is only set when arXiv explicitly states a subject
    different from the allowed one, i.e. the requester must reissue their
    endorsement code.  arXiv writes the requested subject both in the
    "subject category" phrase (e.g. "cs.SE (Software Engineering) subject
    category of arXiv") and plain mentions further down the page, so matching
    either keeps this robust against small wording changes.
    """
    match = SUBJECT_RE.search(page)
    subject = match.group(1) if match else None
    if subject is not None and subject != allowed:
        message = f"arXiv endorsement code is for {subject}, not {allowed}"
        return message, subject
    if subject is None and not re.search(rf"\b{re.escape(allowed)}\b", page):
        return "arXiv confirmation page does not mention the allowed cs.SE subject", None
    return None, None


def read_fields(path: Path) -> dict[str, str]:
    errors = parse_request_file(path)
    if errors:
        raise ValueError("; ".join(errors))

    fields: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        name, value = line.split(":", 1)
        fields[name.strip()] = value.strip()
    if tuple(fields) != REQUIRED_FIELDS:
        raise ValueError("request fields are not in the required order")
    return fields


def request(opener, url: str, data: dict[str, str] | None = None) -> str:
    encoded_data = urlencode(data).encode("utf-8") if data is not None else None
    http_request = Request(url, data=encoded_data, headers={"User-Agent": USER_AGENT})
    with opener.open(http_request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser(description="Endorse one merged arXiv request.")
    parser.add_argument("request_file", type=Path)
    args = parser.parse_args()

    username = os.environ.get("ARXIV_USERNAME")
    password = os.environ.get("ARXIV_PASSWORD")
    if not username or not password:
        print("ARXIV_USERNAME and ARXIV_PASSWORD must be configured as repository secrets.", file=sys.stderr)
        return 2

    try:
        fields = read_fields(args.request_file)
        code = fields["EndorsementCode"]
        opener = build_opener(HTTPCookieProcessor(CookieJar()))

        # This endpoint returns a redirect to /user for a successful login.
        request(opener, LOGIN_URL, {"username": username, "password": password})
        confirmation_page = request(
            opener,
            f"https://arxiv.org/auth/endorse.php?{urlencode({'x': code, 'submit': 'Submit'})}",
        )

        form = EndorsementFormParser()
        form.feed(confirmation_page)
        if form.code != code:
            raise RuntimeError("arXiv did not return a confirmation form for this endorsement code")
        subject_error, wrong_subject = confirm_subject(confirmation_page)
        if wrong_subject:
            write_action_output("wrong_subject", wrong_subject)
        if subject_error:
            raise RuntimeError(subject_error)

        result_page = request(
            opener,
            ENDORSE_URL,
            {
                "x": code,
                "choice": "1",
                "seen_paper": "on",
                "comment": "Endorsed after the repository's documented review protocol.",
                "submit": "Submit",
            },
        )
        if "Thank you for endorsing" not in result_page:
            raise RuntimeError("arXiv did not confirm the endorsement")
    except (HTTPError, URLError, OSError, RuntimeError, ValueError) as error:
        print(f"Endorsement was not registered: {error}", file=sys.stderr)
        return 1

    print(f"Registered arXiv endorsement code from {args.request_file}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
