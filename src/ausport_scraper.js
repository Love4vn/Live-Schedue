const axios = require('axios');
const cheerio = require('cheerio');
const fs = require('fs');
const dayjs = require('dayjs');
const utc = require('dayjs/plugin/utc');
const timezone = require('dayjs/plugin/timezone');
const customParseFormat = require('dayjs/plugin/customParseFormat');

dayjs.extend(utc);
dayjs.extend(timezone);
dayjs.extend(customParseFormat);

// --- Cấu hình ---
const CONFIG = {
  BASE_URL: 'https://ausportguide.com',
  DAYS: ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'],
  RETRY_COUNT: 2,
  RETRY_DELAY_MS: 2000,
  TIMEOUT_MS: 30000,
  USER_AGENT: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36',
  OUTPUT_FILE: './ausport_schedule.json',
};

// --- Danh sách giải/đội hợp lệ ---
const FOOTBALL_CONFIG = {
  leagues: {
    'Premier League': ['arsenal', 'aston villa', 'bournemouth', 'brentford', 'brighton', 'chelsea',
                       'crystal palace', 'everton', 'fulham', 'leeds united', 'liverpool', 'manchester city',
                       'manchester united', 'newcastle', 'nottingham forest', 'sunderland', 'tottenham hotspur',
                       'west ham united', 'wolverhampton'],
    'Serie A': ['inter milan', 'ac milan', 'napoli', 'juventus', 'roma', 'atalanta', 'lazio'],
    'La Liga': ['barcelona', 'real madrid', 'atlético'],
    'Bundesliga': ['bayern', 'borussia dortmund', 'bayer leverkusen'],
    'Ligue 1': ['psg', 'olympique marseille'],
    'UEFA Champions League': 'all',
    'UEFA Europa League': 'all',
    'UEFA Europa Conference League': 'all',
    'World Cup': 'all',
    'EURO': 'all',
    'UEFA European Championship': 'all',
  },
  friendlyAllowedTeams: ['argentina', 'brazil', 'japan', 'south korea', 'nhật bản', 'hàn quốc'],
};

// --- Hàm tiện ích ---
function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function fetchWithRetry(url, options, retries = CONFIG.RETRY_COUNT) {
  for (let attempt = 1; attempt <= retries; attempt++) {
    try {
      const response = await axios.get(url, {
        ...options,
        timeout: CONFIG.TIMEOUT_MS,
        validateStatus: status => status >= 200 && status < 400,
      });
      return response;
    } catch (error) {
      if (attempt === retries) throw error;
      console.warn(`Retry ${attempt}/${retries} for ${url}: ${error.message}`);
      await sleep(CONFIG.RETRY_DELAY_MS);
    }
  }
}

// Chuyển đổi thời gian từ AEDT sang giờ Việt Nam
function convertToVietnamTime(baseDate, timeStr) {
  if (!timeStr) return null;
  const match = timeStr.match(/^(\d{1,2}):(\d{2})(AM|PM)$/i);
  if (!match) return null;

  let [, hourStr, minuteStr, ampm] = match;
  let hour = parseInt(hourStr, 10);
  const minute = parseInt(minuteStr, 10);

  if (ampm.toUpperCase() === 'PM' && hour !== 12) hour += 12;
  if (ampm.toUpperCase() === 'AM' && hour === 12) hour = 0;

  // Tạo datetime ở múi giờ AEDT (Australia/Sydney)
  const aedtTime = dayjs(baseDate).tz('Australia/Sydney').hour(hour).minute(minute).second(0);
  // Chuyển sang giờ Việt Nam (UTC+7)
  const vietnamTime = aedtTime.tz('Asia/Ho_Chi_Minh');
  return vietnamTime;
}

// Lấy ngày/tháng ở giờ Việt Nam
function getVietnamDateTime(baseDate, timeStr) {
  const dt = convertToVietnamTime(baseDate, timeStr);
  if (!dt) return null;
  return {
    datetime: dt.toISOString(),
    hari: dt.format('dddd'),
    tanggal: dt.format('DD/MM/YYYY'),
    jam: dt.format('HH:mm'),
    jam12h: dt.format('h:mm A'),
  };
}

// --- Hàm lọc bóng đá ---
function isFootballRelevant(event) {
  const competition = (event.competition || '').toLowerCase();
  const home = (event.home || '').toLowerCase();
  const away = (event.away || '').toLowerCase();
  const title = (event.title || '').toLowerCase();

  // 1. Các giải đặc biệt (UEFA, World Cup, Euro) -> lấy tất cả
  const specialLeagues = ['uefa champions league', 'uefa europa league', 'uefa europa conference league',
                          'world cup', 'euro', 'uefa european championship'];
  if (specialLeagues.some(l => competition.includes(l))) {
    return true;
  }

  // 2. Các giải có danh sách đội cụ thể
  for (const [league, teams] of Object.entries(FOOTBALL_CONFIG.leagues)) {
    if (competition.includes(league.toLowerCase())) {
      if (teams === 'all') return true;
      const teamList = teams.map(t => t.toLowerCase());
      if (teamList.some(team => home.includes(team) || away.includes(team))) {
        return true;
      }
    }
  }

  // 3. Giao hữu: chỉ lấy nếu có đội từ danh sách cho phép
  if (competition.includes('friendly') || title.includes('friendly')) {
    const allowed = FOOTBALL_CONFIG.friendlyAllowedTeams;
    if (allowed.some(team => home.includes(team) || away.includes(team))) {
      return true;
    }
  }

  return false;
}

// --- Hàm lọc tennis ---
function isTennisRelevant(event) {
  const sport = (event.sport || '').toLowerCase();
  const competition = (event.competition || '').toLowerCase();
  if (sport !== 'tennis') return false;
  const allowed = ['atp', 'wta', 'grand slam'];
  return allowed.some(key => competition.includes(key));
}

// --- Kiểm tra tổng thể ---
function isEventRelevant(event) {
  const sport = (event.sport || '').toLowerCase();
  if (sport === 'soccer' || sport === 'football') {
    return isFootballRelevant(event);
  }
  if (sport === 'tennis') {
    return isTennisRelevant(event);
  }
  return false;
}

// --- Lọc theo thời gian (24h tới) ---
function isWithin24Hours(event) {
  if (!event.vietnam_datetime) return false;
  const eventTime = dayjs(event.vietnam_datetime);
  const now = dayjs();
  const diffHours = eventTime.diff(now, 'hour', true);
  return diffHours >= 0 && diffHours <= 24;
}

// --- Parse ngày từ header của trang ---
function resolveDateForPage($, pathSuffix) {
  const headerText = $('h2.dayInfo').first().text().trim();
  if (headerText) {
    const parsed = dayjs(headerText, 'dddd, D. MMM', true);
    if (parsed.isValid()) {
      const baseDate = parsed.toDate();
      const hariIndo = dayjs(baseDate).format('dddd');
      const tanggalFormatted = dayjs(baseDate).format('DD/MM/YYYY');
      return { baseDate, hariIndo, tanggalFormatted };
    }
  }

  // Fallback: dùng tên ngày trong path
  const now = dayjs();
  const targetDay = { mon: 1, tue: 2, wed: 3, thu: 4, fri: 5, sat: 6, sun: 0 }[pathSuffix];
  const currentDay = now.day();
  const diff = targetDay - currentDay;
  const baseDate = now.add(diff, 'day').toDate();
  const hariIndo = dayjs(baseDate).format('dddd');
  const tanggalFormatted = dayjs(baseDate).format('DD/MM/YYYY');
  return { baseDate, hariIndo, tanggalFormatted };
}

// --- Tìm môn thể thao từ cấu trúc DOM ---
function findSportForEvent($, eventDiv) {
  const $event = $(eventDiv);
  const panelLeague = $event.closest('.panelLeague');
  if (panelLeague.length) {
    const panelType = panelLeague.prevAll('.panelType').first();
    if (panelType.length) {
      const h3 = panelType.find('h3').first();
      if (h3.length) {
        const img = h3.find('img').first();
        const span = h3.find('span.align-middle').first();
        const sport =
          (img.attr('title') || img.attr('alt') || '').trim() ||
          span.text().trim() ||
          h3.text().trim();
        if (sport) return sport;
      }
    }
  }

  let cur = $event.parent();
  for (let i = 0; i < 10 && cur.length; i++) {
    const h3 = cur.prevAll().find('h3').first();
    if (h3.length) {
      const img = h3.find('img').first();
      const span = h3.find('span.align-middle').first();
      const sport =
        (img.attr('title') || img.attr('alt') || '').trim() ||
        span.text().trim() ||
        h3.text().trim();
      if (sport) return sport;
    }
    cur = cur.parent();
  }
  return '';
}

// --- Xử lý Hot Events ---
function extractTimeFromHotText(text) {
  const m = text.match(/\bfrom\s+(\d{1,2}:\d{2}(?:AM|PM))\b/i);
  return m ? m[1].toUpperCase() : '';
}

function resolveBaseDateFromHotText(text) {
  const now = dayjs();
  if (/^Tomorrow\b/i.test(text)) {
    return now.add(1, 'day').toDate();
  }

  const m = text.match(/^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\.?\s+(\d{1,2})\s+([A-Za-z]+)\b/i);
  if (m) {
    const dayNum = parseInt(m[2], 10);
    const monthRaw = m[3];
    const dateStr = `${dayNum} ${monthRaw}`;
    const parsed = dayjs(dateStr, 'D MMM', true);
    if (parsed.isValid()) {
      return parsed.toDate();
    }
  }
  return now.toDate();
}

function parseHotEvents($) {
  const rows = [];
  $('.panel-body-desktop .hotEvents .list-group-item').each((idx, el) => {
    const item = $(el);
    const open = item.find('.openUrl').first();
    if (!open.length) return;

    const eventPath = (open.attr('data-link') || '').trim();
    const line1 = open.find('.eventText > div').first().text().replace(/\s+/g, ' ').trim();
    const line2 = open.find('.eventText > div').eq(1).text().replace(/\s+/g, ' ').trim();

    const [datetimeText, match] = line1.split('|').map(v => v.trim());
    const sport = (line2.split('|')[0] || '').trim();
    const league = (line2.split('|')[1] || '').replace(/\s+/g, ' ').trim();

    let channel = item.find('.ml-10 img').attr('title') || item.find('.ml-10 img').attr('alt') || '';
    channel = channel.replace(/Live on\s*/i, '').trim();

    const timeAedt = extractTimeFromHotText(datetimeText);
    const baseDate = resolveBaseDateFromHotText(datetimeText);
    const vietnamInfo = timeAedt ? getVietnamDateTime(baseDate, timeAedt) : null;

    const [home, away] = match.includes(' - ') ? match.split(' - ').map(s => s.trim()) : [match, ''];

    rows.push({
      day: 'hot',
      hari: dayjs(baseDate).format('dddd'),
      tanggal: dayjs(baseDate).format('DD/MM/YYYY'),
      time_aedt: timeAedt,
      sport,
      competition: league || 'Hot Events',
      home,
      away,
      title: league ? `${sport} | ${league}` : sport,
      channels: channel,
      event_url: eventPath ? `${CONFIG.BASE_URL}/${eventPath}` : '',
      vietnam_datetime: vietnamInfo?.datetime || null,
      vietnam_hari: vietnamInfo?.hari || '',
      vietnam_tanggal: vietnamInfo?.tanggal || '',
      vietnam_jam: vietnamInfo?.jam || '',
      vietnam_jam12h: vietnamInfo?.jam12h || '',
    });
  });
  return rows;
}

// --- Scraping một ngày ---
async function scrapeDay(pathSuffix) {
  const url = `${CONFIG.BASE_URL}/live-sports-tv-guide/${pathSuffix}`;
  console.log(`Scraping: ${url}`);

  const response = await fetchWithRetry(url, {
    headers: {
      'User-Agent': CONFIG.USER_AGENT,
      'Accept-Language': 'en-US,en;q=0.9',
    },
  });

  const $ = cheerio.load(response.data);
  const dateInfo = resolveDateForPage($, pathSuffix);

  const rows = [];
  let currentCompetition = '';

  $('h3, .leagueTitle, div.list-group-item.d-flex.gap-3.shadow-sm').each((idx, el) => {
    const $el = $(el);

    if ($el.hasClass('leagueTitle')) {
      currentCompetition = $el.find('span.align-middle').first().text().trim();
      return;
    }

    if ($el.hasClass('list-group-item')) {
      const eventDiv = $el;
      const timeAedt = eventDiv.find('.eventTime').first().text().trim();
      if (!timeAedt) return;

      const eventText = eventDiv.find('.eventText').first();
      const teamDivs = eventText.children('div').filter((i, e) => {
        const cls = $(e).attr('class') || '';
        return !cls.includes('gameSpacer') && !cls.includes('fs-10');
      });

      const home = (teamDivs.eq(0).text() || '').replace(/\s+/g, ' ').trim();
      const away = (teamDivs.eq(1).text() || '').replace(/\s+/g, ' ').trim();

      const title = eventText
        .find('div.fs-10 i')
        .first()
        .text()
        .replace(/\s+/g, ' ')
        .trim();

      const channels = [];
      eventDiv.find('div.text-end img.stationImg').each((i, img) => {
        let t = $(img).attr('title') || $(img).attr('alt') || '';
        t = t.replace(/Live on\s*/i, '').trim();
        if (t) channels.push(t);
      });

      const sport = findSportForEvent($, eventDiv);
      const vietnamInfo = getVietnamDateTime(dateInfo.baseDate, timeAedt);

      rows.push({
        day: pathSuffix,
        hari: dateInfo.hariIndo,
        tanggal: dateInfo.tanggalFormatted,
        time_aedt: timeAedt,
        sport,
        competition: currentCompetition,
        home,
        away,
        title,
        channels: channels.join(' | '),
        event_url: '',
        vietnam_datetime: vietnamInfo?.datetime || null,
        vietnam_hari: vietnamInfo?.hari || '',
        vietnam_tanggal: vietnamInfo?.tanggal || '',
        vietnam_jam: vietnamInfo?.jam || '',
        vietnam_jam12h: vietnamInfo?.jam12h || '',
      });
    }
  });

  // Thêm hot events
  const hotRows = parseHotEvents($);
  if (hotRows.length) {
    console.log(`HotEvents for ${pathSuffix}: ${hotRows.length}`);
    rows.push(...hotRows);
  }

  console.log(`Rows for ${pathSuffix}: ${rows.length}`);
  return rows;
}

// --- Loại bỏ trùng lặp ---
function dedupeRows(rows) {
  const seen = new Set();
  return rows.filter(row => {
    const key = [
      row.vietnam_tanggal,
      row.vietnam_jam,
      row.sport,
      row.competition,
      row.home,
      row.away,
      row.channels,
    ].join('|').toLowerCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

// --- Xuất JSON ---
function writeJSON(rows, outputPath) {
  fs.writeFileSync(outputPath, JSON.stringify(rows, null, 2));
  console.log(`JSON written: ${outputPath}`);
}

// --- Gửi lên Google Sheets (tuỳ chọn) ---
async function sendToGoogleSheets(rows) {
  const webappUrl = process.env.WEBAPP_URL;
  if (!webappUrl) {
    console.log('WEBAPP_URL not set, skipping Google Sheets upload');
    return;
  }
  try {
    const response = await axios.post(webappUrl, rows, {
      headers: { 'Content-Type': 'application/json' },
      timeout: 30000,
    });
    console.log('GAS status:', response.status);
    console.log('GAS response:', response.data);
  } catch (error) {
    console.error('Failed sending to Google Sheets:', error.response?.data || error.message);
  }
}

// --- Hàm chính (chạy tuần tự) ---
(async () => {
  let allRows = [];
  for (const day of CONFIG.DAYS) {
    try {
      const rows = await scrapeDay(day);
      allRows = allRows.concat(rows);
    } catch (error) {
      console.error(`Error scraping ${day}:`, error.message);
    }
  }

  // Lọc theo môn thể thao và giải đấu
  let filteredRows = allRows.filter(isEventRelevant);
  console.log('After sport/league filter:', filteredRows.length);

  // Lọc theo thời gian 24h
  filteredRows = filteredRows.filter(isWithin24Hours);
  console.log('After time filter (24h):', filteredRows.length);

  // Loại bỏ trùng lặp
  filteredRows = dedupeRows(filteredRows);
  console.log('After deduplication:', filteredRows.length);

  // Sắp xếp theo thời gian tăng dần
  filteredRows.sort((a, b) => {
    if (!a.vietnam_datetime) return 1;
    if (!b.vietnam_datetime) return -1;
    return dayjs(a.vietnam_datetime).diff(dayjs(b.vietnam_datetime));
  });

  writeJSON(filteredRows, CONFIG.OUTPUT_FILE);
  await sendToGoogleSheets(filteredRows);
})();
