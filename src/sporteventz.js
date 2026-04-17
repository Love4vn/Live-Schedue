// src/sporteventz.js
// SportEventz scraper - Puppeteer cho bóng đá, Axios cho tennis

const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
puppeteer.use(StealthPlugin());
const axios = require('axios');
const fs = require('fs');
const path = require('path');

// ---------- Cấu hình ----------
const BASE_URL = 'https://www.sporteventz.com';
const SOCCER_URL = `${BASE_URL}/en/soccer`;
const TENNIS_URL = `${BASE_URL}/en/other-sport/tennis.html`;

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
const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms));

// ---------- Bóng đá: Puppeteer + trích xuất DOM ----------
async function fetchFootballFixtures() {
    log('Đang lấy lịch bóng đá (Puppeteer DOM extraction)...');
    let browser = null;
    let page = null;
    try {
        browser = await puppeteer.launch({
            headless: 'new',
            args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-gpu']
        });
        page = await browser.newPage();
        await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36');
        await page.setViewport({ width: 1920, height: 1080 });

        log(`Truy cập ${SOCCER_URL}`);
        await page.goto(SOCCER_URL, { waitUntil: 'networkidle2', timeout: 60000 });

        // Chấp nhận cookie nếu có
        try {
            await page.click('button[id*="accept"], button[class*="accept"]', { timeout: 3000 });
            await delay(1000);
        } catch (e) {}

        // Đợi selector đặc trưng của jTable
        try {
            await page.waitForSelector('.MagicTableRow', { timeout: 30000 });
            log('Dữ liệu bóng đá đã được tải.');
        } catch (e) {
            log('Không tìm thấy .MagicTableRow sau 30s, kiểm tra selector.');
            await page.screenshot({ path: path.join(__dirname, '..', 'debug_football_timeout.png'), fullPage: true });
            return [];
        }

        // Đợi thêm để đảm bảo các phần tử con được render
        await delay(2000);

        // Lưu HTML và ảnh chụp để debug (tuỳ chọn)
        const htmlPath = path.join(__dirname, '..', 'debug_football.html');
        fs.writeFileSync(htmlPath, await page.content());
        log(`Đã lưu HTML: ${htmlPath}`);

        // Trích xuất dữ liệu trực tiếp từ DOM
        const fixtures = await page.evaluate(() => {
            const results = [];
            const rows = document.querySelectorAll('.MagicTableRow');
            
            rows.forEach(row => {
                try {
                    // Lấy giải đấu
                    const headline = row.querySelector('.MagicTableRowHeadline');
                    const competition = headline ? headline.innerText.trim() : '';

                    // Lấy tên đội
                    const homeEl = row.querySelector('.MagicTableRowMainHomeTeamName');
                    const awayEl = row.querySelector('.MagicTableRowMainAwayTeamName');
                    if (!homeEl || !awayEl) return;
                    const homeTeam = homeEl.innerText.trim();
                    const awayTeam = awayEl.innerText.trim();

                    // Lấy thời gian
                    const footline = row.querySelector('.MagicTableRowFootline h3');
                    const kickoffUtc = footline ? footline.innerText.trim() : null;

                    // Lấy danh sách kênh
                    const channelButtons = row.querySelectorAll('.MagicTableRowMoreButton');
                    const channels = Array.from(channelButtons).map(btn => {
                        const text = btn.innerText.trim();
                        return text.split('\n')[0]; // Dòng đầu là tên kênh
                    }).filter(Boolean);

                    results.push({
                        competition,
                        homeTeam,
                        awayTeam,
                        kickoffUtc,
                        channels: [...new Set(channels)]
                    });
                } catch (e) {
                    // Bỏ qua dòng lỗi
                }
            });
            return results;
        });

        // Lọc theo danh sách cho phép
        const filtered = fixtures.filter(f => shouldIncludeFootballFixture(f.homeTeam, f.awayTeam, f.competition));
        log(`Đã tìm thấy ${fixtures.length} trận thô, ${filtered.length} trận sau lọc.`);
        
        return filtered.map(f => ({
            homeTeam: f.homeTeam,
            awayTeam: f.awayTeam,
            kickoffUtc: f.kickoffUtc,
            competition: f.competition,
            channels: f.channels,
            sport: 'football'
        }));
    } catch (error) {
        log(`Lỗi khi lấy dữ liệu bóng đá: ${error.message}`);
        return [];
    } finally {
        if (page) await page.close();
        if (browser) await browser.close();
    }
}

// ---------- Tennis: Trang tĩnh ----------
async function fetchTennisFixtures() {
    log('Đang lấy lịch tennis (trang tĩnh)...');
    try {
        const response = await axios.get(TENNIS_URL, {
            headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36' }
        });
        const text = response.data;
        const fixtures = [];
        
        // Tìm các dòng có chứa "##"
        const lines = text.split('\n');
        for (const line of lines) {
            if (line.includes('##')) {
                const parts = line.split('##').map(s => s.trim());
                if (parts.length >= 3) {
                    const tournament = parts[0];
                    const players = parts[1];
                    const datetime = parts[2];
                    
                    const vsMatch = players.match(/(.+?)\s+vs\.?\s+(.+)/i);
                    if (!vsMatch) continue;
                    const player1 = vsMatch[1].trim();
                    const player2 = vsMatch[2].trim();
                    
                    fixtures.push({
                        player1,
                        player2,
                        kickoffUtc: datetime,
                        tournament,
                        channels: [],
                        sport: 'tennis'
                    });
                }
            }
        }
        log(`Đã tìm thấy ${fixtures.length} trận tennis.`);
        return fixtures;
    } catch (error) {
        log(`Lỗi khi lấy dữ liệu tennis: ${error.message}`);
        return [];
    }
}

// ---------- Hàm chính ----------
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
        console.log('=== SportEventz Scraper (DOM Extraction) ===');
        const data = await scrapeAll();
        const outputPath = path.join(__dirname, '..', 'sportevent_schedule.json');
        fs.writeFileSync(outputPath, JSON.stringify(data, null, 2));
        console.log(`✅ Đã lưu kết quả vào: ${outputPath}`);
    })();
}

module.exports = { scrapeAll };
