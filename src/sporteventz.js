// src/sporteventz.js
// Giải pháp kết hợp Puppeteer (cho bóng đá động) và Axios (cho tennis tĩnh)

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

// ---------- Hàm lấy dữ liệu bóng đá (Puppeteer) ----------
async function fetchFootballFixtures() {
    log('Đang lấy lịch bóng đá (sử dụng Puppeteer)...');
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

        // Đợi selector của jTable (quan trọng)
        try {
            await page.waitForSelector('.MagicTableRow, .jtable-data-row', { timeout: 30000 });
            log('Dữ liệu bóng đá đã được tải.');
        } catch (e) {
            log('Không tìm thấy dữ liệu bóng đá sau 30 giây, kiểm tra lại cấu trúc trang.');
            // Chụp ảnh debug
            await page.screenshot({ path: path.join(__dirname, '..', 'debug_football_error.png'), fullPage: true });
            return [];
        }

        // Đợi thêm một chút cho các kênh hiển thị
        await delay(2000);

        // Lấy toàn bộ nội dung trang sau khi render
        const html = await page.content();

        // Phân tích cú pháp HTML
        const fixtures = [];
        // Sử dụng regex để tìm các khối dữ liệu. Dựa trên cấu trúc đã quan sát:
        // Mỗi trận đấu thường được bọc trong một thẻ <div> với class "MagicTableRow".
        const rowRegex = /<div class="MagicTableRow.*?">(.*?)<\/div>\s*<div class="MagicTableChannels"/gs;
        const rows = html.match(rowRegex) || [];

        for (const rowHtml of rows) {
            // Trích xuất tiêu đề (giải đấu)
            const headlineMatch = rowHtml.match(/<div class="MagicTableRowHeadline">(.*?)<\/div>/i);
            const competition = headlineMatch ? headlineMatch[1].trim() : '';

            // Trích xuất tên đội
            const homeMatch = rowHtml.match(/<span class="MagicTableRowMainHomeTeamName">(.*?)<\/span>/i);
            const awayMatch = rowHtml.match(/<span class="MagicTableRowMainAwayTeamName">(.*?)<\/span>/i);
            if (!homeMatch || !awayMatch) continue;
            const homeTeam = homeMatch[1].trim();
            const awayTeam = awayMatch[1].trim();

            // Lọc bóng đá
            if (!shouldIncludeFootballFixture(homeTeam, awayTeam, competition)) continue;

            // Trích xuất thời gian
            const timeMatch = rowHtml.match(/<div class="MagicTableRowFootline"><h3>(.*?)<\/h3><\/div>/i);
            const kickoffUtc = timeMatch ? timeMatch[1].trim() : null;

            // Trích xuất kênh (nếu có)
            const channelMatches = rowHtml.match(/<div class="MagicTableRowMoreButton.*?">(.*?)<\/div>/gi) || [];
            const channels = channelMatches.map(btn => {
                const text = btn.replace(/<[^>]*>/g, '').trim();
                return text.split('\n')[0]; // Lấy dòng đầu tiên
            });

            fixtures.push({
                homeTeam,
                awayTeam,
                kickoffUtc,
                competition,
                channels: [...new Set(channels)],
                sport: 'football'
            });
        }

        log(`Đã tìm thấy ${fixtures.length} trận bóng đá sau khi lọc.`);
        return fixtures;
    } catch (error) {
        log(`Lỗi khi lấy dữ liệu bóng đá: ${error.message}`);
        return [];
    } finally {
        if (page) await page.close();
        if (browser) await browser.close();
    }
}

// ---------- Hàm lấy dữ liệu tennis (Static) ----------
async function fetchTennisFixtures() {
    log('Đang lấy lịch tennis (trang tĩnh)...');
    try {
        const response = await axios.get(TENNIS_URL, {
            headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36' }
        });
        const text = response.data;
        const fixtures = [];
        
        // Dựa trên cấu trúc đã thấy: các trận được phân tách bằng "##"
        const matches = text.match(/[^#]+##[^#]+##[^#]+/g) || [];
        
        for (const match of matches) {
            const parts = match.split('##').map(s => s.trim());
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
                    channels: [], // Có thể bổ sung sau
                    sport: 'tennis'
                });
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
        console.log('=== SportEventz Scraper (Hybrid) ===');
        const data = await scrapeAll();
        const outputPath = path.join(__dirname, '..', 'sportevent_schedule.json');
        fs.writeFileSync(outputPath, JSON.stringify(data, null, 2));
        console.log(`✅ Đã lưu kết quả vào: ${outputPath}`);
    })();
}

module.exports = { scrapeAll };
