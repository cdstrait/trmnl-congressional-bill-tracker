# TRMNL Congressional Bill Tracker

Track any bill in the U.S. Congress and display its status on a [TRMNL](https://usetrmnl.com) e-ink device. The tracker fetches live data from the [Congress.gov API](https://api.congress.gov/) and pushes updates to your TRMNL screen via webhook.

---

### ⚠️ DISCLAIMER

**This project was created with the assistance of AI. I am not a programmer. Use at your own risk.**

---

## What it does

- Fetches real-time bill data from Congress.gov (status, sponsor, committees, cosponsors, latest action, related bills)
- Pushes updates to a TRMNL e-ink display via webhook
- Only pushes when data actually changes (SHA-256 change detection)
- Runs on a configurable schedule inside Docker
- Supports any bill type: Senate bills, House bills, joint resolutions, etc.

## Display

The TRMNL screen shows:

| Field | Description |
|-------|-------------|
| Title | Full bill title |
| Status | Introduced, Passed Senate, Passed House, To President, Became Law |
| Congress | Which Congress (e.g., 119th) |
| Introduced | Date bill was introduced |
| Cosponsors | Current cosponsor count |
| Lead Sponsor | Name, party, and state |
| Committee | Current committee assignment |
| Latest Action | Most recent action with date |
| Related Bills | Companion bills in the other chamber |

## Prerequisites

- [TRMNL device](https://usetrmnl.com) with an active account
- [Congress.gov API key](https://api.data.gov/signup/) (free)
- Docker and Docker Compose

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/cdstrait/trmnl-congressional-bill-tracker.git
cd trmnl-congressional-bill-tracker
```

### 2. Create a TRMNL Private Plugin

1. Log into [usetrmnl.com](https://usetrmnl.com)
2. Go to **Plugins** > **Private Plugins** > **Create New Plugin**
3. Name it "Congressional Bill Tracker"
4. Set Strategy to **Webhook**
5. Paste the contents of `template.html` into the **Markup Editor**
6. Save and copy the **Webhook URL**

### 3. Configure environment

```bash
cp .env.example .env
```

Edit `.env` with your API key and webhook URL:

```
CONGRESS_API_KEY=your_api_key_here
TRMNL_WEBHOOK_URL=https://usetrmnl.com/api/custom_plugins/your-plugin-uuid
UPDATE_INTERVAL=3600
```

### 4. Choose a bill to track

```bash
cp bills.example.json bills.json
```

Edit `bills.json` to specify the bill you want to track:

```json
{
  "bills": [
    {
      "congress": 119,
      "type": "s",
      "number": 1546,
      "description": "Patent Eligibility Restoration Act of 2025"
    }
  ]
}
```

The first bill in the array is displayed on the TRMNL screen.

**Bill types:**

| Type | Description |
|------|-------------|
| `s` | Senate Bill |
| `hr` | House Bill |
| `sjres` | Senate Joint Resolution |
| `hjres` | House Joint Resolution |
| `sconres` | Senate Concurrent Resolution |
| `hconres` | House Concurrent Resolution |
| `sres` | Senate Resolution |
| `hres` | House Resolution |

**Finding bill numbers:** Search for bills at [congress.gov](https://www.congress.gov/search) and note the bill type, number, and congress from the URL.

### 5. Start the tracker

```bash
docker compose up -d
```

The tracker will immediately fetch the bill data, push it to your TRMNL screen, and then continue checking for updates at the configured interval.

## Usage

```bash
# Start
docker compose up -d

# View logs
docker compose logs -f

# Stop
docker compose down

# Rebuild after changes
docker compose build --no-cache && docker compose up -d

# Force an update (delete cached state)
rm data/last_state.json && docker compose restart
```

## Running without Docker

```bash
pip install -r requirements.txt
cp .env.example .env   # edit with your keys
cp bills.example.json bills.json   # edit with your bill

# Source environment variables
export $(cat .env | xargs)

# Run once
python3 fetch_and_push.py

# Or set UPDATE_INTERVAL in .env to run on a loop
```

## How it works

```
Congress.gov API  --->  fetch_and_push.py  --->  TRMNL Webhook
                           |                         |
                     Change detection           e-ink display
                     (SHA-256 hash)              updates
```

1. The script reads `bills.json` for the bill to track
2. Fetches bill data from the Congress.gov API (main data, committees, cosponsors, related bills)
3. Computes a SHA-256 hash of the response
4. Compares against the last known hash in `data/last_state.json`
5. If data changed, transforms it into TRMNL merge variables and POSTs to the webhook
6. Saves the new hash to avoid redundant pushes
7. Sleeps for `UPDATE_INTERVAL` seconds, then repeats

## Rate limits

| Service | Limit |
|---------|-------|
| Congress.gov API | 5,000 requests/hour |
| TRMNL (standard) | 12 pushes/hour |
| TRMNL+ | 30 pushes/hour |

The default 1-hour interval uses ~5 API calls per cycle and at most 1 TRMNL push, well within both limits.

## Project structure

```
trmnl-congressional-bill-tracker/
├── fetch_and_push.py       # Main script: fetch from Congress.gov, push to TRMNL
├── bills.example.json      # Example bill configuration
├── template.html           # TRMNL markup template (paste into TRMNL dashboard)
├── docker-compose.yml      # Docker Compose service definition
├── Dockerfile              # Container image
├── requirements.txt        # Python dependencies
├── .env.example            # Example environment variables
└── data/                   # Runtime data (gitignored)
    └── last_state.json     # Change detection state
```

## License

MIT
