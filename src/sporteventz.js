// src/sporteventz.js
// SportEventz scraper dựa trên jTable - chờ render dữ liệu AJAX

const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
puppeteer.use(StealthPlugin());

const fs = require('fs');
const path = require('path');

// ---------- Cấu hình ----------
const BASE_URL = 'https://www.sporteventz.com';
const SOCCER_URL = `${BASE_URL}/en/soccer`;
const TENNIS_URL = `${BASE_URL}/en/tennis`;
const DEFAULT_TIMEOUT = 60000;
const WAIT_SELECTOR = '.MagicTableRow, .jtable-data-row'; // jTable row selector

// Kênh truyền hình
const TV_CHANNELS = [
  'Sky Sports Main Event', 'Sky Sports Premier League', 'Sky Sports Football',
  'Sky Sports', 'TNT Sports 1', 'TNT Sports 2', 'TNT Sports 3', 'TNT Sports 4',
  'TNT Sports', 'BBC One', 'BBC Two', 'BBC iPlayer', 'ITV1', 'ITV4', 'ITVX',
  'Channel 4', 'Amazon Prime Video', 'Amazon Prime', 'Premier Sports 1',
  'Premier Sports 2', 'Premier Sports', 'BT Sport 1', 'BT Sport 2', 'BT Sport 3',
  'LaLigaTV', 'FreeSports', 'discovery+', 'DAZN', 'ESPN', 'ESPN+', 'beIN Sports',
  'Paramount+', 'Peacock', 'fuboTV', 'CBS Sports', 'Eurosport', 'Viaplay', 'SuperSport'
];

// Bộ lọc bóng đá nam
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
    if (ALLOWED_TEAMS_PER_LEAGUE[league].has(homeLower) || ALLOWED_TEAMS_PER_LEAGUE[league].has(awayLower)) return true;
  }
  return false;
}

// ---------- Logging ----------
function log(msg) {
  console.log(`[${new Date().toISOString()}] [SPORTEVENTZ] ${msg}`);
}

// Hàm delay thay thế waitForTimeout
const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms));

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
      '--disable-features=site-per-process',
      '--window-size=1920,1080'
    ]
  });
  return browser;
}

// ---------- Hàm scrape chính ----------
async function scrapeSportPage(url, sportType) {
  let page = null;
  try {
    const browserInstance = await getBrowser();
    page = await browserInstance.newPage();
    await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36');
    await page.setViewport({ width: 1920, height: 1080 });

    log(`Truy cập ${url}`);
    await page.goto(url, { waitUntil: 'networkidle2', timeout: DEFAULT_TIMEOUT });

    // Chấp nhận cookie nếu có
    try {
      const cookieBtn = await page.$('button[id*="accept"], button[class*="accept"], [class*="cookie"] button');
      if (cookieBtn) {
        await cookieBtn.click();
        await delay(1000);
        log('Đã chấp nhận cookie');
      }
    } catch (e) {}

    // Đợi jTable load dữ liệu
    log(`Đợi dữ liệu xuất hiện (${WAIT_SELECTOR})...`);
    try {
      await page.waitForSelector(WAIT_SELECTOR, { timeout: 30000 });
      log(`Dữ liệu đã load.`);
    } catch (e) {
      log(`Không tìm thấy dữ liệu sau 30s, kiểm tra lại selector.`);
      const debugPath = path.join(__dirname, '..', `debug_${sportType}_nodata.png`);
      await page.screenshot({ path: debugPath, fullPage: true });
      log(`Ảnh debug lưu tại ${debugPath}`);
      return [];
    }

    // Đợi thêm một chút để các kênh phát sóng hiển thị đầy đủ
    await delay(2000);

    // Lưu HTML để debug
    const htmlPath = path.join(__dirname, '..', `debug_${sportType}.html`);
    fs.writeFileSync(htmlPath, await page.content());
    log(`Đã lưu HTML: ${htmlPath}`);

    // Trích xuất dữ liệu
    const fixtures = await page.evaluate((TV_CHANNELS, sportType) => {
      const results = [];
      const rows = document.querySelectorAll('.MagicTableRow');
      
      rows.forEach(row => {
        try {
          // Tên đội
          const homeEl = row.querySelector('.MagicTableRowMainHomeTeamName');
          const awayEl = row.querySelector('.MagicTableRowMainAwayTeamName');
          let home = homeEl ? homeEl.innerText.trim() : '';
          let away = awayEl ? awayEl.innerText.trim() : '';

          if (!home || !away) {
            const mainData = row.querySelector('.MagicTableRowMainData');
            if (mainData) {
              const text = mainData.innerText;
              const vsMatch = text.match(/(.+?)\s+vs\.?\s+(.+)/i);
              if (vsMatch) {
                home = vsMatch[1].trim();
                away = vsMatch[2].trim();
              }
            }
          }
          if (!home || !away) return;

          // Giải đấu
          const headline = row.querySelector('.MagicTableRowHeadline');
          let competition = headline ? headline.innerText.trim() : null;

          // Thời gian
          const footline = row.querySelector('.MagicTableRowFootline h3');
          let kickoffUtc = footline ? footline.innerText.trim() : null;

          // Kênh phát sóng (trong các button .MagicTableRowMoreButton)
          const channelButtons = row.querySelectorAll('.MagicTableRowMoreButton');
          const channels = [];
          channelButtons.forEach(btn => {
            const btnText = btn.innerText.trim();
            if (btnText) {
              // Lấy dòng đầu tiên làm tên kênh
              const channelName = btnText.split('\n')[0].trim();
              if (channelName && !channels.includes(channelName)) {
                channels.push(channelName);
              }
            }
          });

          // Bổ sung kênh từ danh sách TV_CHANNELS nếu có trong text
          const rowText = row.innerText.toLowerCase();
          TV_CHANNELS.forEach(ch => {
            if (rowText.includes(ch.toLowerCase()) && !channels.includes(ch)) {
              channels.push(ch);
            }
          });

          results.push({
            home,
            away,
            kickoffUtc,
            competition,
            channels: [...new Set(channels)]
          });
        } catch (e) {
          // bỏ qua lỗi parse
        }
      });

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

// ---------- Hàm chính ----------
async function fetchFootballFixtures() {
  log('Đang lấy lịch bóng đá...');
  const raw = await scrapeSportPage(SOCCER_URL, 'football');
  const filtered = raw.filter(f => shouldIncludeFootballFixture(f.home, f.away, f.competition));
  log(`Bóng đá: ${raw.length} thô, ${filtered.length} sau lọc`);
  return filtered;
}

async function fetchTennisFixtures() {
  log('Đang lấy lịch tennis...');
  return await scrapeSportPage(TENNIS_URL, 'tennis');
}

async function scrapeAll() {
  const [football, tennis] = await Promise.all([
    fetchFootballFixtures(),
    fetchTennisFixtures()
  ]);

  const footballOut = football.map(f => ({
    homeTeam: f.home,
    awayTeam: f.away,
    kickoffUtc: f.kickoffUtc || null,
    competition: f.competition || null,
    channels: f.channels,
    sport: 'football'
  }));

  const tennisOut = tennis.map(f => ({
    player1: f.home,
    player2: f.away,
    kickoffUtc: f.kickoffUtc || null,
    tournament: f.competition || null,
    channels: f.channels,
    sport: 'tennis'
  }));

  return {
    football: footballOut,
    tennis: tennisOut,
    total: footballOut.length + tennisOut.length,
    scrapedAt: new Date().toISOString(),
    source: 'sporteventz'
  };
}

// ---------- Chạy độc lập ----------
if (require.main === module) {
  (async () => {
    console.log('=== SportEventz Scraper (jTable aware) ===');
    try {
      const data = await scrapeAll();
      console.log(`\n✅ Bóng đá: ${data.football.length} | Tennis: ${data.tennis.length}`);

      const outputPath = path.join(__dirname, '..', 'sportevent_schedule.json');
      fs.writeFileSync(outputPath, JSON.stringify(data, null, 2));
      console.log(`📁 Đã lưu: ${outputPath}`);
    } catch (e) {
      console.error('❌ Lỗi:', e);
    } finally {
      if (browser) await browser.close();
      process.exit(0);
    }
  })();
}

module.exports = { scrapeAll };
