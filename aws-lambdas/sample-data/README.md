# Sample data recovered before teardown

`subscriptions_2025-12-30_22-28-40.json` is the last output of
`youtube-subscriptions` (Lambda `youtube-subscription-fetcher-sls`), pulled from
`s3://youtube-digest/all-subscriptions/` on 2026-10-31 just before that bucket was
emptied and deleted.

It is the full subscription list for the account, in the shape the orphaned S3 leg
of the pipeline produced — nothing downstream ever read it; it existed for a human
to hand-pick channels from into `scoped_subscriptions.json`.

The bucket held four dumps, all from 2025-12-30 (44 B, 1.3 KB, 52.7 KB, 52.7 KB).
This is the newest. The two 52.7 KB files were identical in size; the earlier two
were partial runs.

Regenerable at any time by running `../../subscriptions.py` from the prototype.
