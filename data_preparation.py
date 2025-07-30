import os
import time
import json
import unicodedata
import re
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import atexit

# ---- Constants ----
PLAYER_MAP_PATH = "player_map.json"
ALL_PLAYERS_PATH = "all_players.json"
REQUEST_DELAY = 3.2  # seconds between requests to avoid hammering

# ---- Global state ----
player_map = {}
all_players = []
dirty_player_map = False

# ---- Helper Functions ----

def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            print(f"Warning: Failed to decode JSON from {path}, starting fresh")
            return default
    else:
        return default

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=4)

def normalize_token(token):
    special_map = {
        "ı": "i", "İ": "I",
        "Ł": "l", "ł": "l",
        "Ø": "o", "ø": "o",
        "Đ": "d", "đ": "d",
        # Add more as needed
    }
    for char, replacement in special_map.items():
        token = token.replace(char, replacement)
    token = unicodedata.normalize('NFD', token)
    token = token.encode('ascii', 'ignore').decode('utf-8')
    token = re.sub(r'[^a-zA-Z]', '', token).lower()
    return token

def normalize_name(name):
    tokens = name.strip().split()
    normalized_tokens = [normalize_token(token) for token in tokens]
    return ' '.join(normalized_tokens)

def safe_goto(page, url, retries=3, delay=5, timeout=60000):
    for attempt in range(retries):
        try:
            page.goto(url, timeout=timeout)
            return
        except Exception as e:
            print(f"Attempt {attempt + 1} to load {url} failed: {e}. Retrying in {delay} seconds...")
            time.sleep(delay)
    raise Exception(f"Failed to load {url} after {retries} attempts")

# ---- Core Functions ----

def get_player_code(first, last, page):
    base_url = "https://www.basketball-reference.com/friv/teammates_and_opponents.fcgi?pid="
    name_code = (last[:5] + first[:2]).lower()
    suffix = "&type=t"

    for i in range(1, 10):
        pid = f"{name_code}{i:02d}"
        url = f"{base_url}{pid}{suffix}"
        safe_goto(page, url)
        h1_text = page.locator("h1").inner_text() if page.locator("h1").count() > 0 else ""
        page_name = normalize_name(h1_text.lower())
        if first.lower() in page_name and last.lower() in page_name:
            return url

    raise ValueError(f"Could not find the correct pid for {first} {last}")

def get_teammates(player, page):
    time.sleep(1)
    names = player.split()
    if len(names) == 3:
        first_name = names[0]
        last_name = names[1] + " " + names[2]
    else:
        first_name, last_name = names[0], names[1]

    first_name = normalize_name(first_name)
    last_name = normalize_name(last_name)

    # Hardcoded special cases for known player name discrepancies
    overrides = {
        ("jeff", "ayres"): "https://www.basketball-reference.com/friv/teammates_and_opponents.fcgi?pid=pendeje02&type=t",
        ("mark", "baker"): "https://www.basketball-reference.com/friv/teammates_and_opponents.fcgi?pid=bakerla01&type=t",
        ("jj", "barea"): "https://www.basketball-reference.com/friv/teammates_and_opponents.fcgi?pid=bareajo01&type=t",
        ("billy", "ray bates"): "https://www.basketball-reference.com/friv/teammates_and_opponents.fcgi?pid=batesbi01&type=t",
        ("george", "bon salle"): "https://www.basketball-reference.com/friv/teammates_and_opponents.fcgi?pid=bonsage01&type=t",
        ("deonte", "burton"): "https://www.basketball-reference.com/friv/teammates_and_opponents.fcgi?pid=burtode02&type=t",
        ("clint", "capela"): "https://www.basketball-reference.com/friv/teammates_and_opponents.fcgi?pid=capelca01&type=t",
        ("bub", "carrington"): "https://www.basketball-reference.com/friv/teammates_and_opponents.fcgi?pid=carrica01&type=t",
        ("joe", "barry carroll"): "https://www.basketball-reference.com/friv/teammates_and_opponents.fcgi?pid=carrojo01&type=t",
        ("dick", "clark"): "https://www.basketball-reference.com/friv/teammates_and_opponents.fcgi?pid=clarkri01&type=t",
        ("cui", "yongxi"): "https://www.basketball-reference.com/friv/teammates_and_opponents.fcgi?pid=cuiyo01&type=t",
        ("tristan", "da silva"): "https://www.basketball-reference.com/friv/teammates_and_opponents.fcgi?pid=dasiltr01&type=t",
        ("n'faly", "dante"): "https://www.basketball-reference.com/friv/teammates_and_opponents.fcgi?pid=nfalyda01&type=t",
        ("gigi", "datome"): "https://www.basketball-reference.com/friv/teammates_and_opponents.fcgi?pid=datomlu01&type=t",
    }

    url = overrides.get((first_name, last_name))
    if url is None:
        url = get_player_code(first_name, last_name, page)

    safe_goto(page, url)
    try:
        page.wait_for_selector("#teammates-and-opponents", timeout=60000)
    except Exception as e:
        print(f"Timeout waiting for teammates table for player {player}: {e}")

    html = page.inner_html("#teammates-and-opponents")
    soup = BeautifulSoup(html, "html.parser")

    teammates = []
    for row in soup.find_all("tr"):
        cell = row.find(["td", {"data-stat": "pid2"}])
        if cell:
            name = cell.get_text(strip=True)
            teammates.append(name.replace("*", ""))

    return teammates

def build_adjacency_list():
    global dirty_player_map

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for idx, player in enumerate(all_players, start=1):
            if player not in player_map:
                try:
                    teammates = get_teammates(player, page)
                    player_map[player] = teammates
                    dirty_player_map = True
                    print(f"[{idx}/{len(all_players)}] Added {player} with {len(teammates)} teammates")
                except Exception as e:
                    print(f"Error processing {player}: {e}")
                time.sleep(REQUEST_DELAY)  # respect server rate limits
            else:
                print(f"[{idx}/{len(all_players)}] Skipped {player} (already in map)")

        browser.close()

# ---- Load/Save functions ----
def load_data():
    global player_map, all_players
    player_map = load_json(PLAYER_MAP_PATH, {})
    all_players = load_json(ALL_PLAYERS_PATH, [])
def save_data():
    global dirty_player_map
    if dirty_player_map:
        print("Saving player_map.json...")
        save_json(PLAYER_MAP_PATH, player_map)
        dirty_player_map = False

atexit.register(save_data)

# ---- Main ----
if __name__ == "__main__":
    load_data()
    build_adjacency_list()
    save_data()
