------------------------------------------------------------------
-- YouTube Digest — Neon PostgreSQL tables (ARCHIVED)
------------------------------------------------------------------
-- Extracted from ssilambarasan/applications :: database-ddls/table_ddls.sql
-- (lines 11-43) at commit 3c2eab3a75579561337be7c4d23da0923e20e5f3.
--
-- These two tables live in Neon PostgreSQL, NOT in AWS. The AWS teardown
-- of this project did not drop them. They may still contain data.
--
-- Pipeline role:
--   scoped_channels      <- written by youtube-playlist-fetcher
--                           (channel + its uploads_playlist_id)
--                        -> read by youtube-payload-generator
--   all_uploaded_videos  <- written by youtube-fetch-videos
--                        -> read by youtube-digest-emailer (latest batch_id)
------------------------------------------------------------------

-- 1. scoped_channels
CREATE TABLE scoped_channels (
    id SERIAL PRIMARY KEY,
    channel_id VARCHAR(255) UNIQUE NOT NULL,
    channel_title VARCHAR(255) NOT NULL,
    description TEXT,
    published_at TIMESTAMP WITH TIME ZONE NOT NULL,
    uploads_playlist_id VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_channel_id ON scoped_channels(channel_id);
CREATE INDEX idx_published_at ON scoped_channels(published_at);

-- 2. all_uploaded_videos

CREATE TABLE all_uploaded_videos (
    id SERIAL PRIMARY KEY,
    channel_id VARCHAR(255),
	channel_title VARCHAR(255),
	video_id VARCHAR(255) UNIQUE NOT NULL,
	video_title VARCHAR,
	video_published_at TIMESTAMPTZ NOT NULL,
    uploads_playlist_id VARCHAR(255),
	batch_id VARCHAR(14),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_video_channel_id ON all_uploaded_videos(channel_id);
CREATE INDEX idx_video_published_at ON all_uploaded_videos(video_published_at);
CREATE INDEX idx_batch_id ON all_uploaded_videos(batch_id);
