"""
Catalog updater for animecix.tv and ecchicix.com.
Uses fast 2-letter search and async detail fetching via curl_cffi.
"""
import asyncio
import json
import os
import time
import string
from curl_cffi.requests import AsyncSession

# ---------- File paths (anime data subfolder) ----------
_PRJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR = os.path.join(_PRJ_ROOT, "anime data")
os.makedirs(_DATA_DIR, exist_ok=True)

ANIMECIX_ANIMES   = os.path.join(_DATA_DIR, "animes.json")
ANIMECIX_EPISODES = os.path.join(_DATA_DIR, "episodes.json")
ECCHICIX_ANIMES   = os.path.join(_DATA_DIR, "ecchicix_animes.json")
ECCHICIX_EPISODES = os.path.join(_DATA_DIR, "ecchicix_episodes.json")

def set_token_animecix(token: str):
    pass

def set_token_ecchicix(token: str):
    pass

# ── Common search scraper ──────────────────────────
async def _fetch_search(site, query, session, anime_dict, lock, semaphore):
    base = f"https://{site}.{'tv' if site == 'animecix' else 'com'}"
    url = f"{base}/secure/search/{query}?limit=500"
    
    async with semaphore:
        for _ in range(3):
            try:
                resp = await session.get(url, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    results = data.get("results", [])
                    async with lock:
                        for item in results:
                            aid = item.get("id")
                            if aid and aid not in anime_dict:
                                anime_dict[aid] = {
                                    "id": int(aid),
                                    "title": item.get("name") or item.get("title") or "Bilinmiyor",
                                    "year": str(item.get("year", ""))
                                }
                    break
                elif resp.status_code in (429, 503):
                    await asyncio.sleep(1)
            except Exception:
                await asyncio.sleep(0.5)

async def _scrape_catalog(site):
    chars = list(string.ascii_lowercase) + [str(i) for i in range(10)] + ['.', '-']
    queries = [c1 + c2 for c1 in chars for c2 in chars]

    anime_dict = {}
    lock = asyncio.Lock()
    sem = asyncio.Semaphore(50)

    async with AsyncSession(impersonate="chrome110") as session:
        tasks = [_fetch_search(site, q, session, anime_dict, lock, sem) for q in queries]
        total = len(tasks)
        for i, t in enumerate(asyncio.as_completed(tasks), 1):
            await t
            if i % 300 == 0 or i == total:
                print(f"  [{site}] {i}/{total} queries | {len(anime_dict)} unique", flush=True)

    return sorted(anime_dict.values(), key=lambda x: x["id"])

# ── Detail fetcher ─────────────────────────────────
class DetailFetcher:
    def __init__(self, site, input_file, output_file):
        self.site = site
        self.base_url = f"https://{site}.{'tv' if site == 'animecix' else 'com'}"
        self.input_file = input_file
        self.output_file = output_file
        self.concurrency = 30
        self.detailed_dict = {}

    def load_existing(self):
        if os.path.exists(self.output_file):
            try:
                with open(self.output_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data:
                        if item.get("seasons"):
                            self.detailed_dict[int(item["id"])] = item
                print(f"  [{self.site}] Loaded {len(self.detailed_dict)} existing details")
            except Exception:
                pass

    async def fetch_one(self, anime_data, session, semaphore, lock, stats, total):
        aid = int(anime_data["id"])
        if aid in self.detailed_dict:
            stats["completed"] += 1
            return

        url = f"{self.base_url}/secure/titles/{aid}?titleId={aid}"
        entry = {"id": aid, "title": anime_data.get("title", ""), "year": anime_data.get("year", ""), "seasons": []}

        async with semaphore:
            for _ in range(3):
                try:
                    resp = await session.get(url, timeout=10)
                    if resp.status_code == 200:
                        data = resp.json()
                        t = data.get("title", {})
                        seasons = t.get("seasons", [])

                        if not seasons and t.get("videos"):
                            v = t["videos"][0]
                            entry["seasons"].append({
                                "season": 1,
                                "episodes": [{
                                    "episode": 1,
                                    "name": "Film / Tek Bölüm",
                                    "url": v.get("url", "")
                                }]
                            })
                        else:
                            for s in seasons:
                                sn = s.get("number", 1)
                                ep_url = f"{self.base_url}/secure/related-videos?episode=1&season={sn}&videoId=0&titleId={aid}"
                                try:
                                    ep_resp = await session.get(ep_url, timeout=10)
                                    if ep_resp.status_code == 200:
                                        ep_data = ep_resp.json()
                                        eps = []
                                        for v in ep_data.get("videos", []):
                                            # Filter by season number to prevent cross-season contamination
                                            v_season = v.get("season_num") or v.get("seasonNum")
                                            if v_season is not None and int(v_season) != int(sn):
                                                continue
                                            ep_num = v.get("episode_num") or v.get("episodeNum")
                                            if ep_num is None:
                                                continue
                                            eps.append({
                                                "episode": ep_num,
                                                "name": f"{sn}. Sezon {ep_num}. Bölüm",
                                                "url": v.get("url", "")
                                            })
                                        if eps:
                                            entry["seasons"].append({"season": sn, "episodes": eps})
                                except Exception:
                                    pass
                        break
                    elif resp.status_code in (429, 503):
                        await asyncio.sleep(1)
                except Exception:
                    await asyncio.sleep(0.5)

        async with lock:
            self.detailed_dict[aid] = entry
            stats["completed"] += 1
            if stats["completed"] % 100 == 0:
                print(f"  [{self.site}] {stats['completed']}/{total}")

    async def run(self):
        if not os.path.exists(self.input_file):
            print(f"  [{self.site}] Input file '{self.input_file}' not found.")
            return False
        with open(self.input_file, "r", encoding="utf-8") as f:
            animes = json.load(f)

        self.load_existing()
        total = len(animes)
        print(f"  [{self.site}] Fetching details for {total} anime...")
        semaphore = asyncio.Semaphore(self.concurrency)
        lock = asyncio.Lock()
        stats = {"completed": 0}
        async with AsyncSession(impersonate="chrome110") as session:
            tasks = [self.fetch_one(a, session, semaphore, lock, stats, total) for a in animes]
            await asyncio.gather(*tasks)

        sorted_results = sorted(self.detailed_dict.values(), key=lambda x: x["id"])
        with open(self.output_file, "w", encoding="utf-8") as f:
            json.dump(sorted_results, f, ensure_ascii=False, indent=2)
        print(f"  [{self.site}] Saved {len(sorted_results)} detailed anime to {self.output_file}")
        return True

# ── Public entry points ─────────────────────────────
async def _update_site(site, animes_path, episodes_path):
    print(f"\n--- Updating {site} catalog ---")
    animes = await _scrape_catalog(site)
    if not animes:
        print(f"  [{site}] No anime fetched.")
        return False
    with open(animes_path, "w", encoding="utf-8") as f:
        json.dump(animes, f, ensure_ascii=False, indent=2)
    print(f"  [{site}] Saved {len(animes)} IDs.")

    fetcher = DetailFetcher(site, animes_path, episodes_path)
    return await fetcher.run()

async def run_full_update():
    success = True
    
    if not await _update_site("ecchicix", ECCHICIX_ANIMES, ECCHICIX_EPISODES):
        success = False

    return success