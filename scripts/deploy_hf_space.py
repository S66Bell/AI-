"""Deploy JARVIS to a Hugging Face Space from CI.

Run by .github/workflows/deploy-hf-space.yml. Using the HF_TOKEN secret it:
  1. creates the Space (Docker SDK) under your account if it doesn't exist,
  2. sets the Space's runtime secrets/variables (so the deployed app works),
  3. uploads this repo's files (with a Space-flavoured README front matter).

Everything happens on GitHub's runners + Hugging Face — no local machine.

Env (provided by the workflow):
  HF_TOKEN           required — your Hugging Face write token.
  HF_SPACE_NAME      optional — Space name (default: "jarvis").
  JARVIS_WEB_TOKEN   optional — if set, gates the public app; copied to the Space.
  JARVIS_HF_MODEL    optional — served model id for the brain.
"""

from __future__ import annotations

import os
import pathlib
import sys
import textwrap

SPACE_README = """\
---
title: JARVIS
emoji: 🤖
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# JARVIS

A private, self-hosted JARVIS-style AI assistant, deployed automatically from
GitHub Actions. The brain runs on Hugging Face Inference; the app is this Space.

Open the Space, go to **Settings** in the app, and paste your access token
(if one was configured) to start talking.
"""


def main() -> int:
    token = os.environ.get("HF_TOKEN", "").strip()
    if not token:
        print(
            "HF_TOKEN is not set — skipping Hugging Face deploy.\n"
            "Add it under GitHub → Settings → Secrets and variables → Actions "
            "to enable automatic deployment."
        )
        return 0

    from huggingface_hub import HfApi

    api = HfApi(token=token)
    username = api.whoami()["name"]
    space_name = os.environ.get("HF_SPACE_NAME", "").strip() or "jarvis"
    repo_id = f"{username}/{space_name}"
    print(f"→ Target Space: {repo_id}")

    api.create_repo(
        repo_id=repo_id, repo_type="space", space_sdk="docker", exist_ok=True
    )

    # Runtime config for the deployed container.
    api.add_space_secret(repo_id, "HF_TOKEN", token)
    api.add_space_variable(repo_id, "JARVIS_PROVIDER", "hf")
    web_token = os.environ.get("JARVIS_WEB_TOKEN", "").strip()
    if web_token:
        api.add_space_secret(repo_id, "JARVIS_WEB_TOKEN", web_token)
        print("→ Set JARVIS_WEB_TOKEN secret on the Space (app is gated).")
    else:
        print("⚠ No JARVIS_WEB_TOKEN set — the Space app will be publicly usable.")
    model = os.environ.get("JARVIS_HF_MODEL", "").strip()
    if model:
        api.add_space_variable(repo_id, "JARVIS_HF_MODEL", model)
    # Reply language. Defaults to Japanese for this deployment; override with a
    # JARVIS_LANGUAGE repo variable (e.g. "English") to change it.
    language = os.environ.get("JARVIS_LANGUAGE", "").strip() or "日本語"
    api.add_space_variable(repo_id, "JARVIS_LANGUAGE", language)
    print(f"→ Reply language: {language}")

    # Give the Space its required README front matter (CI checkout only — this
    # does not change the project README on GitHub).
    pathlib.Path("README.md").write_text(SPACE_README, encoding="utf-8")

    print("→ Uploading files…")
    api.upload_folder(
        repo_id=repo_id,
        repo_type="space",
        folder_path=".",
        commit_message="Deploy from GitHub Actions",
        ignore_patterns=[
            ".git*",
            ".github/*",
            "scripts/*",
            "**/__pycache__/*",
            "*.pyc",
            ".venv/*",
            "venv/*",
            ".jarvis/*",
            "DEPLOY_HF.md",
        ],
    )
    print(f"✓ Deployed: https://huggingface.co/spaces/{repo_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
