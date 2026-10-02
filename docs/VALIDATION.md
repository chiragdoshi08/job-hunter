# Validation

On 2 October 2026, 177 regression tests passed on Apple Silicon with Python 3.14.4, Playwright 1.63.0, pypdf 6.19.0 and pypdfium2 5.13.0. The suite includes 10 real browser tests. The final suite also covers native default-style normalization, source-quote whitespace, safe fragment deletion and uncertain receipt recovery.

Verified acceptance flow: import synthetic résumé → immutable profile/PDF → prepare → capture questions → review answers → approve fill → upload exact PDF → approve submit → reserve one attempt → observe configured employer receipt → Submitted → reject duplicate submission.

Real browser coverage also includes separate application pages, stale DOM, readable Lever labels, hidden file controls, custom ARIA dropdowns, CAPTCHA/password redaction and an account résumé swap/verification/restoration without destroying the application page. Failure tests verify recovery after a crash or failed original restoration, account pausing, durable alert retries and duplicate suppression.

## Native documents

The official app-server connected to the existing Google Drive app. A full native template copy was edited through revision-controlled requests, preserving page geometry, paragraph styles, bullet lists and local text styling. Edited claims were audited against a fixed captured profile. A real Strategy CV passed the two-page/lower-content PDF gate and visual inspection of both rendered pages. The source template was never edited. Rejected evidence, provider requests and underfilled layouts exposed real defects that were corrected and retained as regression coverage.

A real AI CV also passed the one-page A4 gate and visual inspection. Testing exposed Google Docs’ protected final newline and bullet-font inheritance; both were repaired. The one-page AI policy is independently enforced. A rejected factual or layout check cannot register a prepared document. Native document work runs separately from the browser worker and saves the copy, plan and revision checkpoints.

## Installers

The Windows installer pipeline runs the complete suite, builds the bundle, starts its executable with empty isolated data, connects to its local API, performs a bundled Chromium upload, stops it, silently installs it, repeats the installed executable smoke check, and uninstalls. [Windows acceptance run](https://github.com/chiragdoshi08/job-hunter/actions/runs/37036870906) passed for the preceding implementation; the final release is built by the same checks on its final code commit.

The Apple Silicon app is built with bundled Codex, Python, Chromium and PDF renderer. Its package is checked for valid ad hoc code signing and smoke-tested for independent service launch, clean role data, browser upload and graceful stop. It is not Apple-notarized: this Mac had zero Developer ID signing identities. Windows publisher signing is also not included.

## Practical limits

Live Lever, Greenhouse and Ashby forms were inspected read-only and their candidate questions captured. Greenhouse’s hidden validation input was being mistaken for a second country question; it is now excluded, and the selected React dropdown value is read from its visible label. A visible CAPTCHA on that page still requires human completion. This proves scanning on that page, not complete platform certification. No actual employer application is submitted as a release test. Original account résumé restoration is browser-fixture tested; each real account requires reviewed controls. Email TLS ordering, SMTP acceptance, credential rejection, protected configuration and backup exclusion are covered by tests. Actual inbox delivery requires user-provided email credentials and a test alert; it is not claimed before those steps. Android delivery also requires notification permission. No ntfy topic was enabled without the user’s choice.

The existing installation was backed up and upgraded. All 171 jobs, 26 applications, 24 historical documents, 188 answers and three profiles were preserved. Both roles passed all-screen UI checks with no page errors and no horizontal overflow at a 390px mobile viewport. Historical approvals do not automatically authorize new submissions.
