#!/usr/bin/env python3
"""
Reddit Subreddit Analyzer
Pulls top contributors and trending topics from a list of subreddits.
Requires: pip install praw rich pandas

Setup:
  1. Go to https://www.reddit.com/prefs/apps
  2. Click "create another app" -> choose "script"
  3. Fill in name/description, set redirect URI to http://localhost:8080
  4. Copy your client_id (under the app name) and client_secret
  5. Fill in the CONFIG block below
"""

import praw
import pandas as pd
from collections import defaultdict, Counter
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.progress import track
from rich import print as rprint
import re
import json
import os

# CONFIG - fill these in
REDDIT_CLIENT_ID     = "YOUR_CLIENT_ID"
REDDIT_CLIENT_SECRET = "YOUR_CLIENT_SECRET"
REDDIT_USER_AGENT    = "prepper-research-bot/1.0 by YOUR_USERNAME"

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
COMMENT_LIMIT = 50
TOP_N_USERS   = 25
TOP_N_TOPICS  = 30
OUTPUT_DIR    = "reddit_output"

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
would you your yourself
""".split())

JUNK_WORDS = set("""
post comment edit thread question anyone something anything nothing
everyone anyone someone nobody somebody anybody everybody
""".split())


def make_reddit():
    return praw.Reddit(
        client_id=REDDIT_CLIENT_ID,
        client_secret=REDDIT_CLIENT_SECRET,
        user_agent=REDDIT_USER_AGENT,
    )


def extract_keywords(text):
    text = text.lower()
    words = re.findall(r"\b[a-z][a-z\-']{2,}\b", text)
    return [w for w in words if w not in STOPWORDS and w not in JUNK_WORDS and not w.isdigit()]


def analyze_subreddit(reddit, sub_name):
    sub = reddit.subreddit(sub_name)
    contributor_posts    = defaultdict(list)
    contributor_comments = defaultdict(list)
    contributor_flair    = {}
    topic_words          = Counter()
    top_posts            = []

    try:
        posts = list(sub.hot(limit=POST_LIMIT))
    except Exception as e:
        console.print(f"[red]  Could not fetch r/{sub_name}: {e}[/red]")
        return None

    for post in posts:
        if post.stickied:
            continue
        author = str(post.author) if post.author else "[deleted]"
        if author not in ("[deleted]", "AutoModerator"):
            contributor_posts[author].append(post.score)
            contributor_flair[author] = post.author_flair_text or ""
        text = post.title + " " + (post.selftext or "")
        topic_words.update(extract_keywords(text))
        top_posts.append((post.title, post.score, post.url))
        try:
            post.comments.replace_more(limit=0)
            for comment in post.comments[:COMMENT_LIMIT]:
                cauthor = str(comment.author) if comment.author else "[deleted]"
                if cauthor not in ("[deleted]", "AutoModerator"):
                    contributor_comments[cauthor].append(comment.score)
                    if cauthor not in contributor_flair:
                        contributor_flair[cauthor] = comment.author_flair_text or ""
                    topic_words.update(extract_keywords(comment.body or ""))
        except Exception:
            pass

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
            "flair":         contributor_flair.get(user, ""),
        })
    contributors.sort(key=lambda x: x["total_score"], reverse=True)
    top_posts.sort(key=lambda x: x[1], reverse=True)
    return {"contributors": contributors[:TOP_N_USERS], "topics": topic_words.most_common(TOP_N_TOPICS), "top_posts": top_posts[:10]}


def print_subreddit_report(sub_name, data):
    rprint(f"\n[bold cyan]=== r/{sub_name} ===[/bold cyan]")
    t = Table(title=f"Top Contributors - r/{sub_name}", show_lines=False)
    t.add_column("#", style="dim", width=4)
    t.add_column("Username", style="bold", min_width=20)
    t.add_column("Posts", justify="right")
    t.add_column("Comments", justify="right")
    t.add_column("Total Score", justify="right", style="green")
    t.add_column("Avg Score", justify="right")
    t.add_column("Flair", style="dim", max_width=30)
    for i, c in enumerate(data["contributors"], 1):
        t.add_row(str(i), c["username"], str(c["post_count"]), str(c["comment_count"]),
                  str(c["total_score"]), str(c["avg_score"]), c["flair"] or "-")
    console.print(t)
    rprint(f"\n[bold yellow]Top Topics - r/{sub_name}[/bold yellow]")
    rprint("  " + "  .  ".join(f"{w} ({n})" for w, n in data["topics"]))
    rprint(f"\n[bold magenta]Top Posts - r/{sub_name}[/bold magenta]")
    for title, score, url in data["top_posts"][:5]:
        rprint(f"  [{score}] {title[:80]}")


def save_outputs(all_data):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(f"{OUTPUT_DIR}/full_data.json", "w") as f:
        json.dump(all_data, f, indent=2)
    rows = []
    for sub, data in all_data.items():
        if data is None:
            continue
        for rank, c in enumerate(data["contributors"], 1):
            rows.append({"subreddit": sub, "rank": rank, **c})
    pd.DataFrame(rows).to_csv(f"{OUTPUT_DIR}/contributors.csv", index=False)
    topic_rows = []
    for sub, data in all_data.items():
        if data is None:
            continue
        for word, count in data["topics"]:
            topic_rows.append({"subreddit": sub, "topic": word, "count": count})
    pd.DataFrame(topic_rows).to_csv(f"{OUTPUT_DIR}/topics.csv", index=False)
    user_subs = defaultdict(list)
    for sub, data in all_data.items():
        if data is None:
            continue
        for c in data["contributors"]:
            user_subs[c["username"]].append(sub)
    power_users = [{"username": u, "subreddit_count": len(s), "subreddits": ", ".join(s)}
                   for u, s in user_subs.items() if len(s) > 1]
    power_users.sort(key=lambda x: x["subreddit_count"], reverse=True)
    pd.DataFrame(power_users).to_csv(f"{OUTPUT_DIR}/power_users.csv", index=False)
    console.print(f"\n[bold green]Saved to ./{OUTPUT_DIR}/[/bold green]")
    console.print("  contributors.csv, topics.csv, power_users.csv, full_data.json")


def main():
    console.print("\n[bold]Reddit Subreddit Analyzer[/bold]")
    console.print(f"Analyzing {len(SUBREDDITS)} subreddits...\n")
    reddit = make_reddit()
    all_data = {}
    for sub_name in track(SUBREDDITS, description="Fetching subreddits..."):
        all_data[sub_name] = analyze_subreddit(reddit, sub_name)
    for sub_name, data in all_data.items():
        if data:
            print_subreddit_report(sub_name, data)
    save_outputs(all_data)


if __name__ == "__main__":
    main()
