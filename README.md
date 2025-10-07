# Meetup RSVP Bot

Automates RSVPs for Meetup events, specifically for badminton or similar clubs.

## Features

- Fetch events from a Meetup group
- Filter events by day of week and partial session name
- Optionally wait for RSVP opening time
- Retry logic for full events
- Supports DRY_RUN mode for testing

## Setup

1. Clone the repo:

```bash
git clone https://github.com/yourusername/meetup_rsvp.git
cd meetup_rsvp
```

2. Create a Python virtual environment:

```bash
python3 -m venv venv
```

3. Activate the virtual environment:

- **Linux/macOS:**

```bash
source venv/bin/activate
```

- **Windows (Command Prompt):**

```cmd
venvScriptsactivate.bat
```

- **Windows (PowerShell):**

```powershell
venvScriptsActivate.ps1
```

4. Install dependencies:

```bash
pip install requests python-dotenv ntplib
```

5. Create a `.env` file:

```
ACCESS_TOKEN=your_meetup_api_token
MEETUP_API_URL=https://api.meetup.com/graphql
DRY_RUN=False
```

---

## Usage

Run the script **inside the activated virtual environment**:

```bash
python meetup_api_rsvp.py --club_name "someclub" --day_in_week "wed" --session_name "session-name"
```

Or without activating the venv:

```bash
./venv/bin/python meetup_api_rsvp.py --club_name "someclub" --day_in_week "wed" --session_name "session-name"
```

### Optional flags

- `--interval_seconds` Retry interval in seconds (default: 5)  
- `--min_days_from_now` Skip events occurring sooner than N days (default: 0)

---

## Deactivate the virtual environment

After running:

```bash
deactivate
```

