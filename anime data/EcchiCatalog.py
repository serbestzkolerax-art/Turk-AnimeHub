import asyncio
import aiohttp
import json
import string
import time

BASE_URL = "https://ecchicix.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": BASE_URL + "/",
    "Accept": "application/json, text/plain, */*",
    "x-e-h": "7Y2ozlO+QysR5w9Q6Tupmtvl9jJp7ThFH8SB+Lo7NvZjgjqRSqOgcT2v4ISM9sP10LmnlYI8WQ==.xrlyOBFS5BHjQ2Lk",
}

# All two‑character combinations (a‑z + 0‑9)
CHARS = list(string.ascii_lowercase) + [str(i) for i in range(10)]
SEARCH_QUERIES = [c1 + c2 for c1 in CHARS for c2 in CHARS]

CONCURRENCY_LIMIT = 35

async def fetch_search(query: str, session: aiohttp.ClientSession, anime_dict: dict, lock: asyncio.Lock, semaphore: asyncio.Semaphore):
    url = f"{BASE_URL}/secure/search/{query}?limit=500"
    async with semaphore:
        for attempt in range(3):
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=6)) as response:
                    if response.status == 200:
                        data = await response.json()
                        results = data.get("results", [])
                        async with lock:
                            for item in results:
                                anime_id = item.get("id")
                                if anime_id and anime_id not in anime_dict:
                                    title = item.get("name") or item.get("title") or "Bilinmiyor"
                                    year = item.get("year") or "Bilinmiyor"
                                    anime_dict[anime_id] = {
                                        "id": int(anime_id),
                                        "title": title,
                                        "year": str(year)
                                    }
                        break
                    elif response.status == 429:
                        await asyncio.sleep(1)
            except Exception:
                await asyncio.sleep(0.5)

async def main():
    print(f"🚀 Ecchicix Catalog Scraper ({len(SEARCH_QUERIES)} queries)...")
    start_time = time.time()

    anime_dict = {}
    lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)

    async with aiohttp.ClientSession(headers=HEADERS) as session:
        tasks = [
            fetch_search(query, session, anime_dict, lock, semaphore)
            for query in SEARCH_QUERIES
        ]
        total_tasks = len(tasks)
        for i, task in enumerate(asyncio.as_completed(tasks), 1):
            await task
            if i % 300 == 0 or i == total_tasks:
                print(f"⏳ Queries: {i}/{total_tasks} | Unique anime: {len(anime_dict)}", flush=True)

    all_animes = sorted(list(anime_dict.values()), key=lambda x: x["id"])

    # Save as ecchicix_animes.json
    with open("ecchicix_animes.json", "w", encoding="utf-8") as f:
        json.dump(all_animes, f, ensure_ascii=False, indent=2)

    elapsed = round(time.time() - start_time, 2)
    print(f"✅ Done! {len(all_animes)} anime saved to 'ecchicix_animes.json' in {elapsed}s.")

if __name__ == "__main__":
    asyncio.run(main())