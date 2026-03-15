#!/usr/bin/env python3
"""
Build + publish script for AgentLens Python SDK.

Usage:
  python build_and_publish.py          # Build only (dry-run)
  python build_and_publish.py --upload # Build + upload to PyPI
  python build_and_publish.py --test   # Build + upload to TestPyPI
"""

import os
import sys
import shutil
import subprocess

SDK_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(SDK_DIR, "..", ".."))

def main():
    # 1. Copy README.md and LICENSE into sdk/python/ for packaging
    for f in ["README.md", "LICENSE"]:
        src = os.path.join(ROOT_DIR, f)
        dst = os.path.join(SDK_DIR, f)
        if os.path.exists(src):
            shutil.copy2(src, dst)
            print(f"  Copied {f}")

    # 2. Clean old builds
    for d in ["dist", "build", "agentlens.egg-info"]:
        p = os.path.join(SDK_DIR, d)
        if os.path.exists(p):
            shutil.rmtree(p)
            print(f"  Cleaned {d}/")

    # 3. Build
    print("\n  Building...")
    result = subprocess.run(
        [sys.executable, "-m", "build"],
        cwd=SDK_DIR,
    )
    if result.returncode != 0:
        print("  Build failed!")
        sys.exit(1)
    print("  Build succeeded!")

    # 4. Check with twine
    print("\n  Checking with twine...")
    subprocess.run(
        [sys.executable, "-m", "twine", "check", "dist/*"],
        cwd=SDK_DIR,
    )

    # 5. Upload if requested
    if "--upload" in sys.argv:
        print("\n  Uploading to PyPI...")
        subprocess.run(
            [sys.executable, "-m", "twine", "upload", "dist/*"],
            cwd=SDK_DIR,
        )
    elif "--test" in sys.argv:
        print("\n  Uploading to TestPyPI...")
        subprocess.run(
            [sys.executable, "-m", "twine", "upload", "--repository", "testpypi", "dist/*"],
            cwd=SDK_DIR,
        )
    else:
        print("\n  Dry run complete. To upload:")
        print("    python build_and_publish.py --test   # TestPyPI")
        print("    python build_and_publish.py --upload  # PyPI (production)")

    # 6. Clean up copied files
    for f in ["README.md", "LICENSE"]:
        p = os.path.join(SDK_DIR, f)
        # Don't remove if it was already there before
        if os.path.exists(p) and os.path.exists(os.path.join(ROOT_DIR, f)):
            pass  # Keep for now; .gitignore should handle it


if __name__ == "__main__":
    main()
