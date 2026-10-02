# Blockers and repair status

| Blocker | Repair | Remaining requirement |
| --- | --- | --- |
| Browser work needed repeated chat handoffs | Local observe/decide/act worker; saved tasks start from the app | A site can still require login or human verification |
| Native CV preparation needed a separate chat | Connected Drive operations, fixed profile, full native copy, factual audit, revision-safe writes, PDF and visual checks | Google Drive must be connected; rejected claims or layout need correction |
| Long CV work blocked the browser | Independent document and browser workers | Each browser/account remains serialized |
| Credentials did not prove inference worked | Real structured model response in setup | Each new user signs in and completes the check |
| One blocked application stopped other work | Application pages, saved checkpoints, leases and independent continuation | Unknown facts require review |
| Hidden uploads/custom dropdowns were missed | Hidden file controls and exact ARIA option capture | Complex employer-specific widgets still need testing |
| Approvals could become stale | Fixed PDF/profile/job versions, manifests and hashes | Changed data requires another review |
| Filling could trigger final submission | Separate submit approval and reserved attempt | Exact destination and confirmation text must be reviewed |
| Delayed receipt or crash risked resubmission | Uncertain attempt journal and employer-bound receipt recheck | Absent receipt requires status verification |
| Account résumé replacement risked losing the original | Download and journal first; verify replacement; restore and verify; pause on failure and offer recovery | Review real account controls; transformed PDFs or extra save steps need an adapter |
| Download relied on developer files | Bundled Mac app and Windows installer; no candidate defaults | Mac notarization and publisher signing need owner certificates |
| Windows paths and subprocess handling failed | Portable ZIP paths, native ACLs, pipe event reader, detached service and graceful stop | Windows installer acceptance runs in CI |
| Phone handover was unclear | Optional email or ntfy alerts, remote desktop to the same browser, Resume | Configure email credentials or the private topic and allow Android notifications; computer stays awake/online |
| Upgrade could damage history | Backup first; replace code only; compare tracker counts | Review saved historical applications before resuming |

## Evidence and limits

The local browser suite checks upload, fill, separate approvals, receipt, duplicate protection, custom dropdowns and exact original résumé restoration. Windows CI checks the packaged executable, silent installation and uninstall. These tests do not certify every live employer or account. No real employer submission is sent as a release test.

See [validation](VALIDATION.md) and [setup](../README.md).
