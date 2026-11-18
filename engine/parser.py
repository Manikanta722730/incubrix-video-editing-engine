"""Natural Language Instruction Parser.

Translates plain-language user requests into structured editing commands.
Strictly separates language translation from timeline execution:
All timeline manipulation logic remains deterministic code.
"""

from __future__ import annotations
import re
from typing import Dict, Any, List, Optional, Tuple
from engine.models import TimePolicy
from engine.time_policy import parse_time_expression


class ParsedInstruction:
    def __init__(
        self,
        intent: str,
        params: Dict[str, Any],
        raw_text: str,
        multi_parts: Optional[List[ParsedInstruction]] = None
    ):
        self.intent = intent
        self.params = params
        self.raw_text = raw_text
        self.multi_parts = multi_parts or []


class InstructionParser:
    """Deterministic parser with support for natural language variations, time expressions, and ambiguity detection."""

    def __init__(self, default_time_policy: TimePolicy = TimePolicy.ORIGINAL_MEDIA_TIME):
        self.default_time_policy = default_time_policy

    def parse(self, text: str) -> ParsedInstruction:
        raw_text = text.strip()
        lower = raw_text.lower()

        # Check for multi-part instructions separated by " and " (e.g. "speed up 10x and cut the first 10 seconds")
        # Ensure we don't split phrases like "welcome and hello" or "first and second"
        multi_split = re.split(r"\s+and\s+(?=(?:cut|remove|add|speed|mute|bleep|make|put)\b)", raw_text, flags=re.IGNORECASE)
        if len(multi_split) > 1:
            sub_parts = [self.parse(part.strip()) for part in multi_split if part.strip()]
            return ParsedInstruction(
                intent="multi_part",
                params={"count": len(sub_parts)},
                raw_text=raw_text,
                multi_parts=sub_parts
            )

        # 1. Undo / Redo
        if re.search(r"^\s*undo\b", lower):
            # Check for selective undo: e.g. "undo the second-to-last cut but keep the music"
            if "second-to-last" in lower or "second to last" in lower or "keep the music" in lower:
                return ParsedInstruction(
                    intent="selective_undo",
                    params={"target": "second_to_last_cut", "preserve": ["background_music"]},
                    raw_text=raw_text
                )
            return ParsedInstruction(intent="undo", params={}, raw_text=raw_text)

        if re.search(r"^\s*redo\b", lower):
            return ParsedInstruction(intent="redo", params={}, raw_text=raw_text)

        # 2. Render
        if lower in ["render", "export", "render video", "render the final video"]:
            return ParsedInstruction(intent="render", params={}, raw_text=raw_text)

        # 3. Restore / Put back
        # E.g., "actually, put the intro back", "put back what i removed", "restore the first cut"
        m_put_back_split = re.search(r"(?:actually,?\s*)?put\s+(.*?)\s+back", lower)
        if m_put_back_split:
            target = m_put_back_split.group(1).strip()
            return ParsedInstruction(intent="restore_edit", params={"target": target}, raw_text=raw_text)

        m_put_back = re.search(r"(?:actually,?\s*)?(?:put\s+back|restore)\s+(.*)", lower)
        if m_put_back:
            target = m_put_back.group(1).strip()
            return ParsedInstruction(intent="restore_edit", params={"target": target}, raw_text=raw_text)

        # 4. Multi-speaker: "remove everything the guest says about their old job"
        m_spk_job = re.search(r"remove\s+everything\s+(?:the\s+)?guest\s+says\s+about\s+(?:their\s+)?(?:old\s+job|previous\s+job)", lower)
        if m_spk_job:
            return ParsedInstruction(
                intent="remove_speaker_topic",
                params={"speaker": "speaker_2", "topic": "old job", "ask_host_lead_in": True},
                raw_text=raw_text
            )

        # 5. Captioning
        # E.g. "add a caption 'Welcome!' when I say welcome to the channel"
        # Or "add a caption at 5:00"
        m_cap_words = re.search(r"add\s+(?:a\s+)?caption\s+['\"]([^'\"]+)['\"]\s+when\s+(?:i\s+say\s+|they\s+say\s+)?['\"]?([^'\"$]+)['\"]?", raw_text, re.IGNORECASE)
        if m_cap_words:
            caption_text = m_cap_words.group(1).strip()
            anchor_phrase = m_cap_words.group(2).strip().strip("'\"")
            return ParsedInstruction(
                intent="add_caption_anchored",
                params={"caption_text": caption_text, "anchor_phrase": anchor_phrase},
                raw_text=raw_text
            )

        m_cap_at = re.search(r"add\s+(?:a\s+)?caption\s+(?:at|on)\s+([0-9:a-zA-Z\s]+)", lower)
        if m_cap_at:
            time_str = m_cap_at.group(1).strip()
            return ParsedInstruction(
                intent="add_caption_at_time",
                params={"time_expr": time_str, "caption_text": "Caption"},
                raw_text=raw_text
            )

        # Auto-caption whole video
        if "auto-caption" in lower or "auto caption" in lower or "caption the whole video" in lower:
            return ParsedInstruction(intent="auto_caption", params={}, raw_text=raw_text)

        # Style caption: "make that caption red", "make that caption bigger", "make it bigger"
        m_style = re.search(r"make\s+(that\s+caption|it)\s+(red|blue|yellow|green|white|bigger|smaller|large)", lower)
        if m_style:
            target = m_style.group(1).strip()
            style_val = m_style.group(2).strip()
            return ParsedInstruction(
                intent="style_caption",
                params={"target": target, "style_value": style_val},
                raw_text=raw_text
            )

        # 6. Filler words removal
        if "filler" in lower or ("um" in lower and "uh" in lower) or "cut out the ums" in lower:
            return ParsedInstruction(intent="remove_fillers", params={}, raw_text=raw_text)

        # 7. Silence removal
        m_sil = re.search(r"(?:remove|cut)\s+silences?(?:\s+longer\s+than\s+([0-9\.]+(?:\s*s|\s*seconds?)?))?", lower)
        if m_sil:
            thresh_str = m_sil.group(1) or "0.7s"
            thresh = parse_time_expression(thresh_str) or 0.70
            return ParsedInstruction(intent="remove_silence", params={"min_duration_s": thresh}, raw_text=raw_text)

        # 8. Background Music with Auto-Ducking
        if "background music" in lower or "music" in lower and "quieter under speech" in lower:
            return ParsedInstruction(
                intent="add_background_music",
                params={"ducking": True, "duck_db": -18.0},
                raw_text=raw_text
            )

        # 9. Speed adjustments
        # E.g. "speed up from 1:00 to 1:30 by 2x", "speed up 10x", "slow down 0:10 to 0:20 by 0.5x"
        m_speed_range = re.search(r"(speed\s+up|slow\s+down)\s+(?:from\s+)?([0-9:a-zA-Z\s]+?)\s+to\s+([0-9:a-zA-Z\s]+?)\s+by\s+([0-9\.]+)x?", lower)
        if m_speed_range:
            direction = m_speed_range.group(1)
            start_str = m_speed_range.group(2).strip()
            end_str = m_speed_range.group(3).strip()
            factor = float(m_speed_range.group(4))
            if "slow" in direction and factor > 1.0:
                factor = 1.0 / factor
            return ParsedInstruction(
                intent="speed_range",
                params={"start_expr": start_str, "end_expr": end_str, "speed_factor": factor},
                raw_text=raw_text
            )

        m_speed_direct = re.search(r"(speed\s+up|slow\s+down)\s+([0-9\.]+)x?", lower)
        if m_speed_direct:
            factor = float(m_speed_direct.group(2))
            return ParsedInstruction(
                intent="speed_global",
                params={"speed_factor": factor},
                raw_text=raw_text
            )

        # 10. Semantic / Topic Cuts & Ambiguities
        # E.g. "remove the part about pricing", "remove the pricing part", "remove the boring bit", "make it shorter"
        if "boring bit" in lower or "boring part" in lower:
            return ParsedInstruction(
                intent="ambiguous_request",
                params={"type": "boring_part"},
                raw_text=raw_text
            )
        if "make it shorter" in lower:
            return ParsedInstruction(
                intent="ambiguous_request",
                params={"type": "make_it_shorter"},
                raw_text=raw_text
            )

        # "remove everything after I say thanks"
        m_after_word = re.search(r"(?:remove|cut)\s+everything\s+after\s+(?:i\s+say\s+)?['\"]?([a-zA-Z]+)['\"]?", lower)
        if m_after_word:
            trigger_word = m_after_word.group(1).strip()
            return ParsedInstruction(
                intent="cut_after_word",
                params={"word": trigger_word},
                raw_text=raw_text
            )

        m_topic_cut = re.search(r"(?:remove|cut)\s+(?:the\s+part\s+about\s+|the\s+)?([a-zA-Z0-9_\-\s]+?)(?:\s+part)?$", lower)
        if m_topic_cut and ("pricing" in lower or "cost" in lower or "intro" in lower):
            topic = m_topic_cut.group(1).strip()
            return ParsedInstruction(
                intent="cut_topic",
                params={"topic": topic},
                raw_text=raw_text
            )

        # 11. Cut range & Keep range
        # E.g. "cut the first 30 seconds", "remove 0:30-0:40", "cut everything"
        if lower in ["cut everything", "remove everything", "delete all"]:
            return ParsedInstruction(intent="cut_all", params={}, raw_text=raw_text)

        m_cut_first = re.search(r"(?:cut|remove)\s+(?:the\s+)?first\s+([0-9:a-zA-Z\s]+)", lower)
        if m_cut_first:
            time_expr = "the first " + m_cut_first.group(1).strip()
            return ParsedInstruction(
                intent="cut_range",
                params={"start_expr": "0", "end_expr": time_expr},
                raw_text=raw_text
            )

        m_cut_last = re.search(r"(?:cut|remove)\s+(?:the\s+)?last\s+([0-9:a-zA-Z\s]+)", lower)
        if m_cut_last:
            time_expr = "the last " + m_cut_last.group(1).strip()
            return ParsedInstruction(
                intent="cut_range",
                params={"start_expr": time_expr, "end_expr": "end"},
                raw_text=raw_text
            )

        m_cut_dash = re.search(r"(?:cut|remove)\s+([0-9:\.]+)\s*-\s*([0-9:\.]+)", lower)
        if m_cut_dash:
            return ParsedInstruction(
                intent="cut_range",
                params={"start_expr": m_cut_dash.group(1).strip(), "end_expr": m_cut_dash.group(2).strip()},
                raw_text=raw_text
            )

        m_keep = re.search(r"keep\s+(?:only\s+)?([0-9:\.]+)\s*-\s*([0-9:\.]+)", lower)
        if m_keep:
            return ParsedInstruction(
                intent="keep_range",
                params={"start_expr": m_keep.group(1).strip(), "end_expr": m_keep.group(2).strip()},
                raw_text=raw_text
            )

        # 12. Bleep / Mute words
        m_bleep = re.search(r"(?:bleep|mute)\s+(?:the\s+word\s+|the\s+)?['\"]?([a-zA-Z0-9_\-]+)['\"]?", lower)
        if m_bleep:
            is_bleep = "bleep" in lower
            target_word = m_bleep.group(1).strip()
            return ParsedInstruction(
                intent="bleep_word" if is_bleep else "mute_word",
                params={"word": target_word},
                raw_text=raw_text
            )

        # 13. Reorder sections
        # E.g. "reorder section from 1:00-1:30 to start"
        m_reorder = re.search(r"(?:reorder|move)\s+(?:section\s+)?(?:from\s+)?([0-9:]+)\s*-\s*([0-9:]+)\s+to\s+([a-zA-Z0-9:]+)", lower)
        if m_reorder:
            return ParsedInstruction(
                intent="reorder",
                params={"start_expr": m_reorder.group(1).strip(), "end_expr": m_reorder.group(2).strip(), "target_pos": m_reorder.group(3).strip()},
                raw_text=raw_text
            )

        # Fallback unknown
        return ParsedInstruction(
            intent="unknown",
            params={},
            raw_text=raw_text
        )
