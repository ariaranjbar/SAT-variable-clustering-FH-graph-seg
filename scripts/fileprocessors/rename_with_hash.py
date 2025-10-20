import argparse
import csv
import logging
from pathlib import Path
from typing import Optional


logger = logging.getLogger(__name__)


def main(
    folder_path: str,
    csv_path: str,
    extension: Optional[str] = None,
    suffix: Optional[str] = None,
) -> None:
    folder = Path(folder_path)
    csv_file = Path(csv_path)

    logger.info("Starting rename run")
    logger.info("Folder: %s", folder.resolve())
    logger.info("CSV: %s", csv_file.resolve())
    ext_filter = None
    if extension:
        ext_filter = extension if extension.startswith(".") else f".{extension}"
        ext_filter = ext_filter.lower()
        logger.info("Extension filter enabled: %s", ext_filter)
    suffix_filter = suffix or None
    if suffix_filter:
        logger.info("Suffix filter enabled: %s", suffix_filter)

    if not folder.is_dir():
        logger.error("Folder not found: %s", folder)
        raise ValueError(f"Folder not found: {folder}")
    if not csv_file.is_file():
        logger.error("CSV not found: %s", csv_file)
        raise ValueError(f"CSV not found: {csv_file}")

    # Build lookup: filename -> hash
    name_to_hash = {}
    with csv_file.open(newline="", encoding="utf-8") as handle:
        header_reader = csv.reader(handle)
        header = next(header_reader, None)
        if not header:
            logger.error("CSV is empty or missing header row")
            raise ValueError("CSV is empty or missing header row.")
        if "filename" not in header or "hash" not in header:
            logger.error("CSV missing required columns: %s", header)
            raise ValueError("CSV must include 'filename' and 'hash' columns.")
        reader = csv.DictReader(handle, fieldnames=header)
        for row in reader:
            filename = row.get("filename")
            hash_value = row.get("hash")
            if filename and hash_value:
                name_to_hash[filename] = hash_value
                logger.debug("Loaded hash for %s -> %s", filename, hash_value)
            else:
                logger.debug("Skipping row without filename/hash: %s", row)

    logger.info("Loaded %d filename->hash mappings", len(name_to_hash))

    # Rename files in folder
    rename_count = 0
    missing_hash = []
    for entry in folder.iterdir():
        if not entry.is_file():
            logger.debug("Skipping non-file entry: %s", entry.name)
            continue
        if ext_filter and not entry.name.lower().endswith(ext_filter):
            logger.debug("Skipping due to extension filter: %s", entry.name)
            actual_ending = entry.name[-len(ext_filter) :]
            logger.debug("  actual ending: %s", actual_ending)
            continue
        effective_name = entry.name
        if suffix_filter:
            suffix_idx = effective_name.rfind(suffix_filter)
            if suffix_idx != -1:
                remainder = effective_name[suffix_idx + len(suffix_filter) :]
                if remainder.startswith("."):
                    effective_name = effective_name[:suffix_idx] + remainder
                    logger.debug(
                        "Applied suffix filter: %s -> %s", entry.name, effective_name
                    )
                else:
                    logger.debug(
                        "Suffix filter found but not before extension for %s",
                        entry.name,
                    )
            else:
                logger.debug(
                    "Suffix filter did not match for %s", entry.name
                )
        hash_value = name_to_hash.get(effective_name)
        if not hash_value:
            missing_hash.append(effective_name)
            logger.debug(
                "No hash found for %s (lookup name %s)", entry.name, effective_name
            )
            continue
        new_name = f"{hash_value}-{effective_name}"
        target = entry.with_name(new_name)
        if target.exists():
            logger.error("Target already exists, skipping rename: %s", target.name)
            raise FileExistsError(f"Target already exists: {target}")
        entry.rename(target)
        rename_count += 1
        logger.info("Renamed %s -> %s", entry.name, new_name)

    if missing_hash:
        logger.info("Skipped %d files without matching hash", len(missing_hash))
        for name in missing_hash:
            logger.debug("Missing hash entry for %s", name)
    logger.info("Completed rename run with %d file(s) renamed", rename_count)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Rename files by prefixing hashes from a CSV mapping."
    )
    parser.add_argument("folder_path", help="Folder containing files to rename")
    parser.add_argument("csv_path", help="CSV file with filename/hash columns")
    parser.add_argument(
        "-e",
        "--extension",
        help="Only process files with the given extension (with or without leading dot)",
    )
    parser.add_argument(
        "-s",
        "--suffix",
        help="Treat files ending with this suffix before the extension as if the suffix were absent",
    )
    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(levelname)s:%(message)s",
    )
    main(
        args.folder_path,
        args.csv_path,
        extension=args.extension,
        suffix=args.suffix,
    )