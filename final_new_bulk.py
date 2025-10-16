# app.py
from flask import Flask, render_template_string, jsonify, request
import random
import pandas as pd
import os
from datetime import datetime
from collections import Counter

app = Flask(__name__)

# Config
RESULTS_FILE = 'lottery_results.xlsx'
RESULTS_FILE_BULK = 'lottery_results_bulk.xlsx'
TICKET_START = 10000
TICKET_END = 20000  # inclusive
TOTAL_WINNERS = 137  # total number of winning tickets to be selected

# Prize master counts (sum must equal TOTAL_WINNERS)
# 7 prizes total. Adjust counts if you need different distribution.
PRIZE_MASTER = {
    "Bullet 350 Classic Bike": {"count": 1, "image": "/static/prizes/bullet_350.jpg"},
    "Chetak Scooter": {"count": 1, "image": "/static/prizes/chetak_scooter.jpg"},
    "1 kg Fine Silver": {"count": 1, "image": "/static/prizes/fine_silver.jpg"},
    "Samsung Washing Machine": {"count": 1, "image": "/static/prizes/samsung_washing_machine.jpg"},
    "Vacuum Cleaner": {"count": 11, "image": "/static/prizes/vacuum_cleaner.jpg"},
    "Futura Pressure Cooker": {"count": 11, "image": "/static/prizes/futura_pressure_cooker.jpg"},
    "Wall Clock": {"count": 111, "image": "/static/prizes/wall_clock.jpg"},  # Wall clock excluded for draws 1-25
}
assert sum(p["count"] for p in PRIZE_MASTER.values()) == TOTAL_WINNERS, "Prize counts must sum to TOTAL_WINNERS"

PRIZE_MASTER_BULK = {"Wall Clock": {"count": 111, "image": "/static/prizes/wall_clock.jpg"}}

# Regions: (name, ((start1,end1),(start2,end2),...), color)
# NOTE: ranges here are illustrative — they use 5-digit ticket space (10000-20000).
REGIONS = [
    ("Koshi", ((15001, 16260),), "#00755b"),
    ("Janakpur", ((18001, 19000),(16501, 16560)), "#a1c181"),
    ("Birgunj", ((16561, 17000),), "#a1c181"),
    # Mu Ka uses multiple ranges example (you can have many tuples)
    ("Mu Ka", ((10001, 10600), (19001, 19240), (13861, 14000)), "#10ac84"),
    ("Bagmati", ((11040, 12000),(12001, 12160),(17001, 17140)), "#004d40"),
    ("Gandaki", ((14001, 15000),(16261, 16500),(17141, 17160)), "#e6091f"),
    ("Karnali", ((19241, 20000),), "#00755b"),
    ("Dang", ((13001, 13860),), "#00755b"),
    ("Lumbini - Bhairahawa", ((17161, 18000),), "#4caf50"),
    ("Sudurpashim", ((10601, 11040),), "#009688"),
    ("Birendranagar", ((12161, 13000),), "#009688"),
]

REGIONS_BULK = [
    ("Koshi", 14, "#00755b"),
    ("Janakpur", 12, "#a1c181"),
    ("Birgunj", 5, "#a1c181"),
    ("Mu Ka", 11, "#10ac84"),
    ("Bagmati", 14, "#004d40"),
    ("Gandaki", 14, "#004d40"),
    ("Karnali", 8, "#00755b"),
    ("Dang", 10, "#00755b"),
    ("Lumbini - Bhairahawa", 9, "#4caf50"),
    ("Sudurpashim", 5, "#009688"),
    ("Birendranagar", 9, "#009688"),
]

def get_region(ticket_number):
    """Return (region_name, color) for given ticket (handles multiple ranges per region)."""
    for name, ranges, color in REGIONS:
        for start, end in ranges:
            if start <= ticket_number <= end:
                return name, color
    return "Unknown", "#999999"

# Global runtime draw state
current_draw = {
    'initialized': False,
    'results': [],               # list of dict results loaded from file + drawn during this session
    'available_tickets': [],     # tickets that remain possible to draw
    'available_prizes': [],      # list of prize names (one entry per remaining prize unit)
    'prize_counts_remaining': {},# counts remaining by prize name
    'total_drawn': 0,
    'draw_id': None,
}

def build_prize_list_from_counts(counts):
    """Return a list of prize dicts {'name','image'} repeated by count."""
    prize_list = []
    for name, meta in counts.items():
        for _ in range(meta['count']):
            prize_list.append({'name': name, 'image': meta.get('image', '/static/prizes/default.jpg')})
    return prize_list

def initialize_draw():
    """(Re)initialize current_draw. Load previously saved winners from RESULTS_FILE if present,
       remove their tickets from available list and decrement prize counts accordingly.
       New session gets new draw_id but retains previous winners in results.
    """
    global current_draw
    # start with all tickets in range
    all_tickets = list(range(TICKET_START, TICKET_END + 1))
    random.shuffle(all_tickets)

    # copy master prize counts
    prize_counts = {name: {"count": meta["count"], "image": meta.get("image", "/static/prizes/default.jpg")}
                    for name, meta in PRIZE_MASTER.items()}

    current_draw = {
        'initialized': True,
        'results': [],
        'available_tickets': all_tickets.copy(),
        'available_prizes': [],  # will be built after accounting for previously allocated prizes
        'prize_counts_remaining': prize_counts,
        'total_drawn': 0,
        'draw_id': datetime.now().strftime("%Y%m%d_%H%M%S")
    }

    # If results file exists, load previous winners and subtract from available tickets/prize counts
    if os.path.exists(RESULTS_FILE):
        try:
            df = pd.read_excel(RESULTS_FILE)
            # Expecting columns: Rank, Ticket Number, Ticket ID, Region, Prize Name, Prize Image (optional)
            for _, row in df.iterrows():
                try:
                    ticket_id = int(row.get('Ticket ID') if 'Ticket ID' in row else row.get('Ticket', None))
                except Exception:
                    continue
                prize_name = str(row.get('Prize Name', '')).strip()
                region = row.get('Region', None) if 'Region' in row else None
                prize_image = row.get('Prize Image', None) if 'Prize Image' in row else None
                rank = int(row.get('Rank', 0)) if not pd.isna(row.get('Rank', 0)) else 0

                # append to results
                current_draw['results'].append({
                    'rank': rank,
                    'ticket_number': ticket_id,
                    'ticket': f"{ticket_id:05d}",
                    'region': region if region else get_region(ticket_id)[0],
                    'region_color': get_region(ticket_id)[1],
                    'prize_name': prize_name,
                    'prize_image': prize_image if prize_image else PRIZE_MASTER.get(prize_name, {}).get('image', '/static/prizes/default.jpg')
                })

                # remove ticket from available_tickets
                if ticket_id in current_draw['available_tickets']:
                    current_draw['available_tickets'].remove(ticket_id)

                # decrement prize count if present
                if prize_name in current_draw['prize_counts_remaining']:
                    # safe decrement (avoid negative)
                    if current_draw['prize_counts_remaining'][prize_name]['count'] > 0:
                        current_draw['prize_counts_remaining'][prize_name]['count'] -= 1

            current_draw['total_drawn'] = len(current_draw['results'])
        except Exception as e:
            print("Warning: could not read RESULTS_FILE:", e)

    # Build available_prizes list (expand counts into list of dicts)
    current_draw['available_prizes'] = build_prize_list_from_counts(current_draw['prize_counts_remaining'])
    # Shuffle available tickets and prizes
    random.shuffle(current_draw['available_tickets'])
    random.shuffle(current_draw['available_prizes'])

    # Save file if not exist: create empty with headers
    if not os.path.exists(RESULTS_FILE):
        df_empty = pd.DataFrame(columns=['Rank', 'Ticket Number', 'Ticket ID', 'Region', 'Prize Name', 'Prize Image'])
        df_empty.to_excel(RESULTS_FILE, index=False)

def save_results_to_excel():
    """Write entire current_draw['results'] into RESULTS_FILE (overwrites file).
       Ensures previously loaded winners + newly drawn winners are saved together.
    """
    if not current_draw['results']:
        # ensure file exists with headers
        if not os.path.exists(RESULTS_FILE):
            df_empty = pd.DataFrame(columns=['Rank', 'Ticket Number', 'Ticket ID', 'Region', 'Prize Name', 'Prize Image'])
            df_empty.to_excel(RESULTS_FILE, index=False)
        return

    df = pd.DataFrame(current_draw['results'])
    # Ensure columns exist and are ordered
    df = df[['rank', 'ticket', 'ticket_number', 'region', 'prize_name', 'prize_image']].copy()
    df.columns = ['Rank', 'Ticket Number', 'Ticket ID', 'Region', 'Prize Name', 'Prize Image']
    with pd.ExcelWriter(RESULTS_FILE, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Lottery Results')

def select_prize_for_draw():
    """Select a prize from available_prizes following the rule:
       - For draws 1..26 (i.e. when total_drawn < 26) do NOT select 'Wall Clock'
       - From draw 26 onward, include 'Wall Clock' like others.
       Returns a dict {'name','image'} and removes it from available_prizes.
    """
    if not current_draw['available_prizes']:
        return None
    exclude_wall_before = (current_draw['total_drawn'] < 26)
    # filter candidates
    candidates = []
    for p in current_draw['available_prizes']:
        if exclude_wall_before and p['name'].lower().startswith('wall clock'):
            continue
        candidates.append(p)
    if not candidates:
        # if no candidate (e.g., only wall clocks remain but rule excludes them), then allow wall clocks only if there are no other prizes
        candidates = current_draw['available_prizes'][:]
    # choose random candidate instance (we will remove the first matching instance from available_prizes)
    chosen = random.choice(candidates)
    # remove one instance of chosen from available_prizes (remove by identity)
    for i, p in enumerate(current_draw['available_prizes']):
        if p['name'] == chosen['name'] and p.get('image') == chosen.get('image'):
            current_draw['available_prizes'].pop(i)
            break
    # also decrement prize_counts_remaining (if tracked)
    if chosen['name'] in current_draw['prize_counts_remaining']:
        if current_draw['prize_counts_remaining'][chosen['name']]['count'] > 0:
            current_draw['prize_counts_remaining'][chosen['name']]['count'] -= 1
    return chosen

def draw_single_winner():
    """Perform a single draw. Returns result dict or None if no winners left."""
    if not current_draw['initialized']:
        initialize_draw()
    if current_draw['total_drawn'] >= TOTAL_WINNERS:
        return None
    # pick a ticket
    if not current_draw['available_tickets']:
        return None
    ticket = current_draw['available_tickets'].pop()  # already shuffled
    # pick prize respecting the 'wall clock' rule
    prize = select_prize_for_draw()
    if not prize:
        # no prize available (shouldn't happen if counts correct)
        return None

    current_draw['total_drawn'] += 1
    rank = current_draw['total_drawn']
    region_name, region_color = get_region(ticket)
    result = {
        'rank': rank,
        'ticket_number': ticket,
        'ticket': f"{ticket:05d}",
        'region': region_name,
        'region_color': region_color,
        'prize_name': prize['name'],
        'prize_image': prize.get('image', '/static/prizes/default.jpg'),
    }
    current_draw['results'].append(result)
    save_results_to_excel()
    return result

def draw_bulk_wall_clocks():
    """
    Draw wall clock winners region-wise after 26 draws.
    - Excludes tickets already in lottery_results.xlsx.
    - Uses REGIONS_BULK for distribution.
    - Saves to lottery_results_bulk.xlsx.
    """
    # --- Load previous winners to exclude ---
    used_tickets = set()
    if os.path.exists(RESULTS_FILE):
        try:
            df_prev = pd.read_excel(RESULTS_FILE)
            for _, row in df_prev.iterrows():
                tid = None
                for col in ['Ticket ID', 'Ticket Number', 'Ticket']:
                    if col in row and not pd.isna(row[col]):
                        try:
                            tid = int(row[col])
                            break
                        except Exception:
                            pass
                if tid is not None:
                    used_tickets.add(tid)
        except Exception as e:
            print("Warning: could not read previous results:", e)

    # --- Prepare all tickets excluding used ones ---
    all_tickets = [t for t in range(TICKET_START, TICKET_END + 1) if t not in used_tickets]
    random.shuffle(all_tickets)

    # --- Prepare results list ---
    results_bulk = []
    total_needed = sum(r[1] for r in REGIONS_BULK)
    if total_needed != PRIZE_MASTER_BULK["Wall Clock"]["count"]:
        print("⚠️ Warning: Region counts do not sum to 111 total wall clocks!")

    # --- For each region, draw given number of wall clocks ---
    rank_counter = 1
    for region_name, count, color in REGIONS_BULK:
        available_tickets_region = []
        # find tickets in this region based on main REGIONS list
        for ticket in all_tickets:
            reg, _ = get_region(ticket)
            if reg == region_name:
                available_tickets_region.append(ticket)
        random.shuffle(available_tickets_region)
        selected_tickets = available_tickets_region[:count]

        for t in selected_tickets:
            results_bulk.append({
                'rank': rank_counter,
                'ticket_number': t,
                'ticket': f"{t:05d}",
                'region': region_name,
                'region_color': color,
                'prize_name': 'Wall Clock',
                'prize_image': PRIZE_MASTER_BULK['Wall Clock']['image']
            })
            rank_counter += 1
            # remove from global list so no duplicates
            if t in all_tickets:
                all_tickets.remove(t)

    # --- Shuffle final bulk results ---
    random.shuffle(results_bulk)

    # --- Save to Excel ---
    df = pd.DataFrame(results_bulk)
    df = df[['rank', 'ticket', 'ticket_number', 'region', 'prize_name', 'prize_image']]
    df.columns = ['Rank', 'Ticket Number', 'Ticket ID', 'Region', 'Prize Name', 'Prize Image']
    df.to_excel(RESULTS_FILE_BULK, index=False)

    return results_bulk


# ---------- Flask routes & API ----------
HTML_TEMPLATE = r"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>ADBL Festive Lucky Draw</title>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<style>
body { font-family: 'Noto Sans', Arial, sans-serif; background:#f0f5f4; color:#004d40; margin:0; padding:0;}
.container { max-width:1140px; margin:30px auto; background:#fff; padding:28px; border-radius:12px; box-shadow:0 8px 30px rgba(0,0,0,0.06); }
.header { text-align:center; border-bottom:3px solid #00755b; padding-bottom:12px; margin-bottom:18px; }
.header h1 { margin:8px 0; font-size:2rem; color:#004c40; }
.stage { display:flex; gap:28px; flex-wrap:wrap; justify-content:center; align-items:flex-start; }
.ticket-box { background:#e6f2ef; padding:22px; border-radius:12px; width:380px; text-align:center; box-shadow:0 6px 18px rgba(0,115,78,0.08); }
.digits { display:flex; justify-content:center; gap:10px; margin:18px 0 8px 0; }
.digit { width:62px; height:86px; border-radius:10px; background:#00755b; color:#a3edd9; display:flex; align-items:center; justify-content:center; font-weight:800; font-size:40px; font-family:monospace; }
#regionBadge { padding:10px 18px; border-radius:22px; background:#e6091f; color:#a3edd9; font-weight:700; display:inline-block; margin-top:8px;}
button { width:100%; padding:12px 14px; border-radius:20px; border:none; font-weight:800; cursor:pointer; margin-top:10px; }
#drawBtn { background:#00755b; color:#a3edd9;}
#bulkBtn { background:#00755b; color:#a3edd9;}
#uploadBtn { background:#004c40; color:#a3edd9;}
.prize-card { text-align:center; max-width:360px; padding:18px; }
#prizeImage { width:260px; height:260px; object-fit:cover; border-radius:16px; box-shadow:0 10px 30px rgba(72,184,163,0.12); }
#statusText { margin-top:12px; font-weight:700; color:#23735f; font-size:1.05rem; }

.table-wrap { margin-top:28px; }
table { width:100%; border-collapse:collapse; font-weight:600; color:#00573a; }
th, td { padding:12px 14px; border:1px solid #cde6db; text-align:left; }
th { background:#00755b; color:#a3edd9; font-size:1rem; }
tr:nth-child(even) { background:#eaf6f1; }
.region-tag { padding:6px 14px; border-radius:20px; color:white; font-weight:700; display:inline-block; }

/* Pagination */
#pagination { margin-top:12px; text-align:center; }
#pagination button { margin:2px; padding:6px 10px; border-radius:6px; border:none; cursor:pointer; }
#resultsCount { font-weight:700; margin-left:10px; color:#01634e; }
</style>
</head>
<body>
<div class="container">
  <header class="header">
    <h1>दशैं-तिहार उपहार कार्यक्रम २०८२ — Lucky Draw</h1>
    <div id="statsBar">🎟️ Total Prizes: <span id="totalPrizes">{{total_winners}}</span> | 🏆 Drawn: <span id="drawnCount">0</span> | 🎁 Remaining: <span id="remainingCount">{{total_winners}}</span></div>
  </header>

  <div class="stage">
    <div class="ticket-box">
      <h3>Lucky Ticket</h3>
      <div class="digits" id="digits">
        <div class="digit" id="d0">0</div>
        <div class="digit" id="d1">0</div>
        <div class="digit" id="d2">0</div>
        <div class="digit" id="d3">0</div>
        <div class="digit" id="d4">0</div>
      </div>
      <hr width="100%" size="2">
      <div id="regionBadge">Region</div>
      <hr width="100%" size="2">
      <button id="drawBtn">🎊 DRAW NOW 🎉</button>
      <hr width="100%" size="2">
      <button id="bulkBtn">🎯 DRAW BULK WALL CLOCKS</button>
      <input type="file" id="uploadInput" style="display:none;">
      <hr width="100%" size="2">
      <div id="statusText">Ready to draw</div>
    </div>

    <div class="prize-card">
      <img id="prizeImage" src="/static/prizes/wall_clock.jpg" alt="Prize Image">
      <div id="prizeBadge" style="font-weight:800; margin-top:12px;">Wall Clock</div>
    </div>
  </div>

  <div class="table-wrap">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <h3 style="margin:8px 0;">Draw Results</h3>
      <div id="resultsCount">Showing <span id="shownCount">0</span> results</div>
    </div>

    <table>
      <thead>
        <tr>
          <th>Rank</th><th>Ticket</th><th>Region</th><th>Prize</th>
        </tr>
      </thead>
      <tbody id="resultsBody"></tbody>
    </table>

    <div id="pagination"></div>
  </div>
</div>

<audio id="drumroll" preload="auto"><source src="/static/sounds/drumroll.mp3" type="audio/mpeg"></audio>
<audio id="cheer" preload="auto"><source src="/static/sounds/cheer.mp3" type="audio/mpeg"></audio>

<script>
const drawBtn = document.getElementById('drawBtn');
const uploadBtn = document.getElementById('uploadBtn');
const uploadInput = document.getElementById('uploadInput');
const regionBadge = document.getElementById('regionBadge');
const prizeImage = document.getElementById('prizeImage');
const prizeBadge = document.getElementById('prizeBadge');
const statusText = document.getElementById('statusText');
const resultsBody = document.getElementById('resultsBody');
const drumroll = document.getElementById('drumroll');
const cheer = document.getElementById('cheer');
const shownCount = document.getElementById('shownCount');
const bulkBtn = document.getElementById('bulkBtn');

let allResults = [];
let currentPage = 1;
const rowsPerPage = 10;

// ---------------------- NEW LUCKY TICKET ROLL LOGIC ----------------------

// rolls a single digit for 3s and ends on the final lucky number
async function rollDigit(digitElement, finalDigit, duration = 3000) {
  const start = Date.now();
  let currentDigit = 0;

  return new Promise(resolve => {
    const interval = setInterval(() => {
      currentDigit = (currentDigit + 1) % 10;
      digitElement.textContent = currentDigit;

      if (Date.now() - start >= duration) {
        clearInterval(interval);
        digitElement.textContent = finalDigit;
        resolve();
      }
    }, 50);
  });
}

// rolls all digits sequentially (3s each)
async function rollDigitsSequentially(luckyNumber, callback) {
  const digits = document.querySelectorAll('.digit');
  for (let i = 0; i < digits.length; i++) {
    await rollDigit(digits[i], luckyNumber[i], 3000);
  }
  callback();
}

function updateStatsUI(total, drawn, remaining) {
  document.getElementById('totalPrizes').textContent = total;
  document.getElementById('drawnCount').textContent = drawn;
  document.getElementById('remainingCount').textContent = remaining;
}

function renderResultsTable() {
  resultsBody.innerHTML = '';
  allResults.slice().reverse().forEach(r => {
    const tr = document.createElement('tr');
    tr.dataset.rank = r.rank;

    const tdRank = document.createElement('td'); tdRank.textContent = r.rank;
    const tdTicket = document.createElement('td'); tdTicket.textContent = r.ticket;
    const tdRegion = document.createElement('td'); 
    tdRegion.innerHTML = `<span class="region-tag" style="background:${r.region_color}">${r.region}</span>`;
    const tdPrize = document.createElement('td'); tdPrize.textContent = r.prize_name;

    tr.appendChild(tdRank); tr.appendChild(tdTicket); tr.appendChild(tdRegion); tr.appendChild(tdPrize);
    resultsBody.appendChild(tr);
  });
  paginateTable();
}

function paginateTable() {
  const rows = Array.from(resultsBody.children);
  const totalPages = Math.max(1, Math.ceil(rows.length / rowsPerPage));
  if (currentPage > totalPages) currentPage = totalPages;
  rows.forEach((row, i) => {
    const visible = (i >= (currentPage - 1) * rowsPerPage && i < currentPage * rowsPerPage);
    row.style.display = visible ? '' : 'none';
  });
  const pagination = document.getElementById('pagination');
  let html = '';
  for (let p = 1; p <= totalPages; p++) {
    html += `<button onclick="gotoPage(${p})" style="${p===currentPage ? 'background:#00755b;color:#fff;' : 'background:#e6f2ef;'}">${p}</button>`;
  }
  pagination.innerHTML = html;
  shownCount.textContent = rows.length;
}

function gotoPage(p) { currentPage = p; paginateTable(); }

// ---------------------- DRAW PROCESS ----------------------

drawBtn.onclick = async function() {
  drawBtn.disabled = true;
  statusText.textContent = "Rolling digits...";

  // ✅ Reset all digits to 0 for new draw
  const digits = document.querySelectorAll('.digit');
  digits.forEach(d => d.textContent = '-');
  regionBadge.textContent = "Region";
  regionBadge.style.backgroundColor = "";
  prizeBadge.textContent = "Shuffling...";
  prizeImage.src = "/static/prizes/wall_clock.jpg";

  drumroll.currentTime = 0;
  drumroll.loop = true;
  drumroll.play();

  // get next winner info
  try {
    const res = await fetch('/api/draw', {method:'POST'});
    const stats = await res.json();

    if (stats.error) {
      statusText.textContent = stats.error;
      drumroll.pause(); drumroll.currentTime = 0;
      drawBtn.disabled = false;
      return;
    }

    const w = stats.winner;
    if (!w) {
      statusText.textContent = "No winner returned.";
      drawBtn.disabled = false;
      drumroll.pause(); drumroll.currentTime = 0;
      return;
    }

    const luckyNumber = w.ticket;

    // Roll all digits sequentially (3s each)
    await rollDigitsSequentially(luckyNumber, () => {});

    // --- Shuffle prize animation for 5 seconds before revealing the actual one ---
    const prizeNames = [
        "Bullet 350 Classic Bike",
        "Chetak Scooter",
        "1 kg Fine Silver",
        "Samsung Washing Machine",
        "Vacuum Cleaner",
        "Futura Pressure Cooker",
        "Wall Clock"
    ];

    const prizeImages = {
        "Bullet 350 Classic Bike": "/static/prizes/bullet_350.jpg",
        "Chetak Scooter": "/static/prizes/chetak_scooter.jpg",
        "1 kg Fine Silver": "/static/prizes/fine_silver.jpg",
        "Samsung Washing Machine": "/static/prizes/samsung_washing_machine.jpg",
        "Vacuum Cleaner": "/static/prizes/vacuum_cleaner.jpg",
        "Futura Pressure Cooker": "/static/prizes/futura_pressure_cooker.jpg",
        "Wall Clock": "/static/prizes/wall_clock.jpg"
    };

    // Shuffle animation (5s total)
    await new Promise(resolve => {
        const start = Date.now();
        const interval = setInterval(() => {
        const randPrize = prizeNames[Math.floor(Math.random() * prizeNames.length)];
        prizeBadge.textContent = randPrize;
        prizeImage.src = prizeImages[randPrize];
        if (Date.now() - start > 5000) { // stop after 5 seconds
            clearInterval(interval);
            resolve();
        }
    }, 120);
    });

    // --- Show the actual prize ---
    regionBadge.textContent = w.region;
    regionBadge.style.backgroundColor = w.region_color;
    prizeBadge.textContent = w.prize_name;
    prizeImage.src = w.prize_image;


    updateStatsUI(stats.total_prizes || {{total_winners}}, stats.drawn_count, stats.remaining_count);
    allResults.push(w);
    renderResultsTable();

    drumroll.pause(); drumroll.currentTime = 0; drumroll.loop = false;
    cheer.currentTime = 0; cheer.play();
    statusText.innerHTML = "<b>Drawn!</b>";
  } catch (err) {
    console.error(err);
    statusText.textContent = "Error drawing prize.";
  } finally {
    drawBtn.disabled = false;
  }
};

// ---------------------- BULK DRAW PROCESS ----------------------
bulkBtn.onclick = async function() {
  bulkBtn.disabled = true;
  statusText.textContent = "🎯 Preparing bulk draw for Wall Clocks...";
  drumroll.currentTime = 0; drumroll.loop = true; drumroll.play();

  try {
    // Fetch bulk draw results
    const res = await fetch('/api/draw_bulk', { method: 'POST' });
    const data = await res.json();

    if (data.error) {
      statusText.textContent = data.error;
      drumroll.pause(); drumroll.currentTime = 0;
      bulkBtn.disabled = false;
      return;
    }

    // --- 5 second shuffle effect (simulate spinning/shuffling) ---
    statusText.textContent = "🔄 Shuffling prizes...";
    const prizeNames = ["🎁 Shuffling...", "🎁 Mixing all...", "🎁 Almost ready...", "🎁 Finalizing..."];
    for (let i = 0; i < 5; i++) {
      prizeBadge.textContent = prizeNames[i % prizeNames.length];
      prizeImage.src = "/static/prizes/wall_clock.jpg";
      await new Promise(r => setTimeout(r, 1000)); // 1s each × 5 = 5 seconds
    }

    // --- Display final result summary ---
    drumroll.pause(); drumroll.currentTime = 0; drumroll.loop = false;
    cheer.currentTime = 0; cheer.play();

    const winners = data.results || [];
    statusText.innerHTML = `<b>${winners.length} Wall Clock winners drawn successfully!</b>`;

    // Update stats UI
    updateStatsUI({{total_winners}}, current_drawn_count = 26 + winners.length, remaining = 0);

    // Merge with allResults so they show in table
    allResults = allResults.concat(winners);
    renderResultsTable();

    // Highlight prize
    prizeBadge.textContent = "Wall Clock (Bulk Winners)";
    prizeImage.src = "/static/prizes/wall_clock.jpg";

  } catch (err) {
    console.error(err);
    statusText.textContent = "Error drawing bulk prizes.";
  } finally {
    bulkBtn.disabled = false;
  }
};

// ---------------------- FILE UPLOAD + RESULTS ----------------------

uploadBtn.onclick = () => uploadInput.click();
uploadInput.onchange = async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const formData = new FormData();
  formData.append("file", file);
  const resp = await fetch('/api/upload', { method:'POST', body: formData });
  const stats = await resp.json();
  updateStatsUI(stats.total_prizes || {{total_winners}}, stats.drawn_count, stats.remaining_count);
  await loadResultsFromServer();
  for (let d = 0; d < 5; d++) document.getElementById('d'+d).textContent = '0';
  regionBadge.textContent = 'Region'; regionBadge.style.backgroundColor = '';
  prizeBadge.textContent = 'Wall Clock'; prizeImage.src = '/static/prizes/wall_clock.jpg';
  statusText.textContent = 'Ready to draw';
};

async function loadResultsFromServer() {
  try {
    const r = await fetch('/api/results');
    const data = await r.json();
    allResults = data.results || [];
    renderResultsTable();
    updateStatsUI(data.total_prizes || {{total_winners}}, data.drawn_count || 0, data.remaining_count || {{total_winners}});
  } catch (e) {
    console.warn("Could not load results:", e);
  }
}

loadResultsFromServer();
</script>
</body>
</html>
"""

#calling API
@app.route("/")
def index():
    # ensure initialization so HTML page can query /api/results immediately
    initialize_draw()
    return render_template_string(HTML_TEMPLATE, total_winners=TOTAL_WINNERS)

@app.route("/api/draw", methods=["POST"])
def api_draw():
    # Restrict single draws after 26 have been completed
    if current_draw['total_drawn'] >= 26:
        return jsonify({
            "error": "Only bulk draw available now."
        }), 400

    winner = draw_single_winner()
    if winner is None:
        return jsonify({
            "error": "All winners drawn or no prize/ticket available."
        }), 400

    remaining_count = sum(meta['count'] for meta in current_draw['prize_counts_remaining'].values())

    return jsonify({
        "total_prizes": TOTAL_WINNERS,
        "drawn_count": current_draw['total_drawn'],
        "remaining_count": max(0, TOTAL_WINNERS - current_draw['total_drawn']),
        "winner": winner
    })


@app.route("/api/results", methods=["GET"])
def api_results():
    # Return full results list and counts for UI to render
    remaining_count = sum(meta['count'] for meta in current_draw['prize_counts_remaining'].values())
    return jsonify({
        "total_prizes": TOTAL_WINNERS,
        "drawn_count": current_draw['total_drawn'],
        "remaining_count": max(0, TOTAL_WINNERS - current_draw['total_drawn']),
        "results": current_draw['results']  # list of dicts
    })

@app.route("/api/upload", methods=["POST"])
def api_upload():
    """Upload an Excel (same format as saved) to populate/overwrite session results.
       The endpoint reads the uploaded file and uses it as the authoritative previously-drawn set,
       then re-computes remaining tickets & prizes for the next draws.
    """
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "No file uploaded"}), 400
    try:
        df = pd.read_excel(file)
    except Exception as e:
        return jsonify({"error": f"Could not read uploaded file: {e}"}), 400

    # Validate and convert rows
    rows = []
    prize_counts = {name: {"count": meta["count"], "image": meta.get("image", "/static/prizes/default.jpg")} for name, meta in PRIZE_MASTER.items()}
    tickets_taken = set()
    for _, row in df.iterrows():
        ticket_id = None
        try:
            if 'Ticket ID' in row and not pd.isna(row['Ticket ID']):
                ticket_id = int(row['Ticket ID'])
            elif 'Ticket Number' in row and not pd.isna(row['Ticket Number']):
                ticket_id = int(row['Ticket Number'])
            elif 'Ticket' in row and not pd.isna(row['Ticket']):
                ticket_id = int(str(row['Ticket']).strip())
        except Exception:
            continue
        prize_name = str(row.get('Prize Name', '')).strip()
        rank = int(row.get('Rank', 0)) if not pd.isna(row.get('Rank', 0)) else 0
        prize_image = row.get('Prize Image', PRIZE_MASTER.get(prize_name, {}).get('image', '/static/prizes/default.jpg'))

        if ticket_id is None:
            continue
        region_name, region_color = get_region(ticket_id)
        rows.append({
            'rank': rank, 'ticket_number': ticket_id, 'ticket': f"{ticket_id:05d}",
            'region': region_name, 'region_color': region_color,
            'prize_name': prize_name, 'prize_image': prize_image
        })
        tickets_taken.add(ticket_id)
        # decrement prize_counts if exists
        if prize_name in prize_counts and prize_counts[prize_name]['count'] > 0:
            prize_counts[prize_name]['count'] -= 1

    # Overwrite in-memory state based on uploaded file
    current_draw['results'] = sorted(rows, key=lambda r: r['rank'])  # keep ascending rank order
    current_draw['total_drawn'] = len(current_draw['results'])
    # rebuild available tickets
    all_tickets = list(range(TICKET_START, TICKET_END + 1))
    current_draw['available_tickets'] = [t for t in all_tickets if t not in tickets_taken]
    # rebuild remaining prizes list and counts
    current_draw['prize_counts_remaining'] = prize_counts
    current_draw['available_prizes'] = build_prize_list_from_counts({k: {'count': v['count'], 'image': v['image']} for k, v in prize_counts.items()})
    random.shuffle(current_draw['available_tickets'])
    random.shuffle(current_draw['available_prizes'])
    # Save uploaded data to RESULTS_FILE so it's persisted as base for the next session
    save_results_to_excel()

    return jsonify({
        "total_prizes": TOTAL_WINNERS,
        "drawn_count": current_draw['total_drawn'],
        "remaining_count": max(0, TOTAL_WINNERS - current_draw['total_drawn']),
        "message": "Uploaded and loaded results."
    })

@app.route("/api/draw_bulk", methods=["POST"])
def api_draw_bulk():
    """
    API endpoint to trigger the bulk Wall Clock draw.
    Returns JSON with summary and winners list.
    """
    # Ensure main draw has reached at least 26
    if current_draw['total_drawn'] < 26:
        return jsonify({
            "error": "Bulk draw allowed only after 26 draws."
        }), 400

    # Prevent multiple bulk draws (if already performed)
    if os.path.exists(RESULTS_FILE_BULK):
        try:
            df_bulk_existing = pd.read_excel(RESULTS_FILE_BULK)
            if not df_bulk_existing.empty and len(df_bulk_existing) >= PRIZE_MASTER_BULK["Wall Clock"]["count"]:
                return jsonify({
                    "error": "Bulk draw already completed. 111 Wall Clock winners have been selected."
                }), 400
        except Exception as e:
            print("⚠️ Warning: Could not read existing bulk file:", e)

    # Perform the bulk wall clock draw
    try:
        results_bulk = draw_bulk_wall_clocks()
    except Exception as e:
        return jsonify({
            "error": f"Bulk draw failed: {str(e)}"
        }), 500

    return jsonify({
        "message": f"{len(results_bulk)} Wall Clock winners drawn successfully.",
        "results": results_bulk,
        "total_prizes": TOTAL_WINNERS,
        "drawn_count": current_draw['total_drawn'],
        "remaining_count": max(0, TOTAL_WINNERS - current_draw['total_drawn'])
    })


if __name__ == "__main__":
    initialize_draw()
    app.run(debug=True, port=5000)
