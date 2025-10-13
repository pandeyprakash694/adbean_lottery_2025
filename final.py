from flask import Flask, render_template_string, jsonify, request
import random
import pandas as pd
import os
from datetime import datetime
from collections import Counter

app = Flask(__name__)

RESULTS_FILE = 'lottery_results.xlsx'
TOTAL_TICKETS = 10000
TOTAL_WINNERS = 136
TOP_PRIZES_COUNT = 4

PRIZES = [
    {"name": "Bullet 350 Classic Bike", "image": "/static/prizes/bullet_350.jpg"},
    {"name": "Chetak Scooter", "image": "/static/prizes/chetak_scooter.jpg"},
    {"name": "1 kg Fine Silver", "image": "/static/prizes/fine_silver.jpg"},
    {"name": "Samsung Washing Machine", "image": "/static/prizes/samsung_washing_machine.jpg"},
] + [{"name": "Vacuum Cleaner", "image": "/static/prizes/vacuum_cleaner.jpg"}] * 11 \
  + [{"name": "Futura Pressure Cooker", "image": "/static/prizes/futura_pressure_cooker.jpg"}] * 11 \
  + [{"name": "Wall Clock", "image": "/static/prizes/wall_clock.jpg"}] * 111

REGIONS = [
    ("Koshi", 0, 1428, "#00755b"),
    ("Madhesh", 1429, 2857, "#a1c181"),
    ("Bagmati", 2858, 4286, "#10ac84"),
    ("Bharatpur", 4287, 5715, "#004d40"),
    ("Karnali", 5716, 7144, "#00755b"),
    ("Lumbini", 7145, 8573, "#4caf50"),
    ("Dang", 8574, 9999, "#009688"),
]

def get_region(ticket_number):
    for name, start, end, color in REGIONS:
        if start <= ticket_number <= end:
            return name, color
    return "Unknown", "#999999"

current_draw = {}

def initialize_draw():
    global current_draw
    current_draw = {
        'results': [],
        'available_tickets': list(range(TOTAL_TICKETS)),
        'available_prizes': PRIZES.copy(),
        'top_prizes_drawn': 0,
        'total_drawn': 0,
        'draw_id': datetime.now().strftime("%Y%m%d_%H%M%S"),
        'initialized': True
    }
    name_to_image = {p['name']: p['image'] for p in PRIZES}
    drawn_tickets = set()
    remaining_prize_counts = Counter(p['name'] for p in PRIZES)

    if os.path.exists(RESULTS_FILE):
        df = pd.read_excel(RESULTS_FILE)
        for _, row in df.iterrows():
            prize_name = row['Prize Name']
            ticket_id = int(row['Ticket ID'])
            rank = row['Rank']
            region_name, region_color = get_region(ticket_id)
            drawn_tickets.add(ticket_id)
            if prize_name in remaining_prize_counts:
                remaining_prize_counts[prize_name] -= 1
            result = {
                'rank': rank,
                'ticket': f"{ticket_id:04d}",
                'ticket_number': ticket_id,
                'region': region_name,
                'region_color': region_color,
                'prize_name': prize_name,
                'prize_image': name_to_image.get(prize_name, '/static/prizes/default.jpg'),
                'is_top_prize': rank <= TOP_PRIZES_COUNT
            }
            if result['is_top_prize']:
                current_draw['top_prizes_drawn'] += 1
            current_draw['results'].append(result)
        current_draw['total_drawn'] = len(df)
        current_draw['available_tickets'] = [t for t in current_draw['available_tickets'] if t not in drawn_tickets]
        current_draw['available_prizes'] = []
        for name, count in remaining_prize_counts.items():
            image = name_to_image.get(name, '/static/prizes/default.jpg')
            current_draw['available_prizes'].extend([{'name': name, 'image': image} for _ in range(count)])
    random.shuffle(current_draw['available_tickets'])
    random.shuffle(current_draw['available_prizes'])
    if not os.path.exists(RESULTS_FILE):
        df = pd.DataFrame(columns=['Rank', 'Ticket Number', 'Ticket ID', 'Region', 'Prize Name'])
        df.to_excel(RESULTS_FILE, index=False)

def save_results_to_excel():
    if not current_draw['results']:
        return
    df = pd.DataFrame(current_draw['results'])
    df = df[['rank', 'ticket', 'ticket_number', 'region', 'prize_name']]
    df.columns = ['Rank', 'Ticket Number', 'Ticket ID', 'Region', 'Prize Name']
    with pd.ExcelWriter(RESULTS_FILE, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Lottery Results')

def draw_single_winner():
    if not current_draw['initialized']:
        initialize_draw()
    if current_draw['total_drawn'] >= TOTAL_WINNERS:
        return None
    ticket = current_draw['available_tickets'].pop()
    prize = current_draw['available_prizes'].pop()
    current_draw['total_drawn'] += 1
    is_top = current_draw['total_drawn'] <= TOP_PRIZES_COUNT
    if is_top:
        current_draw['top_prizes_drawn'] += 1
    region_name, region_color = get_region(ticket)
    result = {
        'rank': current_draw['total_drawn'],
        'ticket': f"{ticket:04d}",
        'ticket_number': ticket,
        'region': region_name,
        'region_color': region_color,
        'prize_name': prize['name'],
        'prize_image': prize['image'],
        'is_top_prize': is_top
    }
    current_draw['results'].append(result)
    save_results_to_excel()
    return result

@app.route("/")
def index():
    initialize_draw()
    return render_template_string(HTML_TEMPLATE, total_winners=TOTAL_WINNERS)

@app.route("/api/draw", methods=["POST"])
def api_draw():
    winner = draw_single_winner()
    remaining_prizes_counter = Counter(p['name'] for p in current_draw['available_prizes'])
    remaining_prizes_summary = [
        {"name": name, "count": count} for name, count in remaining_prizes_counter.items() if count > 0
    ]

    stats = {
        "total_prizes": TOTAL_WINNERS,
        "drawn_count": current_draw['total_drawn'],
        "remaining_count": TOTAL_WINNERS - current_draw['total_drawn'],
        "winner": winner,
        "remaining_prizes_summary": remaining_prizes_summary
    }
    return jsonify(stats)

@app.route("/api/upload", methods=["POST"])
def api_upload():
    file = request.files["file"]
    df = pd.read_excel(file)
    initialize_draw()
    name_to_image = {p['name']: p['image'] for p in PRIZES}
    drawn_tickets = set()
    remaining_prize_counts = Counter(p['name'] for p in PRIZES)
    current_draw['results'] = []
    current_draw['top_prizes_drawn'] = 0
    for _, row in df.iterrows():
        prize_name = row['Prize Name']
        ticket_id = int(row['Ticket ID'])
        rank = row['Rank']
        region_name, region_color = get_region(ticket_id)
        drawn_tickets.add(ticket_id)
        if prize_name in remaining_prize_counts:
            remaining_prize_counts[prize_name] -= 1
        result = {
            'rank': rank,
            'ticket': f"{ticket_id:04d}",
            'ticket_number': ticket_id,
            'region': region_name,
            'region_color': region_color,
            'prize_name': prize_name,
            'prize_image': name_to_image.get(prize_name, '/static/prizes/default.jpg'),
            'is_top_prize': rank <= TOP_PRIZES_COUNT
        }
        if result['is_top_prize']:
            current_draw['top_prizes_drawn'] += 1
        current_draw['results'].append(result)
    current_draw['total_drawn'] = len(df)
    current_draw['available_tickets'] = [t for t in current_draw['available_tickets'] if t not in drawn_tickets]
    current_draw['available_prizes'] = []
    for name, count in remaining_prize_counts.items():
        image = name_to_image.get(name, '/static/prizes/default.jpg')
        current_draw['available_prizes'].extend([{'name': name, 'image': image} for _ in range(count)])

    remaining_prizes_counter = Counter(p['name'] for p in current_draw['available_prizes'])
    remaining_prizes_summary = [
        {"name": name, "count": count} for name, count in remaining_prizes_counter.items() if count > 0
    ]

    return jsonify({
        "total_prizes": TOTAL_WINNERS,
        "drawn_count": current_draw['total_drawn'],
        "remaining_count": TOTAL_WINNERS - current_draw['total_drawn'],
        "remaining_prizes_summary": remaining_prizes_summary
    })

HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>ADBL Festive Lucky Draw</title>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<style>
/* Theme styles as before */
body {
    font-family: 'Noto Sans', 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    background-color: #f0f5f4;
    margin: 0; padding: 0;
    color: #004d40;
}
.container {
    max-width: 1140px;
    margin: 40px auto;
    background: #fff;
    padding: 40px 48px;
    box-shadow: 0 0 30px rgba(4, 91, 73, 0.15);
    border-radius: 15px;
}
.header {
    text-align: center;
    margin-bottom: 30px;
    border-bottom: 3px solid #00755b;
    padding-bottom: 15px;
}
.header h1 {
    font-weight: 800;
    font-size: 2.8rem;
    letter-spacing: 0.06em;
    color: #004c40;
    margin: 0;
}
.header p {
    font-weight: 600;
    font-size: 1.15rem;
    margin-top: 8px;
    color: #23735f;
}
#statsBar {
    font-size: 1.2rem;
    font-weight: 700;
    text-align: center;
    margin-bottom: 8px;
    color: #014c40;
}
#remainingPrizesDetails {
    font-weight: 600;
    text-align: center;
    margin-bottom: 30px;
    color: #01634e;
}
.stage {
    display: flex;
    justify-content: center;
    gap: 50px;
    flex-wrap: wrap;
}
.ticket-box {
    background: #e6f2ef;
    padding: 30px;
    border-radius: 16px;
    box-shadow: 0 6px 20px rgba(0, 115, 78, 0.1);
    max-width: 400px;
    width: 100%;
    text-align: center;
}
.digits {
    display: flex;
    justify-content: center;
    gap: 12px;
    margin: 25px 0 35px 0;
}
.digit {
    width: 72px;
    height: 110px;
    border-radius: 12px;
    background-color: #00755b;
    color: #a3edd9;
    display: flex;
    justify-content: center;
    align-items: center;
    font-weight: 800;
    font-size: 52px;
    box-shadow: inset 0 8px 15px rgba(0, 97, 60, 0.6);
    user-select: none;
    font-family: monospace;
}
#regionBadge {
    margin-top: 10px;
    padding: 14px 26px;
    background-color: #004c40;
    color: #a3edd9;
    border-radius: 26px;
    font-weight: 700;
    font-size: 1.2rem;
    box-shadow: 0 0 22px #01a982aa;
    font-feature-settings: 'liga' 0;
    user-select: none;
}
#prizeImage {
    max-width: 260px;
    max-height: 260px;
    border-radius: 20px;
    margin-bottom: 18px;
    box-shadow: 0 0 45px #48b8a3cc;
    object-fit: cover;
}
#prizeBadge {
    font-weight: 800;
    font-size: 1.7rem;
    color: #004c40;
    margin-bottom: 25px;
    text-transform: uppercase;
    letter-spacing: 0.1em;
}
#statusText {
    font-weight: 600;
    font-size: 1.1rem;
    color: #23735f;
    margin-bottom: 32px;
    user-select: none;
}
button {
    width: 100%;
    padding: 14px 26px;
    font-weight: 700;
    font-size: 1.15rem;
    border-radius: 28px;
    border: none;
    cursor: pointer;
    transition: background-color 0.3s ease;
    margin-bottom: 12px;
    box-shadow: 0 10px 25px rgba(4, 91, 73, 0.2);
    user-select: none;
}
#drawBtn {
    background-color: #00755b;
    color: #a3edd9;
}
#drawBtn:hover:not(:disabled) {
    background-color: #00573a;
}
#drawBtn:disabled {
    background-color: #99c0b6;
    cursor: not-allowed;
    box-shadow: none;
}
#uploadBtn {
    background-color: #004c40;
    color: #a3edd9;
}
#uploadBtn:hover {
    background-color: #003225;
}
table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 40px;
    font-weight: 600;
    color: #00573a;
}
th, td {
    border: 1px solid #a3c9ba;
    padding: 14px 18px;
    text-align: left;
}
th {
    background-color: #00755b;
    color: #a3edd9;
    font-size: 1.15rem;
}
tr:nth-child(even) {
    background-color: #def1ec;
}
.region-tag {
    padding: 6px 18px;
    border-radius: 24px;
    color: white;
    background-color: currentColor;
    font-size: 1rem;
    display: inline-block;
    user-select: none;
    font-weight: 700;
    text-align: center;
}
</style>
</head>
<body>
<div class="container">
        <!-- Header Section -->
        <header class="header">
            <div class="logo-container">
                <img class="header-image" src="/static/logo/logo_union.png" alt="Header Image" />
            </div>
            <h1>दशैं-तिहार उपहार कार्यक्रम २०८२</h1>
            <!-- Uncomment if needed: <h1>कृषि विकास बैंक कर्मचारी संघ, नेपाल</h1> -->
        </header>

        <!-- Prize Information 
        <section class="prize-info">
            <p>Total Prizes: {{total_winners}}</p>
        </section>
        -->
    </div>
    <div id="statsBar">
        🎟️ Total: <span id="totalPrizes">{{total_winners}}</span> | 
        🏆 Drawn: <span id="drawnCount">0</span> | 
        🎁 Remaining: <span id="remainingCount">{{total_winners}}</span>
    </div>
    <div id="remainingPrizesDetails"></div>
    <div class="stage">
        <div class="ticket-box">
            <h3>Lucky Ticket</h3>
            <div class="digits" id="digits">
                <div class="digit" id="d0"></div>
                <div class="digit" id="d1"></div>
                <div class="digit" id="d2"></div>
                <div class="digit" id="d3"></div>
            </div>
            <div id="regionBadge">Region</div>
            <br>
            <button id="drawBtn">🎊 DRAW NOW 🎉</button>
            <button id="uploadBtn">Upload Last Saved Excel</button>
            <input type="file" id="uploadInput" style="display:none;">
        </div>
        <div style="flex:1; max-width:400px; text-align:center;">
            <img id="prizeImage" src="/static/prizes/wall_clock.jpg" alt="Prize Image" />
            <div id="prizeBadge">Wall Clock</div>
            <div id="statusText">Ready to draw</div>
        </div>
    </div>

    <table>
      <thead>
        <tr>
          <th>Rank</th>
          <th>Ticket</th>
          <th>Region</th>
          <th>Prize</th>
        </tr>
      </thead>
      <tbody id="resultsBody"></tbody>
    </table>
</div>

<audio id="drumroll" preload="auto">
    <source src="/static/sounds/drumroll.mp3" type="audio/mpeg"/>
</audio>
<audio id="cheer" preload="auto">
    <source src="/static/sounds/cheer.mp3" type="audio/mpeg"/>
</audio>

<script>
const drawBtn = document.getElementById('drawBtn');
const uploadBtn = document.getElementById('uploadBtn');
const uploadInput = document.getElementById('uploadInput');
const regionBadge = document.getElementById('regionBadge');
const prizeImage = document.getElementById('prizeImage');
const prizeBadge = document.getElementById('prizeBadge');
const statusText = document.getElementById('statusText');
const resultsBody = document.getElementById('resultsBody');
const remainingPrizesDetails = document.getElementById('remainingPrizesDetails');
const drumroll = document.getElementById('drumroll');
const cheer = document.getElementById('cheer');

function spinDigit(index, spins, callback) {
    let count = 0;
    function spin() {
        if (count < spins) {
            document.getElementById('d' + index).textContent = Math.floor(Math.random() * 10);
            count++;
            setTimeout(spin, 60);
        } else {
            callback();
        }
    }
    spin();
}

function spinDigitsSequentially(callback) {
    let index = 0;
    function next() {
        if (index < 4) {
            spinDigit(index, 20 + index * 10, () => {
                index++;
                next();
            });
        } else {
            callback();
        }
    }
    next();
}

function updateRemainingPrizes(prizes) {
    if (!prizes || prizes.length === 0) {
        remainingPrizesDetails.innerHTML = "<b>No remaining prizes.</b>";
        return;
    }
    let html = "<b>Remaining Prizes:</b><br>";
    prizes.forEach(p => {
        html += `${p.name}: ${p.count}<br>`;
    });
    remainingPrizesDetails.innerHTML = html;
}

drawBtn.onclick = function() {
    drawBtn.disabled = true;
    statusText.textContent = "Spinning digits...";
    drumroll.currentTime = 0; drumroll.loop = true; drumroll.play();

    spinDigitsSequentially(() => {
        statusText.textContent = "Revealing prize...";
        fetch('/api/draw', { method: 'POST' })
        .then(r => r.json())
        .then(stats => {
            const w = stats.winner;
            if (w) {
                const t = w.ticket;
                for (let d = 0; d < 4; d++) {
                    document.getElementById('d' + d).textContent = t[d];
                }
                regionBadge.textContent = w.region;
                regionBadge.style.backgroundColor = w.region_color;
                prizeBadge.textContent = w.prize_name;
                prizeImage.src = w.prize_image;
                drumroll.pause();
                drumroll.currentTime = 0;
                drumroll.loop = false;
                cheer.currentTime = 0;
                cheer.play();
                document.getElementById('totalPrizes').textContent = stats.total_prizes;
                document.getElementById('drawnCount').textContent = stats.drawn_count;
                document.getElementById('remainingCount').textContent = stats.remaining_count;

                updateRemainingPrizes(stats.remaining_prizes_summary);

                let tr = document.createElement("tr");
                tr.style.background = "#e3f3ee";
                tr.style.fontWeight = "600";

                let tdRank = document.createElement("td");
                tdRank.style.border = "1px solid #a3c4b7";
                tdRank.style.padding = "8px";
                tdRank.textContent = w.rank;

                let tdTicket = document.createElement("td");
                tdTicket.style.border = "1px solid #a3c4b7";
                tdTicket.style.padding = "8px";
                tdTicket.textContent = w.ticket;

                let tdRegion = document.createElement("td");
                tdRegion.style.border = "1px solid #a3c4b7";
                tdRegion.style.padding = "8px";
                tdRegion.className = "region-tag";
                tdRegion.style.backgroundColor = w.region_color;
                tdRegion.style.color = "white";
                tdRegion.style.textAlign = "center";
                tdRegion.textContent = w.region;

                let tdPrize = document.createElement("td");
                tdPrize.style.border = "1px solid #a3c4b7";
                tdPrize.style.padding = "8px";
                tdPrize.textContent = w.prize_name;

                tr.appendChild(tdRank);
                tr.appendChild(tdTicket);
                tr.appendChild(tdRegion);
                tr.appendChild(tdPrize);
                resultsBody.prepend(tr);

                statusText.innerHTML = w.is_top_prize ? "<b>TOP PRIZE WINNER! 🎉</b>" : "<b>Drawn!</b>";
            }
            drawBtn.disabled = false;
        }).catch(() => {
            statusText.textContent = "Error drawing prize.";
            drawBtn.disabled = false;
        });
    });
};

uploadBtn.onclick = () => uploadInput.click();
uploadInput.onchange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const formData = new FormData();
    formData.append("file", file);
    const resp = await fetch('/api/upload', { method: 'POST', body: formData });
    const stats = await resp.json();

    document.getElementById('totalPrizes').textContent = stats.total_prizes;
    document.getElementById('drawnCount').textContent = stats.drawn_count;
    document.getElementById('remainingCount').textContent = stats.remaining_count;

    updateRemainingPrizes(stats.remaining_prizes_summary);

    for(let d = 0; d < 4; d++) {
        document.getElementById('d'+d).textContent = '0';
    }
    resultsBody.innerHTML = '';
    regionBadge.textContent = 'Region';
    regionBadge.style.backgroundColor = '';
    prizeBadge.textContent = 'Wall Clock';
    prizeImage.src = '/static/prizes/wall_clock.jpg';
    statusText.textContent = 'Ready to draw';
};
</script>

</body>
</html>
"""

if __name__ == "__main__":
    initialize_draw()
    app.run(debug=True, port=5000)
