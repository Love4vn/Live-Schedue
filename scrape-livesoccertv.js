// scrape-livesoccertv.js
// Lấy lịch trực tiếp từ livesoccertv.com, lọc theo cấu hình, xuất livesoccertv_schedule.json

const axios = require("axios");
const cheerio = require("cheerio");
const fs = require("fs");
const { wrapper } = require("axios-cookiejar-support");
const { CookieJar } = require("tough-cookie");

// ================== CẤU HÌNH ==================
const TIMEZONE = "Asia/Ho_Chi_Minh";
const MAX_CHANNELS_PER_MATCH = 500;

// Các giải đấu được phép (bóng đá)
const ALLOWED_FOOTBALL_LEAGUES = new Set([
  "Premier League",
  "Serie A",
  "La Liga",
  "Bundesliga",
  "Ligue 1",
  "UEFA Champions League",
  "UEFA Europa League",
  "UEFA Europa Conference League",
  "UEFA Euro",
  "FA Cup",
  "League Cup",
  "FIFA World Cup",
  "International Friendly"
]);

// Đội bóng được phép theo từng giải
const ALLOWED_TEAMS_PER_LEAGUE = {
  "Premier League": new Set([
    "arsenal", "aston villa", "bournemouth", "brentford", "brighton", "chelsea",
    "crystal palace", "everton", "fulham", "leeds united", "liverpool", "manchester city",
    "manchester united", "newcastle", "nottingham forest", "sunderland", "tottenham hotspur",
    "west ham united", "wolverhampton"
  ]),
  "Serie A": new Set([
    "inter milan", "ac milan", "napoli", "juventus", "roma", "atalanta", "lazio"
  ]),
  "La Liga": new Set([
    "barcelona", "real madrid", "atletico madrid"
  ]),
  "Bundesliga": new Set([
    "bayern munich", "borussia dortmund", "bayer leverkusen"
  ]),
  "Ligue 1": new Set([
    "psg", "paris saint-germain", "olympique marseille", "marseille"
  ]),
  "FA Cup": new Set([
    "arsenal", "aston villa", "bournemouth", "brentford", "brighton", "chelsea",
    "crystal palace", "everton", "fulham", "leeds united", "liverpool", "manchester city",
    "manchester united", "newcastle", "nottingham forest", "sunderland", "tottenham hotspur",
    "west ham united", "wolverhampton"
  ]),
  "League Cup": new Set([
    "arsenal", "aston villa", "bournemouth", "brentford", "brighton", "chelsea",
    "crystal palace", "everton", "fulham", "leeds united", "liverpool", "manchester city",
    "manchester united", "newcastle", "nottingham forest", "sunderland", "tottenham hotspur",
    "west ham united", "wolverhampton"
  ])
};

// Giải tennis được phép
const ALLOWED_TENNIS_TOURNAMENTS = new Set([
  "atp", "atp tour", "grand slam", "australian open", "roland garros",
  "french open", "wimbledon", "us open", "nitto atp finals", "atp masters",
  "atp 1000", "atp 500", "atp 250", "wta"
]);

// Đội friendly được phép
const ALLOWED_FRIENDLY_COUNTRIES = new Set([
  "argentina", "brazil", "japan", "south korea"
]);

// ================== KHỞI TẠO HTTP CLIENT ==================
const jar = new CookieJar();
const client = wrapper(
  axios.create({
    jar,
    withCredentials: true,
    timeout: 30000,
    headers: {
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
      "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
      "Accept-Language": "en-US,en;q=0.9",
      "Referer": "https://www.livesoccertv.com/",
      "Connection": "keep-alive"
    }
  })
);

async function getWithRetry(url, retries = 3, delay = 1000) {
  for (let i = 0; i < retries; i++) {
    try {
      const response = await client.get(url);
      return response;
    } catch (error) {
      if (i === retries - 1) throw error;
      console.log(`Retry ${i + 1} for ${url} after error: ${error.message}`);
      await new Promise(resolve => setTimeout(resolve, delay * (i + 1)));
    }
  }
}

// ================== HÀM TIỆN ÍCH ==================
function normalize(str) {
  return (str || "").toLowerCase().trim().replace(/[-_]/g, " ").replace(/\s+/g, " ");
}

function normalizeTeamName(name) {
  let norm = name.toLowerCase()
    .replace(/\b(fc|afc|sc|united|city|wanderers|rovers|athletic|albion|town|county)\b/g, '')
    .replace(/[^\w\s]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  return norm;
}

function getVNTimeFromTimestamp(msTimestamp) {
  // msTimestamp là timestamp UTC từ livesoccertv (milliseconds)
  const date = new Date(parseInt(msTimestamp));
  const vnDate = new Date(date.getTime() + 7 * 3600000); // UTC+7
  const day = String(vnDate.getUTCDate()).padStart(2, '0');
  const month = String(vnDate.getUTCMonth() + 1).padStart(2, '0');
  let hours = vnDate.getUTCHours();
  const minutes = String(vnDate.getUTCMinutes()).padStart(2, '0');
  const ampm = hours >= 12 ? 'PM' : 'AM';
  hours = hours % 12 || 12;
  return `${day}/${month} ${hours}:${minutes} ${ampm}`;
}

function getKickUtcFromTimestamp(msTimestamp) {
  return Math.floor(parseInt(msTimestamp) / 1000);
}

// ================== LỌC TRẬN ĐẤU ==================
function isTeamAllowed(league, home, away) {
  const allowedSet = ALLOWED_TEAMS_PER_LEAGUE[league];
  if (!allowedSet) return true; // giải không có danh sách đội cụ thể -> cho qua
  const homeNorm = normalizeTeamName(home);
  const awayNorm = normalizeTeamName(away);
  return allowedSet.has(homeNorm) || allowedSet.has(awayNorm);
}

function isLeagueAllowed(league) {
  if (!league) return false;
  const norm = normalize(league);
  // Bóng đá
  for (let allowed of ALLOWED_FOOTBALL_LEAGUES) {
    if (norm.includes(normalize(allowed))) return true;
  }
  // Tennis
  for (let kw of ALLOWED_TENNIS_TOURNAMENTS) {
    if (norm.includes(kw)) return true;
  }
  return false;
}

function isMatchAllowed(league, match, home, away) {
  const normLeague = normalize(league);
  // Kiểm tra giải đấu
  if (!isLeagueAllowed(league)) return false;

  // Loại trừ các giải trẻ, nữ
  if (normLeague.includes("women") || normLeague.includes("u19") || normLeague.includes("u21") || normLeague.includes("youth")) {
    return false;
  }

  // Friendly: chỉ cho phép các đội tuyển quốc gia nhất định
  if (normLeague.includes("friendly")) {
    const homeNorm = normalize(home);
    const awayNorm = normalize(away);
    if (!ALLOWED_FRIENDLY_COUNTRIES.has(homeNorm) && !ALLOWED_FRIENDLY_COUNTRIES.has(awayNorm)) {
      return false;
    }
  }

  // Kiểm tra đội bóng nếu giải có danh sách đội cho phép
  if (ALLOWED_TEAMS_PER_LEAGUE[league]) {
    return isTeamAllowed(league, home, away);
  }
  return true;
}

// ================== PARSE HTML ==================
function extractChannelsFromCell($channelCell) {
  const channelsByCountry = new Map(); // country -> Set of channel names

  // Tìm tất cả img có class chứa 'flag'
  $channelCell.find('img[class*="flag"]').each((_, img) => {
    const $img = $(img);
    let country = "unknown";
    for (const cls of ($img.attr('class') || "").split(' ')) {
      if (cls.startsWith('flag-')) {
        country = cls.replace('flag-', '').replace(/-/g, ' ');
        break;
      }
    }
    let channelName = $img.attr('title') || $img.attr('alt') || "";
    channelName = channelName.replace(/Live on\s*/i, "").replace(/\s*logo\s*$/i, "").trim();
    if (channelName) {
      if (!channelsByCountry.has(country)) channelsByCountry.set(country, new Set());
      channelsByCountry.get(country).add(channelName);
    }
  });

  // Nếu không tìm thấy qua img, tìm qua thẻ a
  if (channelsByCountry.size === 0) {
    $channelCell.find('a').each((_, a) => {
      let channelName = $(a).text().trim();
      if (channelName) {
        const country = "unknown";
        if (!channelsByCountry.has(country)) channelsByCountry.set(country, new Set());
        channelsByCountry.get(country).add(channelName);
      }
    });
  }

  const result = [];
  for (let [country, channelsSet] of channelsByCountry.entries()) {
    result.push({
      country: country,
      channels: Array.from(channelsSet).sort()
    });
  }
  return result;
}

async function scrapeDate(dateStr) {
  // dateStr format: YYYY-MM-DD
  const url = `https://www.livesoccertv.com/schedules/${dateStr}/`;
  console.log(`\n📡 Crawling: ${url}`);
  let html;
  try {
    const response = await getWithRetry(url, 3, 2000);
    html = response.data;
  } catch (err) {
    console.error(`❌ Failed to fetch ${dateStr}: ${err.message}`);
    return [];
  }

  const $ = cheerio.load(html);
  const matches = [];

  // Tìm tất cả các hàng trận đấu (class matchrow hoặc id bắt đầu bằng số)
  let rows = $('tr.matchrow');
  if (rows.length === 0) {
    rows = $('tr[id^="match-"], tr[id^="event-"]'); // fallback
  }

  rows.each((_, row) => {
    const $row = $(row);

    // Lấy timestamp từ span.ts có attribute dv
    const $tsSpan = $row.find('span.ts[dv]');
    if ($tsSpan.length === 0) return;
    const msTimestamp = $tsSpan.attr('dv');
    if (!msTimestamp) return;
    const kickUtc = getKickUtcFromTimestamp(msTimestamp);
    const timeVN = getVNTimeFromTimestamp(msTimestamp);

    // Lấy tên trận đấu
    const $matchCell = $row.find('td#match, td.matchcell');
    if ($matchCell.length === 0) return;
    const $matchLink = $matchCell.find('a');
    if ($matchLink.length === 0) return;
    let matchName = $matchLink.text().trim();
    // Chuẩn hóa: thay @ bằng vs
    matchName = matchName.replace(/ @ /g, ' vs ');

    // Lấy giải đấu
    const $leagueCell = $row.find('td.compcell_right, td.compcell');
    let league = $leagueCell.length ? $leagueCell.text().trim() : "Unknown";

    // Tách home và away từ matchName
    let home = "", away = "";
    const vsIndex = matchName.toLowerCase().indexOf(' vs ');
    if (vsIndex !== -1) {
      home = matchName.substring(0, vsIndex).trim();
      away = matchName.substring(vsIndex + 4).trim();
    } else {
      // fallback: coi toàn bộ là match
      home = matchName;
      away = "";
    }

    // Lọc theo cấu hình
    if (!isMatchAllowed(league, matchName, home, away)) return;

    // Lấy kênh phát sóng
    const $channelCell = $row.find('td.channelcol, td.channels');
    let tvChannels = [];
    if ($channelCell.length) {
      tvChannels = extractChannelsFromCell($channelCell);
    } else {
      // Không có thông tin kênh -> bỏ qua trận này
      return;
    }
    if (tvChannels.length === 0) return;

    matches.push({
      league: league,
      match: matchName,
      kick_utc: kickUtc,
      time: timeVN,
      tv_channels: tvChannels,
      source: "livesoccertv"
    });
  });

  console.log(`   → Found ${matches.length} matches after filtering`);
  return matches;
}

// ================== MAIN ==================
async function main() {
  const nowVN = new Date(new Date().getTime() + 7 * 3600000);
  const endVN = new Date(nowVN.getTime() + 48 * 3600000);

  // Tạo danh sách các ngày cần crawl (hôm nay, mai, mốt)
  const dates = [];
  for (let i = 0; i <= 2; i++) {
    const d = new Date(nowVN);
    d.setDate(nowVN.getDate() + i);
    const yyyy = d.getUTCFullYear();
    const mm = String(d.getUTCMonth() + 1).padStart(2, '0');
    const dd = String(d.getUTCDate()).padStart(2, '0');
    dates.push(`${yyyy}-${mm}-${dd}`);
  }

  console.log("🔄 Bắt đầu lấy lịch từ LiveSoccerTV...");
  console.log(`   Khoảng thời gian: ${nowVN.toISOString()} -> ${endVN.toISOString()}`);
  console.log(`   Các ngày: ${dates.join(", ")}`);

  let allMatches = [];
  for (const date of dates) {
    const matches = await scrapeDate(date);
    allMatches.push(...matches);
  }

  // Loại bỏ trùng lặp dựa trên kick_utc + match
  const seen = new Set();
  const unique = [];
  for (const m of allMatches) {
    const key = `${m.kick_utc}|${normalize(m.match)}`;
    if (!seen.has(key)) {
      seen.add(key);
      unique.push(m);
    }
  }
  allMatches = unique;
  allMatches.sort((a, b) => a.kick_utc - b.kick_utc);

  const output = {
    updated: new Date().toLocaleString('vi-VN', { timeZone: TIMEZONE }),
    total_matches: allMatches.length,
    matches: allMatches
  };

  fs.writeFileSync("livesoccertv_schedule.json", JSON.stringify(output, null, 2));
  console.log(`\n✅ Đã lưu ${allMatches.length} trận vào livesoccertv_schedule.json`);
}

main().catch(err => {
  console.error("Fatal error:", err);
  process.exit(1);
});
