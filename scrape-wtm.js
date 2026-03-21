// src/scrape-wtm.js
// WTM SCRAPER - Lọc theo 24h tới, chỉ lấy bóng đá và tennis theo tiêu chí
// Output: results.json

const axios = require("axios");
const cheerio = require("cheerio");
const fs = require("fs");
const path = require("path");
const { wrapper } = require("axios-cookiejar-support");
const { CookieJar } = require("tough-cookie");

/* =========================
   AXIOS CLIENT + COOKIE JAR
   ========================= */
const jar = new CookieJar();
const client = wrapper(
  axios.create({
    jar,
    withCredentials: true,
    timeout: 60000,
    headers: {
      "User-Agent":
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
      Accept:
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
      "Accept-Language": "en-US,en;q=0.9",
    },
  })
);

/* =========================
   DANH SÁCH ĐỘI & GIẢI ĐẤU
   ========================= */
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

const worldCupKeywords = new Set([
  "world cup", "fifa world cup"
]);

const euroKeywords = new Set([
  "european championship", "uefa euro", "euro"
]);

const friendlyKeywords = new Set([
  "friendly", "international friendlies"
]);

// Danh sách quốc gia châu Âu (viết thường, không dấu)
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

// Từ khóa tennis
const tennisKeywords = new Set([
  "atp", "wta", "grand slam", "us open", "wimbledon", "roland garros", "australian open"
]);

/* =========================
   HÀM TIỆN ÍCH
   ========================= */
function getCurrentWITA() {
  const now = new Date();
  const utc = now.getTime() + (now.getTimezoneOffset() * 60000);
  return new Date(utc + (8 * 3600000));
}

function getDatesToScrape() {
  const nowWITA = getCurrentWITA();
  const today = new Date(nowWITA);
  const tomorrow = new Date(nowWITA);
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

function parseEventDateTimeWITA(tanggal, time) {
  const [dd, mm, yyyy] = tanggal.split('-');
  const [HH, MM] = time.split(':');
  return new Date(`${yyyy}-${mm}-${dd}T${HH}:${MM}:00+08:00`);
}

function safeCsv(v) {
  return (v ?? "").toString().replace(/"/g, '""');
}

function buildDailyUrl(dateYYYYMMDD) {
  return `https://www.wheresthematch.com/live-sport-on-tv/?showdatestart=${dateYYYYMMDD}`;
}

function isoToWitaPartsISO(isoZ) {
  const dt = new Date(isoZ);
  if (isNaN(dt.getTime())) return null;

  const options = { timeZone: "Asia/Makassar", hour12: false };
  const yyyy = new Intl.DateTimeFormat("en", { ...options, year: "numeric" }).format(dt);
  const mm = new Intl.DateTimeFormat("en", { ...options, month: "2-digit" }).format(dt);
  const dd = new Intl.DateTimeFormat("en", { ...options, day: "2-digit" }).format(dt);
  const HH = new Intl.DateTimeFormat("en", { ...options, hour: "2-digit" }).format(dt);
  const MM = new Intl.DateTimeFormat("en", { ...options, minute: "2-digit" }).format(dt);
  const hari = new Intl.DateTimeFormat("id-ID", { ...options, weekday: "long" }).format(dt);

  return { hari, tanggal: `${dd}-${mm}-${yyyy}`, time: `${HH}:${MM}` };
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

    const sport = $fx.find(".fixture-sport img").attr("alt")?.trim() || "";
    const competition = $fx.find(".fixture-comp a").first().text().trim() || "";

    const isoZ =
      $tr.find("td.start-details").attr("content") ||
      $tr.find('meta[itemprop="startDate"]').attr("content") ||
      "";

    const w = isoToWitaPartsISO(isoZ) || { hari: "", tanggal: "", time: "" };

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

function fingerprintOfFirstRow(rows) {
  if (!rows || rows.length === 0) return "";
  const r = rows[0];
  return (r.event_url && r.event_url.trim()) || `${r.tanggal}|${r.time}|${r.home}|${r.away}`;
}

/* =========================
   BỘ LỌC SỰ KIỆN
   ========================= */
function filterEventsByTime(events, nowWITA, endWITA) {
  return events.filter(event => {
    const eventDate = parseEventDateTimeWITA(event.tanggal, event.time);
    return eventDate >= nowWITA && eventDate <= endWITA;
  });
}

function isFootball(sport) {
  return sport.toLowerCase().includes("football") || sport.toLowerCase().includes("soccer");
}

function isTennis(sport, competition) {
  if (!sport.toLowerCase().includes("tennis")) return false;
  const compLow = competition.toLowerCase();
  for (const kw of tennisKeywords) {
    if (compLow.includes(kw)) return true;
  }
  return false;
}

function filterFootballEvent(event) {
  const sportLow = event.sport.toLowerCase();
  if (!isFootball(event.sport)) return false;

  const competitionLow = event.competition.toLowerCase();
  const homeLow = event.home.toLowerCase();
  const awayLow = event.away.toLowerCase();

  // UEFA các giải
  if (uefaLegues.has(competitionLow)) return true;

  // World Cup
  for (const kw of worldCupKeywords) {
    if (competitionLow.includes(kw)) return true;
  }

  // Euro
  for (const kw of euroKeywords) {
    if (competitionLow.includes(kw)) return true;
  }

  // Giao hữu
  for (const kw of friendlyKeywords) {
    if (competitionLow.includes(kw)) {
      // Chỉ giữ nếu cả hai đội đều thuộc danh sách quốc gia cho phép
      return allowedFriendlyCountries.has(homeLow) && allowedFriendlyCountries.has(awayLow);
    }
  }

  // Các giải quốc nội
  for (const [league, teams] of Object.entries(footballAllowedLeagues)) {
    if (competitionLow === league) {
      // Nếu home hoặc away nằm trong danh sách đội cho phép
      return teams.has(homeLow) || teams.has(awayLow);
    }
  }

  return false;
}

function filterTennisEvent(event) {
  return isTennis(event.sport, event.competition);
}

function filterEventsBySport(events) {
  return events.filter(event => {
    return filterFootballEvent(event) || filterTennisEvent(event);
  });
}

/* =========================
   SCRAPE MỘT NGÀY
   ========================= */
async function scrapeOneDate(dateYYYYMMDD, opts = {}) {
  const urlBase = buildDailyUrl(dateYYYYMMDD);
  const outDir = path.join("out", dateYYYYMMDD);
  fs.mkdirSync(outDir, { recursive: true });

  const maxPagingIndex = Number.isFinite(opts.maxPagingIndex) ? opts.maxPagingIndex : 60;
  const delayMs = Number.isFinite(opts.delayMs) ? opts.delayMs : 1200;

  console.log(`\n== DATE ${dateYYYYMMDD} ==`);
  console.log(`GET Page 1: ${urlBase}`);

  let currentHtml = "";
  const res1 = await client.get(urlBase);
  currentHtml = res1.data;
  fs.writeFileSync(path.join(outDir, `page-1.html`), currentHtml);

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

  let lastFp = fingerprintOfFirstRow(p1);
  let pageNum = 2;

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
    fs.writeFileSync(path.join(outDir, `page-${pageNum}.html`), currentHtml);

    const $n = cheerio.load(currentHtml);
    const pData = parseWTMEvents($n, pageNum, dateYYYYMMDD);

    if (pData.length === 0) {
      console.log(`Page ${pageNum}: 0 rows => stop paging.`);
      break;
    }

    const fp = fingerprintOfFirstRow(pData);
    if (fp && fp === lastFp) {
      console.log(`Page ${pageNum}: duplicate page returned (same fingerprint) => stop.`);
      break;
    }
    lastFp = fp || lastFp;

    const before = allData.length;
    allData.push(...pData);
    allData = dedupRows(allData);
    const after = allData.length;

    console.log(`Page ${pageNum}: rows ${pData.length} | added unique: ${after - before}`);

    if (after === before) {
      console.log(`No unique added => stop paging.`);
      break;
    }

    pageNum++;
    await new Promise((r) => setTimeout(r, delayMs));
  }

  console.log(`DATE ${dateYYYYMMDD} DONE. unique rows: ${allData.length}`);
  return allData;
}

/* =========================
   MAIN
   ========================= */
async function main() {
  const nowWITA = getCurrentWITA();
  const endWITA = new Date(nowWITA.getTime() + 24 * 3600000);

  const dates = getDatesToScrape();
  console.log("Scraping dates:", dates);

  fs.mkdirSync("out", { recursive: true });

  let allEvents = [];
  for (const d of dates) {
    const rows = await scrapeOneDate(d, { maxPagingIndex: 60, delayMs: 1200 });
    allEvents.push(...rows);
    allEvents = dedupRows(allEvents);
  }

  console.log(`Total unique events (before filter): ${allEvents.length}`);

  // Lọc theo thời gian 24h
  let filteredByTime = filterEventsByTime(allEvents, nowWITA, endWITA);
  console.log(`After time filter (24h): ${filteredByTime.length}`);

  // Lọc theo thể thao
  let finalEvents = filterEventsBySport(filteredByTime);
  console.log(`After sport filter: ${finalEvents.length}`);

  // Loại bỏ các trường không cần xuất
  const output = finalEvents.map(event => {
    const { source_date, page, ...rest } = event;
    return rest;
  });

  fs.writeFileSync("results.json", JSON.stringify(output, null, 2));
  console.log(`\nDONE. Saved results.json with ${output.length} events.`);
}

main().catch((e) => {
  console.error("Fatal:", e);
  process.exit(1);
});
