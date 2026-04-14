# selfmod

Record tmux terminal sessions, analyze them with Claude Code into searchable episodes, and replay those episodes to automate similar tasks in the future.

## How it works

1. **Record** -- captures a tmux pane every 50ms with smart filtering (only stores frames before/after changes and periodic snapshots)
2. **Process** -- sends unprocessed frames to Claude Code, which describes each frame and groups them into named episodes with detailed summaries
3. **Replay** -- feeds an episode summary to an interactive Claude Code session to re-execute the task

## Setup

Requires [Nix](https://nixos.org/) and [Claude Code](https://docs.anthropic.com/en/docs/claude-code).

```
nix develop
```

This gives you a shell with Python 3.12, click, tmux, and sqlite3.

## Usage

```
selfmod [--db PATH] <command>
```

Database defaults to `~/.local/share/selfmod/selfmod.db`.

### Record

Capture a tmux pane with smart frame filtering:

```
selfmod record                          # default: pane 0:selfmod
selfmod record --target main:work.0     # specific session:window.pane
selfmod record --tick 100               # capture every 100ms instead of 50ms
```

Press Ctrl+C to stop. Only "interesting" frames are stored:
- Frame just before content changes
- Frame 400ms after changes settle
- Every 5 seconds if different from last stored frame

### Process

Analyze recorded frames with Claude Code:

```
selfmod process
selfmod process --batch-size 10
```

Creates episodes with hyphenated names (e.g. `check-disk-ppr31`), titles, and detailed summaries. After all batches, episode summaries are consolidated from all frames to ensure full coverage. Summaries are written to be self-contained enough for Claude Code to replay the task.

### Consolidate

Re-summarize an existing episode using all its frames:

```
selfmod consolidate check-disk-ppr31
selfmod consolidate 3
```

Useful when an episode summary is stale or was generated from incomplete data.

### Search

Find episodes by keyword:

```
selfmod search "disk"
```

### Show

Display episode details with frame timeline:

```
selfmod show check-disk-ppr31
selfmod show 1
```

### Replay

Re-execute a recorded task via interactive Claude Code session:

```
selfmod replay check-disk-ppr31                          # by name
selfmod replay 1                                         # by ID
selfmod replay check-disk-ppr31 "use server ppr32"       # with extra instructions
selfmod replay check-disk-ppr31 --tmux-pane main:work.0  # execute in a tmux pane
selfmod replay check-disk-ppr31 --dry-run                # print prompt only
selfmod replay "check disk space"                        # no match — searches episodes DB
```

If the argument doesn't match any episode ID or name, Claude Code searches the episodes database for relevant episodes before executing the task.

### Delete

Delete an episode (frames are kept but unlinked):

```
selfmod delete check-disk-ppr31
selfmod delete 1
```

### Rename

Change an episode's name:

```
selfmod rename 1 check-disk-space
selfmod rename check-disk-ppr31 check-disk-space
```

### Status

Show recording statistics:

```
selfmod status
```

```
Total frames:       42
Unprocessed frames: 0
Episodes:           3
Database size:      0.1 MB
```
