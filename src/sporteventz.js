// src/sporteventz.js
// SportEventz scraper nâng cao - sử dụng stealth và mô phỏng hành vi người dùng

const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
puppeteer.use(StealthPlugin());

const fs = require('fs');
const path = require('path');

// ---------- Cấu hình ----------
const BASE_URL = 'https://www.sporteventz.com';
const SOCCER_URL = `${BASE_URL}/soccer`;
const TENNIS_URL = `${BASE_URL}/tennis`;
const DEFAULT_TIMEOUT = 60000;
const SCROLL_PAUSE_TIME = 2000;
const MAX_SCROLL_ATTEMPTS = 15;

// Danh sách kênh (giữ nguyên)
const TV_CHANNELS = [
  'Sky Sports Main Event', 'Sky Sports Premier League', 'Sky Sports Football',
  'Sky Sports', 'TNT Sports 1', 'TNT Sports 2', 'TNT Sports 3', 'TNT Sports 4',
  'TNT Sports', 'BBC One', 'BBC Two', 'BBC iPlayer', 'ITV1', 'ITV4', 'ITVX',
  'Channel 4', 'Amazon Prime Video', 'Amazon Prime', 'Premier Sports 1',
  'Premier Sports 2', 'Premier Sports', 'BT Sport 1', 'BT Sport 2', 'BT Sport 3',
  'LaLigaTV', 'FreeSports', 'discovery+', 'DAZN', 'ESPN', 'ESPN+', 'beIN Sports',
  'Paramount+', 'Peacock', 'fuboTV', 'CBS Sports', 'Eurosport', 'Viaplay', 'SuperSport'
];

// Bộ lọc bóng đá (giữ nguyên)
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

// ---------- Mô phỏng hành vi người dùng ----------
async function simulateHumanBehavior(page) {
  // Di chuyển chuột ngẫu nhiên
  await page.mouse.move(Math.random() * 500 + 100, Math.random() * 300 + 100);
  await page.waitForTimeout(500 + Math.random() * 1000);
  
  // Cuộn nhẹ
  await page.evaluate(() => window.scrollBy(0, 200));
  await page.waitForTimeout(300);
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

    // Mô phỏng hành vi người
    await simulateHumanBehavior(page);

    // Chấp nhận cookie nếu có
    try {
      const cookieBtn = await page.$('button[id*="accept"], button[class*="accept"], [class*="cookie"] button');
      if (cookieBtn) {
        await cookieBtn.click();
        await page.waitForTimeout(1500);
        log('Đã chấp nhận cookie');
      }
    } catch (e) {}

    // Thử click vào tab "Today" hoặc "All" để đảm bảo hiển thị đầy đủ
    try {
      const todayTab = await page.$('a:contains("Today"), button:contains("Today"), [class*="today"]');
      if (todayTab) {
        await todayTab.click();
        await page.waitForTimeout(2000);
        log('Đã chọn tab Today');
      }
    } catch (e) {}

    // Scroll nhiều lần để tải lazy load
    let lastHeight = 0;
    let scrollCount = 0;
    while (scrollCount < MAX_SCROLL_ATTEMPTS) {
      const newHeight = await page.evaluate(() => document.body.scrollHeight);
      if (newHeight === lastHeight) break;
      lastHeight = newHeight;
      await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
      await page.waitForTimeout(SCROLL_PAUSE_TIME);
      scrollCount++;
    }
    log(`Đã scroll ${scrollCount} lần`);

    // Lưu HTML và ảnh chụp để debug
    const debugDir = path.join(__dirname, '..');
    const htmlPath = path.join(debugDir, `debug_${sportType}.html`);
    const screenshotPath = path.join(debugDir, `debug_${sportType}_full.png`);
    await page.screenshot({ path: screenshotPath, fullPage: true });
    fs.writeFileSync(htmlPath, await page.content());
    log(`Đã lưu HTML: ${htmlPath} và ảnh: ${screenshotPath}`);

    // Trích xuất dữ liệu
    const fixtures = await page.evaluate((TV_CHANNELS, sportType) => {
      const results = [];

      function extractFromElement(el) {
        const text = el.innerText || '';
        const textLower = text.toLowerCase();

        // Bỏ qua nếu không đúng môn
        if (sportType === 'football' && (textLower.includes('tennis') || textLower.includes('basketball'))) return null;
        if (sportType === 'tennis' && !textLower.includes('tennis') && !textLower.includes('atp') && !textLower.includes('wta')) return null;

        // Tên đội/tay vợt
        let home = '', away = '';
        const homeEl = el.querySelector('.home, .home-team, [class*="home"]');
        const awayEl = el.querySelector('.away, .away-team, [class*="away"]');
        if (homeEl) home = homeEl.innerText.trim();
        if (awayEl) away = awayEl.innerText.trim();

        if (!home || !away) {
          const teams = el.querySelectorAll('.team, .team-name, [class*="team"]');
          if (teams.length >= 2) {
            home = teams[0].innerText.trim();
            away = teams[1].innerText.trim();
          }
        }

        // Fallback vs
        if (!home || !away) {
          const vsMatch = text.match(/([A-Za-z0-9\s\-\.']+)\s+(?:v|vs|versus|–|-)\s+([A-Za-z0-9\s\-\.']+)/i);
          if (vsMatch) {
            home = vsMatch[1].trim();
            away = vsMatch[2].trim();
          }
        }

        home = home.replace(/\b(fc|afc|cf|sc|ac)\b/gi, '').replace(/\s+/g, ' ').trim();
        away = away.replace(/\b(fc|afc|cf|sc|ac)\b/gi, '').replace(/\s+/g, ' ').trim();
        if (!home || !away) return null;

        // Thời gian
        let kickoff = null;
        const timeEl = el.querySelector('time, [datetime], .time, .date, .kickoff');
        if (timeEl) kickoff = timeEl.getAttribute('datetime') || timeEl.innerText.trim();
        if (!kickoff) {
          const dateMatch = text.match(/(\d{1,2}[\/\-\.]\d{1,2}(?:[\/\-\.]\d{2,4})?)/);
          const timeMatch = text.match(/(\d{1,2}[:\.]\d{2}\s*(am|pm)?)/i);
          kickoff = [dateMatch?.[1], timeMatch?.[1]].filter(Boolean).join(' ');
        }

        // Giải đấu
        let comp = null;
        const compEl = el.querySelector('.competition, .league, .tournament, [class*="competition"], [class*="league"]');
        if (compEl) comp = compEl.innerText.trim();

        // Kênh
        const channels = [];
        for (const ch of TV_CHANNELS) {
          if (textLower.includes(ch.toLowerCase())) channels.push(ch);
        }
        const channelEls = el.querySelectorAll('.channel, .broadcaster, .tv, .stream');
        channelEls.forEach(c => {
          c.innerText.split(/[,;\/\n]/).forEach(p => {
            const clean = p.trim();
            if (clean) channels.push(clean);
          });
        });

        return { home, away, kickoffUtc: kickoff, competition: comp, channels: [...new Set(channels)] };
      }

      // Các selector ưu tiên
      const selectors = [
        'tr.event', 'tr.match', 'tr.fixture',
        '.event-item', '.match-item', '.fixture-item',
        '[class*="event-row"]', '[class*="match-row"]',
        'table tbody tr', '.fixtures-table tr', '.schedule-table tr',
        'div.event', 'div.match', 'div.fixture'
      ];

      let processed = new Set();
      selectors.forEach(sel => {
        document.querySelectorAll(sel).forEach(el => {
          if (processed.has(el)) return;
          processed.add(el);
          const data = extractFromElement(el);
          if (data) results.push(data);
        });
      });

      // Nếu không có, duyệt tất cả thẻ div, li, tr
      if (results.length === 0) {
        document.querySelectorAll('div, li, tr').forEach(el => {
          if (processed.has(el)) return;
          const text = el.innerText || '';
          if (text.includes(' vs ') || text.includes(' v ') || /\d{1,2}:\d{2}/.test(text)) {
            processed.add(el);
            const data = extractFromElement(el);
            if (data) results.push(data);
          }
        });
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
    console.log('=== SportEventz Scraper với Stealth ===');
    try {
      const data = await scrapeAll();
      console.log(`\n✅ Bóng đá: ${data.football.length} | Tennis: ${data.tennis.length}`);

      // Lưu ra thư mục gốc repo
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
