# immich_sync.py
# Replaces assets in Immich by hash and re-uploads media with XMP (if present alongside).
# Supports: photos, photo+live video, separate videos.
# Requires: requests, immich CLI installed in PATH.

import base64
import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv


# ====== SETTINGS (.env + environment) ======
_env_paths = [
    Path.cwd() / ".env",
    Path(__file__).with_suffix(".env"),
    Path(__file__).parent / ".env",
]
for env_path in _env_paths:
    load_dotenv(dotenv_path=env_path, override=False)

# Environment variables take priority over .env
IMMICH_URL = os.getenv("IMMICH_URL", "")  # WITHOUT trailing /api
API_KEY = os.getenv("IMMICH_API_KEY", "")
ROOT_STR = os.getenv("ROOT", "")
ROOT = Path(ROOT_STR).expanduser()
DRY_RUN = os.getenv("DRY_RUN", "0") == "1"  # DRY_RUN=1 -> show actions only
CHECKPOINT_FILE = os.getenv(
    "CHECKPOINT_FILE", str(ROOT / ".immich_sync.checkpoint")
)

# Extensions
PHOTO_EXT = {".heic", ".jpg", ".jpeg", ".png", ".dng", ".raf", ".cr2", ".arw"}
VIDEO_EXT = {".mov", ".mp4", ".m4v"}

# Batch processing parameters
API_CHUNK = 600  # how many assets to check per POST /api/assets/bulk-upload-check
SEARCH_RETRIES = 12
SEARCH_SLEEP = 2.5

BASE = IMMICH_URL.rstrip("/")
session = requests.Session()
session.headers.update({"x-api-key": API_KEY})

# ---------- Helpers ----------


def sha1_b64(path: Path) -> str:
    """SHA-1 of a file in base64 (what Immich uses for duplicate checks)."""
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return base64.b64encode(h.digest()).decode()


def bulk_upload_check(items: List[Tuple[str, str]]) -> List[dict]:
    if not items:
        return []
    url = f"{BASE}/api/assets/bulk-upload-check"
    payload = {"assets": [{"id": cid, "checksum": csum} for cid, csum in items]}
    r = session.post(url, json=payload, timeout=300)
    r.raise_for_status()
    data = r.json()
    return data.get("results", [])


def asset_delete_many(asset_ids: List[str]) -> None:
    if not asset_ids:
        return
    url = f"{BASE}/api/assets"
    payload = {"ids": asset_ids, "force": True}
    if DRY_RUN:
        print(f"[DRY] DELETE {len(asset_ids)} assets (force)")
        return
    r = session.delete(url, json=payload, timeout=300)
    if r.status_code not in (200, 204):
        print(f"[WARN] deleteAssets -> {r.status_code} {r.text}")


def empty_trash():
    url = f"{BASE}/api/trash/empty"
    if DRY_RUN:
        print("[DRY] POST /api/trash/empty")
        return
    r = session.post(url, timeout=120)
    if not r.ok:
        print(f"[WARN] emptyTrash -> {r.status_code} {r.text}")


def search_assets_by_filename(file_name: str) -> List[dict]:
    url = f"{BASE}/api/search/metadata"
    payload = {"originalFileName": file_name}
    try:
        r = session.post(url, json=payload, timeout=60)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[WARN] search failed for {file_name}: {e}", file=sys.stderr)
        return []
    return data.get("assets", {}).get("items", [])


def find_asset_by_name(file_name: str) -> Optional[dict]:
    candidates = search_assets_by_filename(file_name)
    # Use exact match, since search may be imprecise
    for item in candidates:
        if item.get("originalFileName") == file_name:
            return item
    return None  # Do not return the first hit to avoid mistakes


def get_asset(asset_id: str) -> Optional[dict]:
    if not asset_id:
        return None
    url = f"{BASE}/api/assets/{asset_id}"
    try:
        r = session.get(url, timeout=60)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[WARN] get asset failed for {asset_id}: {e}", file=sys.stderr)
        return None


def get_albums_for_asset(asset_id: str) -> List[str]:
    if not asset_id:
        return []
    url = f"{BASE}/api/albums"
    params = {"assetId": asset_id}
    try:
        r = session.get(url, params=params, timeout=60)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[WARN] get albums failed for asset {asset_id}: {e}", file=sys.stderr)
        return []
    album_ids: List[str] = []
    for album in data or []:
        album_id = album.get("id")
        if album_id:
            album_ids.append(album_id)
    return album_ids


def build_album_asset_index() -> Dict[str, List[str]]:
    """Builds asset_id -> [album_id] index by fetching all albums once."""
    url = f"{BASE}/api/albums"
    try:
        r = session.get(url, timeout=60)
        r.raise_for_status()
        albums = r.json()
    except Exception as e:
        print(f"[WARN] get albums list failed: {e}", file=sys.stderr)
        return {}

    asset_to_albums: Dict[str, List[str]] = {}
    for album in albums or []:
        album_id = album.get("id")
        if not album_id:
            continue
        album_url = f"{BASE}/api/albums/{album_id}"
        try:
            r_album = session.get(album_url, timeout=120)
            r_album.raise_for_status()
            album_full = r_album.json()
        except Exception as e:
            print(
                f"[WARN] get album failed for {album_id} ({album_url}): {e}",
                file=sys.stderr,
            )
            continue

        for asset in album_full.get("assets", []) or []:
            asset_id = asset.get("id")
            if not asset_id:
                continue
            asset_to_albums.setdefault(asset_id, []).append(album_id)

    return asset_to_albums


def stack_assets(parent_id: str, child_ids: List[str]) -> None:
    if not parent_id or not child_ids:
        return
    url = f"{BASE}/api/stacks"

    # The primary asset (stack cover) goes first in the list
    all_asset_ids = [parent_id] + child_ids
    payload = {"assetIds": all_asset_ids}

    if DRY_RUN:
        print(f"[DRY] STACK assets={all_asset_ids} -> POST {url}")
        return

    r = session.post(url, json=payload, timeout=60)
    if not r.ok:
        # Include the new URL in the error for clarity
        print(f"[WARN] createStack on {url} -> {r.status_code} {r.text}", file=sys.stderr)


def add_to_albums(album_ids: List[str], asset_ids: List[str]) -> None:
    if not album_ids or not asset_ids:
        return

    for alb_id in album_ids:
        url = f"{BASE}/api/albums/{alb_id}/assets"

        # Request body remains the same (array of asset IDs)
        payload = {"ids": asset_ids}

        if DRY_RUN:
            print(f"[DRY] ADD assets={asset_ids} to album={alb_id}")
            continue

        print(f"[DEBUG] Adding assets {asset_ids} to album {alb_id}...")
        r = session.put(url, json=payload, timeout=60)
        if r.status_code != 200:
            print(f"[ERROR] Album Add Failed: {r.status_code} {r.text}", file=sys.stderr)
        else:
            print(f"[DEBUG] Album Add Success: {r.json()}")


def set_favorite(asset_id: str, is_fav: bool) -> None:
    if not asset_id:
        return
    if DRY_RUN:
        print(f"[DRY] FAVORITE asset={asset_id} value={is_fav}")
        return
    r = session.put(
        f"{BASE}/api/assets/{asset_id}", json={"isFavorite": is_fav}, timeout=60
    )
    if not r.ok:
        print(f"[WARN] setFavorite -> {r.status_code} {r.text}", file=sys.stderr)


def wait_for_asset(file_name: str) -> Optional[dict]:
    for i in range(SEARCH_RETRIES):
        asset = find_asset_by_name(file_name)
        if asset:
            return asset
        print(f"  ...waiting for asset {file_name} ({i+1}/{SEARCH_RETRIES})")
        time.sleep(SEARCH_SLEEP)
    return None


def index_asset_groups(root: Path) -> List[dict]:
    groups: Dict[Tuple[str, str], dict] = {}
    edited_suffix = "_edited"

    for dirpath, _, files in os.walk(root):
        for name in files:
            p = Path(dirpath) / name
            ext = p.suffix.lower()

            if ext not in PHOTO_EXT and ext not in VIDEO_EXT:
                continue

            stem = p.stem
            is_edited = stem.lower().endswith(edited_suffix)
            base = stem[: -len(edited_suffix)] if is_edited else stem
            key = (str(p.parent), base.lower())

            rec = groups.setdefault(key, {"base": base, "dir": p.parent})

            if ext in PHOTO_EXT:
                field = "edited_photo" if is_edited else "original_photo"
            else:  # VIDEO_EXT
                field = "edited_video" if is_edited else "original_video"

            # Avoid overwriting if multiple files exist (e.g., jpg and heic)
            if field not in rec:
                rec[field] = p

    return list(groups.values())


# ---------- Main flow ----------
def main():
    try:
        r = session.get(f"{BASE}/api/server/ping", timeout=10)
        r.raise_for_status()
        print("[OK] Immich reachable")
    except Exception as e:
        print(f"[WARN] Ping failed: {e}", file=sys.stderr)
        return

    groups = index_asset_groups(ROOT)
    print(f"Discovered {len(groups)} asset groups to process.")
    if not groups:
        return

    resume_index = 0
    try:
        checkpoint_path = Path(CHECKPOINT_FILE)
        if checkpoint_path.exists():
            resume_index = int(checkpoint_path.read_text(encoding="utf-8").strip() or 0)
    except Exception:
        resume_index = 0
    if resume_index > 0:
        print(f"[*] Resuming from group index {resume_index + 1}...")

    print("Building album asset index...")
    asset_album_index = build_album_asset_index()
    print(f"Album index built for {len(asset_album_index)} assets")

    # Preparation: compute hashes and check presence in Immich
    local_files_with_hash: List[Tuple[str, str]] = []
    path_map: Dict[str, dict] = {}
    for group in groups:
        for key in ["edited_photo", "original_photo", "edited_video", "original_video"]:
            if f := group.get(key):
                checksum = sha1_b64(f)
                local_files_with_hash.append((str(f), checksum))
                path_map[str(f)] = {"checksum": checksum, "group": group}

    print("Checking for existing assets by hash...")
    existing_assets_map: Dict[str, dict] = {}  # checksum -> asset_info
    for i in range(0, len(local_files_with_hash), API_CHUNK):
        chunk = local_files_with_hash[i : i + API_CHUNK]
        results = bulk_upload_check(chunk)
        for res in results:
            if res.get("action") == "reject" and res.get("reason") == "duplicate":
                local_path_str = res.get("id")
                checksum = path_map.get(local_path_str, {}).get("checksum")
                if checksum:
                    existing_assets_map[checksum] = {
                        "id": res.get("assetId"),
                        "path": Path(local_path_str),
                    }

    print(f"Found {len(existing_assets_map)} existing assets to be replaced.")

    # Atomic processing loop
    failures = 0
    for i, group in enumerate(groups):
        if i < resume_index:
            continue
        print(f"--- Group {i+1}/{len(groups)}: {group['base']} ---")

        files_to_upload: List[Path] = []
        if f := group.get("edited_photo"):
            files_to_upload.append(f)
        if f := group.get("original_photo"):
            files_to_upload.append(f)
        if f := group.get("edited_video"):
            files_to_upload.append(f)
        if f := group.get("original_video"):
            files_to_upload.append(f)

        if not files_to_upload:
            continue

        # Snapshot & Delete
        ids_to_delete: List[str] = []
        saved_state: Dict[str, object] = {"albums": [], "favorite_ids": set()}
        old_asset_id_by_file: Dict[str, str] = {}

        for f in files_to_upload:
            checksum = sha1_b64(f)
            if checksum in existing_assets_map:
                asset_id = existing_assets_map[checksum]["id"]
                ids_to_delete.append(asset_id)
                old_asset_id_by_file[str(f)] = asset_id
                if not saved_state.get("albums") or asset_id not in saved_state["favorite_ids"]:
                    asset_full = get_asset(asset_id)
                    if asset_full:
                        is_fav = asset_full.get("isFavorite", False)
                        albs = asset_album_index.get(asset_id, [])
                        if is_fav:
                            print(f"[DEBUG] Saved State: isFavorite=True for {asset_id}")
                            saved_state["favorite_ids"].add(asset_id)
                        if albs and not saved_state.get("albums"):
                            print(
                                f"[DEBUG] Saved State: Albums found: {len(albs)} for {asset_id}"
                            )
                            saved_state["albums"] = albs

        unique_ids_to_delete = list(set(ids_to_delete))
        if unique_ids_to_delete:
            print("[*] Old asset hashes (for recovery lookup):")
            for f in files_to_upload:
                checksum = sha1_b64(f)
                asset_info = existing_assets_map.get(checksum)
                if asset_info:
                    print(f"    {f} -> {checksum} (old id: {asset_info['id']})")
            print(
                f"[*] Deleting {len(unique_ids_to_delete)} old asset(s) for {group['base']}"
            )
            asset_delete_many(unique_ids_to_delete)
            time.sleep(2)
            empty_trash()

            # Wait for database indexes to clear (smart verification)
            if unique_ids_to_delete:
                print("[*] Verifying database index cleanup...")
                hashes_to_check = [(str(f), sha1_b64(f)) for f in files_to_upload]

                cleared = False
                for retry in range(10):  # Max 10 attempts (20s)
                    check_results = bulk_upload_check(hashes_to_check)
                    # If Immich no longer reports reject/duplicate for these hashes
                    if all(res.get("action") == "accept" for res in check_results):
                        cleared = True
                        break

                    print(
                        f"    [!] Index not cleared yet (collision risk), waiting... ({retry+1}/10)"
                    )
                    time.sleep(2)

                if not cleared:
                    print(
                        f"[ERROR] Database still sees hashes as duplicates for {group['base']}. Skipping upload to avoid crash.",
                        file=sys.stderr,
                    )
                    failures += 1
                    continue

        # Upload
        upload_cmd = ["immich", "upload"]
        if DRY_RUN:
            upload_cmd.append("--dry-run")
        for f in files_to_upload:
            upload_cmd.append(str(f))

        print(f"[*] Uploading {len(files_to_upload)} file(s)...")
        exit_code = subprocess.call(upload_cmd)

        if exit_code != 0:
            print(
                f"[ERROR] immich-cli failed with code {exit_code} for {group['base']}",
                file=sys.stderr,
            )
            failures += 1
            continue

        if DRY_RUN:
            print("[DRY] Skipping indexing/restore for this group.")
            continue

        print("[*] Waiting for indexing (3s)...")
        time.sleep(3)

        # Stack & Restore
        edited_photo = group.get("edited_photo")
        original_photo = group.get("original_photo")
        edited_video = group.get("edited_video")
        original_video = group.get("original_video")

        has_photos = bool(edited_photo or original_photo)
        if has_photos:
            edited_asset_file = edited_photo
            original_asset_file = original_photo
        else:
            edited_asset_file = edited_video
            original_asset_file = original_video

        if edited_asset_file:
            print(f"[DEBUG] Searching for new edited: {edited_asset_file.name}")
        new_edited = wait_for_asset(edited_asset_file.name) if edited_asset_file else None
        new_orig = wait_for_asset(original_asset_file.name) if original_asset_file else None

        if new_edited:
            print(f"[DEBUG] Found new edited ID: {new_edited['id']}")
        if new_orig:
            print(f"[DEBUG] Found new orig ID: {new_orig['id']}")

        main_asset = new_edited or new_orig
        if not main_asset:
            print(
                f"[ERROR] Uploaded primary asset NOT FOUND for {group['base']}. State may be lost!",
                file=sys.stderr,
            )
            failures += 1
            continue

        main_id = main_asset.get("id")

        # Manual stacking: apply to photos and videos (edited -> original)
        if new_edited and new_orig and new_orig.get("id") != main_id:
            refreshed_orig = get_asset(new_orig["id"])
            if refreshed_orig and not refreshed_orig.get("stackParentId"):
                print(f"[*] Stacking {new_orig.get('id')} -> {main_id}")
                stack_assets(parent_id=main_id, child_ids=[new_orig.get("id")])

        # Restore state (as it was)
        favorite_old_ids = saved_state.get("favorite_ids", set())
        favorite_new_ids: List[str] = []
        if new_edited and edited_asset_file:
            old_id = old_asset_id_by_file.get(str(edited_asset_file))
            if old_id in favorite_old_ids:
                favorite_new_ids.append(new_edited["id"])
        if new_orig and original_asset_file:
            old_id = old_asset_id_by_file.get(str(original_asset_file))
            if old_id in favorite_old_ids:
                favorite_new_ids.append(new_orig["id"])
        for fav_id in set(favorite_new_ids):
            print(f"[*] Restoring Favorite for {fav_id}")
            set_favorite(fav_id, True)
        album_to_new_assets: Dict[str, List[str]] = {}
        if new_edited and edited_asset_file:
            old_id = old_asset_id_by_file.get(str(edited_asset_file))
            if old_id:
                for alb_id in asset_album_index.get(old_id, []):
                    album_to_new_assets.setdefault(alb_id, []).append(new_edited["id"])
        if new_orig and original_asset_file:
            old_id = old_asset_id_by_file.get(str(original_asset_file))
            if old_id:
                for alb_id in asset_album_index.get(old_id, []):
                    album_to_new_assets.setdefault(alb_id, []).append(new_orig["id"])

        if album_to_new_assets:
            print(f"[*] Restoring to {len(album_to_new_assets)} albums...")
            for alb_id, asset_ids in album_to_new_assets.items():
                add_to_albums([alb_id], list(set(asset_ids)))
        elif ids_to_delete:
            print("[DEBUG] No albums to restore from snapshot.")

        if not DRY_RUN:
            try:
                Path(CHECKPOINT_FILE).write_text(str(i + 1), encoding="utf-8")
            except Exception:
                pass

    if failures > 0:
        print(f"Done with {failures} errors.", file=sys.stderr)
    else:
        print("All Done!")


if __name__ == "__main__":
    if not IMMICH_URL.startswith("http"):
        print("Please set IMMICH_URL and IMMICH_API_KEY env vars.", file=sys.stderr)
        sys.exit(2)
    main()
