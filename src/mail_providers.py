"""Provider choices without changing existing Outlook profile/history keys."""
from urllib.parse import urlsplit

from merge_core import MergeError, validate_url


PROVIDER_NAMES = {"outlook": "Outlook web", "gmail": "Gmail web"}
GMAIL_URL = "https://mail.google.com/mail/u/0/#inbox"


def provider_for_url(url):
    return "gmail" if urlsplit(url).hostname == "mail.google.com" else "outlook"


def validate_provider_url(provider, url):
    url = validate_url(url)
    if provider not in PROVIDER_NAMES:
        raise MergeError("Choose Outlook web or Gmail web.")
    if provider_for_url(url) != provider:
        raise MergeError("The website address does not match the selected mail service.")
    return url
