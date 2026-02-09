# Immich MacOS Power Uploader: iCloud Sync with Stacking & Metadata Fix

This tool helps you seamlessly integrate your Apple Photos library with Immich, fixing common issues like incorrect timezones and unstacked original/edited versions.

## 😫 The Problem: iCloud + Immich Challenges

The standard Immich mobile app is great for backups, but it has limitations when syncing with iCloud Photos on iOS:

* **Incorrect Timezones:** Often fails to capture the correct timezone from iCloud metadata, leading to incorrect timestamps in Immich.
* **Unstacked Edits:** Loads both Original and Edited versions of photos as separate assets, cluttering your timeline instead of creating a clean stack.
* **Limited State Sync:** Doesn't offer flexible synchronization of Albums, Favorites, and other metadata.

## ✨ The Solution: MacOS Power Uploader

This set of scripts leverages the power of `osxphotos` and `immich-cli` to:

1. **Export Photos from Apple Photos.app with Accurate XMP Profiles:** Extracts photos and videos with correct timezone information and other metadata stored in XMP sidecar files.
2. **Automatically Stack Originals and Edited Versions:** Combines Original and Edited versions of photos into a single asset within Immich, creating a cleaner, more organized library.
3. **Replace "Mobile" Versions with Enhanced Mac Versions:** Replaces assets uploaded via the mobile app with versions exported from your Mac, ensuring consistency and metadata accuracy, **without losing album assignments or favorites**.

## 🚀 Quickstart: Get Up and Running

### Prerequisites

* **MacOS:** A Mac with access to your local Photos.app library (iCloud Photos must be synced locally).
* **Python 3:** Make sure you have Python 3 installed.
* **Node.js:** Required to install `@immich/cli`.
* **`osxphotos`:** Install via `pipx install osxphotos` (or `pip install osxphotos`).
* **`immich-cli`:** Install globally via `npm install -g @immich/cli`.

### Setup

1. **Clone the repository:**

    ```bash
    git clone https://github.com/the80hz/immich-osxphotos-sync.git
    cd immich-osxphotos-sync
    ```

2. **Configure Environment Variables:**

    ```bash
    cp .env.example .env
    # Edit .env and fill in your Immich URL and API Key
    nano .env
    ```

3. **Install Python Dependencies:**

    ```bash
    pip install -r requirements.txt
    ```

### Usage

1. **Export Photos from Apple Photos:**

    Run the `export_photos.sh` script to export your photos from Apple Photos to a local directory.  This script uses `osxphotos` to pull your photos, create XMP sidecar files, and organize them into folders by year and date.

    ```bash
    ./export_photos.sh
    ```

    **Configuration**: You can customize the export process using environment variables (see "Configuration" section below).

2. **Sync Photos to Immich:**

    Run the `immich_sync.py` script to upload the exported photos to Immich, fix metadata, and create stacks. This script uses `immich-cli` to upload the photos and updates existing assets where possible.

    ```bash
    python3 immich_sync.py
    ```

## ⚙️ Configuration

You can customize the behavior of the scripts using environment variables:

| Variable              | Description                                                                                                | Default Value                     |
| --------------------- | ---------------------------------------------------------------------------------------------------------- | --------------------------------- |
| `IMMICH_URL`          | The URL of your Immich instance (without `/api`).  Example: `https://immich.example.com`                   | **Required**                      |
| `IMMICH_API_KEY`      | Your Immich API Key.  Create one in the Immich Admin settings.                                           | **Required**                      |
| `ROOT`                | The base directory for the exported photos.                                                              | `$HOME/Downloads/reexport`       |
| `EXPORT_ALBUM`        | The name of the album in Photos.app to export.                                                            | `reexport`                        |
| `EXPORT_USE_JPEG_EXT` | Use `.jpg` extension for edited photos (1 for yes, 0 for no).                                               | `0`                               |
| `EXPORT_DB_PATH`      | Path to the `osxphotos` export database.  Used for incremental exports.                                  | `$HOME/osxphotos-export.db`      |
| `EXPORT_REPORT_FILE`  | Path to the `osxphotos` export report file.                                                               | `$HOME/osxphotos-export.csv`      |
| `EXPORT_PHOTOS_LIBRARY` | Path to a specific Photos library to use (optional).                                                   | *(unset)*                        |
| `DRY_RUN`             | Enable dry run mode (1 for yes, 0 for no). Runs `immich upload --dry-run` and skips restore steps.         | `0`                               |

**Example `.env` file:**

```env
IMMICH_URL=https://your-immich-instance.com
IMMICH_API_KEY=YOUR_API_KEY
ROOT=/Users/youruser/Pictures/immich_export
EXPORT_ALBUM=reexport
EXPORT_PHOTOS_LIBRARY=/Users/youruser/Pictures/Photos Library.photoslibrary
```

## ⚠️ Disclaimer

**This script performs potentially destructive operations (deleting and replacing assets in your Immich library). Use it at your own risk!  Always back up your Immich library before running this script.**

* **Test Thoroughly:**  Run the script in dry-run mode (`DRY_RUN=1`) and carefully review the output before making any changes.
* **Backup First:**  Ensure you have a recent backup of your Immich library in case something goes wrong.
* **Understand the Code:**  Familiarize yourself with the code before running it to ensure it aligns with your intended use.

## Contributing

Contributions are welcome! Please submit pull requests or create issues to suggest improvements or report bugs.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Credits

* [The Immich Team](https://github.com/immich-app) for creating an awesome self-hosted photo solution.
* [The `osxphotos` project](https://github.com/RhetTbull/osxphotos) for providing a powerful tool to interact with Apple Photos.
