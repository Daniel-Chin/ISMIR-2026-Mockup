import pytest

from scripts.time_stretch_videos import stretch_captions


def test_stretch_captions_retimes_cues_only_and_keeps_the_original(tmp_path):
    original = '﻿1\r\n00:00:02,000 --> 00:01:00,500\r\nAt 00:00:02,000 sharp\r\n\r\n2\r\n01:00:00,000 --> 01:00:03,000\r\nLast\r\n'
    path = tmp_path / '7.srt'
    path.write_bytes(original.encode('utf-8'))
    stretch_captions(path, 2)
    assert path.read_bytes().decode('utf-8') == (
        '﻿1\r\n00:00:01,000 --> 00:00:30,250\r\nAt 00:00:02,000 sharp\r\n\r\n2\r\n00:30:00,000 --> 00:30:01,500\r\nLast\r\n')
    assert (tmp_path / '7-too-long.srt').read_bytes().decode('utf-8') == original


def test_stretch_captions_keeps_the_vtt_separator(tmp_path):
    path = tmp_path / '7.vtt'
    path.write_text('WEBVTT\n\n00:00:03.000 --> 00:00:06.000\nHi\n', encoding='utf-8')
    stretch_captions(path, 1.5)
    assert '00:00:02.000 --> 00:00:04.000' in path.read_text(encoding='utf-8')


def test_stretch_captions_refuses_a_file_without_cues(tmp_path):
    path = tmp_path / '7.srt'
    path.write_text('not captions', encoding='utf-8')
    with pytest.raises(ValueError):
        stretch_captions(path, 2)
    assert path.read_text(encoding='utf-8') == 'not captions'
    assert not (tmp_path / '7-too-long.srt').exists()
