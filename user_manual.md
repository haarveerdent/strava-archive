# Strava YAML Archive Utility — User Manual

A zero-cost system to sync your Strava activities into a YAML archive and view them via a GitHub Pages dashboard.

---

## Prerequisites

- A [Strava](https://www.strava.com) account with activities
- A [GitHub](https://github.com) account
- Python 3.x installed locally (for initial setup and local testing)
- Git installed locally

---

## Phase 1: Strava API Setup

### 1.1 Create a Strava API Application

1. Go to [https://www.strava.com/settings/api](https://www.strava.com/settings/api)
2. Fill in the form:
   - **Application Name:** anything (e.g. `MyStravaArchive`)
   - **Category:** choose any
   - **Website:** `http://localhost` (placeholder)
   - **Authorization Callback Domain:** `localhost`
3. Click **Create** and note your **Client ID** and **Client Secret**

### 1.2 Authorize and Obtain Your Refresh Token

This is a one-time manual step.

**Step 1 — Build the authorization URL** and open it in your browser:

```
https://www.strava.com/oauth/authorize?client_id=YOUR_CLIENT_ID&response_type=code&redirect_uri=http://localhost/exchange_token&approval_prompt=force&scope=read,activity:read_all
```

Replace `YOUR_CLIENT_ID` with your actual Client ID.

**Step 2 — Authorize the app.** After clicking "Authorize", your browser will redirect to a URL like:

```
http://localhost/exchange_token?state=&code=AUTHORIZATION_CODE&scope=read,activity:read_all
```

Copy the `AUTHORIZATION_CODE` from the URL.

**Step 3 — Exchange the code for a refresh token** using curl or any HTTP client:

```bash
curl -X POST https://www.strava.com/oauth/token \
  -d client_id=YOUR_CLIENT_ID \
  -d client_secret=YOUR_CLIENT_SECRET \
  -d code=AUTHORIZATION_CODE \
  -d grant_type=authorization_code
```

The response JSON will contain a `refresh_token`. **Save this value — you will not see it again.**

---

## Phase 2: Repository Setup

### 2.1 Create Your GitHub Repository

1. Go to [https://github.com/new](https://github.com/new)
2. Name it (e.g. `strava-archive`)
3. Choose **Public** (required for free GitHub Pages) or Private (requires GitHub Pro for Pages)
4. Do not initialize with a README — you'll push the files yourself

### 2.2 Clone and Push the Project

```bash
git clone https://github.com/YOUR_USERNAME/strava-archive.git
cd strava-archive
# Copy all project files into this directory
git add .
git commit -m "Initial commit"
git push origin main
```

### 2.3 Add GitHub Secrets

Navigate to your repo on GitHub: **Settings → Secrets and variables → Actions → New repository secret**

Add each of the following:

| Secret Name | Value |
|---|---|
| `STRAVA_CLIENT_ID` | Your numeric Client ID |
| `STRAVA_CLIENT_SECRET` | Your Client Secret string |
| `STRAVA_REFRESH_TOKEN` | The refresh token from Phase 1 |

> **Security note:** Never commit these values to your repository. The `.gitignore` already excludes `.env` files.

---

## Phase 3: Local Development Setup

```bash
# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate      # macOS/Linux
venv\Scripts\activate         # Windows

# Install dependencies
pip install requests PyYAML python-dotenv
```

Create a `.env` file in the project root for local use (already excluded by `.gitignore`):

```env
STRAVA_CLIENT_ID=your_client_id
STRAVA_CLIENT_SECRET=your_client_secret
STRAVA_REFRESH_TOKEN=your_refresh_token
```

---

## Phase 4: Running the Sync Script

### Full historical sync (first run)

```bash
python sync_activities.py
```

If `activities.yaml` is empty or missing, the script fetches all historical data.

### Incremental sync (default)

```bash
python sync_activities.py
```

The script reads the most recent date in `activities.yaml` and fetches only newer activities.

### Custom date range

```bash
python sync_activities.py --start 2024-01-01 --end 2024-03-31
```

---

## Phase 5: GitHub Actions Automation

The workflow file at `.github/workflows/sync_strava.yml` runs on manual trigger.

### Running a sync from GitHub

1. Go to your repo → **Actions** tab
2. Select **Sync Strava Activities**
3. Click **Run workflow**
4. Optionally enter `start_date` and/or `end_date` (YYYY-MM-DD format)
5. Click **Run workflow**

The action will sync activities and automatically commit the updated `activities.yaml` to your repo.

---

## Phase 6: Dashboard (GitHub Pages)

### Enable GitHub Pages

1. Go to **Settings → Pages**
2. Under **Source**, select **Deploy from a branch**
3. Choose `main` branch, `/ (root)` folder
4. Click **Save**

Your dashboard will be live at:
```
https://YOUR_USERNAME.github.io/strava-archive/
```

---

## activities.yaml Format

Activities are stored grouped by date:

```yaml
2024-03-15:
  - id: 11234567890
    name: "Morning Run"
    sport_type: "Run"
    distance_km: 8.42
    moving_time_sec: 2580
    elevation_gain_m: 45.0
```

---

## Troubleshooting

**Workflow fails with auth error**
- Double-check that all three secrets are set correctly in GitHub
- Refresh tokens can expire if unused for 6+ months — repeat Phase 1.3 to get a new one

**No new activities appear**
- Ensure the activity is marked as public (or that `activity:read_all` scope was granted)
- Check the workflow logs under the **Actions** tab for API errors

**GitHub Pages shows a blank page**
- Confirm Pages is enabled and pointing to the correct branch/folder
- Check browser console for JS errors (likely a path issue fetching `activities.yaml`)

**Rate limit errors**
- Strava allows 100 requests per 15 minutes and 1000 per day
- For large historical syncs, re-run the workflow the next day to continue

---

## Security Checklist

- [ ] `.env` is listed in `.gitignore` and never committed
- [ ] All secrets are stored in GitHub Secrets, not in code
- [ ] Repository does not contain any hardcoded tokens or credentials
- [ ] `[skip ci]` is used in bot commit messages to prevent workflow loops
