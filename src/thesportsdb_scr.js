const axios = require("axios");
const fs = require("fs").promises;
const dayjs = require("dayjs");
const utc = require("dayjs/plugin/utc");
const timezone = require("dayjs/plugin/timezone");

dayjs.extend(utc);
dayjs.extend(timezone);

// Dùng free API key "123" cho V1
const API_KEY = "123";

const leagues = {
  // Football
  4328: { name: "Premier League", filterTeams: true },
  4332: { name: "Serie A", filterTeams: true },
  4335: { name: "La Liga", filterTeams: true },
  4331: { name: "Bundesliga", filterTeams: true },
  4334: { name: "Ligue 1", filterTeams: true },
  4480: { name: "UEFA Champions League", filterTeams: false },
  4490: { name: "UEFA Europa League", filterTeams: false },
  4577: { name: "UEFA Europa Conference League", filterTeams: false },
  4385: { name: "World Cup", filterTeams: false },
  4498: { name: "UEFA Euro", filterTeams: false },

  // Tennis
  4758: { name: "ATP Tour", filterTeams: false },
  4759: { name: "WTA Tour", filterTeams: false },
  4875: { name: "Australian Open", filterTeams: false },
  4876: { name: "Wimbledon", filterTeams: false },
  4877: { name: "French Open", filterTeams: false },
  4878: { name: "US Open", filterTeams: false },
};

// Team filters (lowercase)
const teamFilters = {
  "4328": new Set([
    "arsenal", "aston villa", "bournemouth", "brentford", "brighton",
    "chelsea", "crystal palace", "everton", "fulham", "leeds united",
    "liverpool", "manchester city", "manchester united", "newcastle",
    "nottingham forest", "sunderland", "tottenham hotspur",
    "west ham united", "wolverhampton"
  ]),
  "4332": new Set([
    "inter milan", "ac milan", "napoli", "juventus", "roma",
    "atalanta", "lazio"
  ]),
  "4335": new Set(["barcelona", "real madrid", "atlético"]),
  "4331": new Set(["bayern", "borussia dortmund", "bayer leverkusen"]),
  "4334": new Set(["psg", "olympique marseille"]),
};

// API V1 - dùng free key "123" trong URL
const api = axios.create({
  baseURL: `https://www.thesportsdb.com/api/v1/json/${API_KEY}`,
});

/**
 * Lấy upcoming events cho league (V1 endpoint)
 * Endpoint: /eventsnextleague.php?id={leagueId}
 */
async function getUpcomingEvents(leagueId) {
  try {
    const res = await api.get(`/eventsnextleague.php?id=${leagueId}`);
    return res.data?.events || [];
  } catch (err) {
    console.error(`Lỗi khi lấy events cho league ${leagueId}:`, err.message);
    return [];
  }
}

function isTeamAllowed(leagueId, homeTeam, awayTeam) {
  if (!teamFilters[leagueId]) return true;
  const lowerHome = homeTeam?.toLowerCase() || "";
  const lowerAway = awayTeam?.toLowerCase() || "";
  const filterSet = teamFilters[leagueId];
  return filterSet.has(lowerHome) || filterSet.has(lowerAway);
}

function isWithinNext24Hours(timestamp) {
  const now = dayjs().utc();
  const eventTime = dayjs(timestamp);
  const diffHours = eventTime.diff(now, "hour");
  return diffHours >= 0 && diffHours <= 24;
}

async function main() {
  const vnTimezone = "Asia/Ho_Chi_Minh";
  const allEvents = [];

  for (const [leagueId, info] of Object.entries(leagues)) {
    const leagueName = info.name;
    console.log(`Đang lấy events cho ${leagueName}...`);

    const events = await getUpcomingEvents(leagueId);
    if (events.length === 0) {
      console.warn(`⚠️ Không có events sắp tới cho ${leagueName}`);
      continue;
    }

    for (const ev of events) {
      const timestamp = ev.strTimestamp;
      if (!timestamp) continue;

      if (!isWithinNext24Hours(timestamp)) continue;

      if (info.filterTeams && !isTeamAllowed(leagueId, ev.strHomeTeam, ev.strAwayTeam)) {
        continue;
      }

      const localTime = dayjs.utc(timestamp).tz(vnTimezone).format("YYYY-MM-DD HH:mm:ss");

      allEvents.push({
        league: leagueName,
        title: ev.strEvent,
        timestamp: localTime,
        homeTeam: ev.strHomeTeam,
        awayTeam: ev.strAwayTeam,
        homeBadge: ev.strHomeTeamBadge,
        awayBadge: ev.strAwayTeamBadge,
        tvStation: ev.strTVStation || "N/A",
      });
    }
  }

  allEvents.sort((a, b) => {
    const aDate = dayjs.tz(a.timestamp, "Asia/Ho_Chi_Minh").valueOf();
    const bDate = dayjs.tz(b.timestamp, "Asia/Ho_Chi_Minh").valueOf();
    return aDate - bDate;
  });

  await fs.writeFile("thesportsdb_schedue.json", JSON.stringify(allEvents, null, 2));
  console.log(`✅ Đã ghi ${allEvents.length} events vào thesportsdb_schedue.json`);
}

main().catch((err) => {
  console.error("❌ Lỗi:", err.message);
  process.exit(1);
});
