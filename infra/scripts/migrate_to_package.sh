#!/usr/bin/env bash
# Git-mv SyncCut flat root modules into the synccut/ package layout (preserves history).
# Usage (from repo root):  bash infra/scripts/migrate_to_package.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

git_mv() {
  local src="$1" dst="$2"
  if [[ ! -e "$src" ]]; then
    echo "SKIP (missing): $src" >&2
    return 0
  fi
  mkdir -p "$(dirname "$dst")"
  if [[ -e "$dst" ]]; then
    echo "SKIP (exists): $dst" >&2
    return 0
  fi
  echo "git mv $src -> $dst"
  git mv -- "$src" "$dst"
}

echo "=== SyncCut package migration (git mv) ==="
echo "CWD: $ROOT"

git_mv config.py              synccut/config.py
git_mv paths.py               synccut/paths.py

git_mv sync_engine.py         synccut/core/sync_engine.py
git_mv drift.py               synccut/core/drift.py
git_mv confidence.py          synccut/core/confidence.py
git_mv robustness.py          synccut/core/robustness.py
git_mv camera_switch.py       synccut/core/camera_switch.py

git_mv rough_cut.py           synccut/ai/rough_cut.py

git_mv extract.py             synccut/media/extract.py
[[ -d ffmpeg_bin ]] && git_mv ffmpeg_bin synccut/media/ffmpeg_bin

git_mv timeline_builder.py    synccut/export/timeline_builder.py
git_mv fcp7_exporter.py       synccut/export/fcp7_exporter.py
git_mv export_switch_timeline.py synccut/export/switch_timeline.py

git_mv job_manager.py         synccut/api/job_manager.py
git_mv db.py                  synccut/api/db.py

if [[ -d templates ]]; then
  mkdir -p synccut/api/templates
  for f in templates/*; do
    [[ -f "$f" ]] && git_mv "$f" "synccut/api/templates/$(basename "$f")"
  done
fi
if [[ -d static ]]; then
  mkdir -p synccut/api/static
  # shellcheck disable=SC2086
  git mv -- static/* synccut/api/static/ 2>/dev/null || true
fi

git_mv synccut_gui.py         synccut/desktop/gui.py
git_mv synccut.py             synccut/cli/main.py

[[ -f Dockerfile ]] && git_mv Dockerfile infra/Dockerfile
[[ -f build_installer.ps1 ]] && git_mv build_installer.ps1 infra/scripts/build_installer.ps1
[[ -f Procfile ]] && git_mv Procfile infra/Procfile
[[ -f synccut.spec ]] && git_mv synccut.spec infra/synccut.spec

echo
echo "=== Migration complete. Next: fix imports + recreate root app.py shim. ==="
git status --short
