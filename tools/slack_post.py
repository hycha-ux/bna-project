#!/usr/bin/env python3
"""빌디 봇 이름으로 슬랙에 메시지 전송. 토큰은 ~/.bna-slack.env 에서만 읽음.
사용: python3 tools/slack_post.py <channel_id> [thread_ts] < message.txt
"""
import json, os, sys, urllib.request

def load_token():
    p = os.path.expanduser("~/.bna-slack.env")
    for line in open(p):
        if line.startswith("SLACK_BOT_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"')
    sys.exit("SLACK_BOT_TOKEN not found in ~/.bna-slack.env")

def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    channel, thread = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else None)
    text = sys.stdin.read().strip()
    body = {"channel": channel, "text": text}
    if thread:
        body["thread_ts"] = thread
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {load_token()}",
                 "Content-Type": "application/json; charset=utf-8"})
    r = json.load(urllib.request.urlopen(req))
    if not r.get("ok"):
        sys.exit(f"slack error: {r.get('error')}")
    print("ok", r["channel"], r["ts"])

if __name__ == "__main__":
    main()
