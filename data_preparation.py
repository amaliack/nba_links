import os
import time
import unicodedata
import re
from email.message import EmailMessage
import smtplib
from dotenv import load_dotenv

from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import json
import atexit
import warnings
warnings.filterwarnings("ignore")

def safe_goto(page, url, retries=3, delay=5, timeout=60000):
    for attempt in range(retries):
        try:
            page.goto(url, timeout=timeout)
            return
        except Exception as e:
            print(f"Attempt {attempt+1} failed with timeout. Retrying in {delay} seconds")
            time.sleep(delay)
    raise Exception(f"Failed to load {url} after {retries} attempts")

def load_player_map():
    global player_map
    if os.path.exists("player_map.json"):
        with open("player_map.json", "r") as f:
            player_map = json.load(f)
    else:
        # we are starting fresh (not sure what to do here)
        player_map = {}

def save_player_map():
    global player_map
    with open("player_map.json", "w") as f:
        json.dump(player_map, f, indent=4)

def load_all_players():
    global all_players
    if os.path.exists("all_players.json"):
        with open("all_players.json", "r") as f:
            all_players = json.load(f)
    else:
        all_players = []

def save_all_players():
    global all_players
    with open("all_players.json", "w") as f:
        json.dump(all_players, f)

def get_all_players():
    base_url = "https://www.basketball-reference.com/players/"
    letters = [chr(i) for i in range(ord('a'), ord('z') + 1)]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for letter in letters:
            url = f"{base_url}{letter}/"
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_selector("#players")
            html = page.inner_html("#players")
            soup = BeautifulSoup(html, "html.parser")

            for row in soup.select("th[data-stat='player'] a"):
                player_name = row.get_text(strip=True)
                all_players.append(player_name)

            time.sleep(3.1)  # prevent hammering the server

        browser.close()
    save_all_players()
    return all_players

# deals with loading and saving the updated information
load_player_map()
load_all_players()
atexit.register(save_player_map)

def build_adjacency_list():
    # here, we will build the graph/adjacency list for the given player
    # accessing the api to find a list of teammates hopefully
    for player in all_players:
        if player not in player_map:
            teammates = get_teammates(player)
            player_map[player] = teammates
            print(f"{player} has {len(teammates)} teammates")
        else:
            continue
        time.sleep(1)

def get_player_code(first, last):
    base_url = "https://www.basketball-reference.com/friv/teammates_and_opponents.fcgi?pid="
    name_code = (last[:5] + first[:2]).lower()
    suffix = "&type=t"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # loop through the possible codes
        for i in range (1, 10):
            pid = f"{name_code}{i:02d}"
            url = f"{base_url}{pid}{suffix}"
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            # check to see that the player's name is on the top of the page
            h1_text = page.locator("h1").inner_text() if page.locator("h1").count() > 0 else ""
            page_name = normalize_name(h1_text.lower())
            if first.lower() in page_name and last.lower() in page_name:
                browser.close()
                return url
        browser.close()
        raise ValueError(f"Could not find the correct pid for {first} {last}")

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

def get_teammates(player):
    names = player.split()
    print(player)
    if len(names) == 3:
        first_name = names[0]
        last_name = names[1] + " " + names[2]
    else:
        first_name, last_name = names[0], names[1]

    first_name = normalize_name(first_name)
    last_name = normalize_name(last_name)
    if first_name == "jeff" and last_name == "ayres":
        url = "https://www.basketball-reference.com/friv/teammates_and_opponents.fcgi?pid=pendeje02&type=t"
    elif first_name == "mark" and last_name == "baker":
        url = "https://www.basketball-reference.com/friv/teammates_and_opponents.fcgi?pid=bakerla01&type=t"
    elif first_name == "jj" and last_name == "barea":
        url = "https://www.basketball-reference.com/friv/teammates_and_opponents.fcgi?pid=bareajo01&type=t"
    elif first_name == "billy" and last_name == "ray bates":
        url = "https://www.basketball-reference.com/friv/teammates_and_opponents.fcgi?pid=batesbi01&type=t"
    elif first_name == "george" and last_name == "bon salle":
        url = "https://www.basketball-reference.com/friv/teammates_and_opponents.fcgi?pid=bonsage01&type=t"
    elif first_name == "deonte" and last_name == "burton":
        url = "https://www.basketball-reference.com/friv/teammates_and_opponents.fcgi?pid=burtode02&type=t"
    else:
        url = get_player_code(first_name, last_name)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        safe_goto(page, url)

        # Wait for the table to load
        page.wait_for_selector("#teammates-and-opponents", timeout=60000)

        # Get the entire HTML of the table
        html = page.inner_html("#teammates-and-opponents")
        browser.close()

    # Parse the table with BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")

    # Extract rows and store player names
    rows = soup.find_all("tr")
    teammates = []
    for row in rows:
        cell = row.find(["td", {"data-stat": "pid2"}])
        if cell:
            name = cell.get_text(strip=True)
            teammates.append(name)

    teammates = [x.replace("*", "") for x in teammates]
    return teammates

def is_teammate(player, teammate):
    # take in a player, access the list of teammates
    # and return if the teammate is a teammate or not
    teammates = player_map[player]
    if teammate in teammates:
        return True
    else:
        return False

if __name__ == "__main__":
    build_adjacency_list()
