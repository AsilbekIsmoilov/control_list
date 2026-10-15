"""Operator photos, sourced from WFM instead of the spreadsheet.

The spreadsheet used to carry a photo link in column B. WFM already stores
every employee's photo in MinIO and exposes it through an integration
endpoint, so that is the authority now — one place to update a face, not two.

Two calls are involved:

    POST /oauth/token                     client_credentials -> bearer token
    GET  /integration/users-images?all=1  every user, one page

The listing needs the token; the URLs it hands back are public and go into
the page unchanged, so the browser loads the file from WFM's storage
directly. Nothing is copied to this side.
"""

import hashlib
import os
import re
import time

import requests
from django.core.cache import cache


BASE_URL = os.getenv(
    "WFM_IMAGES_BASE_URL", "https://api.wfm.kontaktmarkazi.uz/api/v1"
).rstrip("/")
CLIENT_ID = os.getenv("WFM_IMAGES_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("WFM_IMAGES_CLIENT_SECRET", "")

TOKEN_TIMEOUT = 15
LIST_TIMEOUT = 60
# The token is valid for 30 minutes; renew a little early so a long sync
# cannot be caught out mid-run.
TOKEN_LEEWAY = 120

# Selecting an operator resolves their photo through the search endpoint.
# Caching the answer keeps a page refresh from becoming an API call.
SEARCH_CACHE_SECONDS = 3600
SEARCH_MISS = ""

_token = None
_token_expires_at = 0.0


class WfmImagesUnavailable(RuntimeError):
    """WFM could not be reached or refused us — photos are skipped, not wiped."""


def get_token(force=False):
    global _token, _token_expires_at
    if not force and _token and time.time() < _token_expires_at:
        return _token

    if not CLIENT_ID or not CLIENT_SECRET:
        raise WfmImagesUnavailable(
            "WFM_IMAGES_CLIENT_ID / WFM_IMAGES_CLIENT_SECRET .env da yo'q"
        )

    try:
        response = requests.post(
            f"{BASE_URL}/oauth/token",
            json={
                "grant_type": "client_credentials",
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
            },
            timeout=TOKEN_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise WfmImagesUnavailable(f"token olinmadi: {exc}") from exc

    token = (payload.get("data") or {}).get("access_token")
    if not token:
        raise WfmImagesUnavailable(f"javobda access_token yo'q: {payload}")

    _token = token
    _token_expires_at = time.time() + 1800 - TOKEN_LEEWAY
    return token


def normalize_name(name):
    """Spreadsheet and WFM spellings reduced to a comparable form.

    Drops the `(0227)` code, folds case, and removes the apostrophes that
    Uzbek names carry inconsistently (`o'g'li` / `o‘g‘li` / `ogli`).
    """
    text = re.sub(r"\(\d+\)", "", name or "").lower()
    text = text.replace("‘", "").replace("’", "").replace("'", "").replace("`", "")
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", text).split())


def _tight(name):
    """Same, minus the spaces — WFM sometimes splits a name ("Ulug bek")."""
    return normalize_name(name).replace(" ", "")


def fetch_photo_urls():
    """Returns {normalized name: image url} for every WFM user who has a photo.

    One request for all of them: matching per operator would mean hundreds of
    round trips during a full sync.
    """
    try:
        response = requests.get(
            f"{BASE_URL}/integration/users-images",
            params={"all": "true", "page": 1, "limit": 5000},
            headers={"Authorization": f"Bearer {get_token()}"},
            timeout=LIST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise WfmImagesUnavailable(f"ro'yxat olinmadi: {exc}") from exc

    data = payload.get("data")
    users = data.get("data") if isinstance(data, dict) else data
    if not isinstance(users, list):
        raise WfmImagesUnavailable(f"kutilmagan javob shakli: {type(data)}")

    exact, tight = {}, {}
    for user in users:
        url = (user.get("image") or {}).get("url")
        if not url:
            continue
        key = normalize_name(user.get("fullName"))
        if not key:
            continue
        exact.setdefault(key, url)
        tight.setdefault(key.replace(" ", ""), []).append(url)

    # A spaceless key that two different people share is not a match, it is a
    # coin toss — better no photo than someone else's face.
    return exact, {k: v[0] for k, v in tight.items() if len(v) == 1}


class PhotoDirectory:
    """Name -> photo URL, with the exact match tried before the loose one."""

    def __init__(self, exact, tight):
        self.exact = exact
        self.tight = tight

    def __len__(self):
        return len(self.exact)

    def url_for(self, name):
        return self.exact.get(normalize_name(name)) or self.tight.get(_tight(name))


def load_directory():
    exact, tight = fetch_photo_urls()
    return PhotoDirectory(exact, tight)


def _users_from_payload(payload):
    """The endpoint answers with a bare list or a paginated envelope."""
    data = payload.get("data")
    if isinstance(data, dict):
        data = data.get("data")
    return data if isinstance(data, list) else []


def search_query(name):
    """The string handed to the endpoint: the name, minus the `(0227)` code.

    Apostrophes are kept. WFM matches `o'g'li` against its own `o‘g‘li`, but
    a query with them stripped out ("ogli") finds nothing at all.
    """
    return " ".join(re.sub(r"\(\d+\)", "", name or "").split())


def _search(query):
    try:
        response = requests.get(
            f"{BASE_URL}/integration/users-images",
            params={"search": query, "all": "false", "page": 1, "limit": 20},
            headers={"Authorization": f"Bearer {get_token()}"},
            timeout=LIST_TIMEOUT,
        )
        response.raise_for_status()
        return _users_from_payload(response.json())
    except (requests.RequestException, ValueError) as exc:
        raise WfmImagesUnavailable(f"qidiruv ishlamadi: {exc}") from exc


def _pick(users, name):
    """The one person who is actually ours, or nobody.

    The endpoint matches substrings, so a result set is a shortlist, not an
    answer — every candidate is re-checked against our own normalisation.
    """
    wanted = normalize_name(name)
    for user in users:
        if normalize_name(user.get("fullName")) == wanted:
            return user

    tight = _tight(name)
    loose = [u for u in users if _tight(u.get("fullName")) == tight]
    return loose[0] if len(loose) == 1 else None


def search_user(name):
    """Looks one operator up by surname / name / middle name."""
    query = search_query(name)
    if not query:
        return None

    user = _pick(_search(query), name)
    if user:
        return user

    # Spelling drifts between the two systems ("Ulug'bek" / "Ulug bek"), and
    # a full-name query then matches nothing. The surname is the stable part;
    # `_pick` still has the final say over who is returned.
    surname = query.split()[0]
    if surname != query:
        return _pick(_search(surname), name)
    return None


def active_image_url(user):
    """The photo currently in use, out of the `images` array.

    An operator accumulates several files — the original upload, a
    compressed variant — and only one of them carries `isActive`.
    """
    if not user:
        return None
    for image in user.get("images") or []:
        if image.get("isActive") and image.get("url"):
            return image["url"]
    return (user.get("image") or {}).get("url") or None


def _cache_key(name):
    # Ism probel va apostrof saqlaydi — kesh kalitida ular xatoga olib keladi.
    digest = hashlib.md5(normalize_name(name).encode("utf-8")).hexdigest()
    return f"wfm-photo:{digest}"


def prime_cache(names):
    """Fills the cache from the bulk listing — one request for everybody.

    Without this the first person to open an operator waits on a live search,
    over a second of it. The listing covers the same ground in a single call,
    so a periodic task can keep every answer warm.

    Only hits are stored. The bulk match is stricter than `search_user`, which
    also falls back to the surname; caching a miss here would deny that second
    chance to somebody the live search would have found.
    """
    directory = load_directory()
    warmed = 0
    for name in names:
        url = directory.url_for(name)
        if url:
            cache.set(_cache_key(name), url, SEARCH_CACHE_SECONDS)
            warmed += 1
    return warmed


def find_photo_url(name):
    """Photo URL for one operator, or None. Cached, misses included."""
    key = _cache_key(name)
    cached = cache.get(key)
    if cached is not None:
        return cached or None

    try:
        url = active_image_url(search_user(name))
    except WfmImagesUnavailable:
        # Vaqtinchalik nosozlikni keshlab qo'ymaymiz — chaqiruvchi lokal
        # nusxaga qaytadi, keyingi urinishda esa yana so'raladi.
        return None

    cache.set(key, url or SEARCH_MISS, SEARCH_CACHE_SECONDS)
    return url
