const puppeteer = require('puppeteer');
const fs = require('fs').promises;

// --- Cấu hình ---
const TIMEZONE = 'Asia/Ho_Chi_Minh';
const TARGET_URL = 'https://www.livesoccertv.com/schedules/';
const OUTPUT_FILE = 'livesoccertv_schedule.json';

/**
 * Hàm chính để chạy Puppeteer, crawl dữ liệu và ghi ra file
 */
async function scrapeAndSave() {
    console.log('🚀 Khởi động trình duyệt ảo...');
    const browser = await puppeteer.launch({
        headless: true, // Chạy ở chế độ nền (không hiện cửa sổ trình duyệt)
        args: ['--no-sandbox', '--disable-setuid-sandbox'] // Cần thiết cho môi trường CI như GitHub Actions
    });
    const page = await browser.newPage();

    // Cấu hình User-Agent và các header để tránh bị phát hiện
    await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36');
    await page.setExtraHTTPHeaders({
        'Accept-Language': 'en-US,en;q=0.9',
    });

    console.log(`🌐 Đang truy cập: ${TARGET_URL}`);
    try {
        await page.goto(TARGET_URL, { waitUntil: 'networkidle2', timeout: 60000 });
        console.log('✅ Đã tải trang thành công.');
    } catch (error) {
        console.error(`❌ Lỗi khi tải trang: ${error}`);
        await browser.close();
        return;
    }

    // Chờ đợi các hàng (row) của lịch thi đấu xuất hiện trên trang
    await page.waitForSelector('tr.matchrow, tr[id^="event-"]', { timeout: 30000 });

    console.log('🔍 Đang trích xuất dữ liệu...');
    // Trích xuất dữ liệu bằng cách chạy code JavaScript ngay trong trang web
    const matches = await page.evaluate(() => {
        const results = [];
        // Lấy tất cả các hàng có thể chứa dữ liệu trận đấu
        const rows = document.querySelectorAll('tr.matchrow, tr[id^="event-"]');

        rows.forEach(row => {
            // Lấy timestamp từ span.ts (thuộc tính dv)
            const tsSpan = row.querySelector('span.ts[dv]');
            if (!tsSpan) return;
            const msTimestamp = tsSpan.getAttribute('dv');
            if (!msTimestamp) return;

            // Lấy thông tin trận đấu
            const matchCell = row.querySelector('td#match, td.matchcell');
            const matchLink = matchCell ? matchCell.querySelector('a') : null;
            if (!matchLink) return;
            const matchName = matchLink.innerText.trim().replace(/ @ /g, ' vs ');

            // Lấy giải đấu
            const leagueCell = row.querySelector('td.compcell_right, td.compcell');
            const league = leagueCell ? leagueCell.innerText.trim() : "Unknown";

            // Lấy danh sách kênh
            const channelCell = row.querySelector('td.channelcol, td.channels');
            const channels = [];
            if (channelCell) {
                // Tìm các thẻ img có chứa logo kênh (có class flag)
                const channelImgs = channelCell.querySelectorAll('img[class*="flag"]');
                channelImgs.forEach(img => {
                    let channelName = img.getAttribute('title') || img.getAttribute('alt') || "";
                    channelName = channelName.replace(/Live on\s*/i, "").replace(/\s*logo\s*$/i, "").trim();
                    if (channelName) channels.push(channelName);
                });
                // Nếu không có ảnh, tìm thẻ a
                if (channels.length === 0) {
                    const channelLinks = channelCell.querySelectorAll('a');
                    channelLinks.forEach(a => {
                        let channelName = a.innerText.trim();
                        if (channelName) channels.push(channelName);
                    });
                }
            }

            if (channels.length === 0) return; // Bỏ qua nếu không có kênh nào

            results.push({
                league: league,
                match: matchName,
                kick_utc: Math.floor(parseInt(msTimestamp) / 1000),
                time: new Date(parseInt(msTimestamp)).toLocaleString('vi-VN', { timeZone: 'Asia/Ho_Chi_Minh' }),
                tv_channels: [{ country: "unknown", channels: [...new Set(channels)] }],
                source: "livesoccertv"
            });
        });
        return results;
    });

    await browser.close();

    if (matches.length === 0) {
        console.log('⚠️ Không tìm thấy dữ liệu lịch thi đấu nào.');
        return;
    }

    // Sắp xếp kết quả theo thời gian
    matches.sort((a, b) => a.kick_utc - b.kick_utc);

    // Dữ liệu đầu ra
    const outputData = {
        updated: new Date().toLocaleString('vi-VN', { timeZone: TIMEZONE }),
        total_matches: matches.length,
        matches: matches
    };

    // Ghi dữ liệu ra file JSON
    await fs.writeFile(OUTPUT_FILE, JSON.stringify(outputData, null, 2), 'utf8');
    console.log(`🎉 Hoàn tất! Đã lưu ${matches.length} trận đấu vào file ${OUTPUT_FILE}`);
}

// Chạy hàm chính
scrapeAndSave().catch(console.error);
