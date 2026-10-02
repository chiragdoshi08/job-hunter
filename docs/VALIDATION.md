# Validation

On 2 October 2026, 154 tests passed on an Apple Silicon Mac with Python 3.14.4, Playwright 1.63.0 and pypdf 6.19.0. The suite includes six real local-browser tests.

Verified acceptance flow: import synthetic résumé → immutable profile/PDF → prepare → capture live questions → reuse confirmed email → confirm consent → approve fill → enter fields and upload exact PDF → approve submit → reserve one attempt → observe employer fixture confirmation → mark Submitted → reject another submission.

Also covered: role isolation, expiry/context-aware answer reuse, immutable documents and approval hashes, ambiguous fields, login handover, task cancellation, page-change detection, multiple browser pages, recovery of scan tasks, retained multi-page questions, destination configuration, cross-host confirmation rejection, and backup integrity, packaged native-task CLI routing, and employer-bound native submission confirmation.

A real structured request completed through an existing ChatGPT-authenticated Codex session. This proves that inference ran, not merely that credentials were present. It does not certify every employer or a fresh third-party user's sign-in.

No real employer application was submitted during validation. Employer-specific support, native Google Docs automation, Windows execution, notarization and notifications remain outside the verified coverage. The existing production installation was backed up and migrated without changing job, application, document, answer or profile counts.

The packaged Apple Silicon app launched with empty isolated data. Its own API verified ChatGPT authentication, a real structured model response using the bundled official Codex CLI, and a real local upload using bundled Chromium. Its code signature was verified as valid ad hoc; the app is not Apple-notarized. Desktop and 390px phone layouts had no page errors or horizontal overflow.

A read-only inspection of a live Lever employer application captured its visible questions, including custom compensation and notice-period fields. No private candidate data was entered and no employer application was submitted. This establishes scanner behavior on that page, not complete platform certification.
