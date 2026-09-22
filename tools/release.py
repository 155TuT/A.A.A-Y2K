"""Publish only a complete, verified native matrix from the current commit."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess

from build_support import ROOT, command, digest, project_metadata, source_snapshot

TARGETS = {
    "windows-x64": {"-Setup.exe"},
    "macos-arm64": {".pkg", ".dmg"},
    "macos-x64": {".pkg", ".dmg"},
    "linux-x64": {"-portable.zip"},
}


def collect_assets(directory: Path, commit: str, *, source_root: Path = ROOT) -> list[Path]:
    assets = []
    seen = set()
    metadata = project_metadata(source_root)
    version, app_name = metadata["__version__"], metadata["APP_NAME"]
    snapshot = source_snapshot(source_root)
    shared_tests = None
    for path in sorted(directory.rglob("*-manifest.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        target = manifest["target"]
        if target not in TARGETS or target in seen:
            raise RuntimeError(f"Unexpected or duplicate target: {target}")
        seen.add(target)
        if manifest["version"] != version or manifest["commit"] != commit or manifest["dirty"]:
            raise RuntimeError(f"Version, commit or clean-tree mismatch: {target}")
        if manifest["source_files_sha256"] != snapshot or not manifest["source_frozen_parity"]:
            raise RuntimeError(f"Source or test parity mismatch: {target}")
        tests = sorted(manifest["test_ids"])
        if not tests or len(tests) != manifest["tests_run"] or len(set(tests)) != len(tests):
            raise RuntimeError(f"Invalid test inventory: {target}")
        if shared_tests is not None and tests != shared_tests:
            raise RuntimeError("Platforms did not run the same shared contract.")
        shared_tests = tests
        expected = {f"{app_name}-{version}-{target}{suffix}" for suffix in TARGETS[target]}
        if set(manifest["assets"]) != expected or set(manifest["install_verification"]) != expected:
            raise RuntimeError(f"Incomplete installation artifacts: {target}")
        for name, checksum in manifest["assets"].items():
            result = manifest["install_verification"][name]
            if (not result.get("successful") or not result.get("source_frozen_parity")
                    or not result.get("launch_and_shutdown") or sorted(result.get("test_ids", [])) != tests):
                raise RuntimeError(f"Unverified installed application: {name}")
            asset = path.parent / name
            if digest(asset) != checksum:
                raise RuntimeError(f"Asset checksum mismatch: {name}")
            assets.append(asset)
        archive = manifest["verification_archive"]
        if Path(archive["name"]).name != archive["name"]:
            raise RuntimeError("Invalid verification archive name.")
        audit = path.parent / archive["name"]
        if digest(audit) != archive["sha256"]:
            raise RuntimeError("Verification archive checksum mismatch.")
        assets.extend((path, audit))
    if seen != set(TARGETS):
        raise RuntimeError(f"Missing native targets: {sorted(set(TARGETS) - seen)}")
    if len({path.name for path in assets}) != len(assets):
        raise RuntimeError("Release asset names must be unique.")
    return sorted(assets, key=lambda path: path.name)


def github_api(endpoint: str, *, paginate: bool = False) -> dict | list:
    arguments = ["gh", "api", endpoint]
    if paginate:
        arguments.extend(("--paginate", "--slurp"))
    response = subprocess.run(arguments,
                              encoding="utf-8", capture_output=True, check=False)
    if response.returncode:
        raise RuntimeError(response.stderr)
    return json.loads(response.stdout)


def github_release(repo: str, tag: str) -> dict | None:
    # The tag endpoint only returns published releases. Listing also finds drafts
    # when the authenticated caller has push access, including resumable uploads.
    pages = github_api(f"repos/{repo}/releases?per_page=100", paginate=True)
    return next((item for page in pages for item in page if item["tag_name"] == tag), None)


def validate_source_run(repo: str, run_id: int, commit: str) -> None:
    run = github_api(f"repos/{repo}/actions/runs/{run_id}")
    if (run["head_sha"] != commit or run["status"] != "completed"
            or run["path"] != ".github/workflows/build.yml"):
        raise RuntimeError("Artifacts must come from the completed native workflow at this source commit.")
    pages = github_api(f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=100", paginate=True)
    jobs = {job["name"]: job["conclusion"] for page in pages for job in page["jobs"]}
    if any(jobs.get(f"Build and install ({target})") != "success" for target in TARGETS):
        raise RuntimeError("Every native build and installation job must have passed.")


def publish(directory: Path, *, source_root: Path = ROOT, source_run: int | None = None) -> None:
    metadata = project_metadata(source_root)
    version, app_name = metadata["__version__"], metadata["APP_NAME"]
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source_root, text=True).strip()
    repo = os.environ["GITHUB_REPOSITORY"]
    if source_run is not None:
        validate_source_run(repo, source_run, commit)
    assets = collect_assets(directory, commit, source_root=source_root)
    checksum_file = directory / "SHA256SUMS.txt"
    checksum_file.write_text("".join(f"{digest(path)}  {path.name}\n" for path in assets), encoding="utf-8")
    assets.append(checksum_file)
    tag = f"v{version}"
    existing_tag = subprocess.run(["git", "rev-parse", "--verify", f"refs/tags/{tag}^{{}}"],
                                  cwd=source_root, text=True, capture_output=True, check=False)
    if existing_tag.returncode == 0 and existing_tag.stdout.strip() != commit:
        raise RuntimeError("Release tag already points at a different commit; refusing to move it.")
    notes = source_root / "docs/releases" / f"{tag}.md"
    if not notes.is_file():
        raise RuntimeError(f"Missing release notes: {notes}")
    existing = github_release(repo, tag)
    if existing is not None and not existing["draft"]:
        raise RuntimeError("The release is already public; refusing to overwrite published binaries.")
    if existing is None:
        command(["gh", "release", "create", tag, "--repo", repo, "--draft", "--target", commit,
                 "--title", f"{app_name} {version}", "--notes-file", str(notes)])
    else:
        command(["gh", "release", "edit", tag, "--repo", repo, "--notes-file", str(notes)])
    command(["gh", "release", "upload", tag, "--repo", repo, "--clobber", *map(str, assets)])
    uploaded = github_release(repo, tag)
    if uploaded is None:
        raise RuntimeError("Uploaded draft could not be found; refusing to publish.")
    remote = {asset["name"]: asset for asset in uploaded["assets"]}
    if set(remote) != {path.name for path in assets}:
        raise RuntimeError("GitHub release asset inventory differs; leaving it as a draft.")
    for path in assets:
        if (remote[path.name]["size"] != path.stat().st_size
                or remote[path.name].get("digest") != f"sha256:{digest(path)}"):
            raise RuntimeError(f"Uploaded checksum/size mismatch: {path.name}; leaving release as a draft.")
    command(["gh", "release", "edit", tag, "--repo", repo, "--draft=false", "--latest"])
    print(f"Published https://github.com/{repo}/releases/tag/{tag}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--source-root", type=Path, default=ROOT,
                        help="Clean checkout of the commit used to build the artifacts")
    parser.add_argument("--source-run", type=int, help="Completed native Actions run to validate when resuming")
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    if args.publish:
        publish(args.directory, source_root=source_root, source_run=args.source_run)
    else:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source_root, text=True).strip()
        for asset in collect_assets(args.directory, commit, source_root=source_root):
            print(asset.name)
