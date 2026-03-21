const axios = require("axios");
const fs = require("fs").promises;
const dayjs = require("dayjs");
const utc = require("dayjs/plugin/utc");
const timezone = require("dayjs/plugin/timezone");

dayjs.extend(utc);
dayjs.extend(timezone);

const apiKey = process.env.SPORTSDB_API_KEY;
if (!apiKey) {
  throw new Error("Missing API key! Set SPORTSDB_API_KEY as an environment variable.");
}

// ------------------------------------------------------------------
// 1. Define leagues & team filters
// ------------------------------------------------------------------
const leagues = {
  // Football
  4328: { name: "Premier League", filterTeams: true },      // Premier League
  4332: { name: "Serie A", filterTeams: true },              // Serie A
  4335: { name: "La Liga", filterTeams: true },              // La Liga
  4331: { name: "Bundesliga", filterTeams: true },           // Bundesliga
  4334: { name: "Ligue 1", filterTeams: true },              // Ligue 1
  4480: { name: "UEFA Champions League", filterTeams: false },
  4490: { name: "UEFA Europa League", filterTeams: false },
  4577: { name: "UEFA Europa Conference League", filterTeams: false },
  4385: { name: "World Cup", filterTeams: false },           // World Cup
  4498: { name: "UEFA Euro", filterTeams: false },           // UEFA Euro

  // Tennis
  4758: { name: "ATP Tour", filterTeams: false },
  4759: { name: "WTA Tour", filterTeams: false },
  4875: { name: "Australian Open", filterTeams: false },
  4876: { name: "Wimbledon", filterTeams: false },
  4877: { name: "French Open", filterTeams: false },
  4878: { name: "US Open", filterTeams: false },
};

// Team filters (lowercase for case‑insensitive matching)
const teamFilters = {
  "4328": new Set([   // Premier League
    "arsenal", "aston villa", "bournemouth", "brentford", "brighton",
    "chelsea", "crystal palace", "everton", "fulham", "leeds united",
    "liverpool", "manchester city", "manchester united", "newcastle",
    "nottingham forest", "sunderland", "tottenham hotspur",
    "west ham united", "wolverhampton"
  ]),
  "4332": new Set([   // Serie A
    "inter milan", "ac milan", "napoli", "juventus", "roma",
    "atalanta", "lazio"
  ]),
  "4335": new Set([   // La Liga
    "barcelona", "real madrid", "atlético"
  ]),
  "4331": new Set([   // Bundesliga
    "bayern", "borussia dortmund", "bayer leverkusen"
  ]),
  "4334": new Set([   // Ligue 1
    "psg", "olympique marseille"
  ]),
};

// ------------------------------------------------------------------
// 2. API client
// ------------------------------------------------------------------
const api = axios.create({
  baseURL: "https://www.thesportsdb.com/api/v2/json",
  headers: { "X-API-KEY": apiKey },
});

/**
 * Fetch upcoming events for a league (max 15 events).
 * Endpoint: /eventsnextleague.php?id={leagueId}
 */
async function getUpcomingEvents(leagueId) {
  try {
    const res = await api.get(`/eventsnextleague.php?id=${leagueId}`);
    return res.data?.events || [];
  } catch (err) {
    console.error(`Error fetching events for league ${leagueId}:`, err.message);
    return [];
  }
}

// ------------------------------------------------------------------
// 3. Filtering helpers
// ------------------------------------------------------------------
function isTeamAllowed(leagueId, homeTeam, awayTeam) {
  if (!teamFilters[leagueId]) return true; // no filter → include all
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

// ------------------------------------------------------------------
// 4. Main execution
// ------------------------------------------------------------------
async function main() {
  const vnTimezone = "Asia/Ho_Chi_Minh";
  const allEvents = [];

  for (const [leagueId, info] of Object.entries(leagues)) {
    const leagueName = info.name;
    console.log(`Fetching upcoming events for ${leagueName}...`);

    const events = await getUpcomingEvents(leagueId);
    if (events.length === 0) {
      console.warn(`⚠️ No upcoming events found for ${leagueName}`);
      continue;
    }

    for (const ev of events) {
      const timestamp = ev.strTimestamp;
      if (!timestamp) continue;

      // Filter by time (next 24h)
      if (!isWithinNext24Hours(timestamp)) continue;

      // Filter by team if necessary
      if (info.filterTeams && !isTeamAllowed(leagueId, ev.strHomeTeam, ev.strAwayTeam)) {
        continue;
      }

      // Convert timestamp to Vietnam time
      const localTime = dayjs.utc(timestamp).tz(vnTimezone).format("YYYY-MM-DD HH:mm:ss");

      allEvents.push({
        league: leagueName,
        title: ev.strEvent,
        timestamp: localTime,                 // Vietnam time
        homeTeam: ev.strHomeTeam,
        awayTeam: ev.strAwayTeam,
        homeBadge: ev.strHomeTeamBadge,
        awayBadge: ev.strAwayTeamBadge,
        tvStation: ev.strTVStation || "N/A",
      });
    }
  }

  // Sort by timestamp (original UTC order, but we already filtered by time)
  allEvents.sort((a, b) => {
    const aDate = dayjs.tz(a.timestamp, "Asia/Ho_Chi_Minh").valueOf();
    const bDate = dayjs.tz(b.timestamp, "Asia/Ho_Chi_Minh").valueOf();
    return aDate - bDate;
  });

  await fs.writeFile("thesportsdb_schedue.json", JSON.stringify(allEvents, null, 2));
  console.log(`✅ Written ${allEvents.length} events to thesportsdb_schedue.json`);
}

main().catch((err) => {
  console.error("❌ Fatal error:", err.message);
  process.exit(1);
});
