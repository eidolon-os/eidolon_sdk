"""Music contracts; executor implementation remains in Channel."""

from . import CapabilityDefinition


def definitions():
    return [
        CapabilityDefinition(**value)
        for value in [
            {
                "description": "Search authorized online music. Provide title and artist separately when known; "
                "the capability performs bounded query fallback. Results are non-exhaustive; "
                "unverified candidates are not confirmed matches. Return candidate provider song "
                "ids. Use the selected song_id with music_play without repeating search. Do not "
                "substitute a different song without user agreement. Use keyword 'random' for "
                "recommendations.",
                "execution_location": "channel",
                "idempotent": True,
                "input_schema": {
                    "additionalProperties": False,
                    "anyOf": [
                        {"required": ["keyword"]},
                        {"required": ["title"]},
                        {"required": ["artist"]},
                    ],
                    "properties": {
                        "artist": {"minLength": 1, "type": "string"},
                        "keyword": {"minLength": 1, "type": "string"},
                        "language": {"type": "string"},
                        "title": {"minLength": 1, "type": "string"},
                        "version": {"type": "string"},
                    },
                    "type": "object",
                },
                "legacy_channel": True,
                "llm_name": "music_search",
                "name": "music.search",
                "required_output": "speech",
                "side_effect": False,
                "timeout_s": 15.0,
            },
            {
                "description": "Start a new playback of a selected authorized song by its provider song id, "
                "including replaying a stopped or completed song from the beginning. Acceptance "
                "does not mean audio has started. Use music_status for playback state; do not "
                "claim audible playback from acceptance alone.",
                "execution_location": "channel",
                "idempotent": False,
                "input_schema": {
                    "additionalProperties": False,
                    "properties": {"song_id": {"minLength": 1, "type": "string"}},
                    "required": ["song_id"],
                    "type": "object",
                },
                "legacy_channel": True,
                "llm_name": "music_play",
                "name": "music.play",
                "required_output": "speech",
                "side_effect": True,
                "timeout_s": 60.0,
            },
            {
                "description": "Stop the current online music playback.",
                "execution_location": "channel",
                "idempotent": True,
                "input_schema": {
                    "additionalProperties": False,
                    "properties": {"playback_ref": {"minLength": 1, "type": "string"}},
                    "type": "object",
                },
                "legacy_channel": True,
                "llm_name": "music_stop",
                "name": "music.stop",
                "required_output": "speech",
                "side_effect": True,
                "timeout_s": 10.0,
            },
            {
                "description": "Read the current online music playback status.",
                "execution_location": "channel",
                "idempotent": True,
                "input_schema": {"additionalProperties": False, "properties": {}, "type": "object"},
                "legacy_channel": True,
                "llm_name": "music_status",
                "name": "music.status",
                "required_output": "speech",
                "side_effect": False,
                "timeout_s": 5.0,
            },
        ]
    ]


def presentations():
    """What the Owner reads about each music tool (labels for the tool catalog)."""

    def entry(label, summary):
        return {"label": label, "summary": summary, "group": "music", "host_feature": "music"}

    return {
        "music.search": entry("搜歌", "按歌名、歌手找歌。"),
        "music.play": entry("播放音乐", "播放找到的歌。"),
        "music.status": entry("播放状态", "查一下现在在放什么。"),
        "music.stop": entry("停止音乐", "停掉正在放的音乐。"),
    }
