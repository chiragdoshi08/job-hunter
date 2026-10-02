# Blockers and repair status

This records the product problems behind the redesign. Implementation and acceptance evidence are kept separate from employer-specific certification.

| Blocker | Repair | Remaining limit |
| --- | --- | --- |
| Queued work repeatedly required a new chat and manual Send | Local observe/decide/act worker runs browser tasks automatically through structured Codex decisions | Native connected document tools still use a desktop handoff |
| ChatGPT credentials were treated as proof the model worked | Setup verifies an actual structured model response through subscription sign-in | A new user's account must complete its own connection check |
| Browser extension/profile permissions interrupted applications | Dedicated local browser and persistent sessions, plus a real upload check | Site authentication, MFA and access restrictions still apply |
| One blocked application stopped progress | Per-application pages, saved blockers, leases and independent continuation | Unknown answers require candidate review |
| Form questions disappeared or labels were unreadable | Multi-page questions are retained; standard and visual labels are captured; ambiguity blocks filling | Custom widgets and platform-specific forms need adapters |
| Approved answers or PDFs changed before entry | Fixed versions, hashes and exact manifests are checked before acting | Changed pages or documents require another review |
| Filling could accidentally trigger a final action | Final actions are prohibited during fill; submit uses a distinct approval and reserved attempt | Generic action detection is tested locally, not certified on every employer |
| Uncertain submission could be repeated or marked complete without evidence | One attempt is reserved, an employer-bound confirmation is required, and uncertainty requires verification | Employer-specific confirmation behavior must be reviewed |
| Account-wide résumé swaps risked overwriting the original | Generic writes to these sites are blocked; the dedicated workflow requires a recoverable original | Automated swapping/restoration is not implemented in this preview |
| Native CV requirements could be bypassed by a generic upload | Required native template and page policies remain enforced; native workflow gets the existing tracker and bundled CLI | Portable automatic native Google Docs tailoring remains unfinished |
| Installation depended on development folders and private candidate defaults | Apple Silicon bundle includes runtimes; new-user PDF onboarding; runtime data lives separately; public source excludes personal data | Apple notarization, signed updates and verified Windows packaging remain unfinished |
| Phone handover was unclear | Resolve the same Mac browser through remote desktop, then Resume the saved task | The Mac must remain awake and connected; no remote notification service is included |
| Migration could lose records or resume old approvals | Backup before code replacement; counts checked; historical work remains paused | Review saved tasks before resuming an old run |

## Release scope

Version 0.2.0 is a preview. A synthetic employer verifies the complete upload, fill, approval, submission and recovery path. A live employer page was inspected read-only. No real employer application was submitted as a release test.

The remaining work is to implement portable native document integration, test individual employer and job-board adapters against their real workflows, implement verified account-wide résumé restoration where needed, and complete distribution/signing and remote notifications. The tool must not advertise universal or flawless application support before those paths have evidence.

See [validation](VALIDATION.md) and [setup instructions](../README.md).
