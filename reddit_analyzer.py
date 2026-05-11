#!/usr/bin/env python3
"""
Reddit Subreddit Analyzer — no API keys required
Uses Reddit's public JSON endpoints (no auth needed for public data).

Install: pip install requests rich pandas
Run:     python reddit_analyzer.py
"""

import time
import json
import os
import re
from collections import defaultdict, Counter

import requests
import pandas as pd
from rich.console import Console
from rich.table import Table
from rich.progress import track
from rich import print as rprint

# CONFIG
SUBREDDITS = [
    "preppers", "bugout", "survival", "SurvivalistIdeas", "SHTF",
    "72hourkits", "urbansurvival", "disasterpreparedness",
    "EDC", "myog",
    "homesteading", "selfreliance", "OffGrid", "homestead", "permaculture",
    "FoodStorage", "Canning", "Frugal",
    "bushcraft", "camping", "ultralight",
    "PandemicPreps", "FirstAid", "Amateur_Radio",
]

POST_LIMIT    = 100
TOP_N_USERS   = 25
TOP_N_TOPICS  = 30
OUTPUT_DIR    = "reddit_output"
DELAY         = 2.0   # seconds between requests - keep this!

HEADERS = {"User-Agent": "prepper-research-script/1.0 (personal research, no login)"}
BASE    = "https://www.reddit.com"
console = Console()

STOPWORDS = set("""
a about after all also am an and any are as at be because been before
being between both but by came can come could did do does doing done
during each for from get got had has have he her here him himself his
how i if in into is it its just know let like make many me might more
most much my no not now of on only or other our out over own people
re said same see should since so some still such take than that the
their them then there these they this those through to too under until
up very was we well were what when where which while who will with
would you your yourself https http www com reddit
""".split())

JUNK = set("""
post comment edit thread question something anything nothing deleted removed
""".split())


def reddit_get(url, params=None):
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, params=params, timeout=15)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 30))
                console.print(f"[yellow]Rate limited - waiting {wait}s[/yellow]")
                time.sleep(wait)
                continue
            if r.status_code != 200:
                console.print(f"[red]HTTP {r.status_code} for {url}[/red]")
                return None
            return r.json()
        except Exception as e:
            console.print(f"[red]Request error: {e}[/red]")
            time.sleep(5)
    return None


def extract_keywords(text):
    words = re.findall(r"\b[a-z][a-z\-']{2,}\b", text.lower())
    return [w for w in words if w not in STOPWORDS and w not in JUNK]


def fetch_posts(sub):
    posts, after = [], None
    while len(posts) < POST_LIMIT:
        params = {"limit": min(100, POST_LIMIT - len(posts)), "raw_json": 1}
        if after:
            params["after"] = after
        data = reddit_get(f"{BASE}/r/{sub}/hot.json", params)
        if not data:
            break
        children = data.get("data", {}).get("children", [])
        if not children:
            break
        for child in children:
            post = child.get("data", {})
            if not post.get("stickied"):
                posts.append(post)
        after = data.get("data", {}).get("after")
        if not after:
            break
        time.sleep(DELAY)
    return posts


def fetch_comments(sub, post_id):
    data = reddit_get(f"{BASE}/r/{sub}/comments/{post_id}.json",
                      {"limit": 50, "depth": 1, "raw_json": 1})
    if not data or len(data) < 2:
        return []
    comments = []
    for child in data[1].get("data", {}).get("children", []):
        c = child.get("data", {})
        if c.get("body") and c.get("author") not in ("AutoModerator", "[deleted]", None):
            comments.append(c)
    return comments


def analyze_subreddit(sub):
    posts = fetch_posts(sub)
    if not posts:
        console.print(f"[red]  No posts found for r/{sub}[/red]")
        return None

    contributor_posts    = defaultdict(list)
    contributor_comments = defaultdict(list)
    topic_words          = Counter()
    top_posts            = []

    for i, post in enumerate(posts):
        author = post.get("author", "[deleted]")
        score  = post.get("score", 0)
        title  = post.get("title", "")
        body   = post.get("selftext", "") or ""
        pid    = post.get("id", "")

        if author not in ("[deleted]", "AutoModerator"):
            contributor_posts[author].append(score)

        topic_words.update(extract_keywords(title + " " + body))
        top_posts.append((title, score, f"https://reddit.com{post.get('permalink','')}"))

        if i % 5 == 0 and pid:
            time.sleep(DELAY)
            for c in fetch_comments(sub, pid):
                cauthor = c.get("author", "[deleted]")
                if cauthor not in ("[deleted]", "AutoModerator"):
                    contributor_comments[cauthor].append(c.get("score", 0))
                topic_words.update(extract_keywords(c.get("body", "")))

    all_users = set(contributor_posts) | set(contributor_comments)
    contributors = []
    for user in all_users:
        pc = contributor_posts.get(user, [])
        cc = contributor_comments.get(user, [])
        all_scores = pc + cc
        if not all_scores:
            continue
        contributors.append({
            "username":      user,
            "post_count":    len(pc),
            "comment_count": len(cc),
            "total_score":   sum(all_scores),
            "avg_score":     round(sum(all_scores) / len(all_scores), 1),
        })

    contributors.sort(key=lambda x: x["total_score"], reverse=True)
    top_posts.sort(key=lambda x: x[1], reverse=True)
    return {
        "contributors": contributors[:TOP_N_USERS],
        "topics":       topic_words.most_common(TOP_N_TOPICS),
        "top_posts":    top_posts[:10],
    }


def print_report(sub, data):
    rprint(f"\n[bold cyan]=== r/{sub} ===[/bold cyan]")
    t = Table(show_lines=False)
    t.add_column("#",           style="dim",   width=4)
    t.add_column("Username",    style="bold",  min_width=20)
    t.add_column("Posts",       justify="right")
    t.add_column("Comments",    justify="right")
    t.add_column("Total Score", justify="right", style="green")
    t.add_column("Avg Score",   justify="right")
    for i, c in enumerate(data["contributors"], 1):
        t.add_row(str(i), c["username"], str(c["post_count"]),
                  str(c["comment_count"]), str(c["total_score"]), str(c["avg_score"]))
    console.print(t)
    rprint(f"\n[bold yellow]Top Topics[/bold yellow]")
    rprint("  " + "  .  ".join(f"{w} ({n})" for w, n in data["topics"]))
    rprint(f"\n[bold magenta]Top Posts[/bold magenta]")
    for title, score, _ in data["top_posts"][:5]:
        rprint(f"  [green]^{score:>6}[/green]  {title[:80]}")


def save_outputs(all_data):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(f"{OUTPUT_DIR}/full_data.json", "w") as f:
        json.dump(all_data, f, indent=2)

    rows = []
    for sub, data in all_data.items():
        if data:
            for rank, c in enumerate(data["contributors"], 1):
                rows.append({"subreddit": sub, "rank": rank, **c})
    pd.DataFrame(rows).to_csv(f"{OUTPUT_DIR}/contributors.csv", index=False)

    topic_rows = []
    for sub, data in all_data.items():
        if data:
            for word, count in data["topics"]:
                topic_rows.append({"subreddit": sub, "topic": word, "count": count})
    pd.DataFrame(topic_rows).to_csv(f"{OUTPUT_DIR}/topics.csv", index=False)

    user_subs = defaultdict(list)
    for sub, data in all_data.items():
        if data:
            for c in data["contributors"]:
                user_subs[c["username"]].append(sub)
    power_users = [
        {"username": u, "subreddit_count": len(s), "subreddits": ", ".join(s)}
        for u, s in user_subs.items() if len(s) > 1
    ]
    power_users.sort(key=lambda x: x["subreddit_count"], reverse=True)
    pd.DataFrame(power_users).to_csv(f"{OUTPUT_DIR}/power_users.csv", index=False)

    console.print(f"\n[bold green]Done! Saved to ./{OUTPUT_DIR}/[/bold green]")
    console.print("  contributors.csv  - ranked contributors per sub")
    console.print("  topics.csv        - keyword frequencies per sub")
    console.print("  power_users.csv   - users active across multiple subs  <- start here")
    console.print("  full_data.json    - everything")


def main():
    console.print("\n[bold]Reddit Subreddit Analyzer[/bold] [dim](no API key needed)[/dim]")
    console.print(f"Analyzing {len(SUBREDDITS)} subreddits...\n")
    all_data = {}
    for sub in track(SUBREDDITS, description="Scanning subreddits..."):
        all_data[sub] = analyze_subreddit(sub)
        time.sleep(DELAY)
    for sub, data in all_data.items():
        if data:
            print_report(sub, data)
    save_outputs(all_data)


if __name__ == "__main__":
    main()
