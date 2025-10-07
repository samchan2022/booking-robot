#!/usr/bin/env python3

import requests
from requests.adapters import HTTPAdapter, Retry
import argparse
import os
from datetime import datetime, timezone, timedelta
import time
import ntplib   # for NTP drift
import logging
from dotenv import load_dotenv

# ---------------------------
# Logging Setup
# ---------------------------
def get_logger(name=__name__):
    logger = logging.getLogger(name)
    if not logger.hasHandlers():
        logger.setLevel(logging.DEBUG)
        ch = logging.StreamHandler()
        ch.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s | %(levelname)-8s | %(message)s')
        ch.setFormatter(formatter)
        logger.addHandler(ch)
    return logger

logger = get_logger()

# ---------------------------
# Load environment variables
# ---------------------------
load_dotenv()
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
MEETUP_API_URL = os.getenv("MEETUP_API_URL")
DRY_RUN = os.getenv("DRY_RUN", "False").lower() in ("1", "true", "yes")

# Retry config
RETRY_INTERVAL = 2
MIN_ATTEMPTS = 2
MAX_ATTEMPTS = 3
TIMEOUT_MINUTES = 2

# Requests session with retry
session = requests.Session()
retries = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[500,502,503,504],
    allowed_methods=["POST"]
)
adapter = HTTPAdapter(max_retries=retries)
session.mount("https://", adapter)
session.mount("http://", adapter)

# ---------------------------
# Utilities
# ---------------------------
def parse_iso_datetime(dt_str: str) -> datetime:
    if not isinstance(dt_str, str):
        raise TypeError(f"Expected string, got {type(dt_str).__name__}")
    dt_str = dt_str.strip().replace("Z","+00:00")
    return datetime.fromisoformat(dt_str)

def get_ntp_drift(server="pool.ntp.org"):
    try:
        client = ntplib.NTPClient()
        response = client.request(server, version=3)
        return response.offset
    except Exception as e:
        logger.warning(f"Failed to fetch NTP drift, using system time only: {e}")
        return 0.0

def now_corrected(drift_seconds=0.0):
    return datetime.fromtimestamp(time.time() + drift_seconds, tz=timezone.utc)

def wait_until_minute_range_target_time(
    start_minute=55,
    end_minute=59,
    target_hour=None,
    target_minute=0,
    margin_seconds=0.1,
    drift_seconds=0.0
):
    now_corr = time.time() + drift_seconds
    local = time.localtime(now_corr)
    current_min = local.tm_min
    current_hour = local.tm_hour

    if start_minute <= current_min <= end_minute:
        tgt_min = target_minute % 60
        next_hour = target_hour % 24 if target_hour is not None else (current_hour+1)%24 if current_min>=tgt_min else current_hour
        target_timestamp = time.mktime((
            local.tm_year, local.tm_mon, local.tm_mday,
            next_hour, tgt_min, 0,
            local.tm_wday, local.tm_yday, local.tm_isdst
        )) + margin_seconds
        if target_timestamp <= now_corr:
            target_timestamp += 24*3600
        wait_time = target_timestamp - now_corr
        logger.info(f"⏳ Waiting {wait_time:.3f}s until {next_hour:02d}:{tgt_min:02d}")
        time.sleep(wait_time)
    else:
        logger.info(f"⏱ Current minute {current_min} outside range {start_minute}-{end_minute}, continuing")

# ---------------------------
# Meetup API Functions
# ---------------------------
def get_group_events(session_name):
    query = """
    query ($urlname: String!) {
      groupByUrlname(urlname: $urlname) {
        events(first: 25) {
          edges {
            node { id title dateTime }
          }
        }
      }
    }
    """
    variables = {"urlname": session_name}
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    resp = session.post(MEETUP_API_URL, json={"query":query,"variables":variables}, headers=headers)
    resp.raise_for_status()
    events = resp.json()["data"]["groupByUrlname"]["events"]["edges"]
    logger.debug(f"Retrieved {len(events)} events")
    return events

def find_next_event(events, day_of_week, partial_title, drift_seconds=0.0, min_days_from_now=0):
    today = now_corrected(drift_seconds)
    start_date = today + timedelta(days=min_days_from_now)
    days_map = {"mon":0,"tue":1,"wed":2,"thu":3,"fri":4,"sat":5,"sun":6}
    target_day = days_map.get(day_of_week.lower())
    if target_day is None:
        raise ValueError(f"Invalid day_of_week: {day_of_week}")

    weekday_events = []
    for event in events:
        node = event["node"]
        dt = parse_iso_datetime(node["dateTime"]).astimezone(timezone.utc)
        if partial_title.lower() in node["title"].lower() and dt.weekday()==target_day and dt>=start_date:
            weekday_events.append((dt,node))

    if not weekday_events: return None
    weekday_events.sort(key=lambda x:x[0])
    return weekday_events[0][1]

def rsvp_event(event_id, venue_id=None):
    input_data = {"eventId":event_id,"response":"YES","proEmailShareOptin":False,"guestsCount":0,"eventPromotionId":"0"}
    if venue_id: input_data["venueId"]=venue_id
    query={"operationName":"rsvpToEvent","variables":{"input":input_data},"extensions":{"persistedQuery":{"version":1,"sha256Hash":"d73f3044c4ef90143cb5f1380f7c665a295a997a14a9a21f345a288f55d9cee8"}}}
    headers = {"Authorization":f"Bearer {ACCESS_TOKEN}"}
    resp = requests.post(MEETUP_API_URL,json=query,headers=headers)
    resp.raise_for_status()
    return resp.json()

# ---------------------------
# Main Function
# ---------------------------
def main():
    logger.info("=== Meetup Booking Script Started ===")
    drift_seconds = get_ntp_drift()
    start_time = now_corrected(drift_seconds)
    end_time = start_time + timedelta(minutes=TIMEOUT_MINUTES)
    logger.info(f"NTP drift: {drift_seconds:+.6f}s")

    parser = argparse.ArgumentParser(description="Book a meetup event")
    parser.add_argument('--club_name', required=True)
    parser.add_argument('--day_in_week', required=True)
    parser.add_argument('--session_name', required=True)
    parser.add_argument('--interval_seconds', type=int, default=5)
    parser.add_argument('--min_days_from_now', type=int, default=0)
    args = parser.parse_args()

    try:
        events = get_group_events(args.club_name)
        next_event = find_next_event(events,args.day_in_week,args.session_name,drift_seconds,args.min_days_from_now)
        if not next_event:
            logger.info("No matching event found.")
            return

        logger.info(f"Booking event: {next_event['title']} at {next_event['dateTime']}")
        wait_until_minute_range_target_time(55,59,target_minute=0,margin_seconds=0.1,drift_seconds=drift_seconds)

        attempts=0
        while attempts<MIN_ATTEMPTS or (now_corrected(drift_seconds)<end_time and attempts<MAX_ATTEMPTS):
            attempts+=1
            logger.info(f"Attempt {attempts} to RSVP...")
            if DRY_RUN:
                logger.info(f"[DRY RUN] Would RSVP to {next_event['id']}")
                result={"data":{"rsvp":{"rsvp":{"status":"DRY_RUN"},"errors":[]}}}
            else:
                result = rsvp_event(next_event["id"])
            rsvp_data = result.get("data",{}).get("rsvp",{})
            rsvp_info = rsvp_data.get("rsvp")
            errors = rsvp_data.get("errors") or []
            rsvp_status = rsvp_info.get("status") if rsvp_info else None
            logger.info(f"RSVP status: {rsvp_status}")
            too_few_spots = any(err.get("code")=="too_few_spots" for err in errors)
            if too_few_spots:
                logger.warning(f"Too few spots, retrying in {args.interval_seconds}s...")
                time.sleep(args.interval_seconds)
            else:
                logger.info(f"RSVP result: {result}")
                break
        else:
            logger.error(f"RSVP failed after {attempts} attempts or timeout reached.")

    except Exception as e:
        logger.exception(f"Error: {e}")

    elapsed = now_corrected(drift_seconds)-start_time
    logger.info(f"=== Script Finished | Elapsed time: {elapsed} ===")

if __name__=="__main__":
    main()
