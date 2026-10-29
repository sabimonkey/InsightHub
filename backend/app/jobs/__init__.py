"""Redis + RQ job boundary.

Long-running work must enter through this package in later milestones.
M1 inbox ingestion stays synchronous. PDF, OCR, and web extraction enter through extraction jobs.
"""
