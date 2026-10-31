# AWS Lambda pipeline — RETIRED

This folder is an **archive**. Nothing in it is deployed.

These five Lambda services were the AWS deployment of the YouTube digest. They ran
in `us-west-2` on a daily schedule until **2026-10-31**, when the project was
retired: every Lambda was removed with `serverless remove` and the supporting
Terraform resources were deleted from `my-aws-infrastructure`.

The code is kept here verbatim so the project can be revisited or rebuilt.

## Where this came from

| | |
|---|---|
| Source repo | `ssilambarasan/applications` |
| Source commit | `3c2eab3a75579561337be7c4d23da0923e20e5f3` (branch `Adding-Chrome-Extensions`) |
| Source paths | `applications/youtube-*` (five directories, moved here as-is) |
| Infra repo | `ssilambarasan/my-aws-infrastructure` — see `terraform-snapshot/` |

Build artifacts (`__pycache__`, `.serverless`, `node_modules`) were stripped. Nothing
else was changed: these files are exactly what was deployed, defects included.

## Relationship to the local prototype

The parent folder of this repo holds a **different, more capable implementation** that
runs on a laptop against Google APIs directly. It is not the same code, and the AWS
version is not a port — it is a reimplementation that lost features:

| | local prototype (`../main.py`) | these Lambdas |
|---|---|---|
| AI summaries | Gemini 2.5 Flash via Vertex AI | **none** |
| Shorts vs long split (≤180 s) | yes | **none** |
| Video links | yes | **none** |
| Per-channel counts | yes | **none** |
| Lookback window | 3 days | latest batch only |
| Output | rich HTML (see `../screenshots-gifs/`) | plain `<ul>` of titles by channel |

If you revive anything, revive the prototype's summarisation. It never existed in AWS.

## The pipeline as it actually ran

```
[manual] edit youtube-playlist-fetcher/utils/scoped_subscriptions.json
         (29 KB, baked INTO the Lambda zip -> changing channels needed a REDEPLOY)
    |
youtube-playlist-fetcher   (manual invoke)    -> adds uploads_playlist_id
                                              -> scoped_channels table
    |
youtube-payload-generator  (cron 01:00 UTC)   -> reads scoped_channels
                                              -> SQS pull-youtube-videos-by-channel-sqs
    |
youtube-fetch-videos       (SQS, batchSize 1) -> YouTube Data API
                                              -> all_uploaded_videos table
    |
youtube-digest-emailer     (cron 01:30 UTC)   -> latest batch_id -> HTML
                                              -> Gmail SMTP (self-send)

ORPHAN: youtube-subscriptions (manual invoke)
        -> writes every subscription to s3://youtube-digest/all-subscriptions/
        -> nothing read it; it existed for a human to hand-pick channels from
```

### Deployed names

| Directory | Service name | Lambda | CFN stack | Trigger |
|---|---|---|---|---|
| `youtube-subscriptions` | `youtube-subscriptions` | `youtube-subscription-fetcher-sls` | `youtube-subscriptions-prod` | manual |
| `youtube-playlist-fetcher` | `youtube-playlistid` | `youtube-playlistid-fetcher-sls` | `youtube-playlistid-prod` | manual |
| `youtube-payload-generator` | `youtube-payload-generator` | `youtube-payload-generator-sls` | `youtube-payload-generator-prod` | `cron(0 1 * * ? *)` |
| `youtube-fetch-videos` | `youtube-fetch-videos` | `youtube-fetch-videos-sls` | `youtube-fetch-videos-prod` | SQS, batchSize 1 |
| `youtube-digest-emailer` | `youtube-digest-emailer` | `youtube-digest-emailer-sls` | `youtube-digest-emailer-prod` | `cron(30 1 * * ? *)` |

Note the directory name and the service name differ for `youtube-playlist-fetcher`.

## Known defects at time of retirement

These were **not fixed** — the project was retired, not repaired. Fix them before any
redeployment.

1. **Changing channels requires a code deploy.** `youtube-playlist-fetcher/utils/helpers.py:82`
   reads `Path(__file__).parent / 'scoped_subscriptions.json'`, a 29 KB file inside the
   deployment package. The prototype's manual "edit the file" step was frozen into the
   artifact. `scoped_channels` already has the right columns to hold this instead.
2. **An empty batch re-sends yesterday's digest.** The emailer selects
   `where batch_id = (select max(batch_id) from all_uploaded_videos)` and the only guard
   is `if db_content:`. If the 01:00 generator produced nothing, the 01:30 emailer resends
   the previous digest.
3. **The two crons race.** 30 minutes is the entire budget for SQS fan-out plus every
   channel's API fetch, with no completion signal between them. A slow or failed channel
   means the digest goes out partial, silently.
4. **Dead code in the emailer.** `youtube-digest-emailer/utils/helpers.py` defines
   `get_authenticated_service()`, `YOUTUBE_SCOPES` and imports `googleapiclient`, but the
   handler never calls the YouTube API — and `GOOGLE_SERVICE_ACCOUNT_SECRET` is not even set
   in its `serverless.yml`, so calling it would raise. The service shipped the Google API
   client libraries for nothing.
5. **`get_logger()` is copy-pasted into all five `utils/helpers.py`.** None of these services
   imported `applications/common/`, which is why the move here was clean — but it is also why
   the helper is duplicated five times.

## Dependencies that were NOT deleted

Removing this pipeline deliberately left these in place, because other projects use them:

| Resource | Still used by |
|---|---|
| Secret `neon-postgres-service-account` | `api-jobs-endpoint`, `gmail-sender`, `job-hunt-application-enricher` |
| Secret `google_gmail_iam_auth_token_secret` | `gmail-sender` (job-hunt) |
| Neon tables `scoped_channels`, `all_uploaded_videos` | nothing — but they live in Neon, not AWS, so teardown did not drop them. They may still hold data. See `database-ddls/`. |

## If you revive this

1. Recreate the two deleted secrets — `google-service-account` (a Google OAuth token for the
   YouTube Data API) and `google-gmail-app-credentials` (a Gmail app password). Both were
   populated by hand and had a 7-day recovery window, so by now they must be regenerated
   from Google.
2. Restore the Terraform blocks in `terraform-snapshot/main.tf.youtube` into
   `my-aws-infrastructure/infra/main.tf` and apply — this recreates the S3 bucket, the SQS
   queue and DLQ, and the SSM parameter.
3. `npm install` then `npx serverless deploy --region us-west-2` in each service directory.
   `serverless-python-requirements` uses `dockerizePip: true`, so Docker must be running.
4. Fix at least defects 1 and 2 above first.
