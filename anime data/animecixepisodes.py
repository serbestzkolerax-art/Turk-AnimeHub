import asyncio
import aiohttp
import json
import os
import time

class AnimeDetailFetcher:
    def __init__(self, input_file="animes.json", output_json="episodes.json", output_txt="animecix_detay.txt", concurrency=20):
        self.input_file = input_file
        self.output_json = output_json
        self.output_txt = output_txt
        self.concurrency = concurrency
        self.base_url = "https://animecix.tv"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": self.base_url + "/",
            "Accept": "application/json, text/plain, */*",
            "x-e-h": "aPs/7VNuJq1hp0RMagxG2aMCLJBSsrgTSA==.JkDVyfXZlnGRdkQM",
        }
        self.detailed_dict = {}

    def load_existing(self):
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
        aid = int(anime_data["id"])
        if aid in self.detailed_dict:
            stats["completed"] += 1
            return

        url = f"{self.base_url}/secure/titles/{aid}?titleId={aid}"
        entry = {
            "id": aid,
            "title": anime_data.get("title", "Bilinmiyor"),
            "year": anime_data.get("year", "Bilinmiyor"),
            "seasons": []
        }

        async with semaphore:
            for _ in range(3):
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
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
                                    for _ in range(3):
                                        try:
                                            async with session.get(ep_url, timeout=aiohttp.ClientTimeout(total=8)) as ep_resp:
                                                if ep_resp.status == 200:
                                                    ep_data = await ep_resp.json()
                                                    eps = []
                                                    for v in ep_data.get("videos", []):
                                                        ep_num = v.get("episode_num") or v.get("episodeNum") or 1
                                                        eps.append({
                                                            "episode": ep_num,
                                                            "name": f"{sn}. Sezon {ep_num}. Bölüm",
                                                            "url": v.get("url", "")
                                                        })
                                                    if eps:
                                                        entry["seasons"].append({"season": sn, "episodes": eps})
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
            self.detailed_dict[aid] = entry
            stats["completed"] += 1
            if stats["completed"] % 50 == 0 or stats["completed"] == total_count:
                print(f"⏳ [{stats['completed']}/{total_count}] - Last: {entry['title']}", flush=True)

    def save_outputs(self):
        sorted_results = sorted(self.detailed_dict.values(), key=lambda x: x["id"])
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
        self.load_existing()
        animes = self.load_catalog()
        if not animes:
            return
        print(f"🚀 Fetching details for {len(animes)} anime...")
        start = time.time()
        semaphore = asyncio.Semaphore(self.concurrency)
        lock = asyncio.Lock()
        stats = {"completed": 0}
        total = len(animes)

        async with aiohttp.ClientSession(headers=self.headers) as session:
            tasks = [self.fetch_details(a, session, semaphore, lock, stats, total) for a in animes]
            await asyncio.gather(*tasks)

        self.save_outputs()
        print(f"⏱️ Finished in {round(time.time() - start, 2)}s.")

if __name__ == "__main__":
    fetcher = AnimeDetailFetcher(concurrency=20)
    asyncio.run(fetcher.start())