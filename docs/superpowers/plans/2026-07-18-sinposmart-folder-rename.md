# SinpoSmart Folder Rename Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the legacy project-folder name with `SinpoSmart_值班台` everywhere it affects GUI path discovery, handoff documentation, and the linked Git worktree.

**Architecture:** Keep the existing environment-variable override and the G:/I: dual-drive fallback in `duty_gui.py`; only replace the folder-name segment. Update user-facing handoff references and let Git repair its own linked-worktree metadata rather than editing `.git` files directly.

**Tech Stack:** Python `pathlib`, Markdown, Git worktree commands, PowerShell, `rg`.

## Global Constraints

- Do not delete or move files.
- Do not change `.env`, credentials, runtime configuration, or NAS deployment files.
- Preserve the existing G:/ and I:/ cloud-drive fallback behavior.
- Do not stage or commit unrelated working-tree changes.

---

### Task 1: Update GUI cloud-project candidates

**Files:**
- Modify: `WinPython_公務電腦使用包/duty_gui.py:53-54`

**Interfaces:**
- Consumes: `SINPOSMART_CLOUD_PROJECT_DIR` and the existing `CLOUD_PROJECT_CANDIDATES` tuple.
- Produces: The same tuple shape, with both fallback paths pointing to the renamed folder.

- [ ] **Step 1: Confirm the old paths are present**

Run: `rg -n 'legacy-folder-name' WinPython_公務電腦使用包/duty_gui.py` after substituting the known legacy folder name in the local command.

Expected: Two matches in the `CLOUD_PROJECT_CANDIDATES` tuple.

- [ ] **Step 2: Replace only the folder-name segment**

```python
    Path("G:/我的雲端硬碟/專案/SinpoSmart_值班台"),
    Path("I:/我的雲端硬碟/專案/SinpoSmart_值班台"),
```

- [ ] **Step 3: Compile-check the edited module**

Run: `py -3 -m py_compile WinPython_公務電腦使用包/duty_gui.py`

Expected: Exit code 0 with no output.

### Task 2: Update project-name documentation

**Files:**
- Modify: `WinPython_公務電腦使用包/docs/DEPLOYMENT_HANDOFF_20260521.md:10,16`
- Modify: `WinPython_公務電腦使用包/docs/HANDOFF.md:1,10`
- Modify: `WinPython_公務電腦使用包/docs/CODE_MAP.md:1`

**Interfaces:**
- Consumes: Historical handoff and code-map text.
- Produces: Documentation that names the current project folder and no longer provides obsolete absolute paths.

- [ ] **Step 1: Replace every exact old project-folder segment**

Replace the legacy folder-name segment with `SinpoSmart_值班台` in the listed files, preserving surrounding drive letters and Markdown formatting.

- [ ] **Step 2: Verify no stale project name remains outside excluded generated folders**

Run: `rg -n -i --hidden --glob '!.git/**' --glob '!.worktrees/**' --glob '!archive/**' --glob '!tmp/**' --glob '!outputs/**' --glob '!runtime_outputs/**' --glob '!logs/**' 'legacy-folder-name' .` after substituting the known legacy folder name in the local command.

Expected: Exit code 1 and no matches.

### Task 3: Repair the linked Git worktree

**Files:**
- Modify: Git-managed metadata for `.worktrees/sinposmart-google-site-duty-board` only.

**Interfaces:**
- Consumes: The moved worktree directory.
- Produces: A linked worktree whose `.git` file and parent repository metadata point to the renamed location.

- [ ] **Step 1: Repair from the main worktree**

Run: `git worktree repair .worktrees/sinposmart-google-site-duty-board`

Expected: Exit code 0.

- [ ] **Step 2: Verify the repaired location**

Run: `git worktree list --porcelain`

Expected: The linked worktree uses `G:/我的雲端硬碟/專案/SinpoSmart_值班台/.worktrees/sinposmart-google-site-duty-board` and has no `prunable` line.

### Task 4: Final migration verification

**Files:**
- Verify: the four modified tracked files and Git worktree metadata.

- [ ] **Step 1: Inspect the scoped diff**

Run: `git diff -- WinPython_公務電腦使用包/duty_gui.py WinPython_公務電腦使用包/docs/DEPLOYMENT_HANDOFF_20260521.md WinPython_公務電腦使用包/docs/HANDOFF.md WinPython_公務電腦使用包/docs/CODE_MAP.md`

Expected: Only old-to-new folder-name substitutions.

- [ ] **Step 2: Confirm unrelated work remains unstaged**

Run: `git status --short`

Expected: Existing unrelated changes remain present and no files are staged.
