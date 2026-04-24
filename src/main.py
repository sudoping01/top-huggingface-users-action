"""
top-huggingface-users-action
Fetches HuggingFace user stats per country and writes ranked markdown leaderboards.

Rankings (one markdown file per country per ranking):
  models/           – by number of models published
  model_downloads/  – by total model downloads
  model_likes/      – by total model likes
  datasets/         – by number of datasets published
  dataset_downloads/– by total dataset downloads
  dataset_likes/    – by total dataset likes
  spaces/           – by number of spaces published
  space_likes/      – by total space likes
  followers/        – by follower count
  contributions/    – by discussion count (community engagement proxy)
  papers/           – by number of papers linked to the user's HF profile

API notes:
  • With HF_TOKEN: GET /api/users?search={city}&limit=100  → richer results incl. location
  • Without token:  GET /api/quicksearch?q={city}&type=user&limit=100  → username + fullname only
  • Profile:        GET /api/users/{username}/overview     → counts, followers, discussions, papers
  • Items:          GET /api/models|datasets|spaces?author={u}&limit=1000&full=false  → downloads/likes
"""

import json
import os
import subprocess
import time
import urllib.parse
from datetime import datetime, timezone

import requests

CONFIG_PATH = "config.json"
CHECKPOINT_PATH = "checkpoint.json"
CACHE_DIR = "cache"
MARKDOWN_DIR = "markdown"
HF_API = "https://huggingface.co/api"
MAX_RETRIES = 4



def _build_session():
    s = requests.Session()
    s.headers["User-Agent"] = "top-huggingface-users/1.0"
    token = os.environ.get("HF_TOKEN", "").strip()
    if token:
        s.headers["Authorization"] = f"Bearer {token}"
    return s


SESSION = _build_session()
HF_TOKEN = os.environ.get("HF_TOKEN", "").strip()


def api_get(url, retries=MAX_RETRIES):
    delay = 2
    for attempt in range(retries):
        try:
            resp = SESSION.get(url, timeout=30)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 429:
                print(f"  [429] rate limited, sleeping {delay}s …")
                time.sleep(delay)
                delay = min(delay * 2, 120)
                continue
            if resp.status_code in (401, 403, 404):
                print(f"  [HTTP {resp.status_code}] {url}")
                return None
            print(f"  [HTTP {resp.status_code}] {url}")
            if attempt < retries - 1:
                time.sleep(delay)
                delay = min(delay * 2, 60)
        except Exception as exc:
            print(f"  [ERR] {url}: {exc}")
            if attempt < retries - 1:
                time.sleep(delay)
                delay = min(delay * 2, 60)
    return None


def search_city(city):
    """Return list of user dicts for a city search."""
    city = city.strip()
    if not city:
        return []
    q = urllib.parse.quote(city)

    seen_names = set()
    combined = []

    if HF_TOKEN:
        data = api_get(f"{HF_API}/users?search={q}&limit=100")
        if isinstance(data, list):
            for item in data:
                uname = (item.get("user") or item.get("name") or item.get("id") or "").strip()
                if uname and uname not in seen_names:
                    seen_names.add(uname)
                    combined.append(item)

    data = api_get(f"{HF_API}/quicksearch?q={q}&type=user&limit=20")
    if isinstance(data, dict):
        for item in data.get("users", []):
            uname = (item.get("user") or item.get("name") or item.get("id") or "").strip()
            if uname and uname not in seen_names:
                seen_names.add(uname)
                combined.append(item)

    return combined



def get_overview(username):
    """GET /api/users/{username}/overview — public, no auth required."""
    return api_get(f"{HF_API}/users/{username}/overview")


def get_models(username):
    data = api_get(f"{HF_API}/models?author={username}&limit=1000&full=false")
    return data if isinstance(data, list) else []


def get_datasets(username):
    data = api_get(f"{HF_API}/datasets?author={username}&limit=1000&full=false")
    return data if isinstance(data, list) else []


def get_spaces(username):
    data = api_get(f"{HF_API}/spaces?author={username}&limit=1000&full=false")
    return data if isinstance(data, list) else []


def _sum(items, key):
    return sum(int(item.get(key) or 0) for item in items)



def build_user_record(username, search_item=None):
    """
    Fetch all stats for one user and return a flat dict.
    search_item: raw dict from the search results (may already have location/company).
    """
    overview = get_overview(username)
    if not overview:
        return None
    time.sleep(0.3)

    models = get_models(username)
    time.sleep(0.3)
    datasets = get_datasets(username)
    time.sleep(0.3)
    spaces = get_spaces(username)

    # Location / company come from:
    #   1. Authenticated /api/users?search= results (search_item)
    #   2. Overview might have them in future API versions
    si = search_item or {}
    _si_details = si.get("details")
    _si_details = _si_details if isinstance(_si_details, dict) else {}
    location = (
        si.get("location") or _si_details.get("location")
        or overview.get("location") or ""
    ).strip() or "No Location"
    company = (
        si.get("company") or _si_details.get("company")
        or overview.get("company") or ""
    ).strip() or "No Company"

    avatar = overview.get("avatarUrl") or si.get("avatarUrl") or ""
    # Relative avatar URLs need the HF base
    if avatar and avatar.startswith("/avatars/"):
        avatar = f"https://huggingface.co{avatar}"

    fullname = (overview.get("fullname") or si.get("fullname") or "").strip() or "No Name"

    return {
        "username": username,
        "fullname": fullname,
        "avatarUrl": avatar,
        "location": location,
        "company": company,
        "followers": int(overview.get("numFollowers") or 0),
        "following": int(overview.get("numFollowing") or 0),
        "discussions_count": int(overview.get("numDiscussions") or 0),
        "papers_count": int(overview.get("numPapers") or 0),
        "models_count": len(models),
        "models_downloads": _sum(models, "downloads"),
        "models_likes": _sum(models, "likes"),
        "datasets_count": len(datasets),
        "datasets_downloads": _sum(datasets, "downloads"),
        "datasets_likes": _sum(datasets, "likes"),
        "spaces_count": len(spaces),
        "spaces_likes": _sum(spaces, "likes"),
    }



def process_country(location_data):
    country = location_data["country"]
    print(f"\n{'='*50}")
    print(f"Country: {country}")
    print(f"{'='*50}")

    seen = {}

    # Search by country/geo name first — the authenticated endpoint (/api/users?search=)
    # indexes the location field, so country-level terms are more likely to surface users
    # who explicitly set their location (e.g. "Senegal", "France").  City names follow as
    # a secondary pass for users who set a more specific location.
    country_terms = list(dict.fromkeys([
        location_data["country"],
        location_data["geoName"],
    ]))
    search_terms = country_terms + [c.strip() for c in location_data["cities"] if c.strip()]

    for term in search_terms:
        print(f"\nSearching: {term!r}")
        results = search_city(term)
        print(f"  {len(results)} candidates found")

        for item in results:
            uname = (item.get("user") or item.get("login") or item.get("name") or item.get("id") or "").strip()
            utype = item.get("type", "user")
            if uname and utype != "org" and uname not in seen:
                # Pre-filter: if the search result already carries location data,
                # skip candidates that clearly belong to a different country.
                # Items without location data pass through and are checked after
                # the full profile is fetched.
                _details = item.get("details")
                item_location = (
                    item.get("location")
                    or (_details.get("location") if isinstance(_details, dict) else "")
                    or ""
                ).strip()
                if item_location and not location_matches(item_location, location_data):
                    continue
                seen[uname] = item
        time.sleep(0.5)

    print(f"\nUnique users to enrich: {len(seen)}")
    records = []
    for uname, search_item in seen.items():
        print(f"  {uname}")
        record = build_user_record(uname, search_item)
        if record:
            records.append(record)
        time.sleep(0.5)

    # Post-filter: drop anyone whose profile location doesn't match this country.
    # Catches users whose name/username coincidentally matched the city search.
    before = len(records)
    records = [r for r in records if location_matches(r["location"], location_data)]
    print(f"\nLocation filter: {before} → {len(records)} users kept")
    return records



def _slug(country):
    return country.strip().lower().replace(" ", "_").replace(".", "")


def save_cache(country, users):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"{_slug(country)}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)
    print(f"Cache → {path} ({len(users)} users)")


def load_cache(country):
    path = os.path.join(CACHE_DIR, f"{_slug(country)}.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return []


#  Ranking configuration
# (sort_key, human label, table-specific columns)
# Table columns = list of (header, user_field, formatter)

def _n(v):
    return str(int(v or 0))


def _fmt(v):
    v = int(v or 0)
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"{v / 1_000:.1f}K"
    return str(v)


def location_matches(user_location, location_data):
    """Return True if the user's location plausibly maps to this country.

    Users with no location set are kept (can't prove they're wrong).
    Users with a location that doesn't mention this country/cities are dropped.
    """
    if not user_location or user_location == "No Location":
        return True  # no location data → benefit of the doubt
    loc = user_location.lower()
    terms = [location_data["country"].lower(), location_data["geoName"].lower()]
    terms += [c.strip().lower() for c in location_data["cities"] if c.strip()]
    return any(t and t in loc for t in terms)


RANK_CONFIG = {
    "models": {
        "sort_key": "models_count",
        "label": "Models",
        "columns": [
            ("Models",     "models_count",     _n),
            ("Downloads",  "models_downloads",  _fmt),
            ("Likes",      "models_likes",      _fmt),
            ("Followers",  "followers",         _n),
        ],
    },
    "model_downloads": {
        "sort_key": "models_downloads",
        "label": "Model Downloads",
        "columns": [
            ("Models",     "models_count",     _n),
            ("Downloads",  "models_downloads",  _fmt),
            ("Likes",      "models_likes",      _fmt),
            ("Followers",  "followers",         _n),
        ],
    },
    "model_likes": {
        "sort_key": "models_likes",
        "label": "Model Likes",
        "columns": [
            ("Models",     "models_count",     _n),
            ("Downloads",  "models_downloads",  _fmt),
            ("Likes",      "models_likes",      _fmt),
            ("Followers",  "followers",         _n),
        ],
    },
    "datasets": {
        "sort_key": "datasets_count",
        "label": "Datasets",
        "columns": [
            ("Datasets",   "datasets_count",     _n),
            ("Downloads",  "datasets_downloads",  _fmt),
            ("Likes",      "datasets_likes",      _fmt),
            ("Followers",  "followers",           _n),
        ],
    },
    "dataset_downloads": {
        "sort_key": "datasets_downloads",
        "label": "Dataset Downloads",
        "columns": [
            ("Datasets",   "datasets_count",     _n),
            ("Downloads",  "datasets_downloads",  _fmt),
            ("Likes",      "datasets_likes",      _fmt),
            ("Followers",  "followers",           _n),
        ],
    },
    "dataset_likes": {
        "sort_key": "datasets_likes",
        "label": "Dataset Likes",
        "columns": [
            ("Datasets",   "datasets_count",     _n),
            ("Downloads",  "datasets_downloads",  _fmt),
            ("Likes",      "datasets_likes",      _fmt),
            ("Followers",  "followers",           _n),
        ],
    },
    "spaces": {
        "sort_key": "spaces_count",
        "label": "Spaces",
        "columns": [
            ("Spaces",    "spaces_count",  _n),
            ("Likes",     "spaces_likes",  _fmt),
            ("Followers", "followers",     _n),
        ],
    },
    "space_likes": {
        "sort_key": "spaces_likes",
        "label": "Space Likes",
        "columns": [
            ("Spaces",    "spaces_count",  _n),
            ("Likes",     "spaces_likes",  _fmt),
            ("Followers", "followers",     _n),
        ],
    },
    "followers": {
        "sort_key": "followers",
        "label": "Followers",
        "columns": [
            ("Models",   "models_count",   _n),
            ("Datasets", "datasets_count", _n),
            ("Spaces",   "spaces_count",   _n),
            ("Followers", "followers",     _n),
        ],
    },
    "contributions": {
        "sort_key": "discussions_count",
        "label": "Contributions",
        "columns": [
            ("Discussions", "discussions_count", _n),
            ("Followers",   "followers",         _n),
        ],
    },
    "papers": {
        "sort_key": "papers_count",
        "label": "Papers",
        "columns": [
            ("Papers",    "papers_count",    _n),
            ("Followers", "followers",       _n),
        ],
    },
}

NAV_ORDER = list(RANK_CONFIG.keys())
ICON_BASE = "https://github.com/gayanvoice/github-active-users-monitor"



def _share_table(title, page_url):
    enc_t = urllib.parse.quote(title)
    enc_u = urllib.parse.quote(page_url)
    links = [
        ("Facebook",
         f"https://web.facebook.com/sharer.php?t={enc_t}&u={enc_u}&_rdc=1&_rdr",
         f"{ICON_BASE}/raw/master/public/images/icons/facebook.svg"),
        ("Facebook Messenger",
         f"https://www.facebook.com/dialog/send?link={enc_u}&app_id=291494419107518&redirect_uri={enc_u}",
         f"{ICON_BASE}/raw/master/public/images/icons/facebook_messenger.svg"),
        ("Twitter",
         f"https://twitter.com/intent/tweet?text={enc_t}&url={enc_u}",
         f"{ICON_BASE}/raw/master/public/images/icons/twitter.svg"),
        ("WhatsApp",
         f"https://web.whatsapp.com/send?text={title} {page_url}",
         f"{ICON_BASE}/blob/master/public/images/icons/whatsapp.svg"),
        ("Telegram",
         f"https://t.me/share/url?url={enc_u}&text={enc_t}",
         f"{ICON_BASE}/blob/master/public/images/icons/telegram.svg"),
        ("LinkedIn",
         f"https://www.linkedin.com/shareArticle?title={enc_t}&url={enc_u}",
         f"{ICON_BASE}/blob/master/public/images/icons/linkedin.svg"),
        ("Vkontakte",
         f"https://vk.com/share.php?url={enc_u}",
         f"{ICON_BASE}/blob/master/public/images/icons/vkontakte.svg"),
        ("Blogger",
         f"https://www.blogger.com/blog-this.g?n={urllib.parse.quote('Top HuggingFace Users')}&t={enc_t}&u={enc_u}",
         f"{ICON_BASE}/blob/master/public/images/icons/blogger.svg"),
        ("Wordpress",
         f"https://wordpress.com/wp-admin/press-this.php?u={enc_u}&t={enc_t}&s={urllib.parse.quote('Top HuggingFace Users by country')}&i=",
         f"{ICON_BASE}/blob/master/public/images/icons/wordpress.svg"),
        ("Email",
         f"mailto:?subject={enc_t}&body={urllib.parse.quote('Top HuggingFace Users by country')}-{enc_u}",
         f"{ICON_BASE}/blob/master/public/images/icons/gmail.svg"),
        ("Reddit",
         f"https://www.reddit.com/submit?title={enc_t}&url={enc_u}",
         f"{ICON_BASE}/blob/master/public/images/icons/reddit.svg"),
    ]
    cells = "\n".join(
        f'\t\t<td>\n\t\t\t<a href="{href}">\n\t\t\t\t<img src="{icon}" height="48" width="48" alt="{name}"/>\n\t\t\t</a>\n\t\t</td>'
        for name, href, icon in links
    )
    return f"<table>\n\t<tr>\n{cells}\n\t</tr>\n</table>"


def generate_markdown(repo, location_data, users, rank_by, timestamp):
    cfg = RANK_CONFIG[rank_by]
    sort_key = cfg["sort_key"]
    rank_label = cfg["label"]
    extra_cols = cfg["columns"]

    country = location_data["country"]
    geo_name = location_data["geoName"]
    image_url = location_data["imageUrl"]
    cities_str = ", ".join(c.strip().capitalize() for c in location_data["cities"] if c.strip())
    slug = _slug(country)

    title = f"Top HuggingFace Users By {rank_label} in {geo_name}"
    page_url = f"https://github.com/{repo}/blob/main/markdown/{rank_by}/{slug}.md"

    sorted_users = sorted(users, key=lambda u: u.get(sort_key, 0), reverse=True)


    nav_cells = []
    for rk in NAV_ORDER:
        nav_label = f"Top Users By {RANK_CONFIG[rk]['label']}"
        if rk == rank_by:
            nav_cells.append(f"\t\t<td>\n\t\t\t<strong>{nav_label}</strong>\n\t\t</td>")
        else:
            href = f"https://github.com/{repo}/blob/main/markdown/{rk}/{slug}.md"
            nav_cells.append(f'\t\t<td>\n\t\t\t<a href="{href}">{nav_label}</a>\n\t\t</td>')
    nav_html = "<table>\n\t<tr>\n" + "\n".join(nav_cells) + "\n\t</tr>\n</table>"


    base_headers = ["#", "Username", "Company", "Location"]
    all_headers = base_headers + [h for h, _, _ in extra_cols]
    th_cells = "".join(f"\n\t\t<th>{h}</th>" for h in all_headers)
    table_header = f"\t<tr>{th_cells}\n\t</tr>"


    rows = []
    for i, u in enumerate(sorted_users, 1):
        uname = u["username"]
        avatar = u.get("avatarUrl", "")
        fullname = u.get("fullname", "No Name")
        company = u.get("company", "No Company")
        location = u.get("location", "No Location")

        extra_cells = "".join(
            f"\n\t\t<td>{fmt(u.get(field, 0))}</td>"
            for _, field, fmt in extra_cols
        )
        rows.append(
            f"\t<tr>\n"
            f"\t\t<td>{i}</td>\n"
            f"\t\t<td>\n"
            f'\t\t\t<a href="https://huggingface.co/{uname}">\n'
            f'\t\t\t\t<img src="{avatar}" width="24" alt="Avatar of {uname}"> {uname}\n'
            f"\t\t\t</a><br/>\n"
            f"\t\t\t{fullname}\n"
            f"\t\t</td>\n"
            f"\t\t<td>{company}</td>\n"
            f"\t\t<td>{location}</td>"
            f"{extra_cells}\n"
            f"\t</tr>"
        )

    user_table = f"<table>\n{table_header}\n" + "\n".join(rows) + "\n</table>"
    share_table = _share_table(title, page_url)
    owner = repo.split("/")[0]

    return (
        f"# {title}\n"
        f"[![Top HuggingFace Users]"
        f"(https://github.com/{repo}/actions/workflows/action.yml/badge.svg)]"
        f"(https://github.com/{repo}/actions/workflows/action.yml)\n"
        f"\n"
        f'<a href="https://github.com/{repo}">\n'
        f'\t<img align="right" width="200" src="{image_url}" alt="{geo_name}">\n'
        f"</a>\n"
        f"\n"
        f"The `{rank_label.lower()}` of users in {geo_name} on `{timestamp}`. "
        f"This list contains users from `{geo_name}` and cities `{cities_str}`.\n"
        f"\n"
        f"There are `138 countries` and `674 cities` can be found [here](https://github.com/{repo}).\n"
        f"\n"
        f"There are `{len(users)} users` in {geo_name}. "
        f"You need at least `0 followers` to be on this list.\n"
        f"\n"
        f"<table>\n\t<tr>\n\t\t<td>\n\t\t\tDon't forget to star ⭐ this repository\n\t\t</td>\n\t</tr>\n</table>\n"
        f"\n"
        f"{nav_html}\n"
        f"\n"
        f"### 🚀 Share on\n"
        f"\n"
        f"{share_table}\n"
        f"\n"
        f"{user_table}\n"
        f"\n"
        f"### 🚀 Share on\n"
        f"\n"
        f"{share_table}\n"
        f"\n"
        f"## 📦 Third party\n"
        f"\n"
        f"- [requests](https://pypi.org/project/requests/) - HTTP library for Python.\n"
        f"- [GitPython](https://gitpython.readthedocs.io/) - Handling Git commands.\n"
        f"\n"
        f"## 📄 License\n"
        f"\n"
        f"- GitHub Action - [{owner}/top-huggingface-users-action](https://github.com/{owner}/top-huggingface-users-action)\n"
        f"- Repository - [{repo}](https://github.com/{repo})\n"
        f"- Data in the `./cache` directory - [Open Database License](https://opendatacommons.org/licenses/odbl/1-0/)\n"
        f"- Code - [MIT](./LICENSE) © [{owner}](https://github.com/{owner})\n"
    )


def save_markdown_files(repo, location_data, users, timestamp):
    slug = _slug(location_data["country"])
    for rank_by in RANK_CONFIG:
        dir_path = os.path.join(MARKDOWN_DIR, rank_by)
        os.makedirs(dir_path, exist_ok=True)
        content = generate_markdown(repo, location_data, users, rank_by, timestamp)
        path = os.path.join(dir_path, f"{slug}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    print(f"Markdown written: {len(RANK_CONFIG)} files for {location_data['country']}")




def main():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        config = json.load(f)
    with open(CHECKPOINT_PATH, encoding="utf-8") as f:
        checkpoint_data = json.load(f)

    if not HF_TOKEN:
        print("WARNING: HF_TOKEN is not set — only quicksearch (unauthenticated) will be used. Results will be limited.")
    else:
        print("HF_TOKEN: present")

    dev_mode = config.get("devMode", "false") == "true"
    locations = config["locations"]
    countries_per_run = int(config.get("countriesPerRun", 1))
    checkpoint = checkpoint_data["checkpoint"]

    repo = os.environ.get("GITHUB_REPOSITORY", "sudoping01/top-huggingface-users")
    timestamp = datetime.now(timezone.utc).strftime("%Y/%m/%d %I:%M %p UTC")
    processed = []

    print(f"countriesPerRun: {countries_per_run} | checkpoint: {checkpoint}/{len(locations)-1}")

    for i in range(countries_per_run):
        idx = (checkpoint + i) % len(locations)
        location_data = locations[idx]
        country = location_data["country"]

        print(f"\n[{i+1}/{countries_per_run}] index {idx}: {country}")

        users = process_country(location_data)

        existing = load_cache(country)
        if existing and len(existing) > len(users) and len(users) < 50:
            print(f"Keeping existing cache ({len(existing)}) over new ({len(users)})")
            users = existing
        else:
            save_cache(country, users)

        save_markdown_files(repo, location_data, users, timestamp)
        processed.append(country)


    new_checkpoint = (checkpoint + countries_per_run) % len(locations)
    with open(CHECKPOINT_PATH, "w") as f:
        json.dump({"checkpoint": new_checkpoint}, f)
    print(f"\nCheckpoint: {checkpoint} → {new_checkpoint}")

    if not dev_mode:
        token = os.environ.get("GIT_TOKEN", "")
        if token:

            names = ", ".join(
                " ".join(w.capitalize() for w in c.replace("_", " ").split())
                for c in processed
            )
            now = datetime.now(timezone.utc)
            msg = f"Update {names} - {now.strftime('%Y/%m/%d %I:%M %p')} UTC"
            subprocess.run(["git", "config", "user.email", "action@github.com"], check=True)
            subprocess.run(["git", "config", "user.name", "GitHub Action"], check=True)
            subprocess.run(["git", "add", "-A"], check=True)
            if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode != 0:
                subprocess.run(["git", "commit", "-m", msg], check=True)
                subprocess.run(
                    ["git", "remote", "set-url", "origin",
                     f"https://x-access-token:{token}@github.com/{repo}.git"],
                    check=True,
                )
                subprocess.run(["git", "push", "origin", "HEAD"], check=True)
                print(f"Pushed: {msg}")
            else:
                print("Nothing to commit.")
        else:
            print("No GIT_TOKEN — skipping push.")
    else:
        print("Dev mode: skipping git push.")


if __name__ == "__main__":
    main()
