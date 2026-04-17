// src/sporteventz.js
// SportEventz scraper sử dụng các trang tĩnh (text) để lấy dữ liệu.
// Giải quyết triệt để vấn đề JavaScript và AJAX.

const axios = require('axios');
const fs = require('fs');
const path = require('path');

// ---------- Cấu hình ----------
const BASE_URL = 'https://www.sporteventz.com';
// Các trang tĩnh đã được xác định là hoạt động tốt
const SOCCER_STATIC_URL = `${BASE_URL}/en/soccer`;
const TENNIS_STATIC_URL = `${BASE_URL}/en/other-sport/tennis.html`;

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

// ---------- Hàm lấy và phân tích dữ liệu từ trang tĩnh ----------
async function fetchAndParse(url, type) {
    log(`Đang tải dữ liệu từ ${url}`);
    try {
        const response = await axios.get(url, {
            headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36' }
        });
        const text = response.data;

        // Dựa trên cấu trúc quan sát được: mỗi trận đấu được phân tách bằng "##"
        // Định dạng: "Giải đấu ## Đội 1 vs. Đội 2 ## Ngày giờ"
        const matches = [];
        const lines = text.split('\n');
        let currentCompetition = '';

        for (const line of lines) {
            const trimmedLine = line.trim();
            if (!trimmedLine) continue;

            // Dòng chứa "##" thường là dòng có thông tin trận đấu
            if (trimmedLine.includes('##')) {
                const parts = trimmedLine.split('##').map(s => s.trim());
                if (parts.length >= 3) {
                    const competition = parts[0];
                    const teams = parts[1];
                    const datetime = parts[2];

                    const vsMatch = teams.match(/(.+?)\s+vs\.?\s+(.+)/i);
                    if (!vsMatch) continue;
                    const homeTeam = vsMatch[1].trim();
                    const awayTeam = vsMatch[2].trim();

                    // Lọc bóng đá
                    if (type === 'football' && !shouldIncludeFootballFixture(homeTeam, awayTeam, competition)) {
                        continue;
                    }

                    matches.push({
                        competition,
                        homeTeam,
                        awayTeam,
                        kickoffUtc: datetime,
                        sport: type
                    });
                }
            } else if (type === 'tennis' && (trimmedLine.startsWith('ATP,') || trimmedLine.startsWith('WTA,'))) {
                currentCompetition = trimmedLine.replace(/,/g, '').trim();
            }
        }

        log(`Đã tìm thấy ${matches.length} trận ${type}.`);
        return matches;
    } catch (error) {
        log(`Lỗi khi lấy dữ liệu ${type}: ${error.message}`);
        return [];
    }
}

// ---------- Hàm chính ----------
async function scrapeAll() {
    const [footballMatches, tennisMatches] = await Promise.all([
        fetchAndParse(SOCCER_STATIC_URL, 'football'),
        fetchAndParse(TENNIS_STATIC_URL, 'tennis')
    ]);

    const footballOut = footballMatches.map(m => ({
        homeTeam: m.homeTeam,
        awayTeam: m.awayTeam,
        kickoffUtc: m.kickoffUtc,
        competition: m.competition,
        channels: [], // Có thể bổ sung sau
        sport: 'football'
    }));

    const tennisOut = tennisMatches.map(m => ({
        player1: m.homeTeam,
        player2: m.awayTeam,
        kickoffUtc: m.kickoffUtc,
        tournament: m.competition,
        channels: [],
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
        console.log('=== SportEventz Scraper (Trang tĩnh) ===');
        const data = await scrapeAll();
        const outputPath = path.join(__dirname, '..', 'sportevent_schedule.json');
        fs.writeFileSync(outputPath, JSON.stringify(data, null, 2));
        console.log(`✅ Đã lưu kết quả vào: ${outputPath}`);
    })();
}

module.exports = { scrapeAll };
