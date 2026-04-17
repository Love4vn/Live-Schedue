// src/sporteventz.js
// SportEventz scraper cải tiến - lọc bóng đá nam + toàn bộ tennis
// Lưu kết quả ra sportevent_schedule.json tại thư mục gốc repo.

const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');

// ---------- Cấu hình ----------
const BASE_URL = 'https://www.sporteventz.com';
const SOCCER_URL = `${BASE_URL}/soccer`;
const TENNIS_URL = `${BASE_URL}/tennis`;
const DEFAULT_TIMEOUT = 45000;          // Tăng timeout
const SCROLL_PAUSE_TIME = 2000;          // Tăng thời gian chờ sau scroll
const MAX_SCROLL_ATTEMPTS = 15;          // Tăng số lần scroll

// Danh sách kênh truyền hình
const TV_CHANNELS = [
  'Sky Sports Main Event', 'Sky Sports Premier League', 'Sky Sports Football',
  'Sky Sports', 'TNT Sports 1', 'TNT Sports 2', 'TNT Sports 3', 'TNT Sports 4',
  'TNT Sports', 'BBC One', 'BBC Two', 'BBC iPlayer', 'ITV1', 'ITV4', 'ITVX',
  'Channel 4', 'Amazon Prime Video', 'Amazon Prime', 'Premier Sports 1',
  'Premier Sports 2', 'Premier Sports', 'BT Sport 1', 'BT Sport 2', 'BT Sport 3',
  'LaLigaTV', 'FreeSports', 'discovery+', 'DAZN', 'ESPN', 'ESPN+', 'beIN Sports',
  'Paramount+', 'Peacock', 'fuboTV', 'CBS Sports', 'Eurosport', 'Viaplay', 'SuperSport'
];

// ---------- Bộ lọc bóng đá ----------
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
    const teamsSet = ALLOWED_TEAMS_PER_LEAGUE[league];
    if (teamsSet.has(homeLower) || teamsSet.has(awayLower)) return true;
  }
  return false;
}

// ---------- Logging ----------
function log(msg) {
  const timestamp = new Date().toISOString();
  console.log(`[${timestamp}] [SPORTEVENTZ] ${msg}`);
}

// ---------- Browser ----------
let browser = null;
async function getBrowser() {
  if (browser && browser.isConnected()) return browser;
  browser = await puppeteer.launch({
    headless: 'new',
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage',
      '--disable-gpu',
      '--disable-features=site-per-process'
    ]
  });
  return browser;
}

// ---------- Hàm scrape chung ----------
async function scrapeSportPage(url, sportType, debugScreenshot = false) {
  let page = null;
  try {
    const browserInstance = await getBrowser();
    page = await browserInstance.newPage();
    await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36');

    log(`Đang tải ${url}`);
    await page.goto(url, { waitUntil: 'networkidle2', timeout: DEFAULT_TIMEOUT });

    // Chờ một phần tử đặc trưng xuất hiện (có thể là bảng hoặc event)
    try {
      await page.waitForSelector('table, .event, .match, .fixture, [class*="event"]', { timeout: 15000 });
    } catch (e) {
      log(`Không tìm thấy selector đặc trưng, tiếp tục...`);
    }

    // Chấp nhận cookie nếu có
    try {
      const cookieBtn = await page.$('button[id*="accept"], button[class*="accept"], [class*="cookie"] button');
      if (cookieBtn) {
        await cookieBtn.click();
        await new Promise(r => setTimeout(r, 1000));
        log('Đã chấp nhận cookie');
      }
    } catch (e) {}

    // Scroll để tải thêm nội dung
    let lastHeight = 0;
    let scrollCount = 0;
    while (scrollCount < MAX_SCROLL_ATTEMPTS) {
      const newHeight = await page.evaluate(() => document.body.scrollHeight);
      if (newHeight === lastHeight) break;
      lastHeight = newHeight;
      await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
      await new Promise(r => setTimeout(r, SCROLL_PAUSE_TIME));
      scrollCount++;
    }
    log(`Đã scroll ${scrollCount} lần cho ${sportType}`);

    // Chụp ảnh debug nếu cần (khi chạy thủ công)
    if (debugScreenshot) {
      const screenshotPath = path.join(__dirname, `debug_${sportType}.png`);
      await page.screenshot({ path: screenshotPath, fullPage: false });
      log(`Đã lưu ảnh debug: ${screenshotPath}`);
    }

    // Trích xuất dữ liệu
    const fixtures = await page.evaluate((TV_CHANNELS, sportType) => {
      const results = [];
      // Selector ưu tiên: các hàng trong bảng (phổ biến trên SportEventz)
      const rows = document.querySelectorAll('table tbody tr, .event, .match, .fixture, .game, [class*="event"], [class*="match"]');
      
      rows.forEach(el => {
        try {
          const text = el.innerText || el.textContent || '';
          const textLower = text.toLowerCase();

          // Bỏ qua nếu không phải môn thể thao mong muốn
          if (sportType === 'football' && (textLower.includes('tennis') || textLower.includes('basketball') || textLower.includes('cricket') || textLower.includes('rugby'))) return;
          if (sportType === 'tennis' && !textLower.includes('tennis') && !textLower.includes('atp') && !textLower.includes('wta')) return;

          // Lấy tên đội / tay vợt
          let home = '', away = '';
          const homeEl = el.querySelector('.home-team, .home, [class*="home"]');
          const awayEl = el.querySelector('.away-team, .away, [class*="away"]');
          if (homeEl) home = homeEl.innerText.trim();
          if (awayEl) away = awayEl.innerText.trim();

          if (!home || !away) {
            const teams = el.querySelectorAll('.team, .team-name, [class*="team"]');
            if (teams.length >= 2) {
              home = teams[0].innerText.trim();
              away = teams[1].innerText.trim();
            }
          }

          // Fallback: tìm mẫu "vs"
          if (!home || !away) {
            const vsMatch = text.match(/([A-Za-z\s\-'\.0-9]+)\s+(?:v|vs|versus|–|-)\s+([A-Za-z\s\-'\.0-9]+)/i);
            if (vsMatch) {
              home = vsMatch[1].trim();
              away = vsMatch[2].trim();
            }
          }

          // Làm sạch tên
          home = home.replace(/\b(fc|afc|cf|sc|ac)\b/gi, '').replace(/\s+/g, ' ').trim();
          away = away.replace(/\b(fc|afc|cf|sc|ac)\b/gi, '').replace(/\s+/g, ' ').trim();
          if (!home || !away) return;

          // Thời gian
          let kickoffUtc = null;
          const timeEl = el.querySelector('time, [datetime], .time, .date, .kickoff');
          if (timeEl) kickoffUtc = timeEl.getAttribute('datetime') || timeEl.innerText.trim();
          if (!kickoffUtc) {
            const dateMatch = text.match(/(\d{1,2}[\/\-\.]\d{1,2}(?:[\/\-\.]\d{2,4})?)/);
            const timeMatch = text.match(/(\d{1,2}[:\.]?\d{2}\s*(am|pm|GMT|BST|CET|UTC)?)/i);
            kickoffUtc = [dateMatch?.[1], timeMatch?.[1]].filter(Boolean).join(' ');
          }

          // Giải đấu
          let competition = null;
          const compEl = el.querySelector('.competition, .league, .tournament, [class*="competition"], [class*="league"]');
          if (compEl) competition = compEl.innerText.trim();

          // Kênh phát sóng
          const channels = [];
          for (const ch of TV_CHANNELS) {
            if (textLower.includes(ch.toLowerCase())) channels.push(ch);
          }
          const channelEls = el.querySelectorAll('.channel, .broadcaster, .tv, .stream, [class*="channel"], [class*="broadcaster"]');
          channelEls.forEach(cEl => {
            const chText = cEl.innerText.trim();
            if (chText) {
              chText.split(/[,;\/\n]/).forEach(part => {
                const clean = part.trim();
                if (clean && !channels.includes(clean)) channels.push(clean);
              });
            }
          });

          results.push({ home, away, kickoffUtc, competition, channels: [...new Set(channels)] });
        } catch (e) {}
      });

      // Nếu không tìm thấy gì, thử quét toàn bộ văn bản để tìm pattern
      if (results.length === 0) {
        const allText = document.body.innerText;
        const lines = allText.split('\n');
        // Logic dự phòng có thể thêm sau
      }

      return results;
    }, TV_CHANNELS, sportType);

    return fixtures;
  } catch (err) {
    log(`Lỗi scrape ${sportType}: ${err.message}`);
    return [];
  } finally {
    if (page) await page.close().catch(() => {});
  }
}

// ---------- Hàm công khai ----------
async function fetchFootballFixtures() {
  log('Đang lấy lịch bóng đá...');
  const raw = await scrapeSportPage(SOCCER_URL, 'football', true); // bật screenshot khi chạy thủ công
  const filtered = raw.filter(f => shouldIncludeFootballFixture(f.home, f.away, f.competition));
  log(`Bóng đá: ${raw.length} trận thô, ${filtered.length} trận sau lọc`);
  return filtered;
}

async function fetchTennisFixtures() {
  log('Đang lấy lịch tennis...');
  const raw = await scrapeSportPage(TENNIS_URL, 'tennis', true);
  log(`Tennis: ${raw.length} trận`);
  return raw;
}

async function scrapeAll() {
  const [football, tennis] = await Promise.all([
    fetchFootballFixtures(),
    fetchTennisFixtures()
  ]);

  const footballFormatted = football.map(f => ({
    homeTeam: f.home,
    awayTeam: f.away,
    kickoffUtc: f.kickoffUtc || null,
    competition: f.competition || null,
    channels: f.channels,
    sport: 'football'
  }));

  const tennisFormatted = tennis.map(f => ({
    player1: f.home,
    player2: f.away,
    kickoffUtc: f.kickoffUtc || null,
    tournament: f.competition || null,
    channels: f.channels,
    sport: 'tennis'
  }));

  return {
    football: footballFormatted,
    tennis: tennisFormatted,
    total: footballFormatted.length + tennisFormatted.length,
    scrapedAt: new Date().toISOString(),
    source: 'sporteventz'
  };
}

// ---------- Chạy độc lập ----------
if (require.main === module) {
  (async () => {
    console.log('=== SportEventz Scraper (Filtered Football + Tennis) ===');
    
    // Kiểm tra sức khỏe nhanh
    try {
      const browser = await getBrowser();
      const page = await browser.newPage();
      await page.goto(SOCCER_URL, { waitUntil: 'domcontentloaded', timeout: 20000 });
      await page.close();
      log('Kết nối đến SportEventz thành công');
    } catch (e) {
      log(`Không thể truy cập SportEventz: ${e.message}`);
      process.exit(1);
    }

    const data = await scrapeAll();
    
    // In kết quả
    console.log(`\nKết quả:`);
    console.log(`- Bóng đá: ${data.football.length} trận`);
    console.log(`- Tennis: ${data.tennis.length} trận`);

    // Lưu file ra thư mục gốc repo (đường dẫn tương đối từ thư mục src)
    const outputPath = path.join(__dirname, '..', 'sportevent_schedule.json');
    fs.writeFileSync(outputPath, JSON.stringify(data, null, 2));
    console.log(`\nĐã lưu kết quả vào: ${outputPath}`);

    if (browser) await browser.close();
    process.exit(0);
  })();
}

module.exports = { scrapeAll, fetchFootballFixtures, fetchTennisFixtures };
