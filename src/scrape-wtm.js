// src/scrape-wtm.js
// WTM SCRAPER - Lọc 24h tới, giờ Việt Nam, chỉ bóng đá/tennis, xuất JSON

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
    timeout: 60000,
    headers: {
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
      Accept: "text/html,application/xhtml+xml,application/xml;q=0.9",
    },
  })
);

// ========== DANH SÁCH ĐỘI & GIẢI ĐẤU ==========
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
  "miami open", "miami", "open"
]);

// ========== HÀM TIỆN ÍCH ==========
function normalize(str) {
  return (str || "").trim().toLowerCase().replace(/\s+/g, " ");
}

function getCurrentVietnamTime() {
  const now = new Date();
  return new Date(now.getTime() + 7 * 3600000);
}

function getDatesToScrape() {
  const nowVN = getCurrentVietnamTime();
  const today = new Date(nowVN);
  const tomorrow = new Date(nowVN);
  tomorrow.setDate(today.getDate() + 1);

  const formatDate = (date) => {
    const yyyy = date.getFullYear();
    const mm = String(date.getMonth() + 1).padStart(2, '0');
    const dd = String(date.getDate()).padStart(2, '0');
    return `${yyyy}${mm}${dd}`;
  };

  const dates = [formatDate(today)];
  if (formatDate(tomorrow) !== formatDate(today)) {
    dates.push(formatDate(tomorrow));
  }
  return dates;
}

function buildDailyUrl(dateYYYYMMDD) {
  return `https://www.wheresthematch.com/live-sport-on-tv/?showdatestart=${dateYYYYMMDD}`;
}

function isoToVietnamParts(isoZ) {
  if (!isoZ) return null;
  const dt = new Date(isoZ);
  if (isNaN(dt.getTime())) return null;
  // Convert to UTC+7 (Vietnam)
  const vnTime = new Date(dt.getTime() + 7 * 3600000);
  const yyyy = vnTime.getUTCFullYear();
  const mm = String(vnTime.getUTCMonth() + 1).padStart(2, '0');
  const dd = String(vnTime.getUTCDate()).padStart(2, '0');
  let HH = String(vnTime.getUTCHours()).padStart(2, '0');
  const MM = String(vnTime.getUTCMinutes()).padStart(2, '0');
  const hari = new Intl.DateTimeFormat('id-ID', { timeZone: 'Asia/Ho_Chi_Minh', weekday: 'long' }).format(dt);
  // Fix giờ 24 thành 00
  if (HH === '24') HH = '00';
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
    if (!w) {
      // Nếu không parse được thời gian, bỏ qua event
      return;
    }

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

// ========== SCRAPE MỘT NGÀY ==========
async function scrapeOneDate(dateYYYYMMDD, opts = {}) {
  const urlBase = buildDailyUrl(dateYYYYMMDD);
  const maxPagingIndex = Number.isFinite(opts.maxPagingIndex) ? opts.maxPagingIndex : 60;
  const delayMs = Number.isFinite(opts.delayMs) ? opts.delayMs : 1200;

  console.log(`\n== DATE ${dateYYYYMMDD} ==`);
  console.log(`GET Page 1: ${urlBase}`);

  let currentHtml = "";
  const res1 = await client.get(urlBase);
  currentHtml = res1.data;

  const $1 = cheerio.load(currentHtml);
  const p1 = parseWTMEvents($1, 1, dateYYYYMMDD);

  let allData = [];
  allData.push(...p1);
  allData = dedupRows(allData);

  console.log(`Page 1 rows: ${p1.length} | unique total: ${allData.length}`);

  if (p1.length === 0) {
    console.log(`No rows on Page 1. Stop date ${dateYYYYMMDD}.`);
    return allData;
  }

  let pageNum = 2;
  let consecutiveEmpty = 0;

  for (let idx = 0; idx <= maxPagingIndex; idx++) {
    const $prev = cheerio.load(currentHtml);
    const hidden = extractHiddenFields($prev);

    const payload = new URLSearchParams({
      ...hidden,
      __EVENTTARGET: `pagetotalhp${idx}`,
      __EVENTARGUMENT: "",
    });

    console.log(`POST Page ${pageNum} (target=pagetotalhp${idx})`);

    let resNext;
    try {
      resNext = await client.post(
        "https://www.wheresthematch.com/live-sport-on-tv/?paging=true",
        payload.toString(),
        {
          headers: {
            "Content-Type": "application/x-www-form-urlencoded",
            Referer: urlBase,
          },
        }
      );
    } catch (e) {
      console.log(`POST failed on idx ${idx}: ${e.message}`);
      break;
    }

    currentHtml = resNext.data;
    const $n = cheerio.load(currentHtml);
    const pData = parseWTMEvents($n, pageNum, dateYYYYMMDD);

    if (pData.length === 0) {
      console.log(`Page ${pageNum}: 0 rows.`);
      consecutiveEmpty++;
      if (consecutiveEmpty >= 2) {
        console.log(`Empty for 2 times => stop.`);
        break;
      }
      continue;
    }

    const before = allData.length;
    allData.push(...pData);
    allData = dedupRows(allData);
    const after = allData.length;
    const added = after - before;
    console.log(`Page ${pageNum}: rows ${pData.length} | added unique: ${added}`);

    if (added === 0) {
      consecutiveEmpty++;
      if (consecutiveEmpty >= 2) {
        console.log(`No unique for 2 times => stop.`);
        break;
      }
    } else {
      consecutiveEmpty = 0;
    }

    pageNum++;
    await new Promise((r) => setTimeout(r, delayMs));
  }

  console.log(`DATE ${dateYYYYMMDD} DONE. unique rows: ${allData.length}`);
  return allData;
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
      return teams.has(homeLow) || teams.has(awayLow);
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
  const endVN = new Date(nowVN.getTime() + 24 * 3600000);

  const dates = getDatesToScrape();
  console.log("Scraping dates:", dates);
  console.log("Now (VN):", nowVN.toISOString());
  console.log("End (VN):", endVN.toISOString());

  let allEvents = [];
  for (const d of dates) {
    const rows = await scrapeOneDate(d, { maxPagingIndex: 60, delayMs: 1200 });
    allEvents.push(...rows);
    allEvents = dedupRows(allEvents);
  }

  console.log(`Total unique events (before filter): ${allEvents.length}`);

  // Debug: in ra các sự kiện có chứa Milan, Torino và tennis
  console.log("\n--- Debug: events containing 'milan' or 'torino' ---");
  allEvents.forEach(e => {
    if (normalize(e.home).includes('milan') || normalize(e.away).includes('milan') ||
        normalize(e.home).includes('torino') || normalize(e.away).includes('torino')) {
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
  console.log(`After time filter (24h): ${filteredByTime.length}`);

  let finalEvents = filterEventsBySport(filteredByTime);
  console.log(`After sport filter: ${finalEvents.length}`);

  const serieAEvents = finalEvents.filter(e => normalize(e.competition).includes("serie a"));
  console.log("\nSerie A matches found:", serieAEvents.length);
  serieAEvents.forEach(e => console.log(`- ${e.home} vs ${e.away} at ${e.tanggal} ${e.time}`));

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
