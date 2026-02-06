#!/usr/bin/env python3
"""
upload_to_drive.py
Automatically uploads any files from ~/Downloads/chatgpt_exports/
to your Google Drive tmp folder.
"""

from __future__ import print_function
import os
import glob
import pickle
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# ====== CONFIG ======
FOLDER_ID = "10ThCkNa6jHUFy9T6EWeGXYUXrIANbo9D"  # your tmp folder
LOCAL_EXPORT_DIR = os.path.expanduser("~/Downloads/chatgpt_exports/")
SCOPES = ["https://www.googleapis.com/auth/drive.file"]
# =====================


def authenticate():
    """Authenticate with Google Drive API, storing token for reuse."""
    creds = None
    token_path = os.path.expanduser("~/.config/google-drive-uploader/token.pickle")

    if os.path.exists(token_path):
        with open(token_path, "rb") as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            creds_path = os.path.expanduser("~/google-drive-uploader/credentials.json")
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=0)
        os.makedirs(os.path.dirname(token_path), exist_ok=True)
        with open(token_path, "wb") as token:
            pickle.dump(creds, token)

    return creds


def upload_file(service, file_path):
    """Upload a single file to Google Drive."""
    file_name = os.path.basename(file_path)
    file_metadata = {"name": file_name, "parents": [FOLDER_ID]}
    media = MediaFileUpload(file_path, resumable=True)
    uploaded = service.files().create(
        body=file_metadata, media_body=media, fields="id, name"
    ).execute()
    print(f"✅ Uploaded: {file_name} (ID: {uploaded.get('id')})")


def main():
    creds = authenticate()
    service = build("drive", "v3", credentials=creds)

    if not os.path.exists(LOCAL_EXPORT_DIR):
        print(f"⚠️ Directory not found: {LOCAL_EXPORT_DIR}")
        return

    files = glob.glob(os.path.join(LOCAL_EXPORT_DIR, "*"))
    if not files:
        print(f"ℹ️ No files found in {LOCAL_EXPORT_DIR}")
        return

    print(f"Found {len(files)} file(s) to upload from {LOCAL_EXPORT_DIR}:")
    for f in files:
        print("  -", os.path.basename(f))

    for f in files:
        try:
            upload_file(service, f)
        except Exception as e:
            print(f"❌ Failed to upload {f}: {e}")


if __name__ == "__main__":
    main()
