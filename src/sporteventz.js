// src/sporteventz.js
const axios = require('axios');
const cheerio = require('cheerio');
const fs = require('fs');
const path = require('path');

// ---------- Cấu hình ----------
const BASE_URL = 'https://www.sporteventz.com';
// Endpoint quan trọng: Lấy lịch bóng đá
const MAGIC_TABLE_URL = `${BASE_URL}/en/component/magictable/`;
// Các tham số base64 đã giải mã:
// se_module: bW9kX3Nwb3J0ZXZlbnRzX2ZpbHRlcg== -> mod_sportevents_filter
// se_id: U2NoZWR1bGU= -> Schedule
const FOOTBALL_ENDPOINT = (date) => {
    const formattedDate = date.toISOString().split('T')[0]; // YYYY-MM-DD
    return `${MAGIC_TABLE_URL}?Itemid=0&se_date=${formattedDate}%2000:00:00&se_module=bW9kX3Nwb3J0ZXZlbnRzX2ZpbHRlcg==&se_id=U2NoZWR1bGU=`;
};

// Các kênh truyền hình (để tham khảo khi lọc)
const TV_CHANNELS = [
  'Sky Sports', 'TNT Sports', 'BBC', 'ITV', 'Amazon Prime', 'Premier Sports', 'BT Sport',
  'LaLigaTV', 'FreeSports', 'discovery+', 'DAZN', 'ESPN', 'beIN Sports', 'Paramount+',
  'Peacock', 'fuboTV', 'CBS Sports', 'Eurosport', 'Viaplay', 'SuperSport', 'Diema Sport',
  'Nova Sport', 'Sport TV', 'Arena Sport', 'Spiler TV', 'Dazn'
];

// ---------- Bộ lọc bóng đá (giữ nguyên) ----------
const ALLOWED_FOOTBALL_LEAGUES = new Set([
  "Premier League", "Serie A", "La Liga", "Bundesliga", "Ligue 1",
  "UEFA Champions League", "UEFA Europa League", "UEFA Europa Conference League",
  "UEFA Euro", "FA Cup", "League Cup", "FIFA World Cup", "International Friendly"
]);

const PREMIER_LEAGUE_TEAMS = new Set([
  "arsenal", "aston villa", "bournemouth", "brentford", "brighton", "chelsea",
  "crystal palace", "everton", "fulham", "leeds united", "liverpool", "manchester city",
  "manchester united", "newcastle", "nottingham forest", "sunderland", "tottenham hotspur",
  "west ham united", "wolverhampton"
]);

const ALLOWED_TEAMS_PER_LEAGUE = {
  "Premier League": PREMIER_LEAGUE_TEAMS,
  "Serie A": new Set(["inter milan", "ac milan", "napoli", "juventus", "roma", "atalanta", "lazio"]),
  "La Liga": new Set(["barcelona", "real madrid", "atletico madrid"]),
  "Bundesliga": new Set(["bayern munich", "borussia dortmund", "bayer leverkusen"]),
  "Ligue 1": new Set(["psg", "paris saint-germain", "olympique marseille", "marseille"]),
  "FA Cup": PREMIER_LEAGUE_TEAMS,
  "League Cup": PREMIER_LEAGUE_TEAMS
};

function shouldIncludeFootballFixture(homeTeam, awayTeam, competition) {
  // ... (hàm lọc của bạn giữ nguyên)
  if (competition && ALLOWED_FOOTBALL_LEAGUES.has(competition)) {
    const allowedTeams = ALLOWED_TEAMS_PER_LEAGUE[competition];
    if (allowedTeams) {
      const homeLower = homeTeam.toLowerCase();
      const awayLower = awayTeam.toLowerCase();
      return allowedTeams.has(homeLower) || allowedTeams.has(awayLower);
    }
    return true;
  }
  const homeLower = homeTeam.toLowerCase();
  const awayLower = awayTeam.toLowerCase();
  for (const league in ALLOWED_TEAMS_PER_LEAGUE) {
    if (ALLOWED_TEAMS_PER_LEAGUE[league].has(homeLower) || ALLOWED_TEAMS_PER_LEAGUE[league].has(awayLower)) return true;
  }
  return false;
}

// ---------- Hàm chính ----------
async function fetchFootballFixtures(date = new Date()) {
  console.log(`Đang lấy lịch bóng đá cho ngày ${date.toDateString()}...`);
  try {
    const url = FOOTBALL_ENDPOINT(date);
    console.log(`Gọi API: ${url}`);
    const response = await axios.get(url, {
      headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36' }
    });
    
    const $ = cheerio.load(response.data);
    const fixtures = [];

    // Phân tích cú pháp HTML. Dựa trên cấu trúc đã thấy:
    // Mỗi trận đấu được phân tách bằng "##". 
    // Cấu trúc: "Giải đấu ## Đội 1 vs. Đội 2 ## Ngày giờ"
    const text = $('body').text();
    const matches = text.match(/[^#]+##[^#]+##[^#]+/g) || [];

    for (const match of matches) {
      const parts = match.split('##').map(s => s.trim());
      if (parts.length >= 3) {
        const competition = parts[0];
        const teams = parts[1];
        const datetime = parts[2];

        const vsMatch = teams.match(/(.+?)\s+vs\.?\s+(.+)/i);
        if (!vsMatch) continue;
        const homeTeam = vsMatch[1].trim();
        const awayTeam = vsMatch[2].trim();

        // Lọc theo yêu cầu
        if (!shouldIncludeFootballFixture(homeTeam, awayTeam, competition)) {
          continue;
        }

        // Tìm kênh (có thể không có trong HTML này, cần scrape từ trang chi tiết nếu muốn)
        const channels = [];
        TV_CHANNELS.forEach(ch => {
          if (match.toLowerCase().includes(ch.toLowerCase())) {
            channels.push(ch);
          }
        });

        fixtures.push({
          homeTeam,
          awayTeam,
          kickoffUtc: datetime,
          competition,
          channels: [...new Set(channels)],
          sport: 'football'
        });
      }
    }

    console.log(`Tìm thấy ${fixtures.length} trận bóng đá sau khi lọc.`);
    return fixtures;
  } catch (error) {
    console.error('Lỗi khi lấy dữ liệu bóng đá:', error.message);
    return [];
  }
}

async function fetchTennisFixtures() {
  console.log('Đang lấy lịch tennis...');
  // Logic tương tự cho tennis, có thể sử dụng URL trực tiếp nếu nó là tĩnh
  try {
    const response = await axios.get('https://www.sporteventz.com/en/other-sport/tennis.html', {
      headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36' }
    });
    const $ = cheerio.load(response.data);
    const fixtures = [];
    
    // Phân tích cú pháp HTML cho tennis
    const text = $('body').text();
    const lines = text.split('\n');
    let currentTournament = '';
    for (const line of lines) {
      // Logic trích xuất tùy chỉnh
      const vsMatch = line.match(/(.+?)\s+vs\.\s+(.+)/i);
      if (vsMatch) {
        const player1 = vsMatch[1].trim();
        const player2 = vsMatch[2].trim();
        // Tìm ngày giờ (có thể ở dòng tiếp theo hoặc trước đó)
        // ... thêm logic tìm ngày giờ
        fixtures.push({
          player1,
          player2,
          tournament: currentTournament,
          sport: 'tennis'
        });
      } else if (line.includes('ATP,') || line.includes('WTA,')) {
        currentTournament = line.replace(/,/g, '').trim();
      }
    }
    console.log(`Tìm thấy ${fixtures.length} trận tennis.`);
    return fixtures;
  } catch (error) {
    console.error('Lỗi khi lấy dữ liệu tennis:', error.message);
    return [];
  }
}

async function scrapeAll() {
  const [football, tennis] = await Promise.all([
    fetchFootballFixtures(),
    fetchTennisFixtures()
  ]);

  return {
    football,
    tennis,
    total: football.length + tennis.length,
    scrapedAt: new Date().toISOString(),
    source: 'sporteventz'
  };
}

// ---------- Chạy độc lập ----------
if (require.main === module) {
  (async () => {
    console.log('=== SportEventz Scraper (Sử dụng MagicTable) ===');
    const data = await scrapeAll();
    const outputPath = path.join(__dirname, '..', 'sportevent_schedule.json');
    fs.writeFileSync(outputPath, JSON.stringify(data, null, 2));
    console.log(`✅ Đã lưu kết quả vào: ${outputPath}`);
  })();
}

module.exports = { scrapeAll };
