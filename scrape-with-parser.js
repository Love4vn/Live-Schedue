// scrape-with-parser.js
const matches = require('livesoccertv-parser');
const fs = require('fs').promises;

async function fetchAndSaveSchedule() {
    console.log('🔄 Bắt đầu lấy dữ liệu lịch thi đấu...');

    // --- CẤU HÌNH ---
    // Thay đổi 'england' và 'arsenal' theo ý muốn
    const league = 'england';      // Mã giải đấu (ví dụ: 'england', 'spain', 'italy')
    const team = 'arsenal';        // Mã đội bóng (ví dụ: 'arsenal', 'real-madrid')
    const timezone = 'Asia/Ho_Chi_Minh'; // Múi giờ của bạn

    try {
        // Gọi hàm matches từ thư viện
        const scheduleData = await matches(league, team, { timezone });

        if (!scheduleData || scheduleData.length === 0) {
            console.log('⚠️ Không tìm thấy dữ liệu lịch thi đấu.');
            return;
        }

        console.log(`✅ Đã lấy thành công dữ liệu cho ${scheduleData.length} trận đấu.`);

        // Chuẩn bị dữ liệu đầu ra
        const outputData = {
            updated: new Date().toLocaleString('vi-VN', { timeZone: timezone }),
            total_matches: scheduleData.length,
            matches: scheduleData
        };

        // Ghi dữ liệu vào file JSON
        await fs.writeFile('livesoccertv_schedule.json', JSON.stringify(outputData, null, 2), 'utf8');
        console.log('📁 Dữ liệu đã được lưu vào file livesoccertv_schedule.json');

    } catch (error) {
        console.error('❌ Có lỗi xảy ra trong quá trình xử lý:', error);
    }
}

fetchAndSaveSchedule();
