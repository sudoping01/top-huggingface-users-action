# Top HuggingFace Users Action

A GitHub Action that powers [top-huggingface-users](https://github.com/sudoping01/top-huggingface-users).

Each run processes one country and produces **10 ranked leaderboards**:

| Folder | Ranked by |
|--------|-----------|
| `models/` | Number of models |
| `model_downloads/` | Total model downloads |
| `model_likes/` | Total model likes |
| `datasets/` | Number of datasets |
| `dataset_downloads/` | Total dataset downloads |
| `dataset_likes/` | Total dataset likes |
| `spaces/` | Number of spaces |
| `space_likes/` | Total space likes |
| `followers/` | Follower count |
| `contributions/` | Discussion count (community engagement proxy) |
| `papers/` | Number of papers linked to the user's HF profile |

## API endpoints used

| Endpoint | Auth required | Purpose |
|----------|---------------|---------|
| `GET /api/users?search={city}&limit=100` | Yes (HF_TOKEN) | Search users by city; returns location/company |
| `GET /api/quicksearch?q={city}&type=user&limit=100` | No | Fallback search without location data |
| `GET /api/users/{username}/overview` | No | Profile: followers, numDiscussions, numPapers, counts |
| `GET /api/models?author={u}&limit=1000&full=false` | No | Model list with downloads + likes |
| `GET /api/datasets?author={u}&limit=1000&full=false` | No | Dataset list with downloads + likes |
| `GET /api/spaces?author={u}&limit=1000&full=false` | No | Space list with likes |

## Inputs

| Input | Required | Description |
|-------|----------|-------------|
| `GIT_TOKEN` | Yes | GitHub PAT with repo write access |
| `HF_TOKEN` | Yes | HuggingFace token — enables the richer `/api/users?search=` endpoint which returns location/company |

## Usage

```yaml
- uses: sudoping01/top-huggingface-users-action@master
  with:
    GIT_TOKEN: ${{ secrets.GIT_TOKEN }}
    HF_TOKEN: ${{ secrets.HF_TOKEN }}
```

## Local testing

```bash
pip install -r requirements.txt

# From inside the data repo (top-huggingface-users/):
GITHUB_REPOSITORY=sudoping01/top-huggingface-users \
HF_TOKEN=hf_xxx \
python path/to/top-huggingface-users-action/src/main.py
```

Set `"devMode": "true"` in `config.json` to skip the git push during local tests.

## About the Contributions and Papers rankings

HuggingFace does not expose a commit or PR counter.

- **`contributions/`** — ranks by `numDiscussions`: discussions the user opened or participated in across Hub repos and forums. Best available proxy for community engagement.
- **`papers/`** — ranks by `numPapers`: arXiv papers the user has claimed authorship of on their HF profile. Kept separate because it measures research output, not community activity.

Both fields come from the public `/api/users/{username}/overview` endpoint, no token required.

## Dependencies

- [requests](https://pypi.org/project/requests/)
- [GitPython](https://gitpython.readthedocs.io/)

## License

MIT
