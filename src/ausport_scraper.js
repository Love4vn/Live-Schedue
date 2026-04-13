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

// ========== CẤU HÌNH ==========
const DAY_ORDER = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
const TIME_RANGE_HOURS = 48; // 48 giờ tới
const OUTPUT_FILE = './ausport_schedule.json';

const MONTH_MAP = {
  January: 0, Jan: 0,
  February: 1, Feb: 1,
  March: 2, Mar: 2,
  April: 3, Apr: 3,
  May: 4,
  June: 5, Jun: 5,
  July: 6, Jul: 6,
  August: 7, Aug: 7,
  September: 8, Sep: 8, Sept: 8,
  October: 9, Oct: 9,
  November: 10, Nov: 10,
  December: 11, Dec: 11
};

// ========== BỘ LỌC GIẢI ĐẤU ==========
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
  excludeKeywords: ['u18', 'u19', 'u20', 'u21', 'u23', 'women', 'girls', 'boys', 'youth', 'junior', 'reserves', 'woman'],
};

function isFootballRelevant(competition, home, away, title) {
  const comp = (competition || '').toLowerCase();
  const h = (home || '').toLowerCase();
  const a = (away || '').toLowerCase();
  const t = (title || '').toLowerCase();

  for (const kw of FOOTBALL_CONFIG.excludeKeywords) {
    if (comp.includes(kw) || t.includes(kw)) return false;
  }

  const specialLeagues = ['uefa champions league', 'uefa europa league', 'uefa europa conference league',
                          'world cup', 'euro', 'uefa european championship'];
  if (specialLeagues.some(l => comp.includes(l))) return true;

  for (const [league, teams] of Object.entries(FOOTBALL_CONFIG.leagues)) {
    if (comp.includes(league.toLowerCase())) {
      if (teams === 'all') return true;
      const teamList = teams.map(t => t.toLowerCase());
      if (teamList.some(team => h.includes(team) || a.includes(team))) return true;
    }
  }

  if (comp.includes('friendly') || t.includes('friendly')) {
    const allowed = FOOTBALL_CONFIG.friendlyAllowedTeams;
    if (allowed.some(team => h.includes(team) || a.includes(team))) return true;
  }
  return false;
}

function isTennisRelevant(sport, competition) {
  const s = (sport || '').toLowerCase();
  const c = (competition || '').toLowerCase();
  if (s !== 'tennis') return false;
  const allowed = ['atp', 'wta', 'grand slam'];
  return allowed.some(key => c.includes(key));
}

function isEventRelevant(sport, competition, home, away, title) {
  const s = (sport || '').toLowerCase();
  if (s === 'soccer' || s === 'football') {
    return isFootballRelevant(competition, home, away, title);
  }
  if (s === 'tennis') {
    return isTennisRelevant(sport, competition);
  }
  return false;
}

// ========== CHUYỂN ĐỔI GIỜ VIỆT NAM ==========
function convertAedtToVietnamTime(baseDate, timeStr) {
  if (!timeStr) return null;
  const match = timeStr.match(/^(\d{1,2}):(\d{2})(AM|PM)$/i);
  if (!match) return null;
  let [, hourStr, minuteStr, ampm] = match;
  let hour = parseInt(hourStr, 10);
  const minute = parseInt(minuteStr, 10);
  if (ampm.toUpperCase() === 'PM' && hour !== 12) hour += 12;
  if (ampm.toUpperCase() === 'AM' && hour === 12) hour = 0;
  const aedtTime = dayjs(baseDate).tz('Australia/Sydney').hour(hour).minute(minute).second(0);
  return aedtTime.tz('Asia/Ho_Chi_Minh');
}

function getVietnamInfo(baseDate, timeStr) {
  const dt = convertAedtToVietnamTime(baseDate, timeStr);
  if (!dt) return null;
  return {
    datetime: dt.toISOString(),
    jam: dt.format('HH:mm'),
    tanggal: dt.format('DD/MM/YYYY'),
  };
}

// ========== CÁC HÀM TỪ SCRAPER GỐC ==========
function fallbackDateForDay(pathSuffix) {
  const DAY_MAP = { sun: 0, mon: 1, tue: 2, wed: 3, thu: 4, fri: 5, sat: 6 };
  const now = new Date();
  const currentDay = now.getDay();
  const targetDay = DAY_MAP[pathSuffix];
  const diff = targetDay - currentDay;
  const baseDate = new Date(now);
  baseDate.setDate(now.getDate() + diff);
  baseDate.setHours(0, 0, 0, 0);
  const hariIndo = baseDate.toLocaleDateString('id-ID', { weekday: 'long' });
  const tanggalFormatted = baseDate.toLocaleDateString('id-ID', { day: '2-digit', month: '2-digit', year: '2-digit' });
  return { baseDate, hariIndo, tanggalFormatted };
}

function resolveDateForPage($, pathSuffix) {
  const headerText = $('h2.dayInfo').first().text().trim();
  if (headerText) {
    const m = headerText.match(/(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+(\d{1,2})\.\s+([A-Za-z]+)/i);
    if (m) {
      const dayNum = parseInt(m[2], 10);
      const monthRaw = m[3];
      const monthName = monthRaw.charAt(0).toUpperCase() + monthRaw.slice(1).toLowerCase();
      const monthIdx = MONTH_MAP[monthName];
      if (!isNaN(dayNum) && monthIdx != null) {
        const now = new Date();
        const year = now.getFullYear();
        const baseDate = new Date(year, monthIdx, dayNum);
        baseDate.setHours(0, 0, 0, 0);
        const hariIndo = baseDate.toLocaleDateString('id-ID', { weekday: 'long' });
        const tanggalFormatted = baseDate.toLocaleDateString('id-ID', { day: '2-digit', month: '2-digit', year: '2-digit' });
        return { baseDate, hariIndo, tanggalFormatted };
      }
    }
  }
  return fallbackDateForDay(pathSuffix);
}

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
        const sport = (img.attr('title') || img.attr('alt') || '').trim() ||
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
      const sport = (img.attr('title') || img.attr('alt') || '').trim() ||
                    span.text().trim() ||
                    h3.text().trim();
      if (sport) return sport;
    }
    cur = cur.parent();
  }
  return '';
}

function extractTimeFromHotText(text) {
  const m = text.match(/\bfrom\s+(\d{1,2}:\d{2}(?:AM|PM))\b/i);
  return m ? m[1].toUpperCase() : "";
}

function resolveBaseDateFromHotText(text) {
  const now = new Date();
  if (/^Tomorrow\b/i.test(text)) {
    const d = new Date(now);
    d.setDate(now.getDate() + 1);
    d.setHours(0, 0, 0, 0);
    return d;
  }
  const m = text.match(/^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\.?\s+(\d{1,2})\s+([A-Za-z]+)\b/i);
  if (m) {
    const dayNum = parseInt(m[2], 10);
    const monthRaw = m[3];
    const monthName = monthRaw.charAt(0).toUpperCase() + monthRaw.slice(1).toLowerCase();
    const monthIdx = MONTH_MAP[monthName];
    if (monthIdx != null && !isNaN(dayNum)) {
      const year = now.getFullYear();
      const d = new Date(year, monthIdx, dayNum);
      d.setHours(0, 0, 0, 0);
      return d;
    }
  }
  const d = new Date(now);
  d.setHours(0, 0, 0, 0);
  return d;
}

function parseHotEvents($) {
  const rows = [];
  $(".panel-body-desktop .hotEvents .list-group-item").each((idx, el) => {
    const item = $(el);
    const open = item.find(".openUrl").first();
    if (!open.length) return;
    const eventPath = (open.attr("data-link") || "").trim();
    const line1 = open.find(".eventText > div").first().text().replace(/\s+/g, " ").trim();
    const line2 = open.find(".eventText > div").eq(1).text().replace(/\s+/g, " ").trim();
    const [left, matchRaw] = line1.split("|").map(v => (v || "").trim());
    const datetimeText = left || "";
    const match = matchRaw || "";
    const sport = (line2.split("|")[0] || "").trim();
    const league = (line2.split("|")[1] || "").replace(/\s+/g, " ").trim();
    let channel = item.find(".ml-10 img").attr("title") || item.find(".ml-10 img").attr("alt") || "";
    channel = channel.replace(/Live on\s*/i, "").trim();
    const timeAedt = extractTimeFromHotText(datetimeText);
    const baseDate = resolveBaseDateFromHotText(datetimeText);
    const home = match.includes(" - ") ? match.split(" - ")[0].trim() : match.trim();
    const away = match.includes(" - ") ? match.split(" - ")[1].trim() : "";
    const vietnamInfo = timeAedt ? getVietnamInfo(baseDate, timeAedt) : null;
    rows.push({
      sport, competition: league || "Hot Events", home, away,
      channels: channel,
      vietnam_jam: vietnamInfo?.jam || '',
      vietnam_tanggal: vietnamInfo?.tanggal || '',
      vietnam_datetime: vietnamInfo?.datetime || null,
    });
  });
  return rows;
}

async function scrapeDay(pathSuffix) {
  const url = `https://ausportguide.com/live-sports-tv-guide/${pathSuffix}`;
  console.log('Scraping:', url);
  const res = await axios.get(url, {
    headers: {
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36',
      'Accept-Language': 'en-US,en;q=0.9'
    },
    timeout: 30000,
    maxRedirects: 5,
    validateStatus: status => status >= 200 && status < 400
  });
  const $ = cheerio.load(res.data);
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
      const title = eventText.find('div.fs-10 i').first().text().replace(/\s+/g, ' ').trim();
      const channels = [];
      eventDiv.find('div.text-end img.stationImg').each((i, img) => {
        let t = $(img).attr('title') || $(img).attr('alt') || '';
        t = t.replace(/Live on\s*/i, '').trim();
        if (t) channels.push(t);
      });
      const sport = findSportForEvent($, eventDiv);
      const vietnamInfo = getVietnamInfo(dateInfo.baseDate, timeAedt);
      rows.push({
        day: pathSuffix,
        sport, competition: currentCompetition, home, away, title,
        channels: channels.join(' | '),
        vietnam_jam: vietnamInfo?.jam || '',
        vietnam_tanggal: vietnamInfo?.tanggal || '',
        vietnam_datetime: vietnamInfo?.datetime || null,
      });
    }
  });
  const hotRows = parseHotEvents($);
  if (hotRows.length) console.log(`HotEvents for ${pathSuffix}: ${hotRows.length}`);
  rows.push(...hotRows);
  console.log(`Rows for ${pathSuffix}: ${rows.length}`);
  return rows;
}

// ========== MAIN ==========
(async () => {
  let allRows = [];
  for (const d of DAY_ORDER) {
    try {
      const rows = await scrapeDay(d);
      allRows = allRows.concat(rows);
    } catch (e) {
      console.error(`Skipping day ${d} due to error:`, e.message);
    }
  }
  // Lọc theo môn và giải
  let filtered = allRows.filter(row => isEventRelevant(row.sport, row.competition, row.home, row.away, row.title));
  console.log('After sport/league filter:', filtered.length);
  // Lọc theo thời gian 48h
  const now = dayjs();
  filtered = filtered.filter(row => {
    if (!row.vietnam_datetime) return false;
    const diff = dayjs(row.vietnam_datetime).diff(now, 'hour', true);
    return diff >= 0 && diff <= TIME_RANGE_HOURS;
  });
  console.log(`After time filter (${TIME_RANGE_HOURS}h):`, filtered.length);
  // Loại bỏ trùng lặp
  const seen = new Set();
  filtered = filtered.filter(row => {
    const key = `${row.vietnam_tanggal}|${row.vietnam_jam}|${row.sport}|${row.competition}|${row.home}|${row.away}`.toLowerCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  console.log('After deduplication:', filtered.length);
  // Sắp xếp theo thời gian
  filtered.sort((a,b) => dayjs(a.vietnam_datetime).diff(dayjs(b.vietnam_datetime)));
  // Xuất JSON
  const output = filtered.map(r => ({
    competition: r.competition,
    home: r.home,
    away: r.away,
    vietnam_time: r.vietnam_jam,
    vietnam_date: r.vietnam_tanggal,
    channels: r.channels,
    sport: r.sport,
  }));
  fs.writeFileSync(OUTPUT_FILE, JSON.stringify(output, null, 2));
  console.log('JSON written:', OUTPUT_FILE);
})();
