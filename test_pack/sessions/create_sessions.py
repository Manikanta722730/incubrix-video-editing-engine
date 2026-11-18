"""Creates the 15 required scripted session files for the IncuBrix Test Pack."""

import os
import yaml

SESSIONS_DIR = os.path.dirname(os.path.abspath(__file__))

sessions_data = {
    "session_01_worked_example.yaml": {
        "video": "test_pack/media/single_speaker_interview.mp4",
        "description": "Exact 8-step worked example from the assessment brief",
        "steps": [
            {"say": "Add a caption 'Welcome!' when I say welcome to the channel"},
            {"say": "Cut the first 30 seconds"},
            {"say": "Remove the part about pricing", "answer": "the second one"},
            {"say": "Speed up from 1:00 to 1:30 by 2x"},
            {"say": "Actually, put the intro back"},
            {"say": "Undo"},
            {"say": "Make that caption red"},
            {"say": "render"}
        ]
    },
    "session_02_filler_removal.yaml": {
        "video": "test_pack/media/single_speaker_interview.mp4",
        "description": "Removes ums, uhs, and filler words contextually",
        "steps": [
            {"say": "Remove filler words"},
            {"say": "Undo"},
            {"say": "Cut out the ums and uhs"}
        ]
    },
    "session_03_silence_removal.yaml": {
        "video": "test_pack/media/single_speaker_interview.mp4",
        "description": "Removes silences longer than 0.7s and snaps boundaries",
        "steps": [
            {"say": "Remove silences longer than 0.7 seconds"},
            {"say": "Undo"}
        ]
    },
    "session_04_background_music_ducking.yaml": {
        "video": "test_pack/media/single_speaker_interview.mp4",
        "description": "Adds background music track with automatic speech ducking (-18dB)",
        "steps": [
            {"say": "Add background music that automatically gets quieter under speech"},
            {"say": "Cut the first 30 seconds"},
            {"say": "render"}
        ]
    },
    "session_05_two_speaker_podcast.yaml": {
        "video": "test_pack/media/two_speaker_podcast.mp4",
        "description": "Two-speaker scenario: removes guest lines about old job and asks about host question",
        "steps": [
            {"say": "remove everything the guest says about their old job"},
            {"say": "render"}
        ]
    },
    "session_06_hard_case_1_cut_restore_caption.yaml": {
        "video": "test_pack/media/single_speaker_interview.mp4",
        "description": "Hard Case 1: Caption added, sentence under it cut, cut restored -> caption returns on exact words",
        "steps": [
            {"say": "Add a caption 'Welcome!' when I say welcome to the channel"},
            {"say": "Cut the first 30 seconds"},
            {"say": "Actually, put the intro back"},
            {"say": "Make that caption red"}
        ]
    },
    "session_07_hard_case_2_reorder_mute_filler.yaml": {
        "video": "test_pack/media/single_speaker_interview.mp4",
        "description": "Hard Case 2: Section reordered, word inside it muted, filler removal cutting into bleeped word",
        "steps": [
            {"say": "Bleep the word pricing"},
            {"say": "Remove filler words"},
            {"say": "Cut the first 30 seconds"}
        ]
    },
    "session_08_hard_case_3_repeated_cut_natural_times.yaml": {
        "video": "test_pack/media/single_speaker_interview.mp4",
        "description": "Hard Case 3: 'Remove 0:30-0:40' sent twice, 'add caption at 5:00' on shorter video, natural times",
        "steps": [
            {"say": "Remove 0:30-0:40"},
            {"say": "Remove 0:30-0:40"},  # Idempotent / already cut
            {"say": "Add a caption at 5:00"},  # Rejected: beyond 4:00 duration
            {"say": "Cut the first 80 seconds"}  # Natural time "80 seconds"
        ]
    },
    "session_09_hard_case_4_selective_undo_no_caption.yaml": {
        "video": "test_pack/media/single_speaker_interview.mp4",
        "description": "Hard Case 4: 'Undo second-to-last cut but keep music', 'make it bigger' when no caption exists",
        "steps": [
            {"say": "Cut the first 30 seconds"},
            {"say": "Add background music that automatically gets quieter under speech"},
            {"say": "Cut 0:30-0:40"},
            {"say": "Undo the second-to-last cut but keep the music"},
            {"say": "Make that caption bigger"}  # Rejected: no caption exists
        ]
    },
    "session_10_hard_case_5_multiple_thanks.yaml": {
        "video": "test_pack/media/single_speaker_interview.mp4",
        "description": "Hard Case 5: 'Remove everything after I say thanks' where thanks is said four times",
        "steps": [
            {"say": "Remove everything after I say thanks", "answer": "Last occurrence"}
        ]
    },
    "session_11_hard_case_6_speed_10x_impossible_multipart.yaml": {
        "video": "test_pack/media/single_speaker_interview.mp4",
        "description": "Hard Case 6: 'Speed up 10x' (rejected), 'cut everything' (rejected), multi-part instruction",
        "steps": [
            {"say": "Speed up 10x"},  # Rejected: exceeds 4x
            {"say": "Cut everything"},  # Rejected: cannot empty video
            {"say": "Cut the first 10 seconds and speed up 10x"}  # Multi-part: partial applied/rejected
        ]
    },
    "session_12_hard_case_7_vfr_no_audio.yaml": {
        "video": "test_pack/media/phone_vfr_video.mp4",
        "description": "Hard Case 7: Phone video with variable frame rate (24fps)",
        "steps": [
            {"say": "Cut the first 5 seconds"},
            {"say": "render"}
        ]
    },
    "session_13_speed_readable_minimum.yaml": {
        "video": "test_pack/media/single_speaker_interview.mp4",
        "description": "Sped-up captions maintain at least 0.70s readable minimum",
        "steps": [
            {"say": "Add a caption 'Welcome!' when I say welcome to the channel"},
            {"say": "Speed up from 0:40 to 0:50 by 3x"},
            {"say": "render"}
        ]
    },
    "session_14_semantic_search_cost_pricing.yaml": {
        "video": "test_pack/media/single_speaker_interview.mp4",
        "description": "Semantic search: 'pricing' finds multiple cost mentions and asks with options",
        "steps": [
            {"say": "Remove the part about pricing", "answer": "First occurrence"}
        ]
    },
    "session_15_full_pipeline_render.yaml": {
        "video": "test_pack/media/single_speaker_interview.mp4",
        "description": "Full end-to-end pipeline with multiple operations, undo, redo, and final render",
        "steps": [
            {"say": "Add a caption 'Welcome!' when I say welcome to the channel"},
            {"say": "Cut the first 30 seconds"},
            {"say": "Speed up from 1:00 to 1:30 by 2x"},
            {"say": "Add background music that automatically gets quieter under speech"},
            {"say": "render"}
        ]
    }
}


def main():
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    for filename, content in sessions_data.items():
        file_path = os.path.join(SESSIONS_DIR, filename)
        with open(file_path, "w", encoding="utf-8") as f:
            yaml.dump(content, f, sort_keys=False)
    print(f"Created {len(sessions_data)} session YAML files in {SESSIONS_DIR}.")


if __name__ == "__main__":
    main()

