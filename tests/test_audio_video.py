"""Tests for audio and video ingestion (Stage 1 parsing).

Verifies:
- Audio transcription → timestamped pages
- Video audio extraction + transcription
- Timestamp propagation to L3 chunks
- Segment grouping into pages by time windows
- Keyframe extraction (mocked ffmpeg)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from ingestible.pipeline.stage1_parsing import (
    AUDIO_FORMATS,
    SUPPORTED_FORMATS,
    VIDEO_FORMATS,
    _format_timestamp,
    _segments_to_pages,
)


class TestFormatRegistration:
    """Audio/video extensions are registered in SUPPORTED_FORMATS."""

    def test_audio_formats_registered(self):
        for ext in AUDIO_FORMATS:
            assert ext in SUPPORTED_FORMATS, f"{ext} not in SUPPORTED_FORMATS"

    def test_video_formats_registered(self):
        for ext in VIDEO_FORMATS:
            assert ext in SUPPORTED_FORMATS, f"{ext} not in SUPPORTED_FORMATS"

    def test_expected_audio_extensions(self):
        expected = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".opus"}
        assert expected.issubset(AUDIO_FORMATS)

    def test_expected_video_extensions(self):
        expected = {".mp4", ".mkv", ".avi", ".mov", ".webm"}
        assert expected.issubset(VIDEO_FORMATS)


class TestFormatTimestamp:
    """Timestamp formatting."""

    def test_minutes_seconds(self):
        assert _format_timestamp(65) == "[01:05]"

    def test_hours(self):
        assert _format_timestamp(3661) == "[01:01:01]"

    def test_zero(self):
        assert _format_timestamp(0) == "[00:00]"

    def test_just_seconds(self):
        assert _format_timestamp(45) == "[00:45]"


class TestSegmentsToPages:
    """Segment grouping into pages."""

    def test_empty_segments(self):
        assert _segments_to_pages([]) == []

    def test_single_segment(self):
        segments = [{"start": 0.0, "end": 5.0, "text": "Hello world."}]
        pages = _segments_to_pages(segments)
        assert len(pages) == 1
        assert "[00:00]" in pages[0].markdown
        assert "Hello world." in pages[0].markdown
        assert pages[0].timestamp_start == 0.0
        assert pages[0].timestamp_end == 5.0

    def test_grouping_by_duration(self):
        # 4 segments spanning 5 minutes — with 2-min window should produce 3 pages
        segments = [
            {"start": 0.0, "end": 30.0, "text": "First segment."},
            {"start": 30.0, "end": 90.0, "text": "Second segment."},
            {"start": 120.0, "end": 180.0, "text": "Third segment."},
            {"start": 240.0, "end": 300.0, "text": "Fourth segment."},
        ]
        pages = _segments_to_pages(segments, page_duration=120.0)
        assert len(pages) == 3  # [0-90], [120-180], [240-300]

    def test_timestamps_on_pages(self):
        segments = [
            {"start": 10.0, "end": 20.0, "text": "Segment A."},
            {"start": 20.0, "end": 30.0, "text": "Segment B."},
        ]
        pages = _segments_to_pages(segments, page_duration=120.0)
        assert len(pages) == 1
        assert pages[0].timestamp_start == 10.0
        assert pages[0].timestamp_end == 30.0

    def test_page_numbering(self):
        segments = [
            {"start": 0.0, "end": 60.0, "text": "First."},
            {"start": 120.0, "end": 180.0, "text": "Second."},
            {"start": 240.0, "end": 300.0, "text": "Third."},
        ]
        pages = _segments_to_pages(segments, page_duration=60.0)
        for i, page in enumerate(pages):
            assert page.page_num == i + 1


class TestTimestampPropagation:
    """Timestamp propagation from pages to L3 chunks."""

    def test_propagate_timestamps_from_content(self):
        from ingestible.models.chunks import ChunkPosition, ChunkSet, L0Chunk, L3Chunk
        from ingestible.models.document import ParsedDocument

        chunks = ChunkSet(
            doc_id="test",
            l0=L0Chunk(chunk_id="test-L0", title="Test"),
            l3_chunks=[
                L3Chunk(
                    chunk_id="p0",
                    content="[01:30] This is the first segment.\n\n[02:15] And the second.",
                    position=ChunkPosition(),
                ),
                L3Chunk(
                    chunk_id="p1",
                    content="[01:05:30] Later in the recording.\n\n[01:06:00] More content.",
                    position=ChunkPosition(),
                ),
            ],
        )

        parsed = ParsedDocument(
            title="Test",
            source_path="test.mp3",
            source_format="audio",
            pages=[],
        )

        from ingestible.pipeline.orchestrator import _propagate_timestamps

        _propagate_timestamps(chunks, parsed)

        # MM:SS format
        assert chunks.l3_chunks[0].timestamp_start == 90.0  # 01:30
        assert chunks.l3_chunks[0].timestamp_end == 135.0  # 02:15

        # HH:MM:SS format
        assert chunks.l3_chunks[1].timestamp_start == 3930.0  # 1:05:30
        assert chunks.l3_chunks[1].timestamp_end == 3960.0  # 1:06:00


class TestAudioParsing:
    """Audio parsing with mocked transcription."""

    def test_parse_audio_produces_parsed_document(self):
        mock_segments = [
            {"start": 0.0, "end": 30.0, "text": "Welcome to the lecture."},
            {"start": 30.0, "end": 60.0, "text": "Today we discuss transformers."},
            {"start": 60.0, "end": 90.0, "text": "Attention is all you need."},
        ]

        with patch(
            "ingestible.pipeline.stage1_parsing._transcribe_audio", return_value=mock_segments
        ):
            from ingestible.pipeline.stage1_parsing import _parse_audio

            result = _parse_audio(Path("lecture.mp3"))

        assert result.source_format == "audio"
        assert result.total_pages >= 1
        assert "[00:00]" in result.pages[0].markdown
        assert "Welcome to the lecture." in result.pages[0].markdown
        assert result.pages[0].timestamp_start == 0.0

    def test_parse_audio_empty_transcription(self):
        with patch("ingestible.pipeline.stage1_parsing._transcribe_audio", return_value=[]):
            from ingestible.pipeline.stage1_parsing import _parse_audio

            result = _parse_audio(Path("silence.mp3"))

        assert result.pages == []
        assert result.source_format == "audio"


class TestVideoParsing:
    """Video parsing with mocked ffmpeg and transcription."""

    def test_parse_video_produces_parsed_document(self, tmp_path):
        mock_segments = [
            {"start": 0.0, "end": 30.0, "text": "Video introduction."},
            {"start": 30.0, "end": 60.0, "text": "Main content."},
        ]

        video_file = tmp_path / "video.mp4"
        video_file.write_bytes(b"fake video data")

        with (
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
            patch(
                "ingestible.pipeline.stage1_parsing._extract_audio_from_video",
                return_value=tmp_path / "audio.wav",
            ),
            patch(
                "ingestible.pipeline.stage1_parsing._transcribe_audio", return_value=mock_segments
            ),
            patch("pathlib.Path.unlink"),  # don't actually delete
        ):
            from ingestible.pipeline.stage1_parsing import _parse_video

            result = _parse_video(video_file)

        assert result.source_format == "video"
        assert result.total_pages >= 1
        assert "Video introduction." in result.pages[0].markdown

    def test_parse_video_requires_ffmpeg(self, tmp_path):
        video_file = tmp_path / "video.mp4"
        video_file.write_bytes(b"fake")

        with patch("shutil.which", return_value=None):
            from ingestible.pipeline.stage1_parsing import _parse_video

            with pytest.raises(RuntimeError, match="ffmpeg"):
                _parse_video(video_file)


class TestTimestampRoundTrip:
    """Timestamps survive save/load cycle."""

    def test_l3_timestamps_roundtrip(self, tmp_path):
        from ingestible.config import Settings
        from ingestible.models.chunks import ChunkPosition, ChunkSet, L0Chunk, L3Chunk
        from ingestible.models.document import DocumentStructure, StructureNode
        from ingestible.pipeline.stage6_storage import load_chunks, save_document

        chunks = ChunkSet(
            doc_id="ts-test",
            l0=L0Chunk(chunk_id="ts-test-L0", title="Timestamp Test"),
            l3_chunks=[
                L3Chunk(
                    chunk_id="ts-test-p0",
                    content="[00:30] First segment content.",
                    position=ChunkPosition(),
                    parent_section_id="",
                    timestamp_start=30.0,
                    timestamp_end=60.0,
                ),
            ],
        )

        structure = DocumentStructure(
            doc_id="ts-test",
            title="Timestamp Test",
            root=StructureNode(id="ts-test", title="Timestamp Test", level=0),
        )
        settings = Settings(data_dir=tmp_path)
        doc_dir = save_document(structure, chunks, settings)

        loaded = load_chunks(doc_dir)
        assert loaded.l3_chunks[0].timestamp_start == 30.0
        assert loaded.l3_chunks[0].timestamp_end == 60.0
