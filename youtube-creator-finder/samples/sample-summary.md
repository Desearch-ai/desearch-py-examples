# YouTube Creator Finder

Fictional example data for the five creators in `sample-creators.csv`; no real creators or contacts are represented.

query: "Independent YouTube creators who review mechanical keyboards"

request: {"count": 5, "query": "Independent YouTube creators who review mechanical keyboards", "filters": {"min_subscribers": 5000, "require_contact": false, "exclude_keywords": ["shop", "store"]}}

task_status: "completed"

completion_reason: "count_reached"

stop_reason: "count_reached"

coverage_limited: false

warnings: []

errors: []

counts: {"downloaded": 5, "result_count": 5, "round": 1, "queries": {"total": 8, "failed": 0}, "filtered": {"min_subscribers": 6, "excluded_keyword": 4}, "warnings": [], "qualified": 5, "stop_reason": "count_reached", "videos_attached": 8, "candidates_found": 148, "youtube_enrichment": {"emails_found": 0, "channels_merged": 0, "channels_enriched": 19, "channels_attempted": 19, "innertube_failures": 0, "link_pages_crawled": 16, "youtube_candidates": 20, "about_page_failures": 0, "channel_id_mismatches": 0, "channels_resolved_from_videos": 14, "subscriber_counts_unavailable": 0}, "candidates_processed": 20}

emails_count: 0

flags_counts: {"possible_brand_or_store": 2, "no_contact": 2}

reserved_cost_usd: 0.25

final_cost_usd: 0.25

refunded_usd: 0.0

duration_seconds: 144.45847

creation: {}
