import asyncio
import aiohttp
import json
import string
import time

BASE_URL = "https://animecix.tv"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": BASE_URL + "/",
    "Accept": "application/json, text/plain, */*",
    "x-e-h": "aPs/7VNuJq1hp0RMagxG2aMCLJBSsrgTSA==.JkDVyfXZlnGRdkQM",   # <-- replace with the one that passed the test
}

CHARS = list(string.ascii_lowercase) + [str(i) for i in range(10)]
SEARCH_QUERIES = [c1 + c2 for c1 in CHARS for c2 in CHARS]
CONCURRENCY_LIMIT = 35

async def fetch_search(query, session, anime_dict, lock, semaphore):
    url = f"{BASE_URL}/secure/search/{query}?limit=500"
    async with semaphore:
        for _ in range(3):
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
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
                    elif resp.status == 429:
                        await asyncio.sleep(1)
            except Exception:
                await asyncio.sleep(0.5)

async def main():
    print(f"🚀 Animecix Catalog Scraper ({len(SEARCH_QUERIES)} queries)...")
    start = time.time()
    anime_dict = {}
    lock = asyncio.Lock()
    sem = asyncio.Semaphore(CONCURRENCY_LIMIT)

    async with aiohttp.ClientSession(headers=HEADERS) as session:
        tasks = [fetch_search(q, session, anime_dict, lock, sem) for q in SEARCH_QUERIES]
        total = len(tasks)
        for i, t in enumerate(asyncio.as_completed(tasks), 1):
            await t
            if i % 300 == 0 or i == total:
                print(f"⏳ {i}/{total} queries | {len(anime_dict)} unique", flush=True)

    all_animes = sorted(anime_dict.values(), key=lambda x: x["id"])
    with open("animes.json", "w", encoding="utf-8") as f:
        json.dump(all_animes, f, ensure_ascii=False, indent=2)

    elapsed = round(time.time() - start, 2)
    print(f"✅ {len(all_animes)} anime saved to 'animes.json' in {elapsed}s.")

if __name__ == "__main__":
    asyncio.run(main())