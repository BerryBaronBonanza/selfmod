import asyncio
import subprocess
import sys
import time

import click

from selfmod.db import (
    DEFAULT_DB_PATH,
    delete_episode,
    get_db,
    get_episode_frames,
    get_stats,
    rename_episode,
    resolve_episode,
    search_episodes,
)
from selfmod.processor import process_frames
from selfmod.recorder import FrameRecorder


@click.group()
@click.option("--db", default=None, help="Path to SQLite database")
@click.pass_context
def cli(ctx, db):
    """auto-self-modeling: record, understand, and replay terminal sessions."""
    ctx.ensure_object(dict)
    ctx.obj["db_path"] = db


@cli.command()
@click.option("--target", default="0:selfmod", help="tmux target pane (session:window)")
@click.option("--tick", default=50, type=int, help="Capture interval in milliseconds")
@click.pass_context
def record(ctx, target, tick):
    """Record tmux pane content with smart frame filtering."""
    conn = get_db(ctx.obj["db_path"])
    recorder = FrameRecorder(conn, target=target, tick_ms=tick)
    try:
        asyncio.run(recorder.run())
    except KeyboardInterrupt:
        pass


@cli.command()
@click.option("--batch-size", default=20, type=int, help="Frames per Claude batch")
@click.pass_context
def process(ctx, batch_size):
    """Analyze unprocessed frames with Claude Code and group into episodes."""
    conn = get_db(ctx.obj["db_path"])
    process_frames(conn, batch_size=batch_size)


@cli.command()
@click.argument("query")
@click.pass_context
def search(ctx, query):
    """Search episodes by keyword."""
    conn = get_db(ctx.obj["db_path"])
    episodes = search_episodes(conn, query)
    if not episodes:
        click.echo("No matching episodes found.")
        return
    for ep in episodes:
        frames = get_episode_frames(conn, ep["id"])
        name_part = f" ({ep['name']})" if ep["name"] else ""
        click.echo(f"[Episode {ep['id']}]{name_part} {ep['title']}")
        click.echo(f"  {ep['summary']}")
        click.echo(f"  Time: {_fmt_time(ep['start_time'])} - {_fmt_time(ep['end_time'])}")
        click.echo(f"  Frames: {len(frames)}")
        click.echo()


@cli.command()
@click.argument("episode")
@click.argument("instructions", required=False, default=None)
@click.option("--dry-run", is_flag=True, help="Print the prompt instead of launching Claude")
@click.option("--tmux-pane", default=None, help="Tmux pane target to control via tmux send-keys")
@click.pass_context
def replay(ctx, episode, instructions, dry_run, tmux_pane):
    """Replay an episode using Claude Code. EPISODE can be an ID, name, or a task description."""
    conn = get_db(ctx.obj["db_path"])
    db_path = ctx.obj["db_path"] or DEFAULT_DB_PATH
    ep = resolve_episode(conn, episode)

    if ep is not None:
        prompt = (
            f"I previously performed the following task in my terminal. "
            f"Please perform this same task now.\n\n"
            f"## Task: {ep['title']}\n\n"
            f"{ep['summary']}\n"
        )
        if instructions:
            prompt += f"\n## Additional instructions\n\n{instructions}\n"
    else:
        prompt = (
            f"I want to perform the following task: {episode}\n\n"
            f"I have a SQLite database of previously recorded terminal episodes at: {db_path}\n"
            f"The `episodes` table has columns: id, name, title, summary, start_time, end_time.\n\n"
            f"First, search the database for episodes relevant to this task "
            f"(use SQL queries with LIKE on title and summary columns). "
            f"If you find relevant episodes, use their summaries as guidance for executing the task. "
            f"If no relevant episodes are found, proceed with the task using your best judgment.\n"
        )
        if instructions:
            prompt += f"\n## Additional instructions\n\n{instructions}\n"

    if tmux_pane is not None:
        prompt += (
            f"\n## Execution method\n\n"
            f"Execute commands in tmux pane {tmux_pane} of the current window. "
            f"Use `tmux send-keys -t {tmux_pane} '...' Enter` to run each command. "
            f"Use `tmux capture-pane -t {tmux_pane} -p` to read the pane output and verify results.\n"
        )

    if dry_run:
        click.echo(prompt)
        return

    subprocess.run(["claude"], input=prompt, text=True)


@cli.command()
@click.argument("episode")
@click.pass_context
def show(ctx, episode):
    """Show episode details. EPISODE can be an ID or name."""
    conn = get_db(ctx.obj["db_path"])
    ep = resolve_episode(conn, episode)
    if ep is None:
        click.echo("Episode not found.", err=True)
        sys.exit(1)
    frames = get_episode_frames(conn, ep["id"])
    name_part = f" ({ep['name']})" if ep["name"] else ""
    click.echo(f"[Episode {ep['id']}]{name_part} {ep['title']}")
    click.echo(f"Time: {_fmt_time(ep['start_time'])} - {_fmt_time(ep['end_time'])}")
    click.echo(f"Frames: {len(frames)}")
    click.echo()
    click.echo(ep["summary"])
    if frames:
        click.echo()
        for f in frames:
            ts = _fmt_time(f["timestamp"])
            summary = f["summary"] or "(no summary)"
            click.echo(f"  [{f['id']}] {ts} [{f['frame_type']}] {summary}")


@cli.command()
@click.argument("episode")
@click.pass_context
def delete(ctx, episode):
    """Delete an episode. EPISODE can be an ID or name. Frames are kept but unlinked."""
    conn = get_db(ctx.obj["db_path"])
    ep = resolve_episode(conn, episode)
    if ep is None:
        click.echo("Episode not found.", err=True)
        sys.exit(1)
    name = ep["name"] or ep["title"]
    delete_episode(conn, ep["id"])
    click.echo(f"Deleted episode {ep['id']} ({name})")


@cli.command()
@click.argument("episode")
@click.argument("name")
@click.pass_context
def rename(ctx, episode, name):
    """Rename an episode. EPISODE can be an ID or current name."""
    conn = get_db(ctx.obj["db_path"])
    ep = resolve_episode(conn, episode)
    if ep is None:
        click.echo("Episode not found.", err=True)
        sys.exit(1)
    rename_episode(conn, ep["id"], name)
    click.echo(f"Episode {ep['id']} renamed to '{name}'")


@cli.command()
@click.pass_context
def status(ctx):
    """Show recording statistics."""
    conn = get_db(ctx.obj["db_path"])
    stats = get_stats(conn)
    click.echo(f"Total frames:       {stats['total_frames']}")
    click.echo(f"Unprocessed frames: {stats['unprocessed_frames']}")
    click.echo(f"Episodes:           {stats['episode_count']}")
    click.echo(f"Database size:      {stats['db_size_mb']:.1f} MB")


def _fmt_time(ts):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
