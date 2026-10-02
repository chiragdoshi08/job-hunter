# Job Hunter

A local job-search agent powered by your ChatGPT sign-in. It discovers vacancies, checks fit against your profile, prepares an application record, reads employer forms, and fills the reviewed answers and exact PDF. It saves its progress and continues other applications when one needs your help.

**Preview release.** The complete submission flow is verified against a local synthetic employer. Generic employer automation is not certified across LinkedIn, Workday, Greenhouse, Lever, Hirist or iimjobs. Native Google Docs tailoring remains a connected desktop workflow. Uploaded résumés retain their original layout and wording; the app does not claim they were tailored.

## Download and start

For Apple Silicon Macs, download the Mac ZIP from Releases, unzip it, and open `Job Hunter.app`. The bundle includes Python, Chromium and the official open-source Codex CLI. This preview is not Apple-notarized. If macOS blocks it, use System Settings → Privacy & Security → Open Anyway after checking the release checksum. Do not disable system security settings globally.

In **Agent setup**:

1. Sign in with ChatGPT and run the connection check. It verifies a real model response.
2. Upload a reviewed résumé PDF for your selected role, or retain an existing native master/template.
3. Save your job preferences, including location and work eligibility.
4. Run the browser/upload check. Open job sites in the dedicated agent browser and sign in there.
5. Press **Start agent**. Review applications, missing answers and documents as they appear.

The app runs on your computer at a loopback address, starting at port 8766. Keep the computer awake and online. Closing the app's browser page does not stop workers; use Pause or the stop launcher. To resolve a login, verification code or CAPTCHA from an Android phone, control the same Mac through your configured remote desktop, complete the step in the Job Hunter browser, then Resume.

## Review and submit

The agent stops for missing facts instead of inventing salary, sponsorship, specialised experience or consent. Confirmed reusable answers are matched locally with their context, choices and expiry. Each application keeps fixed answer and document snapshots.

Approve filling after reviewing the destination, email, PDF versions and answers. Submission is a separate application-specific action. An exact employer hostname must be enabled with its observed confirmation phrase before automatic submission. This is user-reviewed configuration, not platform certification. A receipt from that hostname is required for Submitted status. If a response is uncertain or the app restarts after the final action, it requires verification before another attempt.

For account-wide résumé sites such as iimjobs, use the existing desktop workflow and preserve/verify the original résumé before any swap. The generic worker does not implement account-wide résumé replacement.

## Your data

A fresh installation contains no candidate names, CVs, private document IDs, accounts, browser sessions or application history. Runtime data is outside the download:

- macOS: `~/Library/Application Support/Job Hunter/data`
- Windows: `%LOCALAPPDATA%/Job Hunter/data`
- Linux: `${XDG_DATA_HOME:-~/.local/share}/Job Hunter/data`

Existing installations with `data/shared.sqlite` retain that original location. `JOB_HUNTER_DATA` can explicitly select a private data directory. Backups contain tracker databases and fixed documents; they exclude browser profiles, passwords, ChatGPT credentials and browser connection tokens. You must sign in again after restoring onto a new machine. The model receives the profile, job description and observed page data necessary for its step; this is not an offline AI model.

## Run from source

Install Python 3.10 or newer and [Codex CLI](https://learn.chatgpt.com/docs/cli). On a Mac, open `Install Job Hunter.command`, then `Launch Job Hunter.command`. On Windows, use `Launch Job Hunter.bat`. Windows source execution has not been tested on a Windows machine.

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

No acceptance test sends a real employer application. A live ChatGPT connection check uses plan allowance. The supported [non-interactive Codex interface](https://learn.chatgpt.com/docs/non-interactive-mode) provides structured model decisions; your ChatGPT sign-in does not automatically grant this application the desktop app's browser or Drive tools. Job Hunter owns its browser session and action validation.

## Current limits

- A login, account creation requiring agreement, MFA or CAPTCHA can require human takeover.
- Some sites block automation, hide fields inside custom widgets, or use complex multi-step forms. These require further site-specific testing/adapters.
- Native Google Docs template creation and visual CV review use the connected Codex desktop workflow. A native template cannot be silently replaced by an uploaded baseline.
- No remote notification service, signed updater, Apple notarization, or fully verified Windows installer is included in this preview.
- This app cannot override an AI tool's enforced permission denial or a site's access restriction.

See [CHANGELOG](CHANGELOG.md), the [blocker-by-blocker repair status](docs/BLOCKERS.md), and [acceptance evidence](docs/VALIDATION.md). Contributions should improve real workflow reliability, with explicit capability evidence rather than claims of universal support.
