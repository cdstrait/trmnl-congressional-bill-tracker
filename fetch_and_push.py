#!/usr/bin/env python3
"""
TRMNL Congressional Bill Tracker

Fetches bill data from the Congress.gov API and pushes it to a TRMNL
e-ink display via webhook. Designed to run on a schedule inside Docker.

Usage:
    python3 fetch_and_push.py              # Run once
    UPDATE_INTERVAL=3600 python3 fetch_and_push.py  # Run every hour
"""

import json
import hashlib
import os
import sys
import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import requests


# Paths
DATA_DIR = Path("/app/data") if Path("/app/data").exists() else Path(__file__).parent / "data"
STATE_FILE = DATA_DIR / "last_state.json"
BILLS_FILE = Path(__file__).parent / "bills.json"

# Environment variables
CONGRESS_API_KEY = os.environ.get("CONGRESS_API_KEY", "")
TRMNL_WEBHOOK_URL = os.environ.get("TRMNL_WEBHOOK_URL", "")
UPDATE_INTERVAL = int(os.environ.get("UPDATE_INTERVAL", 0))  # 0 = run once

API_BASE = "https://api.congress.gov/v3"

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Congress.gov API
# ---------------------------------------------------------------------------

def api_request(endpoint: str, timeout: int = 30, retries: int = 3) -> Optional[Dict]:
    """Make an authenticated request to the Congress.gov API."""
    url = f"{API_BASE}/{endpoint}"
    params = {"api_key": CONGRESS_API_KEY, "format": "json"}

    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError:
            if resp.status_code == 404:
                logger.warning("Not found: %s", endpoint)
                return None
            if resp.status_code == 429:
                wait = 2 * (attempt + 1)
                logger.warning("Rate limited, waiting %ds...", wait)
                time.sleep(wait)
            else:
                logger.error("HTTP %d for %s", resp.status_code, endpoint)
                if attempt == retries - 1:
                    return None
                time.sleep(2)
        except requests.exceptions.RequestException as exc:
            logger.error("Request error (attempt %d): %s", attempt + 1, exc)
            if attempt == retries - 1:
                return None
            time.sleep(2)

    return None


def chamber_name(bill_type: str) -> str:
    """Convert bill type prefix to chamber name for Congress.gov URLs."""
    return "senate" if bill_type.startswith("s") else "house"


def determine_status(latest_action_text: str) -> str:
    """Determine bill tracker status from the latest action text."""
    text = latest_action_text.lower()

    if "became public law" in text or "became private law" in text:
        return "Became Law"
    if "presented to president" in text or "to president" in text:
        return "To President"
    if "passed house" in text and "passed senate" in text:
        return "To President"
    if "conference" in text or "resolving differences" in text:
        return "In Conference"
    if "passed house" in text or "received in the house" in text:
        return "Passed House"
    if "passed senate" in text or "received in the senate" in text:
        return "Passed Senate"

    return "Introduced"


def fetch_bill(congress: int, bill_type: str, bill_number: int) -> Optional[Dict]:
    """Fetch comprehensive data for a single bill."""
    bill_type = bill_type.lower()
    base = f"bill/{congress}/{bill_type}/{bill_number}"

    logger.info("Fetching %s/%s/%s", congress, bill_type, bill_number)

    data = api_request(base)
    if not data or "bill" not in data:
        logger.error("Failed to fetch bill %s/%s/%s", congress, bill_type, bill_number)
        return None

    bill = data["bill"]
    latest_action = bill.get("latestAction", {})

    result = {
        "id": f"{bill_type}-{bill_number}-{congress}",
        "congress": congress,
        "bill_type": bill_type,
        "bill_number": bill_number,
        "title": bill.get("title", ""),
        "origin_chamber": bill.get("originChamber", ""),
        "introduced_date": bill.get("introducedDate", ""),
        "update_date": bill.get("updateDate", ""),
        "latest_action": {
            "date": latest_action.get("actionDate", ""),
            "text": latest_action.get("text", ""),
        },
        "url": f"https://www.congress.gov/bill/{congress}th-congress/{chamber_name(bill_type)}-bill/{bill_number}",
        "tracker_status": determine_status(latest_action.get("text", "")),
    }

    # Sponsor
    sponsors = bill.get("sponsors", [])
    if sponsors:
        s = sponsors[0]
        result["sponsor"] = {
            "name": s.get("fullName", ""),
            "party": s.get("party", ""),
            "state": s.get("state", ""),
        }
    else:
        result["sponsor"] = {"name": "", "party": "", "state": ""}

    # Committees
    time.sleep(0.5)
    comm_data = api_request(f"{base}/committees")
    if comm_data and "committees" in comm_data:
        result["committees"] = [
            {"name": c.get("name", ""), "chamber": c.get("chamber", "")}
            for c in comm_data["committees"]
        ]
    else:
        result["committees"] = []

    # Cosponsors
    time.sleep(0.5)
    cosponsor_data = api_request(f"{base}/cosponsors")
    if cosponsor_data and "pagination" in cosponsor_data:
        result["cosponsor_count"] = cosponsor_data["pagination"].get("count", 0)
    else:
        result["cosponsor_count"] = 0

    # Related bills
    time.sleep(0.5)
    related_data = api_request(f"{base}/relatedbills")
    if related_data and "relatedBills" in related_data:
        result["related_bills"] = [
            {
                "type": rb.get("type", "").lower(),
                "number": rb.get("number"),
                "title": rb.get("title", ""),
                "relationship": (
                    rb.get("relationshipDetails", [{}])[0].get("type", "")
                    if rb.get("relationshipDetails")
                    else ""
                ),
            }
            for rb in related_data["relatedBills"]
        ]
    else:
        result["related_bills"] = []

    return result


# ---------------------------------------------------------------------------
# TRMNL push
# ---------------------------------------------------------------------------

def build_merge_variables(bill: Dict) -> Dict:
    """Transform bill data into TRMNL merge_variables."""
    sponsor = bill.get("sponsor", {})
    committees = bill.get("committees", [])
    committee = committees[0] if committees else {}
    related_bills = bill.get("related_bills", [])
    related = related_bills[0] if related_bills else {}
    latest_action = bill.get("latest_action", {})

    merge_vars = {
        "bill_type": bill.get("bill_type", "").upper(),
        "bill_number": str(bill.get("bill_number", "")),
        "congress": str(bill.get("congress", "")),
        "title": bill.get("title", ""),
        "status": bill.get("tracker_status", ""),
        "introduced_date": bill.get("introduced_date", ""),
        "sponsor_name": sponsor.get("name", ""),
        "sponsor_party": sponsor.get("party", ""),
        "sponsor_state": sponsor.get("state", ""),
        "cosponsor_count": str(bill.get("cosponsor_count", 0)),
        "committee_name": committee.get("name", ""),
        "committee_chamber": committee.get("chamber", ""),
        "latest_action_date": latest_action.get("date", ""),
        "latest_action_text": latest_action.get("text", ""),
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    if related:
        merge_vars["related_bill_type"] = related.get("type", "").upper()
        merge_vars["related_bill_number"] = str(related.get("number", ""))
        merge_vars["related_bill_relationship"] = related.get("relationship", "")

    return merge_vars


def push_to_trmnl(merge_variables: Dict) -> bool:
    """POST bill data to the TRMNL webhook."""
    try:
        resp = requests.post(
            TRMNL_WEBHOOK_URL,
            json={"merge_variables": merge_variables},
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        if resp.status_code == 200:
            logger.info("Successfully pushed to TRMNL")
            return True
        if resp.status_code == 429:
            logger.error("TRMNL rate limit exceeded (429)")
        else:
            logger.error("TRMNL returned %d: %s", resp.status_code, resp.text)
        return False
    except requests.exceptions.RequestException as exc:
        logger.error("Failed to push to TRMNL: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Change detection
# ---------------------------------------------------------------------------

def compute_hash(data: Dict) -> str:
    """SHA-256 hash of bill data for change detection."""
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def load_last_hash() -> Optional[str]:
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f).get("hash")
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_hash(data_hash: str):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump({"hash": data_hash, "timestamp": datetime.now().isoformat()}, f, indent=2)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def load_bills() -> List[Dict]:
    """Load the list of bills to track from bills.json."""
    try:
        with open(BILLS_FILE, "r") as f:
            return json.load(f).get("bills", [])
    except FileNotFoundError:
        logger.error("bills.json not found. Copy bills.example.json and configure it.")
        sys.exit(1)
    except json.JSONDecodeError as exc:
        logger.error("Invalid JSON in bills.json: %s", exc)
        sys.exit(1)


def run_once():
    """Fetch bill data and push to TRMNL if changed."""
    if not CONGRESS_API_KEY:
        logger.error("CONGRESS_API_KEY not set. See README for setup instructions.")
        sys.exit(1)
    if not TRMNL_WEBHOOK_URL:
        logger.error("TRMNL_WEBHOOK_URL not set. See README for setup instructions.")
        sys.exit(1)

    bills = load_bills()
    if not bills:
        logger.error("No bills configured in bills.json")
        sys.exit(1)

    # Fetch the first bill (one bill per TRMNL screen)
    bill_cfg = bills[0]
    congress = bill_cfg.get("congress")
    bill_type = bill_cfg.get("type")
    bill_number = bill_cfg.get("number")

    if not all([congress, bill_type, bill_number]):
        logger.error("Invalid bill entry in bills.json: %s", bill_cfg)
        sys.exit(1)

    bill_data = fetch_bill(congress, bill_type, bill_number)
    if not bill_data:
        logger.error("Failed to fetch bill data")
        sys.exit(1)

    logger.info(
        "Fetched: %s %s (%s) - %s",
        bill_data["bill_type"].upper(),
        bill_data["bill_number"],
        bill_data["tracker_status"],
        bill_data["title"][:60],
    )

    # Check for changes
    current_hash = compute_hash(bill_data)
    last_hash = load_last_hash()

    if current_hash == last_hash:
        logger.info("No changes detected. Skipping TRMNL push.")
        return

    logger.info("Changes detected. Pushing to TRMNL...")
    merge_vars = build_merge_variables(bill_data)

    if push_to_trmnl(merge_vars):
        save_hash(current_hash)
        logger.info("Update complete.")
    else:
        logger.error("Push failed.")
        sys.exit(1)


def main():
    """Entry point. Runs once or on a loop depending on UPDATE_INTERVAL."""
    logger.info("TRMNL Congressional Bill Tracker starting")

    if UPDATE_INTERVAL > 0:
        logger.info("Running every %d seconds", UPDATE_INTERVAL)
        while True:
            try:
                run_once()
            except Exception:
                logger.exception("Error during update cycle")
            time.sleep(UPDATE_INTERVAL)
    else:
        run_once()


if __name__ == "__main__":
    main()
