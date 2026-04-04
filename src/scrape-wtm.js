// src/scrape-wtm.js
// WTM SCRAPER - Lọc 48h tới, giờ Việt Nam (UTC+7), chỉ bóng đá/tennis, xuất JSON

const axios = require("axios");
const cheerio = require("cheerio");
const fs = require("fs");
const { wrapper } = require("axios-cookiejar-support");
const { CookieJar } = require("tough-cookie");

// ========== AXIOS CLIENT ==========
const jar = new CookieJar();
const client = wrapper(
  axios.create({
    jar,
    withCredentials: true,
    timeout: 120000,
    headers: {
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
      Accept: "text/html,application/xhtml+xml,application/xml;q=0.9",
    },
  })
);

// ========== RETRY HELPER ==========
async function getWithRetry(url, retries = 3, delay = 1000) {
  for (let i = 0; i < retries; i++) {
    try {
      const response = await client.get(url);
      return response;
    } catch (error) {
      if (i === retries - 1) throw error;
      console.log(`Retry ${i + 1} for ${url} after error: ${error.message}`);
      await new Promise(resolve => setTimeout(resolve, delay * (i + 1)));
    }
  }
}

// ========== DANH SÁCH ĐỘI VỚI CÁC BIẾN THỂ ==========
const teamVariants = {
  "arsenal": ["arsenal"],
  "aston villa": ["aston villa"],
  "bournemouth": ["bournemouth"],
  "brentford": ["brentford"],
  "brighton": ["brighton", "brighton & hove albion"],
  "chelsea": ["chelsea"],
  "crystal palace": ["crystal palace"],
  "everton": ["everton"],
  "fulham": ["fulham"],
  "leeds united": ["leeds united", "leeds"],
  "liverpool": ["liverpool"],
  "manchester city": ["manchester city", "man city"],
  "manchester united": ["manchester united", "man utd", "manchester u"],
  "newcastle": ["newcastle", "newcastle united"],
  "nottingham forest": ["nottingham forest", "forest"],
  "sunderland": ["sunderland"],
  "tottenham hotspur": ["tottenham hotspur", "tottenham", "spurs"],
  "west ham united": ["west ham united", "west ham"],
  "wolverhampton": ["wolverhampton", "wolves"],
  "inter milan": ["inter milan", "inter", "internazionale"],
  "ac milan": ["ac milan", "milan", "acmilan"],
  "napoli": ["napoli"],
  "juventus": ["juventus", "juve"],
  "roma": ["roma"],
  "atalanta": ["atalanta"],
  "lazio": ["lazio"],
  "barcelona": ["barcelona", "barça"],
  "real madrid": ["real madrid", "real"],
  "atlético": ["atlético", "atletico madrid", "atletico"],
  "bayern": ["bayern", "bayern munich"],
  "borussia dortmund": ["borussia dortmund", "dortmund"],
  "bayer leverkusen": ["bayer leverkusen", "leverkusen"],
  "psg": ["psg", "paris saint germain", "paris st germain", "paris"],
  "olympique marseille": ["olympique marseille", "marseille", "om"]
};

const footballAllowedLeagues = {
  "premier league": new Set([
    "arsenal", "aston villa", "bournemouth", "brentford", "brighton", "chelsea",
    "crystal palace", "everton", "fulham", "leeds united", "liverpool", "manchester city",
    "manchester united", "newcastle", "nottingham forest", "sunderland", "tottenham hotspur",
    "west ham united", "wolverhampton"
  ]),
  "serie a": new Set([
    "inter milan", "ac milan", "napoli", "juventus", "roma", "atalanta", "lazio"
  ]),
  "la liga": new Set([
    "barcelona", "real madrid", "atlético"
  ]),
  "bundesliga": new Set([
    "bayern", "borussia dortmund", "bayer leverkusen"
  ]),
  "ligue 1": new Set([
    "psg", "olympique marseille"
  ])
};

const uefaLegues = new Set([
  "uefa champions league", "uefa europa league", "uefa europa conference league"
]);

const worldCupKeywords = new Set(["world cup", "fifa world cup"]);
const euroKeywords = new Set(["european championship", "uefa euro", "euro"]);
const friendlyKeywords = new Set(["friendly", "international friendlies"]);

const europeanCountries = new Set([
  "albania", "andorra", "armenia", "austria", "azerbaijan", "belarus", "belgium",
  "bosnia and herzegovina", "bulgaria", "croatia", "cyprus", "czech republic",
  "denmark", "england", "estonia", "faroe islands", "finland", "france", "georgia",
  "germany", "gibraltar", "greece", "hungary", "iceland", "ireland", "israel",
  "italy", "kazakhstan", "kosovo", "latvia", "liechtenstein", "lithuania",
  "luxembourg", "malta", "moldova", "montenegro", "netherlands", "north macedonia",
  "northern ireland", "norway", "poland", "portugal", "romania", "russia",
  "san marino", "scotland", "serbia", "slovakia", "slovenia", "spain", "sweden",
  "switzerland", "turkey", "ukraine", "wales"
]);

const allowedFriendlyCountries = new Set([
  ...europeanCountries,
  "argentina", "brazil", "japan", "south korea", "korea republic"
]);

const tennisKeywords = new Set([
  "atp", "wta", "grand slam", "us open", "wimbledon", "roland garros", "australian open",
  "miami open", "monte carlo rolex masters", "monte carlo", "masters", "linz open"
]);

// ========== HÀM TIỆN ÍCH ==========
function normalize(str) {
  return (str || "").trim().toLowerCase().replace(/[-_]/g, " ").replace(/\s+/g, " ");
}

function isTeamInLeague(teamName, leagueTeams) {
  const normTeam = normalize(teamName);
  for (const teamKey of leagueTeams) {
    const variants = teamVariants[teamKey] || [teamKey];
    for (const variant of variants) {
      if (normTeam === normalize(variant)) return true;
    }
  }
  return false;
}

function getCurrentVietnamTime() {
  const now = new Date();
  return new Date(now.getTime() + 7 * 3600000);
}

function getDatesToScrape() {
  const nowVN = getCurrentVietnamTime();
  const dates = [];
  for (let i = 0; i <= 2; i++) {
    const d = new Date(nowVN);
    d.setDate(nowVN.getDate() + i);
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    dates.push(`${yyyy}${mm}${dd}`);
  }
  return [...new Set(dates)];
}

function buildDailyUrl(dateYYYYMMDD) {
  return `https://www.wheresthematch.com/live-sport-on-tv/?showdatestart=${dateYYYYMMDD}`;
}

// Chuyển đổi thời gian từ chuỗi gốc (giờ UK BST = UTC+1) sang giờ Việt Nam (UTC+7)
function isoToVietnamParts(isoZ) {
  if (!isoZ) return null;
  let raw = isoZ.trim();
  // Thay T bằng space, xóa mili giây
  raw = raw.replace('T', ' ');
  raw = raw.replace(/\.\d+/, '');
  // Tạo Date object (coi như UTC)
  let dt = new Date(raw + 'Z');
  if (isNaN(dt.getTime())) {
    // Thử parse trực tiếp nếu không thành công
    dt = new Date(raw);
    if (isNaN(dt.getTime())) return null;
  }
  // Cộng 6 giờ (vì UK hiện tại BST = UTC+1, VN = UTC+7)
  const vnTime = new Date(dt.getTime() + 6 * 3600000);
  const yyyy = vnTime.getUTCFullYear();
  const mm = String(vnTime.getUTCMonth() + 1).padStart(2, '0');
  const dd = String(vnTime.getUTCDate()).padStart(2, '0');
  let HH = String(vnTime.getUTCHours()).padStart(2, '0');
  const MM = String(vnTime.getUTCMinutes()).padStart(2, '0');
  if (HH === '24') HH = '00';
  const hari = new Intl.DateTimeFormat('id-ID', { timeZone: 'Asia/Ho_Chi_Minh', weekday: 'long' }).format(vnTime);
  return { hari, tanggal: `${dd}-${mm}-${yyyy}`, time: `${HH}:${MM}` };
}

function parseEventDateTimeVN(tanggal, time) {
  const [dd, mm, yyyy] = tanggal.split('-');
  let [HH, MM] = time.split(':');
  if (!HH || !MM) return null;
  let addDay = 0;
  if (HH === '24') {
    HH = '0';
    addDay = 1;
  }
  let eventDate = new Date(`${yyyy}-${mm}-${dd}T${HH}:${MM}:00+07:00`);
  if (isNaN(eventDate.getTime())) return null;
  if (addDay) {
    eventDate.setDate(eventDate.getDate() + addDay);
  }
  return eventDate;
}

function extractHiddenFields($) {
  const fields = {};
  $("input[type='hidden']").each((_, el) => {
    const name = $(el).attr("name");
    const value = $(el).attr("value") || "";
    if (name) fields[name] = value;
  });
  return fields;
}

function uniqKeepOrder(arr) {
  const seen = new Set();
  const out = [];
  for (const x of arr) {
    const k = (x || "").trim();
    if (!k) continue;
    if (seen.has(k)) continue;
    seen.add(k);
    out.push(k);
  }
  return out;
}

function parseWTMEvents($, pageNum, sourceDate) {
  const rows = [];

  $("table tr").each((_, tr) => {
    const $tr = $(tr);
    const $fx = $tr.find("td.fixture-details");
    if ($fx.length === 0) return;

    const matchContent = ($fx.attr("content") || "").trim();
    const parts = matchContent.split(" v ");
    const home = parts[0]?.trim() || "";
    const away = parts[1]?.trim() || "";

    const $sportImg = $fx.find(".fixture-sport img");
    let sport = $sportImg.attr("alt")?.trim() || $sportImg.attr("title")?.trim() || "";
    if (!sport) {
      sport = $fx.find(".fixture-sport").text().trim();
    }

    const competition = $fx.find(".fixture-comp a").first().text().trim() || "";

    const isoZ =
      $tr.find("td.start-details").attr("content") ||
      $tr.find('meta[itemprop="startDate"]').attr("content") ||
      "";

    const w = isoToVietnamParts(isoZ);
    if (!w) return;

    const channels = [];
    $tr.find("td.channel-details img").each((_, img) => {
      let t = $(img).attr("title") || $(img).attr("alt") || "";
      t = t.replace(/Live on\s*/i, "").replace(/\s*logo\s*$/i, "").trim();
      if (t) channels.push(t);
    });

    const href = $fx.find("a[href*='/match/']").attr("href") || "";
    const event_url = href
      ? href.startsWith("http")
        ? href
        : `https://www.wheresthematch.com${href}`
      : "";

    rows.push({
      source_date: sourceDate,
      page: pageNum,
      hari: w.hari,
      tanggal: w.tanggal,
      time: w.time,
      sport,
      competition,
      title: home && away ? `${home} vs ${away}` : matchContent,
      home,
      away,
      channels: uniqKeepOrder(channels),
      event_url,
    });
  });

  return rows;
}

function dedupRows(rows) {
  const map = new Map();
  for (const r of rows) {
    const key =
      (r.event_url && r.event_url.trim()) ||
      `${r.source_date}|${r.tanggal}|${r.time}|${r.home}|${r.away}|${r.sport}|${r.competition}`;
    if (!map.has(key)) map.set(key, r);
  }
  return Array.from(map.values());
}

// ========== SCRAPE MỘT NGÀY (CHỈ LẤY PAGE 1) ==========
async function scrapeOneDate(dateYYYYMMDD) {
  const url = buildDailyUrl(dateYYYYMMDD);
  console.log(`\n== DATE ${dateYYYYMMDD} ==`);
  console.log(`GET ${url}`);

  let html;
  try {
    const res = await getWithRetry(url, 3, 1000);
    html = res.data;
  } catch (error) {
    console.error(`Failed to fetch ${url} after retries: ${error.message}`);
    return [];
  }

  const $ = cheerio.load(html);
  const events = parseWTMEvents($, 1, dateYYYYMMDD);
  console.log(`Page 1 rows: ${events.length}`);
  return events;
}

// ========== BỘ LỌC ==========
function filterEventsByTime(events, nowVN, endVN) {
  return events.filter(event => {
    const eventDate = parseEventDateTimeVN(event.tanggal, event.time);
    if (!eventDate) return false;
    return eventDate >= nowVN && eventDate <= endVN;
  });
}

function isFootball(sport) {
  return normalize(sport).includes("football") || normalize(sport).includes("soccer");
}

function isTennis(sport, competition) {
  const sportLow = normalize(sport);
  const compLow = normalize(competition);
  if (sportLow.includes("tennis")) return true;
  for (const kw of tennisKeywords) {
    if (compLow.includes(kw)) return true;
  }
  return false;
}

function filterFootballEvent(event) {
  if (!isFootball(event.sport)) return false;

  const competitionLow = normalize(event.competition);
  const homeLow = normalize(event.home);
  const awayLow = normalize(event.away);

  if (uefaLegues.has(competitionLow)) return true;
  for (const kw of worldCupKeywords) if (competitionLow.includes(kw)) return true;
  for (const kw of euroKeywords) if (competitionLow.includes(kw)) return true;
  for (const kw of friendlyKeywords) {
    if (competitionLow.includes(kw)) {
      return allowedFriendlyCountries.has(homeLow) && allowedFriendlyCountries.has(awayLow);
    }
  }
  for (const [league, teams] of Object.entries(footballAllowedLeagues)) {
    if (competitionLow.includes(league)) {
      if (isTeamInLeague(homeLow, teams) || isTeamInLeague(awayLow, teams)) return true;
    }
  }
  return false;
}

function filterTennisEvent(event) {
  return isTennis(event.sport, event.competition);
}

function filterEventsBySport(events) {
  return events.filter(event => filterFootballEvent(event) || filterTennisEvent(event));
}

// ========== MAIN ==========
async function main() {
  const nowVN = getCurrentVietnamTime();
  const endVN = new Date(nowVN.getTime() + 48 * 3600000);

  const dates = getDatesToScrape();
  console.log("Scraping dates:", dates);
  console.log("Now (VN):", nowVN.toISOString());
  console.log("End (VN):", endVN.toISOString());

  let allEvents = [];
  for (const d of dates) {
    const rows = await scrapeOneDate(d);
    allEvents.push(...rows);
    allEvents = dedupRows(allEvents);
  }

  console.log(`Total unique events (before filter): ${allEvents.length}`);

  console.log("\n--- Debug: events containing 'milan', 'torino', 'psg' ---");
  allEvents.forEach(e => {
    const homeLow = normalize(e.home);
    const awayLow = normalize(e.away);
    if (homeLow.includes('milan') || awayLow.includes('milan') ||
        homeLow.includes('torino') || awayLow.includes('torino') ||
        homeLow.includes('psg') || awayLow.includes('psg') ||
        homeLow.includes('paris') || awayLow.includes('paris')) {
      console.log(`${e.home} vs ${e.away} | ${e.competition} | ${e.tanggal} ${e.time}`);
    }
  });

  console.log("\n--- Debug: tennis events (before time filter) ---");
  allEvents.forEach(e => {
    if (isTennis(e.sport, e.competition)) {
      console.log(`${e.title} | ${e.competition} | ${e.tanggal} ${e.time}`);
    }
  });

  let filteredByTime = filterEventsByTime(allEvents, nowVN, endVN);
  console.log(`After time filter (48h): ${filteredByTime.length}`);

  let finalEvents = filterEventsBySport(filteredByTime);
  console.log(`After sport filter: ${finalEvents.length}`);

  const serieAEvents = finalEvents.filter(e => normalize(e.competition).includes("serie a"));
  console.log("\nSerie A matches found:", serieAEvents.length);
  serieAEvents.forEach(e => console.log(`- ${e.home} vs ${e.away} at ${e.tanggal} ${e.time}`));

  const ligue1Events = finalEvents.filter(e => normalize(e.competition).includes("ligue 1"));
  console.log("\nLigue 1 matches found:", ligue1Events.length);
  ligue1Events.forEach(e => console.log(`- ${e.home} vs ${e.away} at ${e.tanggal} ${e.time}`));

  const tennisEvents = finalEvents.filter(e => isTennis(e.sport, e.competition));
  console.log("\nTennis matches found:", tennisEvents.length);
  tennisEvents.forEach(e => console.log(`- ${e.title} | ${e.competition} | ${e.tanggal} ${e.time}`));

  const output = finalEvents.map(({ source_date, page, ...rest }) => rest);
  fs.writeFileSync("results.json", JSON.stringify(output, null, 2));
  console.log(`\nDONE. Saved results.json with ${output.length} events.`);
}

main().catch((e) => {
  console.error("Fatal:", e);
  process.exit(1);
});
