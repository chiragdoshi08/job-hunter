# Job Hunter

A local job-search agent powered by your ChatGPT sign-in. It discovers vacancies, checks fit against your profile, prepares an application record, reads employer forms, and fills the reviewed answers and exact PDF. It saves its progress and continues other applications when one needs your help.

**Version 0.3.0.** Automatic native Google Docs CV preparation, verified account résumé recovery, optional Android alerts and a Windows installer are included. The complete submission flow is tested against a synthetic employer. Individual employer workflows still require validation; the app does not claim universal site support. Uploaded baseline résumés retain their original wording.

## Download and start

For Apple Silicon Macs, download the Mac ZIP from Releases, unzip it, and open `Job Hunter.app`. On Windows, download and run the Setup EXE; it installs for your user without requiring administrator access. The bundle includes Python, Chromium and the official open-source Codex CLI. The Mac build is not Apple-notarized and the Windows installer has no publisher signing certificate. If macOS blocks it, use System Settings → Privacy & Security → Open Anyway after checking the release checksum. Do not disable system security settings globally.

In **Agent setup**:

1. Sign in with ChatGPT and run the connection check. It verifies a real model response.
2. Upload a reviewed résumé PDF for your selected role, or select a native Google Docs master and template. For native documents, connect Google Drive in ChatGPT Apps and press **Check Drive** and **Capture master profile** in Agent setup.
3. Save your job preferences, including location and work eligibility.
4. Run the browser/upload check. Open job sites in the dedicated agent browser and sign in there.
5. Press **Start agent**. Review applications, missing answers and documents as they appear.

The app runs on your computer at a loopback address, starting at port 8766. Keep the computer awake and online. Closing the app's browser page does not stop workers; use Pause or the stop launcher. To resolve a login, verification code or CAPTCHA from an Android phone, control the same Mac through your configured remote desktop, complete the step in the Job Hunter browser, then Resume.

## Review and submit

The agent stops for missing facts instead of inventing salary, sponsorship, specialised experience or consent. Confirmed reusable answers are matched locally with their context, choices and expiry. Each application keeps fixed answer and document snapshots.

Approve filling after reviewing the destination, email, PDF versions and answers. Submission is a separate application-specific action. An exact employer hostname must be enabled with its observed confirmation phrase before automatic submission. This is user-reviewed configuration, not platform certification. A receipt from that hostname is required for Submitted status. If a response is uncertain or the app restarts after the final action, it requires verification before another attempt.

For account-wide résumé sites such as iimjobs, Hirist and Naukri, configure the exact original download and upload controls in Agent setup. The worker saves the original PDF before replacement, verifies the replacement bytes, and restores and re-downloads the original after the step. A failed restoration pauses that account and exposes **Restore original résumé**. This flow is verified with a real browser fixture; each actual job-board account needs its own control review. Sites that transform uploaded PDFs or need extra save steps may require an adapter.

## Your data

A fresh installation contains no candidate names, CVs, private document IDs, accounts, browser sessions or application history. Runtime data is outside the download:

- macOS: `~/Library/Application Support/Job Hunter/data`
- Windows: `%LOCALAPPDATA%/Job Hunter/data`
- Linux: `${XDG_DATA_HOME:-~/.local/share}/Job Hunter/data`

Existing installations with `data/shared.sqlite` retain that original location. `JOB_HUNTER_DATA` can explicitly select a private data directory. Backups contain tracker databases, fixed documents and original résumés needed for recovery; they exclude browser profiles, passwords, ChatGPT credentials and browser connection tokens. You must sign in again after restoring onto a new machine. The model receives the profile, job description and observed page data necessary for its step; this is not an offline AI model.

## Run from source

Install Python 3.10 or newer and [Codex CLI](https://learn.chatgpt.com/docs/cli). On a Mac, open `Install Job Hunter.command`, then `Launch Job Hunter.command`. On Windows, use `Launch Job Hunter.bat`. The Windows bundle, silent installer and uninstaller are tested on a GitHub-hosted Windows runner, including a real bundled Chromium upload.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python launch.py
```

The source installer uses pinned Python dependencies. The Mac bundle includes the tested runtimes. GitHub Actions runs isolation, recovery, answer-bank, HTTP and real local-browser tests. To run acceptance tests locally:

```sh
JOB_HUNTER_BROWSER_TESTS=1 .venv/bin/python -m unittest discover -s tests -q
python3 scripts/privacy_check.py
```

No acceptance test sends a real employer application. A live ChatGPT connection check uses plan allowance. The supported [non-interactive Codex interface](https://learn.chatgpt.com/docs/non-interactive-mode) provides structured model decisions. Native document operations use the official [app-server interface](https://learn.chatgpt.com/docs/app-server) and your existing connected Google Drive app. This connection is checked independently from model sign-in. Job Hunter owns its browser session and action validation.

## Current limits

- A login, account creation requiring agreement, MFA or CAPTCHA can require human takeover.
- Some sites block automation, hide fields inside custom widgets, or use complex multi-step forms. These require further site-specific testing/adapters.
- Native CV work runs independently from browser tasks, makes a full template copy, checks profile facts, preserves native formatting, exports PDF and inspects every page. A failed fact or layout check saves progress for correction; it cannot silently fall back to a baseline.
- Optional phone alerts use ntfy. Enable them in Agent setup and subscribe to the private topic in the Android ntfy app. Alerts contain generic status messages, not candidate or employer details. Delivery depends on your network and Android notification settings. The topic is private bearer access; keep it secret.
- Apple notarization and a signed automatic updater are not included. Signing requires the release owner’s Developer ID certificate; no certificate was available for this release.
- This app cannot override an AI tool's enforced permission denial or a site's access restriction.

See [CHANGELOG](CHANGELOG.md), the [blocker-by-blocker repair status](docs/BLOCKERS.md), and [acceptance evidence](docs/VALIDATION.md). Contributions should improve real workflow reliability, with explicit capability evidence rather than claims of universal support.
