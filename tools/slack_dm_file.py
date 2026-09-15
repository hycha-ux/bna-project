#!/usr/bin/env python3
"""빌디 봇 이름으로 슬랙 DM에 파일을 올린다. 토큰은 ~/.bna-slack.env 에서만 읽음.
사용: python3 tools/slack_dm_file.py <user_id> <file> [file...] < message.txt
"""
import json, mimetypes, os, sys, urllib.request, uuid

def token():
    for line in open(os.path.expanduser("~/.bna-slack.env")):
        if line.startswith("SLACK_BOT_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"')
    sys.exit("SLACK_BOT_TOKEN not found in ~/.bna-slack.env")

def api(method, tok, data=None, form=False):
    if form:
        body = urllib.parse.urlencode(data).encode(); ct = "application/x-www-form-urlencoded"
    else:
        body = json.dumps(data).encode(); ct = "application/json; charset=utf-8"
    req = urllib.request.Request(f"https://slack.com/api/{method}", data=body,
        headers={"Authorization": f"Bearer {tok}", "Content-Type": ct})
    r = json.load(urllib.request.urlopen(req))
    if not r.get("ok"): sys.exit(f"slack error {method}: {r.get('error')}")
    return r

def main():
    import urllib.parse
    if len(sys.argv) < 3: sys.exit(__doc__)
    user, files = sys.argv[1], sys.argv[2:]
    text = sys.stdin.read().strip()
    tok = token()
    ch = api("conversations.open", tok, {"users": user})["channel"]["id"]
    ups = []
    for f in files:
        data = open(f, "rb").read(); name = os.path.basename(f)
        u = api("files.getUploadURLExternal", tok, {"filename": name, "length": len(data)}, form=True)
        req = urllib.request.Request(u["upload_url"], data=data, method="POST",
            headers={"Content-Type": mimetypes.guess_type(name)[0] or "application/octet-stream"})
        urllib.request.urlopen(req).read()
        ups.append({"id": u["file_id"], "title": name})
    r = api("files.completeUploadExternal", tok, {"files": ups, "channel_id": ch, "initial_comment": text})
    print("ok", ch, [f["id"] for f in r["files"]])

if __name__ == "__main__":
    main()
