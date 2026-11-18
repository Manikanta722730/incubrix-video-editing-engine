import requests
import json
import time

BASE_URL = 'http://localhost:8000'

print('=' * 80)
print('  INCUBRIX PROMPT-BASED VIDEO EDITING ENGINE -- LIVE DEMONSTRATION')
print('  Official Assessment 2 Worked-Example Walkthrough')
print('=' * 80)

# Step 1: Health & Service Check
print('\n[1] Querying Service Health (GET /health & GET /ready)...')
r_health = requests.get(f'{BASE_URL}/health').json()
r_ready = requests.get(f'{BASE_URL}/ready').json()
print(f"    * Health   : {r_health['status']} (Version {r_health['version']})")
print(f"    * Ready    : {r_ready['status']} (FFmpeg: {r_ready['ffmpeg']}, Storage: {r_ready['storage']})")

# Step 2: Create a Session
print('\n[2] Initializing Clean Editing Session (POST /api/v1/sessions)...')
sess_req = {
    'video_url': 'test_pack/media/single_speaker_interview.mp4',
    'time_policy': 'original_media_time'
}
headers = {'Idempotency-Key': f'demo-run-{int(time.time())}'}
sess = requests.post(f'{BASE_URL}/api/v1/sessions', json=sess_req, headers=headers).json()
session_id = sess['session_id']
print(f"    * Session ID     : {session_id}")
print(f"    * Video Source   : {sess['video']}")
print(f"    * Source SHA256  : {sess['source_sha256'][:24]}... (Immutable)")
print(f"    * Duration       : {sess['duration_s']}s")
print(f"    * Time Policy    : {sess['time_policy']}")

# Step 3: Sequence of Operations
steps = [
    {
        'num': 1,
        'title': 'Add content-anchored caption',
        'say': "Add a caption 'Welcome!' when I say welcome to the channel",
        'answer': None,
        'notes': 'Attaches caption to the specific spoken word tokens in the transcript.'
    },
    {
        'num': 2,
        'title': 'Cut opening section',
        'say': 'Cut the first 30 seconds',
        'answer': None,
        'notes': 'Content-anchoring test: caption shifts forward in timeline, staying glued to the speech.'
    },
    {
        'num': 3,
        'title': 'Ambiguous instruction triggers Clarification',
        'say': 'Remove the part about pricing',
        'answer': None,
        'notes': 'Multiple matches found in speech. Clarification question + choices presented.'
    },
    {
        'num': 4,
        'title': 'Clarification resolved with answer',
        'say': 'Remove the part about pricing',
        'answer': 'the second one',
        'notes': 'User disambiguates; engine applies cut cleanly on the chosen instance.'
    },
    {
        'num': 5,
        'title': 'Speed change with TimePolicy awareness',
        'say': 'Speed up from 1:00 to 1:30 by 2x',
        'answer': None,
        'notes': 'Maps original media timestamp (1:00-1:30) to current timeline coordinates.'
    },
    {
        'num': 6,
        'title': 'Restore previous cut',
        'say': 'Actually, put the intro back',
        'answer': None,
        'notes': 'Restores the first 30s cut; caption automatically shifts back to original playout.'
    },
    {
        'num': 7,
        'title': 'Undo operation',
        'say': 'Undo',
        'answer': None,
        'notes': 'Snapshot restore: rolls back the restoration cleanly.'
    },
    {
        'num': 8,
        'title': 'Style the caption',
        'say': 'Make that caption red',
        'answer': None,
        'notes': 'Alters styling metadata of the active caption.'
    },
    {
        'num': 9,
        'title': 'Remove filler words',
        'say': 'Remove filler words',
        'answer': None,
        'notes': 'Scans transcript for hesitation tokens (um, uh) and cuts them seamlessly.'
    }
]

print('\n[3] Executing Editing Pipeline Step-by-Step...')
for step in steps:
    print(f"\n>>> Step {step['num']}: {step['title']}")
    print(f"    User Prompt : \"{step['say']}\"")
    if step['answer']:
        print(f"    User Answer : \"{step['answer']}\"")
    print(f"    Expectation : {step['notes']}")
    
    payload = {'say': step['say']}
    if step['answer']:
        payload['answer'] = step['answer']
        
    t0 = time.perf_counter()
    res = requests.post(f'{BASE_URL}/api/v1/sessions/{session_id}/instructions', json=payload).json()
    ms = (time.perf_counter() - t0) * 1000
    
    status = res.get('status', 'UNKNOWN').upper()
    print(f"    Result      : [{status}] (Latency: {ms:.2f} ms)")
    if res.get('summary'):
        print(f"    Summary     : {res['summary']}")
    if res.get('question'):
        print(f"    Question    : {res['question']}")
    if res.get('options'):
        print(f"    Choices     : {res['options']}")
    print(f"    Timeline    : Duration = {res.get('duration_s')}s | Hash = {res.get('timeline_hash', '')[:16]}...")

# Step 4: OpenTimelineIO Export
print('\n[4] OpenTimelineIO Export (GET /api/v1/sessions/{id}/export/otio)...')
r_otio = requests.get(f'{BASE_URL}/api/v1/sessions/{session_id}/export/otio')
print(f"    * Response   : HTTP {r_otio.status_code}")
print(f"    * Data size  : {len(r_otio.text)} bytes of JSON-formatted OTIO schema")
print("    * Sample snippet:")
for line in r_otio.text.splitlines()[:5]:
    print(f"        {line}")

# Step 5: Render
print('\n[5] Enqueuing Render Job (POST /api/v1/sessions/{id}/render)...')
r_render = requests.post(f'{BASE_URL}/api/v1/sessions/{session_id}/render', json={}).json()
job_id = r_render.get('job_id')
print(f"    * Job ID     : {job_id}")
print(f"    * Status     : {r_render.get('status')}")
print(f"    * Poll URL   : {r_render.get('poll_url')}")

# Step 6: Job Polling
print('\n[6] Polling Render Job until Completion...')
for tick in range(1, 10):
    time.sleep(1)
    status_data = requests.get(f'{BASE_URL}/api/v1/jobs/{job_id}').json()
    state = status_data.get('status')
    prog = status_data.get('progress')
    print(f"    * [{tick}s] Progress: {prog}% | Status: {state}")
    if state in ['succeeded', 'failed']:
        break

print('\n' + '=' * 80)
print('  LIVE DEMO FINISHED SUCCESSFULLY!')
print('  The interactive Web UI is accessible at: http://localhost:8000')
print('=' * 80)
