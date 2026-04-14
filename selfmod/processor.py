import json
import subprocess
import sys
import time

from selfmod.db import (
    get_unprocessed_frames,
    get_recent_episodes,
    insert_episode,
    update_episode,
    update_frame_summary,
)

PROCESS_PROMPT_TEMPLATE = """\
Analyze these terminal recording frames. For each frame, write a short summary of what is visible.
Group frames into episodes (logical tasks the user performed).
Episode summaries must be detailed enough that Claude Code could execute the same task
in the future using ONLY the summary — no frames will be provided at replay time.
Include: commands run, files touched, purpose, environment context, and outcome.

Respond with ONLY valid JSON (no markdown fences, no commentary) in this exact format:
{{"frames": [{{"id": <frame_id>, "summary": "..."}}, ...],
 "new_episodes": [{{"title": "...", "summary": "...", "frame_ids": [<id>, ...]}}, ...],
 "existing_episode_assignments": [{{"frame_id": <id>, "episode_id": <id>}}, ...]}}

Rules:
- Every frame must appear in exactly one of: new_episodes.frame_ids or existing_episode_assignments
- new_episodes is for frames that start a new task not covered by existing episodes
- existing_episode_assignments is for frames that continue an existing episode
{existing_episodes_section}
Frames:
{frames_section}"""


def _format_existing_episodes(episodes):
    if not episodes:
        return "\nNo existing episodes yet.\n"
    lines = ["\nExisting episodes (assign frames here if they continue these tasks):"]
    for ep in episodes:
        lines.append(f"  Episode {ep['id']}: {ep['title']} (t={ep['start_time']:.1f}-{ep['end_time']:.1f})")
        lines.append(f"    {ep['summary'][:200]}")
    return "\n".join(lines) + "\n"


def _format_frames(frames):
    parts = []
    for f in frames:
        parts.append(f"--- Frame {f['id']} (t={f['timestamp']:.3f}, type={f['frame_type']}) ---")
        parts.append(f['content'])
    return "\n".join(parts)


def _call_claude(prompt):
    result = subprocess.run(
        ["claude", "-p", "--output-format", "json"],
        input=prompt,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI failed (exit {result.returncode}): {result.stderr}")
    response = json.loads(result.stdout)
    text = response.get("result", "")
    # Strip markdown fences if present
    text = text.strip()
    if text.startswith("```"):
        first_nl = text.index("\n")
        text = text[first_nl + 1:]
    if text.endswith("```"):
        text = text[:-3]
    return json.loads(text.strip())


def process_frames(conn, batch_size=20):
    total_processed = 0
    while True:
        frames = get_unprocessed_frames(conn, limit=batch_size)
        if not frames:
            break

        existing_episodes = get_recent_episodes(conn, limit=10)
        prompt = PROCESS_PROMPT_TEMPLATE.format(
            existing_episodes_section=_format_existing_episodes(existing_episodes),
            frames_section=_format_frames(frames),
        )

        sys.stderr.write(f"Processing batch of {len(frames)} frames...\n")
        result = _call_claude(prompt)

        # Build frame_id -> summary map
        frame_summaries = {f["id"]: f["summary"] for f in result["frames"]}

        # Create new episodes, map frame_ids to episode_ids
        frame_to_episode = {}
        for ep_data in result.get("new_episodes", []):
            frame_ids = ep_data["frame_ids"]
            timestamps = [
                f["timestamp"] for f in frames if f["id"] in frame_ids
            ]
            if not timestamps:
                continue
            ep_id = insert_episode(
                conn,
                title=ep_data["title"],
                summary=ep_data["summary"],
                start_time=min(timestamps),
                end_time=max(timestamps),
            )
            for fid in frame_ids:
                frame_to_episode[fid] = ep_id

        # Existing episode assignments
        for assignment in result.get("existing_episode_assignments", []):
            fid = assignment["frame_id"]
            ep_id = assignment["episode_id"]
            frame_to_episode[fid] = ep_id
            # Extend episode end_time
            frame_ts = next(
                (f["timestamp"] for f in frames if f["id"] == fid), None
            )
            if frame_ts is not None:
                update_episode(conn, ep_id, end_time=frame_ts)

        # Update frames
        for f in frames:
            summary = frame_summaries.get(f["id"], "")
            ep_id = frame_to_episode.get(f["id"])
            update_frame_summary(conn, f["id"], summary, ep_id)

        conn.commit()
        total_processed += len(frames)
        sys.stderr.write(f"  Done. Total processed: {total_processed}\n")

    if total_processed == 0:
        sys.stderr.write("No unprocessed frames found.\n")
    else:
        sys.stderr.write(f"Finished processing {total_processed} frames.\n")
