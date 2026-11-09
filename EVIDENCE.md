# Public contribution and reproduction guide

Author identity: [Caledvwlch](https://github.com/Caledvwlch). Prepared November 10, 2026 with AI assistance.

The strongest evidence here is an accepted change to an existing project, followed by a fresh reproduction using its actual source. The separate Python lab is an educational extension.

| Read in this order | What it establishes |
| --- | --- |
| [OpenCodex PR #7621](https://github.com/lidge-jun/opencodex/pull/7621) and its [integration record](https://github.com/lidge-jun/opencodex/pull/7621#issuecomment-6423576279) | Submitted authorization-boundary changes, regression tests, and upstream acceptance. |
| [OpenCodex v2.93.0](https://github.com/lidge-jun/opencodex/releases/tag/v2.93.0) | Public release notes credit `@Caledvwlch` for #7621 and #7622. |
| [Post-revocation technical report](POST_REVOCATION_REPORT.md) | Retrospective report of the accepted fix, exact release-source comparison, controlled reproduction, and narrow impact. This is self-published, not a CVE/GHSA or vendor-issued advisory. |
| [Engineering case study](CASE_STUDY.md) | The defect mechanism, original contribution versus maintainer integration, and the distinction between historical code and the new lab. |
| [Pinned upstream replay](UPSTREAM_REPLAY.md) | Same revocation test against unchanged pre-fix and accepted source: two normal controls pass on both, four revocation checks fail before and pass afterward. |
| [Python lab and run instructions](README.md) | Offline examples of revalidation after asynchronous waits, account-generation changes, replay accounting, and scoped retry holds. |
| [Companion PR #7622](https://github.com/lidge-jun/opencodex/pull/7622) and its [integration record](https://github.com/lidge-jun/opencodex/pull/7622#issuecomment-6426939827) | Unavailable-credit and scoped-retry work, including a clearly attributed maintainer correction. |

The actual upstream replay uses mocked HTTP and synthetic credentials. The lab has no network transport. Neither exercise demonstrates a real-account compromise, paid model call, production race frequency, or general security certification. This repository does not imply an upstream maintainer appointment, CVE, bounty, vendor-issued advisory or approval by a cyber-access program.
