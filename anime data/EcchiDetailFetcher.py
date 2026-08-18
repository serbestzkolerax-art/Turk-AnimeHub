import asyncio
import aiohttp
import json
import os
import time

class AnimeDetailFetcher:
    def __init__(self, input_file="ecchicix_animes.json", output_json="ecchicix_episodes.json", output_txt="ecchicix_detay.txt", concurrency=20):
        self.input_file = input_file
        self.output_json = output_json
        self.output_txt = output_txt
        self.concurrency = concurrency
        self.base_url = "https://ecchicix.com"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": self.base_url + "/",
            "Accept": "application/json, text/plain, */*",
            "x-e-h": "7Y2ozlO+QysR5w9Q6Tupmtvl9jJp7ThFH8SB+Lo7NvZjgjqRSqOgcT2v4ISM9sP10LmnlYI8WQ==.xrlyOBFS5BHjQ2Lk",
        }
        self.detailed_dict = {}

    def load_existing_details(self):
        if os.path.exists(self.output_json):
            try:
                with open(self.output_json, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data:
                        if item.get("seasons"):
                            self.detailed_dict[int(item["id"])] = item
                print(f"🔄 Loaded {len(self.detailed_dict)} existing details (resuming).")
            except Exception:
                print("⚠️ Could not read existing details, starting fresh.")

    def load_catalog(self):
        if not os.path.exists(self.input_file):
            print(f"❌ ERROR: '{self.input_file}' not found! Run the catalog scraper first.")
            return []
        with open(self.input_file, "r", encoding="utf-8") as f:
            return json.load(f)

    async def fetch_details(self, anime_data, session, semaphore, lock, stats, total_count):
        anime_id = int(anime_data["id"])
        if anime_id in self.detailed_dict:
            stats["completed"] += 1
            return

        url = f"{self.base_url}/secure/titles/{anime_id}?titleId={anime_id}"
        anime_result = {
            "id": anime_id,
            "title": anime_data.get("title", "Bilinmiyor"),
            "year": anime_data.get("year", "Bilinmiyor"),
            "seasons": []
        }

        async with semaphore:
            for attempt in range(3):
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            t = data.get("title", {})
                            seasons = t.get("seasons", [])

                            if not seasons and t.get("videos"):
                                # Single video (movie)
                                v = t["videos"][0]
                                rel_url = v.get("url", "")
                                full_url = f"{self.base_url}/{rel_url.lstrip('/')}" if rel_url else ""
                                anime_result["seasons"].append({
                                    "season": 1,
                                    "episodes": [{
                                        "episode": 1,
                                        "name": "Film / Tek Bölüm",
                                        "url": full_url
                                    }]
                                })
                            else:
                                for s in seasons:
                                    season_num = s.get("number", 1)
                                    ep_url = f"{self.base_url}/secure/related-videos?episode=1&season={season_num}&videoId=0&titleId={anime_id}"
                                    for ep_attempt in range(3):
                                        try:
                                            async with session.get(ep_url, timeout=aiohttp.ClientTimeout(total=8)) as ep_resp:
                                                if ep_resp.status == 200:
                                                    ep_data = await ep_resp.json()
                                                    episodes_list = []
                                                    for v in ep_data.get("videos", []):
                                                        ep_num = v.get('episode_num') or v.get('episodeNum') or 1
                                                        rel_url = v.get('url', '')
                                                        full_url = f"{self.base_url}/{rel_url.lstrip('/')}" if rel_url else ""
                                                        episodes_list.append({
                                                            "episode": ep_num,
                                                            "name": f"{season_num}. Sezon {ep_num}. Bölüm",
                                                            "url": full_url
                                                        })
                                                    if episodes_list:
                                                        anime_result["seasons"].append({
                                                            "season": season_num,
                                                            "episodes": episodes_list
                                                        })
                                                    break
                                                elif ep_resp.status in (429, 503):
                                                    await asyncio.sleep(1)
                                        except Exception:
                                            await asyncio.sleep(0.5)
                            break
                        elif resp.status in (429, 503):
                            await asyncio.sleep(1)
                except Exception:
                    await asyncio.sleep(0.5)

        async with lock:
            self.detailed_dict[anime_id] = anime_result
            stats["completed"] += 1
            if stats["completed"] % 50 == 0 or stats["completed"] == total_count:
                print(f"⏳ Detail progress: [{stats['completed']}/{total_count}] - Last: {anime_result['title']}", flush=True)

    def save_outputs(self):
        sorted_results = sorted(list(self.detailed_dict.values()), key=lambda x: x["id"])
        with open(self.output_json, "w", encoding="utf-8") as f:
            json.dump(sorted_results, f, ensure_ascii=False, indent=2)
        with open(self.output_txt, "w", encoding="utf-8") as f:
            for anime in sorted_results:
                f.write("="*60 + "\n")
                f.write(f"ANİME: {anime['title']} (ID: {anime['id']})\n")
                f.write("="*60 + "\n")
                for s in anime.get("seasons", []):
                    f.write(f"\n   --- {s['season']}. SEZON ---\n")
                    for ep in s.get("episodes", []):
                        f.write(f"   • [{ep['name']}] -> {ep['url']}\n")
                f.write("\n\n")
        print(f"💾 Details saved to '{self.output_json}' and '{self.output_txt}'.")

    async def start(self):
        self.load_existing_details()
        animes = self.load_catalog()
        if not animes:
            return
        print(f"🚀 Fetching details for {len(animes)} anime...")
        start_time = time.time()

        semaphore = asyncio.Semaphore(self.concurrency)
        lock = asyncio.Lock()
        stats = {"completed": 0}
        total_count = len(animes)

        async with aiohttp.ClientSession(headers=self.headers) as session:
            tasks = [
                self.fetch_details(anime, session, semaphore, lock, stats, total_count)
                for anime in animes
            ]
            await asyncio.gather(*tasks)

        self.save_outputs()
        elapsed = round(time.time() - start_time, 2)
        print(f"⏱️ Finished in {elapsed} seconds.")

if __name__ == "__main__":
    fetcher = AnimeDetailFetcher(concurrency=20)
    asyncio.run(fetcher.start())